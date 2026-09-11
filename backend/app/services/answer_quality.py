"""P2-2 回答可靠性：答案置信度、引用校验、无答案归因与答案结构模板。

这些能力都只依赖检索证据与生成结果，不额外调用大模型，因此可复现、可测试。
"""

from dataclasses import dataclass, field
import re

from app.schemas.answer import AnswerSource
from app.services.keywords import keyword_text

CITATION_PATTERN = re.compile(r"\[(\d+)\]")
SENTENCE_PATTERN = re.compile(r"[^。！？!?\n]+[。！？!?\n]?")

# 无答案/低置信度归因码
NO_RELEVANT_DOCUMENT = "NO_RELEVANT_DOCUMENT"
PERMISSION_RESTRICTED = "PERMISSION_RESTRICTED"
LOW_RELEVANCE = "LOW_RELEVANCE"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
KB_SCOPE_UNCONFIGURED = "KB_SCOPE_UNCONFIGURED"

NO_ANSWER_MESSAGES = {
    NO_RELEVANT_DOCUMENT: "当前可访问的公司资料中没有找到足够依据。",
    PERMISSION_RESTRICTED: "检索到可能相关的资料，但当前账号没有访问权限，无法据此回答。",
    LOW_RELEVANCE: "检索到的资料与问题相关度较低，不足以形成可靠结论。",
    MODEL_UNAVAILABLE: "本地模型暂时不可用，请稍后重试。",
    KB_SCOPE_UNCONFIGURED: "当前助手尚未配置可访问的资料范围，请联系管理员。",
}

# 置信度分级：页面只展示中文分级，不展示裸分数。
HIGH = "HIGH"
MEDIUM = "MEDIUM"
INSUFFICIENT = "INSUFFICIENT"
CONFIDENCE_LABELS = {HIGH: "高可信", MEDIUM: "中等可信", INSUFFICIENT: "资料不足"}

# 问题类型与答案结构模板（章节顺序）。
GENERAL = "GENERAL"
QUESTION_TYPES = {
    "POLICY": {
        "label": "制度问题",
        "keywords": ["制度", "规定", "规范", "流程", "办理", "审批", "报销", "请假", "政策", "标准", "办法"],
        "sections": ["结论", "适用范围", "办理步骤", "注意事项"],
    },
    "TECHNICAL": {
        "label": "技术问题",
        "keywords": ["技术", "部署", "接口", "报错", "代码", "配置", "安装", "命令", "k8s", "kubernetes",
                     "docker", "数据库", "模型", "训练", "服务", "脚本"],
        "sections": ["结论", "实施步骤", "代码或命令", "风险"],
    },
    "PROGRESS": {
        "label": "项目进度",
        "keywords": ["进展", "进度", "状态", "时间线", "阻塞", "计划", "完成", "上线", "里程碑", "后续"],
        "sections": ["时间线", "当前状态", "阻塞问题", "下一步"],
    },
    "COMPARISON": {
        "label": "对比问题",
        "keywords": ["对比", "区别", "差异", "哪个好", "相比", "优劣", "不同"],
        "sections": ["对比表格", "差异", "建议"],
    },
    "SUMMARY": {
        "label": "汇总问题",
        "keywords": ["汇总", "总结", "综述", "归纳", "概览", "梳理", "有哪些"],
        "sections": ["主题归类", "关键结论", "引用来源"],
    },
    GENERAL: {
        "label": "通用问题",
        "keywords": [],
        "sections": ["直接结论", "依据", "补充说明"],
    },
}


def classify_question(question: str) -> str:
    """基于关键词的确定性分类；命中多个时按优先级取第一个。"""
    text = (question or "").lower()
    priority = ["COMPARISON", "PROGRESS", "POLICY", "TECHNICAL", "SUMMARY"]
    for question_type in priority:
        if any(keyword in text for keyword in QUESTION_TYPES[question_type]["keywords"]):
            return question_type
    return GENERAL


