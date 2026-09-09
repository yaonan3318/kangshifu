"""RAG 编排层：检索证据、构造提示词、调用千问，并可选调用 DeepSeek 增强。

同时负责：
- 记录每次问答各阶段耗时与 token 数（answer/stream 把 metrics 持久化到 chat_messages）
- 相同问题、资料版本与检索配置未变化时命中内存缓存，避免重复检索与生成
- 上下文裁剪限制片段数量，保证本地模型在 Mac M3 Pro 上可用
"""

from collections import OrderedDict
from collections.abc import AsyncIterator
from time import perf_counter
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm import DeepSeekClient, GenerationMessage, LlmError, OllamaClient
from app.models import Assistant, Document, DocumentChunk, DocumentStatus
from app.schemas.answer import (
    AnswerEvent, AnswerProvider, AnswerRequest, AnswerSource, AnswerStatusResponse,
    AnswerWarning, KnowledgeScope,
)
from app.schemas.search import SearchRequest, SearchResult
from app.services.audit import SENSITIVE_LEVELS_EXTERNAL_BLOCKED
from app.services.search import SearchService

NO_INTERNAL_ANSWER = "公司资料库中没有找到能够回答这个问题的内部资料。"

# 简单进程内回答缓存（FIFO）；键包含资料版本指纹，资料变更会自动失效。
_answer_cache: OrderedDict[str, dict] = OrderedDict()


def _seconds_since(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)


