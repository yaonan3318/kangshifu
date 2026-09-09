"""共享混合检索：规范化、双路召回、RRF、可选精排和无答案判断。"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from time import perf_counter
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Document, DocumentChunk, KnowledgeBase, Tag
from app.schemas.search import RetrievalStageItem, SearchDiagnostics, SearchRequest, SearchResult
from app.services.embeddings import EmbeddingService
from app.services.keywords import keyword_text
from app.services.query_processing import QueryProcessor
from app.services.reranking import Reranker
from app.services.retrieval_policy import active_retrieval_clauses


@dataclass
class Candidate:
    chunk: DocumentChunk
    document: Document
    keyword_score: float | None = None
    vector_score: float | None = None
    fusion_score: float = 0.0
    rerank_score: float | None = None
    final_score: float = 0.0
    sources: set[str] | None = None


@dataclass(frozen=True)
class SearchOutcome:
    items: list[SearchResult]
    diagnostics: SearchDiagnostics


class SearchService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings
        self.embeddings = EmbeddingService(settings)
        self.processor = QueryProcessor(settings.search_synonyms)
        self.reranker = Reranker(settings)

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return self.search_with_diagnostics(request).items

    def search_with_diagnostics(self, request: SearchRequest) -> SearchOutcome:
        started = perf_counter()
        processed = self.processor.process(request.query)
        timings: dict[str, float] = {"query_processing": self._milliseconds(started)}
        if not processed.normalized:
            return self._empty(processed, timings, "检索内容为空")

        mark = perf_counter()
        keyword = self._keyword_candidates(processed.normalized, request)
        timings["keyword"] = self._milliseconds(mark)
        mark = perf_counter()
        vector = self._vector_candidates(processed.retrieval_text, request)
        timings["vector"] = self._milliseconds(mark)
        candidates = self._fuse(keyword, vector, processed.normalized)
        stages = ({
            "keyword": [self._stage_item(item, item.keyword_score or 0.0) for item in keyword],
            "vector": [self._stage_item(item, item.vector_score or 0.0) for item in vector],
            "fusion": [self._stage_item(item, item.final_score) for item in candidates],
        } if request.include_stages else {})

        mark = perf_counter()
        ranked, warning, mode = self._rerank(processed.normalized, candidates)
        timings["rerank"] = self._milliseconds(mark)
        accepted = self._accept(ranked, request.limit)
        if request.include_stages:
            stages["rerank"] = [self._stage_item(item, item.rerank_score if item.rerank_score is not None else item.final_score) for item in ranked]
            stages["final"] = [self._stage_item(item, item.final_score) for item in accepted]
        reason = None
        if not accepted:
            reason = "没有片段达到可靠答案阈值，请调整问题或检查资料状态"
        timings["total"] = round((perf_counter() - started) * 1000, 2)
        return SearchOutcome(
            [self._result(item) for item in accepted],
            SearchDiagnostics(
                normalized_query=processed.normalized, expanded_terms=processed.expanded_terms,
                mode=mode, warning=warning, no_answer_reason=reason, timings_ms=timings,
                stages=stages,
            ),
        )

    def _base_clauses(self, request: SearchRequest):
        clauses = active_retrieval_clauses()
        if request.extension:
            clauses.append(Document.extension == request.extension.lower().lstrip("."))
        if request.document_name:
            clauses.append(Document.original_name.ilike(f"%{request.document_name.strip()}%"))
        if request.knowledge_base_id:
            clauses.append(Document.knowledge_base_id == request.knowledge_base_id)
        if request.tags:
            clauses.append(Document.tags.any(Tag.name.in_([tag.strip() for tag in request.tags if tag.strip()])))
        if request.created_from:
            clauses.append(Document.created_at >= datetime.combine(request.created_from, time.min, UTC))
        if request.created_to:
            clauses.append(Document.created_at < datetime.combine(request.created_to, time.min, UTC) + timedelta(days=1))
        return clauses

    def _keyword_candidates(self, query: str, request: SearchRequest) -> list[Candidate]:
        tokens = keyword_text(query)
        if not tokens:
            return []
        tsquery = func.plainto_tsquery("simple", tokens)
        rank = func.ts_rank_cd(DocumentChunk.search_vector, tsquery).label("keyword_score")
        rows = self.session.execute(
            select(DocumentChunk, Document, rank).join(Document).join(KnowledgeBase).where(
                *self._base_clauses(request), DocumentChunk.search_vector.op("@@")(tsquery),
            ).order_by(rank.desc(), DocumentChunk.id).limit(self.settings.search_candidate_limit)
        ).all()
        return [Candidate(row[0], row[1], keyword_score=float(row[2] or 0), sources={"keyword"}) for row in rows]

    def _vector_candidates(self, query: str, request: SearchRequest) -> list[Candidate]:
        vector = self.embeddings.encode_query(query)
        distance = DocumentChunk.embedding.cosine_distance(vector)
        rows = self.session.execute(
            select(DocumentChunk, Document, distance.label("distance")).join(Document).join(KnowledgeBase).where(
                *self._base_clauses(request), DocumentChunk.embedding.is_not(None),
                distance <= 1.0 - self.settings.search_vector_min_similarity,
            ).order_by(distance, DocumentChunk.id).limit(self.settings.search_candidate_limit)
        ).all()
        return [Candidate(row[0], row[1], vector_score=1.0 - float(row[2]), sources={"vector"}) for row in rows]

    def _fuse(self, keyword: list[Candidate], vector: list[Candidate], query: str) -> list[Candidate]:
        values: dict[uuid.UUID, Candidate] = {}
        for source, ranked in (("keyword", keyword), ("vector", vector)):
            for rank, candidate in enumerate(ranked, start=1):
                existing = values.get(candidate.chunk.id)
                if existing is None:
                    existing = candidate
                    existing.sources = set()
                    values[candidate.chunk.id] = existing
                existing.sources.add(source)
                existing.keyword_score = candidate.keyword_score or existing.keyword_score
                existing.vector_score = candidate.vector_score or existing.vector_score
                existing.fusion_score += 1.0 / (self.settings.search_rrf_k + rank)
        maximum = 2.0 / (self.settings.search_rrf_k + 1)
        for item in values.values():
            query_tokens = keyword_text(query).split()
            title = item.document.original_name.lower()
            title_bonus = 0.1 if query in title or any(token in title for token in query_tokens) else 0.0
            item.final_score = min(1.0, item.fusion_score / maximum + title_bonus)
        return sorted(values.values(), key=lambda item: (-item.final_score, str(item.chunk.id)))

    def _rerank(self, query: str, candidates: list[Candidate]) -> tuple[list[Candidate], str | None, str]:
        selected = candidates[: self.settings.rerank_candidate_limit]
        outcome = self.reranker.rerank(query, [item.chunk.content for item in selected])
        if outcome.scores is None:
            return candidates, outcome.warning, "hybrid_rrf"
        for item, score in zip(selected, outcome.scores, strict=True):
            item.rerank_score = score
            item.final_score = 0.85 * score + 0.15 * item.final_score
        selected.sort(key=lambda item: (-item.final_score, str(item.chunk.id)))
        return selected + candidates[len(selected):], outcome.warning, "hybrid_rerank"

    def _accept(self, candidates: list[Candidate], limit: int) -> list[Candidate]:
        accepted: list[Candidate] = []
        per_document: dict[uuid.UUID, int] = {}
        for item in candidates:
            if item.final_score < self.settings.search_min_evidence_score:
                continue
            count = per_document.get(item.document.id, 0)
            if count >= self.settings.search_per_document_limit:
                continue
            accepted.append(item)
            per_document[item.document.id] = count + 1
            if len(accepted) >= limit:
                break
        return accepted

    @staticmethod
    def _result(candidate: Candidate) -> SearchResult:
        chunk, document = candidate.chunk, candidate.document
        sources = candidate.sources or set()
        match_type = "hybrid" if len(sources) == 2 else (next(iter(sources)) if sources else "vector")
        return SearchResult(
            chunk_id=chunk.id, document_id=document.id, document_name=document.original_name,
            extension=document.extension, sequence_number=chunk.sequence_number, content=chunk.content,
            page_start=chunk.page_start, page_end=chunk.page_end, slide_number=chunk.slide_number,
            sheet_name=chunk.sheet_name, row_start=chunk.row_start, row_end=chunk.row_end,
            section_path=chunk.section_path, ocr_confidence=chunk.ocr_confidence, match_type=match_type,
            keyword_score=candidate.keyword_score, vector_score=candidate.vector_score,
            fusion_score=candidate.fusion_score, rerank_score=candidate.rerank_score, final_score=candidate.final_score,
        )

    @staticmethod
    def _milliseconds(started: float) -> float:
        return round((perf_counter() - started) * 1000, 2)

    @staticmethod
    def _stage_item(candidate: Candidate, score: float) -> RetrievalStageItem:
        return RetrievalStageItem(
            chunk_id=candidate.chunk.id, document_id=candidate.document.id,
            document_name=candidate.document.original_name, sequence_number=candidate.chunk.sequence_number,
            score=round(score, 6), content_preview=candidate.chunk.content[:500],
        )

    @staticmethod
    def _empty(processed, timings, reason: str) -> SearchOutcome:
        return SearchOutcome([], SearchDiagnostics(
            normalized_query=processed.normalized, expanded_terms=processed.expanded_terms,
            mode="hybrid_rrf", no_answer_reason=reason, timings_ms=timings,
        ))
