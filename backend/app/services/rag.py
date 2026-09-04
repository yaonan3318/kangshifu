"""RAG 编排层：检索证据、构造提示词、调用千问，并可选调用 DeepSeek 增强。"""

from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app.config import Settings
from app.llm import DeepSeekClient, GenerationMessage, LlmError, OllamaClient
from app.schemas.answer import (
    AnswerEvent, AnswerProvider, AnswerRequest, AnswerSource, AnswerStatusResponse,
    AnswerWarning, KnowledgeScope,
)
from app.schemas.search import SearchRequest, SearchResult
from app.services.search import SearchService

NO_INTERNAL_ANSWER = "公司资料库中没有找到能够回答这个问题的内部资料。"


class RagService:
    """把检索和两种 LLM 串联成可降级、可显示引用的流式问答。"""

    def __init__(self, session: Session, settings: Settings):
        self.settings = settings
        self.search_service = SearchService(session, settings)
        self.ollama = OllamaClient(settings)
        self.deepseek = DeepSeekClient(settings)

    async def status(self) -> AnswerStatusResponse:
        """返回本地模型是否就绪以及 DeepSeek 是否配置。"""
        return AnswerStatusResponse(
            ollama=await self.ollama.status(),
            deepseek_configured=self.deepseek.configured,
            deepseek_model=self.settings.deepseek_model,
        )

    async def stream(self, request: AnswerRequest) -> AsyncIterator[AnswerEvent]:
        """逐阶段产生 SSE 事件；DeepSeek 失败时保留已生成的本地答案。"""
        yield AnswerEvent(type="stage", stage="retrieving")
        results = self.search_service.search(self._search_request(request))
        sources = self._sources(results)
        yield AnswerEvent(type="sources", sources=sources)
        scope = self._internal_scope(results)

        local_answer = ""
        # 无内部证据时禁止千问凭训练知识冒充公司资料回答。
        if sources:
            yield AnswerEvent(type="stage", stage="local_generating")
            try:
                async for delta in self.ollama.stream(self._local_messages(request, sources, scope)):
                    local_answer += delta
                    yield AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=delta)
            except LlmError as exc:
                yield AnswerEvent(type="error", error={"code": exc.code, "message": exc.message})
                return
        else:
            local_answer = NO_INTERNAL_ANSWER
            yield AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=local_answer)

        provider = AnswerProvider.LOCAL
        deepseek_used = False
        # API Key 存在并不等于自动上传资料；本次请求必须显式打开增强开关。
        if request.use_deepseek:
            if not self.deepseek.configured:
                yield AnswerEvent(
                    type="warning",
                    warning=AnswerWarning(
                        code="DEEPSEEK_NOT_CONFIGURED",
                        message="尚未配置 DeepSeek API Key，本次使用本地模型回答。",
                    ),
                )
            else:
                yield AnswerEvent(type="stage", stage="deepseek_enhancing")
                enhanced_parts: list[str] = []
                try:
                    async for delta in self.deepseek.stream(self._deepseek_messages(request, sources, local_answer)):
                        enhanced_parts.append(delta)
                except LlmError as exc:
                    yield AnswerEvent(type="warning", warning=AnswerWarning(code=exc.code, message=exc.message))
                else:
                    enhanced = "".join(enhanced_parts).strip()
                    if enhanced:
                        provider = AnswerProvider.DEEPSEEK
                        deepseek_used = True
                        scope = scope if sources else KnowledgeScope.GENERAL
                        yield AnswerEvent(type="replace", provider=provider, text="")
                        yield AnswerEvent(type="delta", provider=provider, text=enhanced)

        yield AnswerEvent(
            type="done", provider=provider, scope=scope,
            deepseek_requested=request.use_deepseek, deepseek_used=deepseek_used,
            source_count=len(sources),
        )

    def _search_request(self, request: AnswerRequest) -> SearchRequest:
        return SearchRequest(
            query=request.question.strip(), extension=request.extension,
            document_name=request.document_name, created_from=request.created_from,
            created_to=request.created_to, limit=self.settings.rag_source_limit,
        )

    def _sources(self, results: list[SearchResult]) -> list[AnswerSource]:
        """对命中片段去重并按字符预算裁剪，控制模型上下文大小。"""
        sources: list[AnswerSource] = []
        used_chars = 0
        seen = set()
        for result in results:
            if result.chunk_id in seen:
                continue
            remaining = self.settings.rag_max_context_chars - used_chars
            if remaining <= 0:
                break
            content = result.content[:remaining]
            if not content.strip():
                continue
            seen.add(result.chunk_id)
            used_chars += len(content)
            sources.append(AnswerSource(
                citation_number=len(sources) + 1, chunk_id=result.chunk_id,
                document_id=result.document_id, document_name=result.document_name,
                extension=result.extension, sequence_number=result.sequence_number,
                content=content, page_start=result.page_start, page_end=result.page_end,
                slide_number=result.slide_number, sheet_name=result.sheet_name,
                row_start=result.row_start, row_end=result.row_end,
                section_path=result.section_path, ocr_confidence=result.ocr_confidence,
                match_type=result.match_type,
            ))
        return sources

    @staticmethod
    def _internal_scope(results: list[SearchResult]) -> KnowledgeScope:
        if not results:
            return KnowledgeScope.NONE
        if any(result.match_type in ("keyword", "hybrid") for result in results):
            return KnowledgeScope.INTERNAL
        return KnowledgeScope.INTERNAL_LIMITED

    def _history_messages(self, request: AnswerRequest) -> list[GenerationMessage]:
        messages: list[GenerationMessage] = []
        for turn in request.history[-self.settings.rag_history_turns:]:
            messages.extend([
                GenerationMessage(role="user", content=turn.question),
                GenerationMessage(role="assistant", content=turn.answer),
            ])
        return messages

    def _local_messages(
        self, request: AnswerRequest, sources: list[AnswerSource], scope: KnowledgeScope,
    ) -> list[GenerationMessage]:
        """构造只允许依据内部证据、并要求使用 [n] 引用的千问提示词。"""
        evidence = self._format_evidence(sources)
        system = (
            "你是公司内部知识助手。请用中文直接回答，只能把给出的内部资料作为公司事实依据。"
            "每个关键结论使用真实的[n]编号引用；不得创造不存在的引用，也不要输出隐藏推理过程。"
            + ("当前资料依据有限，必须在答案中明确说明。" if scope == KnowledgeScope.INTERNAL_LIMITED else "")
        )
        messages = [GenerationMessage(role="system", content=system), *self._history_messages(request)]
        messages.append(GenerationMessage(
            role="user", content=f"内部资料：\n{evidence}\n\n当前问题：{request.question.strip()}",
        ))
        return messages

    def _deepseek_messages(
        self, request: AnswerRequest, sources: list[AnswerSource], local_answer: str,
    ) -> list[GenerationMessage]:
        """有证据时合并初稿；无证据时要求明确标记为通用知识。"""
        if sources:
            system = (
                "你是公司知识答案编辑。根据内部资料和千问初稿生成一份统一、准确的中文答案。"
                "公司事实只能来自内部资料，保留并校正[n]引用，不得创造引用，不要描述合并过程。"
            )
            content = (
                f"内部资料：\n{self._format_evidence(sources)}\n\n"
                f"千问本地初稿：\n{local_answer}\n\n当前问题：{request.question.strip()}"
            )
        else:
            system = (
                "内部资料库没有找到答案。请使用通用知识用中文回答，但开头必须明确写："
                "“以下内容来自 DeepSeek 通用知识，不是公司资料结论。”不得添加任何[n]内部引用。"
            )
            content = request.question.strip()
        return [GenerationMessage(role="system", content=system), *self._history_messages(request), GenerationMessage(role="user", content=content)]

    @staticmethod
    def _format_evidence(sources: list[AnswerSource]) -> str:
        sections = []
        for source in sources:
            location = RagService._source_location(source)
            sections.append(f"[{source.citation_number}] 文件：{source.document_name}；位置：{location}\n{source.content}")
        return "\n\n".join(sections)

    @staticmethod
    def _source_location(source: AnswerSource) -> str:
        if source.page_start:
            return f"第 {source.page_start} 页"
        if source.slide_number:
            return f"第 {source.slide_number} 张幻灯片"
        if source.sheet_name:
            return f"{source.sheet_name}，第 {source.row_start or '?'} 行起"
        return f"片段 {source.sequence_number}"
