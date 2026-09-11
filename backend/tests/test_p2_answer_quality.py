"""P2-2 回答可靠性纯单元测试：置信度、引用校验、无答案归因与模板（不依赖数据库）。"""

from types import SimpleNamespace
import uuid

from app.schemas.answer import AnswerSource
from app.services.answer_quality import (
    HIGH, INSUFFICIENT, MEDIUM, NO_RELEVANT_DOCUMENT, classify_question, compute_confidence,
    mark_unsupported, no_answer_payload, template_instruction, verify_answer,
)


def _source(number: int, content: str) -> AnswerSource:
    return AnswerSource(
        citation_number=number, chunk_id=uuid.uuid4(), document_id=uuid.uuid4(),
        document_name="doc.txt", extension="txt", sequence_number=1, content=content,
        page_start=None, page_end=None, slide_number=None, sheet_name=None,
        row_start=None, row_end=None, section_path=[], ocr_confidence=None, match_type="hybrid",
    )


def _result(score: float, rerank: float | None = None) -> SimpleNamespace:
    return SimpleNamespace(final_score=score, rerank_score=rerank)


# ---------------------------------------------------------------- 问题分类与模板

def test_classify_question_types():
    assert classify_question("公司的报销制度是怎样的？") == "POLICY"
    assert classify_question("K8s 服务如何部署？") == "TECHNICAL"
    assert classify_question("气泡项目现在进展如何？") == "PROGRESS"
    assert classify_question("方案 A 和方案 B 有什么区别？") == "COMPARISON"
    assert classify_question("帮我汇总一下本周工作") == "SUMMARY"
    assert classify_question("你好") == "GENERAL"


def test_template_instruction_contains_sections():
    policy = template_instruction("POLICY")
    assert "适用范围" in policy and "办理步骤" in policy
    technical = template_instruction("TECHNICAL")
    assert "实施步骤" in technical and "风险" in technical


# ---------------------------------------------------------------- 置信度

def test_confidence_without_sources_is_insufficient():
    result = compute_confidence([], [], "")
    assert result.tier == INSUFFICIENT
    assert result.to_payload()["label"] == "资料不足"


def test_confidence_high_with_strong_evidence_and_citations():
    sources = [_source(1, "部署流程：先构建镜像再滚动更新"), _source(2, "部署流程需要构建镜像并滚动更新")]
    results = [_result(0.9, 0.95), _result(0.8, 0.9)]
    answer = "部署流程需要先构建镜像，再执行滚动更新[1][2]。"
    result = compute_confidence(results, sources, answer)
    assert result.tier == HIGH
    assert result.score > 0.6


def test_confidence_low_with_weak_scores():
    sources = [_source(1, "无关内容")]
    results = [_result(0.2)]
    result = compute_confidence(results, sources, "简短[1]。")
    assert result.tier in (MEDIUM, INSUFFICIENT)


# ---------------------------------------------------------------- 引用校验

def test_verify_answer_flags_invalid_citation_number():
    report = verify_answer("答案是 42[3]。", [_source(1, "内容")])
    assert 3 in report.invalid_numbers
    assert report.unsupported_sentences


def test_verify_answer_flags_unsupported_sentence():
    sources = [_source(1, "部署流程包括构建镜像和滚动更新")]
    report = verify_answer("今天天气很好适合出门散步[1]。", sources)
    assert report.unsupported_sentences
    assert not report.ok


def test_verify_answer_accepts_supported_sentence():
    sources = [_source(1, "部署流程包括构建镜像和滚动更新")]
    report = verify_answer("部署流程包括构建镜像和滚动更新[1]。", sources)
    assert report.ok


def test_verify_answer_marks_unavailable_citations():
    report = verify_answer("内容[1]。", [_source(1, "内容")], {1: "DELETED"})
    assert 1 in report.unavailable_citations
    assert not report.ok


def test_verify_answer_flags_stale_version_citation():
    report = verify_answer("部署流程包括构建镜像[1]。", [_source(1, "部署流程包括构建镜像")], stale={1: "VERSION_CHANGED"})
    assert 1 in report.stale_citations
    assert not report.ok
    assert report.to_payload()["stale_citations"] == [1]


def test_mark_unsupported_appends_inference_tag():
    sources = [_source(1, "部署流程")]
    report = verify_answer("这是没有依据的结论[1]。", sources)
    marked = mark_unsupported("这是没有依据的结论[1]。", report)
    assert "（推断）" in marked


# ---------------------------------------------------------------- 无答案

def test_no_answer_payload_uses_fixed_message():
    payload = no_answer_payload(NO_RELEVANT_DOCUMENT)
    assert payload["message"] == "当前可访问的公司资料中没有找到足够依据。"
    assert payload["missing_knowledge_reason"] == "缺失知识"
    assert payload["rephrase_suggestions"]
