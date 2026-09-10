"""检索实验室服务：保存标准问题并计算可比较的基础指标。"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import Document, RetrievalTestCase, RetrievalTestRun
from app.schemas.retrieval_lab import TestCaseCreate, TestCaseUpdate
from app.schemas.search import SearchRequest
from app.services.search import SearchService


class RetrievalEvaluationService:
    def __init__(self, session: Session, settings: Settings, user=None):
        self.session = session
        self.settings = settings
        self.user = user
        self.search = SearchService(session, settings, user=user)

    def list_cases(self) -> list[RetrievalTestCase]:
        return list(self.session.scalars(select(RetrievalTestCase).order_by(RetrievalTestCase.created_at.desc())))

    def get_case(self, case_id: uuid.UUID) -> RetrievalTestCase:
        value = self.session.get(RetrievalTestCase, case_id)
        if not value:
            raise AppError("RETRIEVAL_CASE_NOT_FOUND", "标准问题不存在", 404)
        return value

    def create_case(self, body: TestCaseCreate) -> RetrievalTestCase:
        self._validate_documents(body.expected_document_ids)
        value = RetrievalTestCase(
            name=body.name.strip(), question=body.question.strip(), knowledge_base_id=body.knowledge_base_id,
            expected_document_ids=[str(item) for item in body.expected_document_ids],
            expected_keywords=[item.strip() for item in body.expected_keywords if item.strip()],
            expected_no_answer=body.expected_no_answer, enabled=body.enabled,
        )
        self.session.add(value)
        self.session.commit()
        self.session.refresh(value)
        return value

    def update_case(self, case_id: uuid.UUID, body: TestCaseUpdate) -> RetrievalTestCase:
        value = self.get_case(case_id)
        supplied = body.model_fields_set
        if "expected_document_ids" in supplied and body.expected_document_ids is not None:
            self._validate_documents(body.expected_document_ids)
            value.expected_document_ids = [str(item) for item in body.expected_document_ids]
        for field in ("name", "question"):
            if field in supplied and getattr(body, field) is None:
                raise AppError("INVALID_RETRIEVAL_CASE", f"{field} 不能为空", 400)
        for field in ("name", "question", "knowledge_base_id", "expected_no_answer", "enabled"):
            if field in supplied:
                setattr(value, field, getattr(body, field))
        if "expected_keywords" in supplied and body.expected_keywords is not None:
            value.expected_keywords = [item.strip() for item in body.expected_keywords if item.strip()]
        self.session.commit()
        self.session.refresh(value)
        return value

    def delete_case(self, case_id: uuid.UUID) -> None:
        self.session.delete(self.get_case(case_id))
        self.session.commit()

    def run(self) -> RetrievalTestRun:
        cases = list(self.session.scalars(select(RetrievalTestCase).where(RetrievalTestCase.enabled.is_(True)).order_by(RetrievalTestCase.created_at)))
        if not cases:
            raise AppError("NO_RETRIEVAL_CASES", "没有已启用的标准问题", 409)
        outcomes = [self._run_case(case) for case in cases]
        count = len(outcomes)
        metrics = {
            "case_count": count,
            "recall_at_k": round(sum(item["recall_at_k"] for item in outcomes) / count, 4),
            "mrr": round(sum(item["reciprocal_rank"] for item in outcomes) / count, 4),
            "no_answer_accuracy": round(sum(item["no_answer_correct"] for item in outcomes) / count, 4),
            "average_latency_ms": round(sum(item["latency_ms"] for item in outcomes) / count, 2),
        }
        run = RetrievalTestRun(settings_snapshot=self._settings_snapshot(), results=outcomes, metrics=metrics)
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def list_runs(self) -> list[RetrievalTestRun]:
        return list(self.session.scalars(select(RetrievalTestRun).order_by(RetrievalTestRun.created_at.desc()).limit(50)))

    def get_run(self, run_id: uuid.UUID) -> RetrievalTestRun:
        value = self.session.get(RetrievalTestRun, run_id)
        if not value:
            raise AppError("RETRIEVAL_RUN_NOT_FOUND", "评测记录不存在", 404)
        return value

    def _run_case(self, case: RetrievalTestCase) -> dict:
        outcome = self.search.search_with_diagnostics(SearchRequest(
            query=case.question, knowledge_base_id=case.knowledge_base_id, limit=10,
        ))
        returned = [str(item.document_id) for item in outcome.items]
        expected = set(case.expected_document_ids)
        first_rank = next((index for index, item in enumerate(returned, start=1) if item in expected), None)
        has_answer = bool(outcome.items)
        content = "\n".join(item.content.lower() for item in outcome.items)
        return {
            "case_id": str(case.id), "name": case.name, "question": case.question,
            "returned_document_ids": returned,
            "recall_at_k": 1.0 if not expected or expected.intersection(returned) else 0.0,
            "reciprocal_rank": 1.0 / first_rank if first_rank else (1.0 if not expected else 0.0),
            "no_answer_correct": 1.0 if case.expected_no_answer == (not has_answer) else 0.0,
            "keyword_hits": [word for word in case.expected_keywords if word.lower() in content],
            "latency_ms": outcome.diagnostics.timings_ms.get("total", 0.0),
            "mode": outcome.diagnostics.mode, "warning": outcome.diagnostics.warning,
        }

    def _validate_documents(self, document_ids) -> None:
        for document_id in document_ids:
            value = self.session.scalar(select(Document.id).where(Document.id == document_id, Document.deleted_at.is_(None)))
            if not value:
                raise AppError("EXPECTED_DOCUMENT_UNAVAILABLE", f"预期文档不存在或已删除：{document_id}", 400)

    def _settings_snapshot(self) -> dict:
        return {
            "embedding_model": self.settings.embedding_model,
            "candidate_limit": self.settings.search_candidate_limit,
            "rrf_k": self.settings.search_rrf_k,
            "vector_min_similarity": self.settings.search_vector_min_similarity,
            "min_evidence_score": self.settings.search_min_evidence_score,
            "rerank_enabled": self.settings.rerank_enabled,
            "rerank_model": self.settings.rerank_model,
        }