def template_instruction(question_type: str) -> str:
    """把答案结构模板转成系统提示词片段。"""
    config = QUESTION_TYPES.get(question_type, QUESTION_TYPES[GENERAL])
    sections = "、".join(config["sections"])
    return (
        f"这是一个{config['label']}。请严格按以下结构组织答案（用简短小标题）：{sections}。"
        "结构中的每一项都要有内部资料依据并带[n]引用；没有依据的部分必须省略或标注“推断”。"
    )


@dataclass(frozen=True)
class ConfidenceResult:
    tier: str
    score: float
    reasons: list[str] = field(default_factory=list)
    factors: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "tier": self.tier,
            "label": CONFIDENCE_LABELS.get(self.tier, "资料不足"),
            "reasons": self.reasons,
            "score": round(self.score, 4),
            "factors": self.factors,
        }


def _content_tokens(text: str) -> set[str]:
    return {token for token in keyword_text(text or "").split() if len(token) >= 2}


def _consistency(sources: list[AnswerSource]) -> float:
    if len(sources) < 2:
        return 1.0 if sources else 0.0
    token_sets = [_content_tokens(source.content) for source in sources[:5]]
    token_sets = [tokens for tokens in token_sets if tokens]
    if len(token_sets) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            union = token_sets[i] | token_sets[j]
            total += len(token_sets[i] & token_sets[j]) / len(union) if union else 0.0
            pairs += 1
    return total / pairs if pairs else 0.0


def _citation_coverage(answer: str, sources: list[AnswerSource]) -> float:
    if not answer.strip() or not sources:
        return 0.0
    valid = {source.citation_number for source in sources}
    sentences = [sentence for sentence in SENTENCE_PATTERN.findall(answer) if sentence.strip()]
    if not sentences:
        return 0.0
    covered = 0
    for sentence in sentences:
        numbers = {int(number) for number in CITATION_PATTERN.findall(sentence)}
        if numbers and numbers <= valid:
            covered += 1
    return covered / len(sentences)


def compute_confidence(
    results: list, sources: list[AnswerSource], answer: str,
) -> ConfidenceResult:
    """综合召回分、精排分、片段数量、一致性与引用覆盖度给出分级。"""
    if not sources:
        return ConfidenceResult(INSUFFICIENT, 0.0, ["没有检索到可用证据"], {"source_count": 0})
    retrieval = max((getattr(item, "final_score", 0.0) or 0.0) for item in results) if results else 0.0
    rerank_values = [getattr(item, "rerank_score", None) for item in results]
    rerank_values = [value for value in rerank_values if value is not None]
    rerank = max(rerank_values) if rerank_values else retrieval
    count_factor = min(1.0, len(sources) / 3.0)
    consistency = _consistency(sources)
    coverage = _citation_coverage(answer, sources)
    score = (
        0.32 * retrieval + 0.24 * rerank + 0.16 * count_factor
        + 0.13 * consistency + 0.15 * coverage
    )
    reasons: list[str] = []
    if retrieval >= 0.6:
        reasons.append("召回分数较高")
    if len(sources) >= 2:
        reasons.append(f"有 {len(sources)} 个相互印证的片段")
    if coverage >= 0.6:
        reasons.append("答案引用覆盖较完整")
    if consistency < 0.2:
        reasons.append("片段之间一致性偏低")
    if coverage < 0.4:
        reasons.append("部分结论缺少引用")
    if score >= 0.68:
        tier = HIGH
    elif score >= 0.42:
        tier = MEDIUM
    else:
        tier = INSUFFICIENT
    return ConfidenceResult(tier, score, reasons, {
        "retrieval": round(retrieval, 4), "rerank": round(rerank, 4),
        "source_count": len(sources), "consistency": round(consistency, 4),
        "citation_coverage": round(coverage, 4),
    })


