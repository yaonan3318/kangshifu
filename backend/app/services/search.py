"""共享混合检索：规范化、双路召回、RRF、可选精排和无答案判断。"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
import hashlib
from time import perf_counter
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Department, Document, DocumentAcl, DocumentChunk, KnowledgeBase, Tag, User
from app.schemas.search import RetrievalStageItem, SearchDiagnostics, SearchRequest, SearchResult
from app.services.dictionaries import load_expansions
from app.services.embeddings import EmbeddingService
from app.services.feedback_ranking import FeedbackRankingService
from app.services.keywords import keyword_text
from app.services.query_processing import QueryProcessor
from app.services.reranking import Reranker
from app.services.retrieval_config import RetrievalConfig
from app.services.retrieval_policy import active_retrieval_clauses
from app.services.permissions import PermissionResolver


@dataclass
class Candidate:
    chunk: DocumentChunk
    document: Document
    keyword_score: float | None = None
    vector_score: float | None = None
    fusion_score: float = 0.0
    rerank_score: float | None = None
    final_score: float = 0.0
    adjusted_score: float = 0.0
    feedback_boost: float = 0.0
    pre_rerank_rank: int | None = None
    post_rerank_rank: int | None = None
    sources: set[str] | None = None


@dataclass(frozen=True)
class SearchOutcome:
    items: list[SearchResult]
    diagnostics: SearchDiagnostics


class SearchService:
    def __init__(self, session: Session, settings: Settings, user=None, config: RetrievalConfig | None = None):
        self.session = session
        self.settings = settings
        self.user = user
        # 可版本化的检索参数；未传入时使用当前运行时配置。
        self.config = config or RetrievalConfig.from_settings(settings)
        self.embeddings = EmbeddingService(settings)
        dictionary = load_expansions(session) if self.config.dictionary_enabled else None
        self.processor = QueryProcessor(
            self.config.query_rewrite_synonyms, dictionary=dictionary,
            spelling_correction=self.config.spelling_correction_enabled,
        )
        self.reranker = Reranker(settings)
        self.feedback = FeedbackRankingService(session, settings)
        # 普通用户只检索对其可见的资料；管理员/无用户上下文不限制。
        self.resolver = PermissionResolver(session, user) if user is not None else None

    def permission_cache_scope(self) -> str:
        """构建随权限状态变化的缓存分区。

        指纹覆盖：启用中的角色及其 updated_at、启用部门链及其 updated_at、
        用户自身 updated_at，以及全部文档 ACL 条目的内容哈希。
        与 RAG 层的资料版本指纹叠加后，角色增删/启停、部门变更/启停、
        ACL 增删或权限级别变化、文档可见范围变化都会让旧缓存失效。
        """
        if self.user is None:
            return "unauthenticated"
        enabled_roles = sorted(
            (str(role.id), role.updated_at.isoformat() if role.updated_at else "")
            for role in self.user.roles if role.enabled
        )
        roles = ";".join(f"{role_id}@{stamp}" for role_id, stamp in enabled_roles)
        department_ids = self.resolver.department_ids if self.resolver else []
        department_stamps: list[str] = []
        for department_id in sorted(department_ids, key=str):
            row = self.session.get(Department, department_id)
            stamp = row.updated_at.isoformat() if row is not None and row.updated_at else ""
            department_stamps.append(f"{department_id}@{stamp}")
        departments = ";".join(department_stamps)
        acl_rows = self.session.execute(
            select(
                DocumentAcl.document_id, DocumentAcl.subject_type,
                DocumentAcl.subject_id, DocumentAcl.permission,
            ).order_by(DocumentAcl.document_id, DocumentAcl.subject_type, DocumentAcl.subject_id)
        ).all()
        acl_digest = hashlib.sha256("|".join(
            f"{document_id}:{getattr(subject_type, 'value', subject_type)}:"
            f"{subject_id}:{getattr(permission, 'value', permission)}"
            for document_id, subject_type, subject_id, permission in acl_rows
        ).encode("utf-8")).hexdigest()[:16]
        user_stamp = self.user.updated_at.isoformat() if self.user.updated_at else ""
        return (
            f"user:{self.user.id}@{user_stamp}|admin:{int(self.user.is_super_admin)}|"
            f"department:{self.user.department_id or ''}|departments:{departments}|"
            f"roles:{roles}|acl:{len(acl_rows)}:{acl_digest}"
        )

    def search(self, request: SearchRequest) -> list[SearchResult]:
        return self.search_with_diagnostics(request).items

    def search_with_diagnostics(self, request: SearchRequest, extra_queries: list[str] | None = None) -> SearchOutcome:
        started = perf_counter()
        queries = self._query_list(request, extra_queries)
        processed = self.processor.process(queries[0])
        timings: dict[str, float] = {"query_processing": self._milliseconds(started)}
        if not processed.normalized:
            return self._empty(processed, timings, "检索内容为空")

        ranked_lists: list[tuple[str, list[Candidate], float]] = []
        keyword_all: list[Candidate] = []
        vector_all: list[Candidate] = []
        keyword_ms = vector_ms = 0.0
        for query in queries:
            item = self.processor.process(query)
            if not item.normalized:
                continue
            mark = perf_counter()
            keyword = self._keyword_candidates(item.normalized, request)
            keyword_ms += self._milliseconds(mark)
            mark = perf_counter()
            vector = self._vector_candidates(item.retrieval_text, request)
            vector_ms += self._milliseconds(mark)
            keyword_all = self._merge_candidates(keyword_all, keyword)
            vector_all = self._merge_candidates(vector_all, vector)
            ranked_lists.append(("keyword", keyword, self.config.keyword_weight))
            ranked_lists.append(("vector", vector, self.config.vector_weight))
        timings["keyword"] = round(keyword_ms, 2)
        timings["vector"] = round(vector_ms, 2)
        candidates = self._fuse_lists(ranked_lists, processed.normalized)
        candidate_count = len(candidates)
        stages = ({
            "keyword": [self._stage_item(item, item.keyword_score or 0.0) for item in keyword_all],
            "vector": [self._stage_item(item, item.vector_score or 0.0) for item in vector_all],
            "fusion": [self._stage_item(item, item.final_score) for item in candidates],
        } if request.include_stages else {})

        mark = perf_counter()
        ranked, warning, mode = self._rerank(processed.normalized, candidates)
        timings["rerank"] = self._milliseconds(mark)
        ranked = self._apply_feedback(ranked)
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
                stages=stages, queries=queries, retrieval_query=processed.normalized,
                rerank_applied=mode == "hybrid_rerank", candidate_count=candidate_count,
            ),
        )

    def restricted_candidate_ids(self, query: str, request: SearchRequest) -> set[uuid.UUID]:
        """返回“存在关键词命中、但当前用户无权访问”的片段 id。

        仅用于无答案归因（区分“没有资料”和“有资料但无权访问”），
        调用方不得把命中名称返回给用户。
        """
        if self.resolver is None or self.user is None or self.user.is_super_admin:
            return set()
        allowed = {item.chunk.id for item in self._keyword_candidates(query, request)}
        unrestricted = SearchService(self.session, self.settings, user=None, config=self.config)
        everything = {item.chunk.id for item in unrestricted._keyword_candidates(query, request)}
        return everything - allowed

    @staticmethod
    def _query_list(request: SearchRequest, extra_queries: list[str] | None) -> list[str]:
        queries = [request.query.strip()]
        for query in extra_queries or []:
            cleaned = (query or "").strip()
            if cleaned and cleaned not in queries:
                queries.append(cleaned)
        return queries

    @staticmethod
    def _merge_candidates(base: list[Candidate], extra: list[Candidate]) -> list[Candidate]:
        seen = {item.chunk.id for item in base}
        for item in extra:
            if item.chunk.id not in seen:
                base.append(item)
                seen.add(item.chunk.id)
        return base

    def _base_clauses(self, request: SearchRequest):
        # 先做权限过滤（active_retrieval_clauses + 可见性），再叠加结构化元数据过滤。
        clauses = active_retrieval_clauses()
        if self.resolver is not None:
            clauses.extend(self.resolver.visibility_clauses())
        if request.extension:
            clauses.append(Document.extension == request.extension.lower().lstrip("."))
        if request.document_name:
            clauses.append(Document.original_name.ilike(f"%{request.document_name.strip()}%"))
        if request.knowledge_base_id:
            clauses.append(Document.knowledge_base_id == request.knowledge_base_id)
        if request.knowledge_base_ids:
            clauses.append(Document.knowledge_base_id.in_(request.knowledge_base_ids))
        if request.tags:
            clauses.append(Document.tags.any(Tag.name.in_([tag.strip() for tag in request.tags if tag.strip()])))
        if request.created_from:
            clauses.append(Document.created_at >= datetime.combine(request.created_from, time.min, UTC))
        if request.created_to:
            clauses.append(Document.created_at < datetime.combine(request.created_to, time.min, UTC) + timedelta(days=1))
        if request.department_id:
            clauses.append(Document.owner_user_id.in_(
                select(User.id).where(User.department_id == request.department_id)
            ))
        if request.owner_user_id:
            clauses.append(Document.owner_user_id == request.owner_user_id)
        if request.document_status:
            clauses.append(Document.status == request.document_status)
        if request.relative_path:
            clauses.append(Document.relative_path.ilike(f"%{request.relative_path.strip()}%"))
        if request.version_number is not None:
            clauses.append(Document.version_number == request.version_number)
        if request.valid_only:
            now = datetime.now(UTC)
            clauses.append(or_(Document.valid_from.is_(None), Document.valid_from <= now))
            clauses.append(or_(Document.valid_until.is_(None), Document.valid_until >= now))
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
            ).order_by(rank.desc(), DocumentChunk.id).limit(self.config.keyword_limit)
        ).all()
        return [Candidate(row[0], row[1], keyword_score=float(row[2] or 0), sources={"keyword"}) for row in rows]

    def _vector_candidates(self, query: str, request: SearchRequest) -> list[Candidate]:
        vector = self.embeddings.encode_query(query)
        distance = DocumentChunk.embedding.cosine_distance(vector)
        rows = self.session.execute(
            select(DocumentChunk, Document, distance.label("distance")).join(Document).join(KnowledgeBase).where(
                *self._base_clauses(request), DocumentChunk.embedding.is_not(None),
                distance <= 1.0 - self.config.similarity_threshold,
            ).order_by(distance, DocumentChunk.id).limit(self.config.vector_limit)
        ).all()
        return [Candidate(row[0], row[1], vector_score=1.0 - float(row[2]), sources={"vector"}) for row in rows]

    def _fuse(self, keyword: list[Candidate], vector: list[Candidate], query: str) -> list[Candidate]:
        return self._fuse_lists([
            ("keyword", keyword, self.config.keyword_weight),
            ("vector", vector, self.config.vector_weight),
        ], query)

    def _fuse_lists(
        self, ranked_lists: list[tuple[str, list[Candidate], float]], query: str,
    ) -> list[Candidate]:
        """对任意数量的排序列表做 RRF 融合（多查询时会有 keyword/vector 多组）。"""
        values: dict[uuid.UUID, Candidate] = {}
        maximum = 0.0
        for source, ranked, weight in ranked_lists:
            maximum += weight / (self.config.rrf_k + 1)
            for rank, candidate in enumerate(ranked, start=1):
                existing = values.get(candidate.chunk.id)
                if existing is None:
                    existing = candidate
                    existing.sources = set()
                    values[candidate.chunk.id] = existing
                existing.sources.add(source)
                existing.keyword_score = candidate.keyword_score or existing.keyword_score
                existing.vector_score = candidate.vector_score or existing.vector_score
                existing.fusion_score += weight / (self.config.rrf_k + rank)
        maximum = maximum or 1.0
        for item in values.values():
            query_tokens = keyword_text(query).split()
            title = item.document.original_name.lower()
            title_bonus = 0.1 if query in title or any(token in title for token in query_tokens) else 0.0
            item.final_score = min(1.0, item.fusion_score / maximum + title_bonus)
        return sorted(values.values(), key=lambda item: (-item.final_score, str(item.chunk.id)))

    def _rerank(self, query: str, candidates: list[Candidate]) -> tuple[list[Candidate], str | None, str]:
        for index, item in enumerate(candidates, start=1):
            item.pre_rerank_rank = index
        selected = candidates[: self.config.rerank_candidate_limit]
        outcome = self.reranker.rerank(
            query, [item.chunk.content for item in selected],
            enabled=self.config.rerank_enabled, model=self.config.rerank_model,
        )
        if outcome.scores is None:
            for index, item in enumerate(candidates, start=1):
                item.post_rerank_rank = index
            return candidates, outcome.warning, "hybrid_rrf"
        for item, score in zip(selected, outcome.scores, strict=True):
            item.rerank_score = score
            item.final_score = 0.85 * score + 0.15 * item.final_score
        selected.sort(key=lambda item: (-item.final_score, str(item.chunk.id)))
        ordered = selected + candidates[len(selected):]
        for index, item in enumerate(ordered, start=1):
            item.post_rerank_rank = index
        return ordered, outcome.warning, "hybrid_rerank"

    def _apply_feedback(self, candidates: list[Candidate]) -> list[Candidate]:
        """在已召回候选上叠加反馈调整分；阈值仍按原始分判断，防止绕过证据门槛。"""
        if not self.feedback.enabled or not candidates:
            return candidates
        boosts = self.feedback.boosts([item.document.id for item in candidates])
        if not boosts:
            return candidates
        for item in candidates:
            boost = boosts.get(item.document.id, 0.0)
            item.feedback_boost = boost
            item.adjusted_score = max(0.0, min(1.0, item.final_score + boost))
        return sorted(candidates, key=lambda item: (-item.adjusted_score, str(item.chunk.id)))

    def _accept(self, candidates: list[Candidate], limit: int) -> list[Candidate]:
        accepted: list[Candidate] = []
        per_document: dict[uuid.UUID, int] = {}
        for item in candidates:
            if item.final_score < self.config.min_evidence_score:
                continue
            count = per_document.get(item.document.id, 0)
            if count >= self.config.per_document_limit:
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
        final_score = candidate.adjusted_score if candidate.feedback_boost else candidate.final_score
        return SearchResult(
            chunk_id=chunk.id, document_id=document.id, document_name=document.original_name,
            extension=document.extension, document_version=document.version_number,
            sequence_number=chunk.sequence_number, content=chunk.content,
            page_start=chunk.page_start, page_end=chunk.page_end, slide_number=chunk.slide_number,
            sheet_name=chunk.sheet_name, row_start=chunk.row_start, row_end=chunk.row_end,
            section_path=chunk.section_path, ocr_confidence=chunk.ocr_confidence, match_type=match_type,
            keyword_score=candidate.keyword_score, vector_score=candidate.vector_score,
            fusion_score=candidate.fusion_score, rerank_score=candidate.rerank_score,
            final_score=final_score, base_score=candidate.final_score, feedback_boost=candidate.feedback_boost,
            pre_rerank_rank=candidate.pre_rerank_rank, post_rerank_rank=candidate.post_rerank_rank,
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
