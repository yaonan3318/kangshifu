"""混合检索服务：融合 PostgreSQL 全文关键词召回与 pgvector 语义召回。"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Document, DocumentChunk, DocumentStatus
from app.schemas.search import SearchRequest, SearchResult
from app.services.embeddings import EmbeddingService
from app.services.keywords import keyword_text


@dataclass
class Candidate:
    """检索内部使用的片段及其所属文档。"""

    chunk: DocumentChunk
    document: Document


class SearchService:
    """执行关键词与语义两路召回，再用 RRF 融合成一个结果列表。"""

    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings
        self.embeddings = EmbeddingService(settings)

    def search(self, request: SearchRequest) -> list[SearchResult]:
        """检索已完成索引的片段，并返回去重、融合排序后的结果。"""
        query = request.query.strip()
        if not query:
            return []
        keyword_candidates = self._keyword_candidates(query, request)
        vector_candidates = self._vector_candidates(query, request)

        candidates: dict[uuid.UUID, Candidate] = {}
        scores: dict[uuid.UUID, float] = {}
        sources: dict[uuid.UUID, set[str]] = {}
        # RRF 只使用各召回列表的名次，不必强行比较两种不同量纲的原始分数。
        for source, ranked in (("keyword", keyword_candidates), ("vector", vector_candidates)):
            for rank, candidate in enumerate(ranked, start=1):
                chunk_id = candidate.chunk.id
                candidates[chunk_id] = candidate
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (self.settings.search_rrf_k + rank)
                sources.setdefault(chunk_id, set()).add(source)

        ordered = sorted(candidates, key=lambda item: (-scores[item], str(item)))[:request.limit]
        return [self._result(candidates[chunk_id], sources[chunk_id]) for chunk_id in ordered]

    def _base_clauses(self, request: SearchRequest):
        clauses = [Document.status == DocumentStatus.READY]
        if request.extension:
            clauses.append(Document.extension == request.extension.lower().lstrip("."))
        if request.document_name:
            clauses.append(Document.original_name.ilike(f"%{request.document_name.strip()}%"))
        if request.created_from:
            clauses.append(Document.created_at >= datetime.combine(request.created_from, time.min, UTC))
        if request.created_to:
            clauses.append(Document.created_at < datetime.combine(request.created_to, time.min, UTC) + timedelta(days=1))
        return clauses

    def _keyword_candidates(self, query: str, request: SearchRequest) -> list[Candidate]:
        """通过 GIN + tsvector 精确召回，适合名称、编号等明确关键词。"""
        tokens = keyword_text(query)
        if not tokens:
            return []
        tsquery = func.plainto_tsquery("simple", tokens)
        rank = func.ts_rank_cd(DocumentChunk.search_vector, tsquery)
        rows = self.session.execute(
            select(DocumentChunk, Document).join(Document).where(
                *self._base_clauses(request),
                DocumentChunk.search_vector.op("@@")(tsquery),
            ).order_by(rank.desc(), DocumentChunk.id).limit(self.settings.search_candidate_limit)
        ).all()
        return [Candidate(chunk=row[0], document=row[1]) for row in rows]

    def _vector_candidates(self, query: str, request: SearchRequest) -> list[Candidate]:
        """通过 pgvector 余弦距离语义召回，并过滤低相似度噪声。"""
        vector = self.embeddings.encode_query(query)
        distance = DocumentChunk.embedding.cosine_distance(vector)
        maximum_distance = 1.0 - self.settings.search_vector_min_similarity
        rows = self.session.execute(
            select(DocumentChunk, Document).join(Document).where(
                *self._base_clauses(request),
                DocumentChunk.embedding.is_not(None),
                distance <= maximum_distance,
            ).order_by(distance, DocumentChunk.id).limit(self.settings.search_candidate_limit)
        ).all()
        return [Candidate(chunk=row[0], document=row[1]) for row in rows]

    @staticmethod
    def _result(candidate: Candidate, sources: set[str]) -> SearchResult:
        chunk, document = candidate.chunk, candidate.document
        match_type = "hybrid" if len(sources) == 2 else next(iter(sources))
        return SearchResult(
            chunk_id=chunk.id, document_id=document.id, document_name=document.original_name,
            extension=document.extension, sequence_number=chunk.sequence_number, content=chunk.content,
            page_start=chunk.page_start, page_end=chunk.page_end, slide_number=chunk.slide_number,
            sheet_name=chunk.sheet_name, row_start=chunk.row_start, row_end=chunk.row_end,
            section_path=chunk.section_path, ocr_confidence=chunk.ocr_confidence, match_type=match_type,
        )