@dataclass
class CitationReport:
    checked: int = 0
    supported: int = 0
    invalid_numbers: list[int] = field(default_factory=list)
    unsupported_sentences: list[str] = field(default_factory=list)
    unavailable_citations: list[int] = field(default_factory=list)
    # 版本已更新 / 位置不一致的引用；与“不可访问”区分，提示用户重新核对。
    stale_citations: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.invalid_numbers or self.unsupported_sentences or self.unavailable_citations
            or self.stale_citations
        )

    def to_payload(self) -> dict:
        return {
            "checked": self.checked, "supported": self.supported,
            "invalid_numbers": self.invalid_numbers,
            "unsupported_sentences": self.unsupported_sentences,
            "unavailable_citations": self.unavailable_citations,
            "stale_citations": self.stale_citations,
            "ok": self.ok,
        }


def verify_answer(
    answer: str, sources: list[AnswerSource], unavailable: dict[int, str] | None = None,
    stale: dict[int, str] | None = None,
) -> CitationReport:
    """校验引用编号、真实片段、事实支持度、可用性与版本/位置一致性；返回报告。"""
    report = CitationReport()
    if not answer.strip():
        return report
    valid = {source.citation_number: source for source in sources}
    unavailable = unavailable or {}
    stale = stale or {}
    sentences = [sentence.strip() for sentence in SENTENCE_PATTERN.findall(answer) if sentence.strip()]
    for sentence in sentences:
        report.checked += 1
        numbers = {int(number) for number in CITATION_PATTERN.findall(sentence)}
        invalid = sorted(number for number in numbers if number not in valid)
        if invalid:
            report.invalid_numbers.extend(number for number in invalid if number not in report.invalid_numbers)
            report.unsupported_sentences.append(sentence)
            continue
        if not numbers:
            # 没有引用且内容较长的句子视为缺少依据。
            if len(sentence) >= 20:
                report.unsupported_sentences.append(sentence)
            else:
                report.supported += 1
            continue
        cited = " ".join(valid[number].content for number in numbers if number in valid)
        sentence_tokens = _content_tokens(CITATION_PATTERN.sub("", sentence))
        cited_tokens = _content_tokens(cited)
        if sentence_tokens and cited_tokens and not (sentence_tokens & cited_tokens):
            report.unsupported_sentences.append(sentence)
        else:
            report.supported += 1
    for number, reason in unavailable.items():
        if number not in report.unavailable_citations:
            report.unavailable_citations.append(number)
    for number in stale:
        if number not in report.stale_citations:
            report.stale_citations.append(number)
    report.unavailable_citations.sort()
    report.stale_citations.sort()
    return report


def mark_unsupported(answer: str, report: CitationReport) -> str:
    """把没有依据的句子标记为“推断”，不直接删除用户可见内容。"""
    if not report.unsupported_sentences:
        return answer
    result = answer
    for sentence in report.unsupported_sentences:
        stripped = sentence.strip()
        if not stripped or "（推断）" in stripped:
            continue
        result = result.replace(stripped, f"{stripped}（推断）", 1)
    return result


def no_answer_payload(
    reason: str, *, recommended_documents: list[dict] | None = None,
    rephrase_suggestions: list[str] | None = None, allow_deepseek: bool = False,
    deepseek_configured: bool = False,
) -> dict:
    return {
        "reason": reason,
        "message": NO_ANSWER_MESSAGES.get(reason, NO_ANSWER_MESSAGES[NO_RELEVANT_DOCUMENT]),
        "recommended_documents": recommended_documents or [],
        "rephrase_suggestions": rephrase_suggestions or [
            "换用更具体的关键词（项目名、时间、模块）",
            "尝试公司内部缩写或英文说法",
            "补充问题背景后重新提问",
        ],
        "allow_deepseek": allow_deepseek,
        "deepseek_configured": deepseek_configured,
        "missing_knowledge_reason": "缺失知识",
    }