class RagService:
    """把检索和两种 LLM 串联成可降级、可显示引用的流式问答。"""

    def __init__(self, session: Session, settings: Settings, user=None):
        self.settings = settings
        self.search_service = SearchService(session, settings, user=user)
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
        """逐阶段产生 SSE 事件；DeepSeek 失败时保留已生成的本地答案。

        事件顺序：
        stage(retrieving) -> sources -> [stage(local_generating) + deltas]
        -> [warning/stage(deepseek_enhancing) + deltas] -> metrics -> done
        """
        cfg = self._assistant_config(request)
        cache_key: str | None = None
        if self._cache_eligible(request, cfg):
            cache_key = self._cache_key(request, cfg)
            hit = _answer_cache.get(cache_key)
            if hit is not None:
                _answer_cache.move_to_end(cache_key)
                yield AnswerEvent(type="stage", stage="retrieving")
                yield AnswerEvent(type="sources", sources=hit["sources"])
                answer_text = hit["answer"] or NO_INTERNAL_ANSWER
                yield AnswerEvent(type="delta", provider=hit["provider"], text=answer_text)
                yield AnswerEvent(type="metrics", metrics={**hit["metrics"], "cache_hit": True})
                yield AnswerEvent(
                    type="done", provider=hit["provider"], scope=hit["scope"],
                    deepseek_requested=False, deepseek_used=False,
                    source_count=len(hit["sources"]),
                )
                return

        started = perf_counter()
        yield AnswerEvent(type="stage", stage="retrieving")
        outcome = self.search_service.search_with_diagnostics(self._search_request(request, cfg))
        results = outcome.items
        sources = self._sources(results)
        cfg["content_allows_external"] = not bool(self._restricted_document_ids([item.document_id for item in sources]))
        yield AnswerEvent(type="sources", sources=sources)
        scope = self._internal_scope(results)

        stage_timings = outcome.diagnostics.timings_ms
        local_stats: dict = {"first_token_ms": None, "generation_ms": None, "prompt_tokens": None, "completion_tokens": None}
        deepseek_stats: dict = {"first_token_ms": None, "generation_ms": None, "prompt_tokens": None, "completion_tokens": None}

        local_answer = ""
        # 无内部证据时禁止千问凭训练知识冒充公司资料回答。
        if sources:
            yield AnswerEvent(type="stage", stage="local_generating")
            try:
                generation_started = perf_counter()
                first_token: float | None = None
                prompt_tokens: int | None = None
                completion_tokens: int = 0
                async for item in self.ollama.stream_with_stats(
                    self._local_messages(request, sources, scope, cfg["system_prompt"]),
                    model=cfg["model_name"],
                    temperature=cfg["temperature"],
                ):
                    if item.get("prompt_eval_count") is not None:
                        prompt_tokens = int(item["prompt_eval_count"])
                    if item.get("eval_count") is not None:
                        completion_tokens = int(item["eval_count"])
                    delta = item.get("delta") or ""
                    if not delta:
                        continue
                    if first_token is None:
                        first_token = perf_counter() - generation_started
                    local_answer += delta
                    yield AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=delta)
                local_stats = {
                    "first_token_ms": _seconds_since(generation_started) if first_token is None else round(first_token * 1000, 2),
                    "generation_ms": _seconds_since(generation_started),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                }
            except LlmError as exc:
                yield AnswerEvent(type="error", error={"code": exc.code, "message": exc.message})
                return
        else:
            local_answer = NO_INTERNAL_ANSWER
            yield AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=local_answer)

        provider = AnswerProvider.LOCAL
        deepseek_used = False
        deepseek_blocked = request.use_deepseek and not cfg["deepseek_allowed"]
        content_blocked = bool(sources) and not cfg["content_allows_external"]
        # API Key 存在并不等于自动上传资料；助手允许、内容允许且用户（或默认配置）开启时才增强。
        if deepseek_blocked:
            yield AnswerEvent(
                type="warning",
                warning=AnswerWarning(
                    code="ASSISTANT_DEEPSEEK_BLOCKED",
                    message="当前助手策略不允许调用外部模型，本次使用本地模型回答。",
                ),
            )
        elif content_blocked:
            yield AnswerEvent(
                type="warning",
                warning=AnswerWarning(
                    code="EXTERNAL_LLM_BLOCKED",
                    message="资料策略禁止将检索到的资料发送到外部模型，本次使用本地模型回答。",
                ),
            )
        elif (request.use_deepseek or cfg["default_deepseek_enabled"]) and cfg["content_allows_external"]:
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
                    ds_started = perf_counter()
                    ds_first: float | None = None
                    async for delta in self.deepseek.stream(self._deepseek_messages(request, sources, local_answer, cfg["system_prompt"])):
                        if ds_first is None:
                            ds_first = perf_counter() - ds_started
                        enhanced_parts.append(delta)
                    combined = "".join(enhanced_parts)
                    deepseek_stats = {
                        "first_token_ms": None if ds_first is None else round(ds_first * 1000, 2),
                        "generation_ms": _seconds_since(ds_started),
                        "prompt_tokens": None,
                        "completion_tokens": self._estimate_tokens(combined),
                    }
                except LlmError as exc:
                    yield AnswerEvent(type="warning", warning=AnswerWarning(code=exc.code, message=exc.message))
                else:
                    enhanced = combined.strip()
                    if enhanced:
                        provider = AnswerProvider.DEEPSEEK
                        deepseek_used = True
                        scope = scope if sources else KnowledgeScope.GENERAL
                        yield AnswerEvent(type="replace", provider=provider, text="")
                        yield AnswerEvent(type="delta", provider=provider, text=enhanced)

        final_text = local_answer
        if deepseek_used and enhanced:
            final_text = enhanced
        metrics = {
            "query_processing_ms": stage_timings.get("query_processing"),
            "keyword_search_ms": stage_timings.get("keyword"),
            "vector_search_ms": stage_timings.get("vector"),
            "rerank_ms": stage_timings.get("rerank"),
            "retrieval_ms": stage_timings.get("total"),
            "llm_first_token_ms": (deepseek_stats if deepseek_used else local_stats).get("first_token_ms"),
            "llm_generation_ms": (deepseek_stats if deepseek_used else local_stats).get("generation_ms"),
            "prompt_tokens": (deepseek_stats if deepseek_used else local_stats).get("prompt_tokens"),
            "completion_tokens": (deepseek_stats if deepseek_used else local_stats).get("completion_tokens"),
            "total_ms": _seconds_since(started),
            "source_count": len(sources),
            "provider": provider.value,
            "cache_hit": False,
        }
        if cache_key is not None:
            self._store_cache(cache_key, final_text, provider, scope, sources, metrics)

        yield AnswerEvent(type="metrics", metrics=metrics)
        yield AnswerEvent(
            type="done", provider=provider, scope=scope,
            deepseek_requested=request.use_deepseek, deepseek_used=deepseek_used,
            source_count=len(sources),
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """没有官方 tokenizer 时的估算：中文近似 1 字 1 token，其余按字符 4 分之 1。"""
        cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        return int(cjk + (len(text) - cjk) / 4) or 1

    def _assistant_config(self, request: AnswerRequest) -> dict:
        """解析请求中的助手配置；返回默认值并避免助手禁用或不存在时报错。"""
        assistant = None
        if request.assistant_id is not None:
            row = self.search_service.session.get(Assistant, request.assistant_id)
            if row is not None and row.enabled:
                assistant = row
        kb_ids = None
        if assistant is not None and assistant.knowledge_bases:
            kb_ids = [kb.id for kb in assistant.knowledge_bases]
        return {
            "assistant": assistant,
            "kb_ids": kb_ids,
            "search_limit": assistant.retrieval_limit if assistant is not None else self.settings.rag_source_limit,
            "model_name": (assistant.model_name or None) if assistant is not None and assistant.model_provider == "ollama" else None,
            "temperature": assistant.temperature if assistant is not None else 0.2,
            "system_prompt": assistant.system_prompt if assistant is not None else None,
            "deepseek_allowed": assistant.use_deepseek_allowed if assistant is not None else True,
            "default_deepseek_enabled": assistant.default_deepseek_enabled if assistant is not None else False,
            "content_allows_external": True,
        }

    def _restricted_document_ids(self, document_ids: list) -> list:
        """返回禁止外发或达到敏感级别的文档 id；命中任一即禁止整次外部增强。"""
        if not document_ids:
            return []
        rows = self.search_service.session.scalars(
            select(Document.id).where(
                Document.id.in_(list(dict.fromkeys(document_ids))),
                or_(
                    Document.external_llm_allowed.is_(False),
                    Document.sensitivity_level.in_(list(SENSITIVE_LEVELS_EXTERNAL_BLOCKED)),
                ),
            )
        ).all()
        return list(rows)

    def _cache_eligible(self, request: AnswerRequest, cfg: dict) -> bool:
        return bool(
            self.settings.answer_cache_enabled and request.question.strip()
            and not request.use_deepseek and not cfg["default_deepseek_enabled"]
            and not request.use_harness and not request.regenerate_message_id
        )

    def _cache_key(self, request: AnswerRequest, cfg: dict) -> str:
        parts = [
            request.question.strip(),
            str(request.assistant_id or ""),
            str(request.knowledge_base_id or ""),
            str(request.extension or ""),
            str(cfg["search_limit"]),
            str(self.settings.rag_max_context_chars),
            cfg["model_name"] or self.settings.ollama_model,
            "-".join(sorted(str(item) for item in (cfg["kb_ids"] or []))),
            self._version_fingerprint(request, cfg),
        ]
        return uuid.uuid5(uuid.NAMESPACE_URL, "|".join(parts)).hex

    def _version_fingerprint(self, request: AnswerRequest, cfg: dict) -> str:
        """资料内容/状态指纹：停用、删除、编辑、重建索引都会改变指纹并让缓存失效。"""
        base = [Document.status == DocumentStatus.READY, Document.enabled.is_(True), Document.deleted_at.is_(None)]
        if request.knowledge_base_id:
            base.append(Document.knowledge_base_id == request.knowledge_base_id)
        elif cfg["kb_ids"]:
            base.append(Document.knowledge_base_id.in_(cfg["kb_ids"]))
        document = self.search_service.session.execute(
            select(func.count(Document.id), func.max(Document.updated_at)).where(*base)
        ).one()
        chunk = self.search_service.session.execute(
            select(func.count(DocumentChunk.id), func.max(DocumentChunk.updated_at))
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(*base, DocumentChunk.enabled.is_(True))
        ).one()
        return f"d{document[0]}:{document[1] or ''}|c{chunk[0]}:{chunk[1] or ''}"

    def _store_cache(
        self, key: str, answer: str, provider: AnswerProvider, scope: KnowledgeScope,
        sources: list[AnswerSource], metrics: dict,
    ) -> None:
        _answer_cache[key] = {
            "answer": answer, "provider": provider, "scope": scope,
            "sources": sources, "metrics": metrics,
        }
        _answer_cache.move_to_end(key)
        while len(_answer_cache) > self.settings.answer_cache_size:
            _answer_cache.popitem(last=False)

    def _search_request(self, request: AnswerRequest, cfg: dict) -> SearchRequest:
        return SearchRequest(
            query=request.question.strip(), extension=request.extension,
            document_name=request.document_name, created_from=request.created_from,
            created_to=request.created_to, knowledge_base_id=request.knowledge_base_id,
            knowledge_base_ids=cfg["kb_ids"] or [],
            limit=cfg["search_limit"],
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
                match_type=result.match_type, score=result.final_score,
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
        system_prompt: str | None = None,
    ) -> list[GenerationMessage]:
        """构造只允许依据内部证据、并要求使用 [n] 引用的千问提示词。"""
        evidence = self._format_evidence(sources)
        role_line = (
            system_prompt
            if system_prompt
            else "你是公司内部知识助手。请用中文直接回答，只能把给出的内部资料作为公司事实依据。"
        )
        system = (
            role_line
            + "每个关键结论使用真实的[n]编号引用；不得创造不存在的引用，也不要输出隐藏推理过程。"
            + ("当前资料依据有限，必须在答案中明确说明。" if scope == KnowledgeScope.INTERNAL_LIMITED else "")
        )
        messages = [GenerationMessage(role="system", content=system), *self._history_messages(request)]
        messages.append(GenerationMessage(
            role="user", content=f"内部资料：\n{evidence}\n\n当前问题：{request.question.strip()}",
        ))
        return messages

    def _deepseek_messages(
        self, request: AnswerRequest, sources: list[AnswerSource], local_answer: str,
        system_prompt: str | None = None,
    ) -> list[GenerationMessage]:
        """有证据时合并初稿；无证据时要求明确标记为通用知识。"""
        if sources:
            editor_role = "你是公司知识答案编辑，负责根据内部资料生成准确的中文答案。"
            system = (
                system_prompt + "\n" + editor_role
                if system_prompt
                else editor_role
            )
            system += "公司事实只能来自内部资料，保留并校正[n]引用，不得创造引用，不要描述合并过程。"
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
