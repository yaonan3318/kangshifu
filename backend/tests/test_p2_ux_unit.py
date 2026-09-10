"""P2-5 用户体验纯单元测试：缺口归一化、状态校验与推荐追问启发式。"""

from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.models import KnowledgeGapReason, KnowledgeGapStatus
from app.services.knowledge_gaps import KnowledgeGapService, normalize_question
from app.services.rag import RagService


def test_normalize_question_collapses_space_and_case():
    assert normalize_question("  Hello   World  ") == "hello world"
    assert normalize_question("") == ""
    assert len(normalize_question("x" * 500)) == 255


def test_knowledge_gap_status_and_reason_validation():
    assert KnowledgeGapService._status("OPEN") == KnowledgeGapStatus.OPEN
    assert KnowledgeGapService._reason("NO_ANSWER") == KnowledgeGapReason.NO_ANSWER
    with pytest.raises(AppError):
        KnowledgeGapService._status("BAD")
    with pytest.raises(AppError):
        KnowledgeGapService._reason("BAD")


def test_heuristic_suggestions_use_sources_and_question():
    request = SimpleNamespace(question="气泡检测项目进展怎么样？")
    sources = [SimpleNamespace(document_name="气泡周报.docx"), SimpleNamespace(document_name="气泡周报.docx")]
    suggestions = RagService._heuristic_suggestions(request, sources)
    assert 1 <= len(suggestions) <= 4
    assert any("气泡周报.docx" in item for item in suggestions)
    assert any("依据" in item for item in suggestions)
