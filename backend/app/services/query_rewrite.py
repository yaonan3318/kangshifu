"""P2-1 查询预处理：多轮上下文补全、Query Rewrite 与 Multi-query。

原则：
- 始终保留原始问题；改写只用于检索，不覆盖用户原问题；
- 只读取最近若干轮上下文，新建会话或明显切换话题时不继承；
- 任何 LLM 失败都回退到原问题，不阻塞检索；
- 改写提示词明确要求不得改变用户原意、不得添加用户没问的内容。
"""

from dataclasses import dataclass, field

from app.config import Settings
from app.llm import GenerationMessage, LlmError, OllamaClient
from app.services.retrieval_config import RetrievalConfig


@dataclass(frozen=True)
class QueryRewriteOutcome:
    original: str
    standalone_question: str
    retrieval_query: str
    queries: list[str] = field(default_factory=list)
    used_context: bool = False
    rewritten: bool = False
    warning: str | None = None

    def to_info(self) -> dict:
        return {
            "original": self.original,
            "standalone_question": self.standalone_question,
            "retrieval_query": self.retrieval_query,
            "queries": self.queries,
            "used_context": self.used_context,
            "rewritten": self.rewritten,
            "warning": self.warning,
        }


_REWRITE_SYSTEM = (
    "你是公司知识库的检索查询改写助手。请根据最近的对话，把用户当前问题补全为一个可独立理解的"
    "问题，并改写为更适合检索的查询。要求：\n"
    "1. 只依据用户已经表达过的信息，不得改变用户原意，不得添加用户没有问到的内容；\n"
    "2. 如果当前问题已经完整，或与历史对话无关（用户切换了话题），standalone_question 保持原问题，"
    "used_context 设为 false；\n"
    "3. 如果确实依赖上下文，才补全主语/对象，used_context 设为 true；\n"
    "4. 只输出 JSON：{\"standalone_question\": \"...\", \"retrieval_query\": \"...\", \"used_context\": true/false}。"
)

_MULTI_QUERY_SYSTEM = (
    "你是检索查询扩展助手。针对给定问题，生成多个不同角度但语义一致的检索表达，"
    "覆盖同义词、缩写、子主题与中英文说法，避免重复。只输出 JSON：{\"queries\": [\"...\", \"...\"]}。"
)


class QueryRewriteService:
    def __init__(self, settings: Settings, config: RetrievalConfig, ollama: OllamaClient | None = None):
        self.settings = settings
        self.config = config
        self.ollama = ollama or OllamaClient(settings)

    async def rewrite(self, question: str, history: list | None = None) -> QueryRewriteOutcome:
        question = question.strip()
        rewrite_enabled = self.config.query_rewrite_enabled
        context_enabled = self.config.context_completion_enabled
        if not rewrite_enabled and not context_enabled:
            return QueryRewriteOutcome(question, question, question, [question])
        recent = self._recent_turns(history) if context_enabled else []
        messages = self._rewrite_messages(question, recent)
        try:
            data = await self.ollama.complete_json(messages, model=self.config.query_rewrite_model or None)
        except LlmError as exc:
            return QueryRewriteOutcome(question, question, question, [question], warning=exc.message)
        if not isinstance(data, dict):
            return QueryRewriteOutcome(question, question, question, [question])
        standalone = str(data.get("standalone_question") or question).strip() or question
        retrieval = str(data.get("retrieval_query") or standalone).strip() or standalone
        used_context = bool(data.get("used_context")) and bool(recent)
        if not context_enabled:
            standalone, used_context = question, False
        if not rewrite_enabled:
            retrieval = standalone
        rewritten = retrieval != question
        return QueryRewriteOutcome(question, standalone, retrieval, [retrieval], used_context, rewritten)

    async def multi_query(self, retrieval_query: str) -> list[str]:
        if not self.config.multi_query_enabled:
            return [retrieval_query]
        count = max(2, min(4, self.config.multi_query_count))
        try:
            data = await self.ollama.complete_json(
                self._multi_query_messages(retrieval_query, count),
                model=self.config.query_rewrite_model or None,
            )
        except LlmError:
            return [retrieval_query]
        raw = data.get("queries") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return [retrieval_query]
        cleaned = [str(item).strip() for item in raw if str(item).strip()]
        return list(dict.fromkeys([retrieval_query, *cleaned]))[:count]

    def _recent_turns(self, history: list | None) -> list:
        if not history:
            return []
        turns = max(0, self.config.context_history_turns)
        return list(history)[-turns:] if turns else []

    @staticmethod
    def _rewrite_messages(question: str, recent: list) -> list[GenerationMessage]:
        if recent:
            lines = []
            for turn in recent:
                asked = getattr(turn, "question", None) or (turn.get("question") if isinstance(turn, dict) else "")
                answered = getattr(turn, "answer", None) or (turn.get("answer") if isinstance(turn, dict) else "")
                lines.append(f"用户：{asked}\n助手：{answered}")
            context = "\n".join(lines)
            user_content = f"最近对话：\n{context}\n\n当前问题：{question}"
        else:
            user_content = f"当前问题：{question}"
        return [
            GenerationMessage(role="system", content=_REWRITE_SYSTEM),
            GenerationMessage(role="user", content=user_content),
        ]

    @staticmethod
    def _multi_query_messages(retrieval_query: str, count: int) -> list[GenerationMessage]:
        return [
            GenerationMessage(role="system", content=_MULTI_QUERY_SYSTEM),
            GenerationMessage(role="user", content=f"问题：{retrieval_query}\n请生成 {count} 个检索表达。"),
        ]
