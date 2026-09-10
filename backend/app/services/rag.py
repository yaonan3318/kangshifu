"""RAG 编排层：检索证据、构造提示词、调用千问，并可选调用 DeepSeek 增强。

同时负责：
- 记录每次问答各阶段耗时与 token 数（answer/stream 把 metrics 持久化到 chat_messages）
- 相同问题、资料版本与检索配置未变化时命中内存缓存，避免重复检索与生成
- 上下文裁剪限制片段数量，保证本地模型在 Mac M3 Pro 上可用
"""

from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import replace
from time import perf_counter
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm import DeepSeekClient, GenerationMessage, LlmError, OllamaClient
from app.models import Assistant, Chatflow, Document, DocumentChunk, DocumentStatus
from app.schemas.answer import (
    AnswerEvent, AnswerProvider, AnswerRequest, AnswerSource, AnswerStatusResponse,
    AnswerWarning, KnowledgeScope,
)
from app.schemas.search import QueryRewriteInfo, SearchRequest, SearchResult
from app.services.answer_quality import (
    GENERAL, INSUFFICIENT, LOW_RELEVANCE, MODEL_UNAVAILABLE, NO_RELEVANT_DOCUMENT,
    PERMISSION_RESTRICTED, QUESTION_TYPES, classify_question, compute_confidence,
    mark_unsupported, no_answer_payload, template_instruction, verify_answer,
)
from app.services.audit import SENSITIVE_LEVELS_EXTERNAL_BLOCKED
from app.services.chatflow import ChatflowPlan, ChatflowService, build_plan
from app.services.query_rewrite import QueryRewriteService
from app.services.retrieval_config import RetrievalConfig
from app.services.search import SearchService

NO_INTERNAL_ANSWER = "公司资料库中没有找到能够回答这个问题的内部资料。"

# 简单进程内回答缓存（FIFO）；键包含资料版本指纹，资料变更会自动失效。
_answer_cache: OrderedDict[str, dict] = OrderedDict()


def _seconds_since(started: float) -> float:
    return round((perf_counter() - started) * 1000, 2)


class RagService:
    """把检索和两种 LLM 串联成可降级、可显示引用的流式问答。"""

    def __init__(self, session: Session, settings: Settings, user=None, config=None, source_limit: int | None = None):
        self.settings = settings
        self.config = config or RetrievalConfig.from_settings(settings)
        self.search_service = SearchService(session, settings, user=user, config=self.config)
        self.source_limit = source_limit
        self.ollama = OllamaClient(settings)
        self.deepseek = DeepSeekClient(settings)
        # 允许测试注入改写器，避免批量评测/测试访问真实模型。
        self.rewrite_factory = QueryRewriteService

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
        plan = build_plan(cfg.get("chatflow"))
        if plan is not None:
            # 绑定 Chatflow 时以图中节点开关为准；未绑定时沿用运行时配置。
            self.config = self._apply_plan(self.config, plan)
            self.search_service.config = self.config
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
                quality = hit.get("quality") or {}
                if quality.get("citation_check"):
                    yield AnswerEvent(type="citation_check", citation_check=quality["citation_check"])
                if quality.get("no_answer"):
                    yield AnswerEvent(type="no_answer", no_answer=quality["no_answer"])
                if quality.get("confidence"):
                    yield AnswerEvent(
                        type="confidence", confidence=quality["confidence"],
                        question_type=quality.get("question_type"),
                    )
                yield AnswerEvent(type="metrics", metrics={**hit["metrics"], "cache_hit": True})
                yield AnswerEvent(
                    type="done", provider=hit["provider"], scope=hit["scope"],
                    deepseek_requested=False, deepseek_used=False,
                    source_count=len(hit["sources"]), question_type=quality.get("question_type"),
                )
                return

        started = perf_counter()
        yield AnswerEvent(type="stage", stage="understanding")
        # 助手可以指定固定答案模板；AUTO 时按问题类型自动分类。
        configured_template = cfg.get("answer_template") or "AUTO"
        if configured_template != "AUTO":
            question_type = configured_template
        elif plan is not None and not plan.classify_enabled:
            question_type = GENERAL
        else:
            question_type = classify_question(request.question)
        rewrite_info, retrieval_query, queries, rewrite_ms = await self._prepare_queries(request)
        if rewrite_info is not None:
            yield AnswerEvent(type="query_rewrite", query_rewrite=rewrite_info)
        yield AnswerEvent(type="stage", stage="rewriting", detail={"queries": queries})
        knowledge_base_count = len(cfg["kb_ids"]) if cfg["kb_ids"] else None
        yield AnswerEvent(type="stage", stage="retrieving", detail={"knowledge_base_count": knowledge_base_count})
        search_request = self._search_request(request, cfg, query=retrieval_query)
        outcome = self.search_service.search_with_diagnostics(search_request, extra_queries=queries[1:])
        results = outcome.items
        sources = self._sources(results)
        cfg["content_allows_external"] = not bool(self._restricted_document_ids([item.document_id for item in sources]))
        yield AnswerEvent(type="stage", stage="candidates", detail={
            "candidate_count": outcome.diagnostics.candidate_count,
            "source_count": len(sources),
        })
        if outcome.diagnostics.rerank_applied:
            yield AnswerEvent(type="stage", stage="reranking")
        yield AnswerEvent(type="sources", sources=sources)
        scope = self._internal_scope(results)

        stage_timings = outcome.diagnostics.timings_ms
        stage_timings["query_rewrite"] = rewrite_ms
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
                    self._local_messages(request, sources, scope, cfg["system_prompt"], question_type),
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
                yield AnswerEvent(type="no_answer", no_answer=no_answer_payload(
                    MODEL_UNAVAILABLE, allow_deepseek=cfg["deepseek_enabled"],
                    deepseek_configured=self.deepseek.configured,
                ))
                yield AnswerEvent(type="error", error={"code": exc.code, "message": exc.message})
                return
        else:
            local_answer = NO_INTERNAL_ANSWER
            yield AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=local_answer)

        provider = AnswerProvider.LOCAL
        deepseek_used = False
        deepseek_blocked = cfg["deepseek_enabled"] and not cfg["deepseek_allowed"]
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
        # STRICT 无答案策略下，没有内部资料时不允许用通用知识“补答”。
        elif (
            cfg["deepseek_enabled"] and cfg["content_allows_external"]
            and (bool(sources) or cfg.get("no_answer_policy") != "STRICT")
            and (plan is None or plan.deepseek_enabled)
        ):
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
                    async for delta in self.deepseek.stream(self._deepseek_messages(
                        request, sources, local_answer, cfg["system_prompt"], question_type,
                    )):
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

        # P2-2：引用真实性校验 + 答案置信度；资料不足时禁止模型猜测。
        confidence = compute_confidence(results, sources, final_text)
        citation_report = None
        no_answer = None
        answer_check_ms = 0.0
        # Chatflow 关闭答案校验节点时跳过引用校验。
        if sources and (plan is None or plan.answer_check_enabled):
            yield AnswerEvent(type="stage", stage="checking")
            check_started = perf_counter()
            citation_report = verify_answer(final_text, sources, self._unavailable_citations(sources))
            marked = mark_unsupported(final_text, citation_report)
            if marked != final_text:
                final_text = marked
                yield AnswerEvent(type="replace", provider=provider, text="")
                yield AnswerEvent(type="delta", provider=provider, text=final_text)
            answer_check_ms = _seconds_since(check_started)
            yield AnswerEvent(type="citation_check", citation_check=citation_report.to_payload())
        if confidence.tier == INSUFFICIENT:
            reason = LOW_RELEVANCE if sources else self._no_answer_reason(outcome, retrieval_query, search_request)
            policy = cfg.get("no_answer_policy") or "SUGGEST"
            no_answer = no_answer_payload(
                reason,
                recommended_documents=(
                    [] if policy == "STRICT"
                    else self._recommended_documents(retrieval_query, search_request)
                ),
                allow_deepseek=cfg["deepseek_enabled"] and policy != "STRICT",
                deepseek_configured=self.deepseek.configured,
            )
            # DeepSeek 通用知识答案本身已明确声明不是公司资料，保留它不做替换。
            if final_text != no_answer["message"] and not (deepseek_used and not sources):
                final_text = no_answer["message"]
                yield AnswerEvent(type="replace", provider=provider, text="")
                yield AnswerEvent(type="delta", provider=provider, text=final_text)
            yield AnswerEvent(type="no_answer", no_answer=no_answer)
        yield AnswerEvent(type="confidence", confidence=confidence.to_payload(), question_type=question_type)
        suggestions = await self._follow_up_suggestions(request, final_text, sources)
        if suggestions:
            yield AnswerEvent(type="suggestions", suggestions=suggestions)

        metrics = {
            "query_processing_ms": stage_timings.get("query_processing"),
            "query_rewrite_ms": stage_timings.get("query_rewrite"),
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
            # 记录实际用于检索的问题，便于追溯与在检索实验室展示。
            "retrieval_query": retrieval_query,
            "retrieval_queries": queries,
            "query_rewrite": rewrite_info.model_dump() if rewrite_info is not None else None,
            "question_type": question_type,
            "question_type_label": QUESTION_TYPES.get(question_type, QUESTION_TYPES[GENERAL])["label"],
            "confidence": confidence.to_payload(),
            "citation_check": citation_report.to_payload() if citation_report is not None else None,
            "no_answer": no_answer,
            "suggestions": suggestions,
            # P2-4：按节点记录耗时，供检索实验室/调试面板展示。
            "node_timings": {
                "classify": 0.0,
                "rewrite": stage_timings.get("query_rewrite") or 0.0,
                "retrieval": stage_timings.get("total") or 0.0,
                "rerank": stage_timings.get("rerank") or 0.0,
                "local_model": local_stats.get("generation_ms") or 0.0,
                "deepseek": deepseek_stats.get("generation_ms") or 0.0,
                "answer_check": answer_check_ms,
                "final_answer": _seconds_since(started),
            },
            "chatflow_id": (cfg.get("assistant").chatflow_id if cfg.get("assistant") else None),
        }
        quality = {
            "question_type": question_type,
            "confidence": confidence.to_payload(),
            "citation_check": citation_report.to_payload() if citation_report is not None else None,
            "no_answer": no_answer,
        }
        if cache_key is not None:
            self._store_cache(cache_key, final_text, provider, scope, sources, metrics, quality)

        yield AnswerEvent(type="metrics", metrics=metrics)
        yield AnswerEvent(
            type="done", provider=provider, scope=scope,
            deepseek_requested=cfg["deepseek_enabled"], deepseek_used=deepseek_used,
            source_count=len(sources), question_type=question_type,
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
            "search_limit": (
                assistant.retrieval_limit if assistant is not None
                else (self.source_limit or self.settings.rag_source_limit)
            ),
            "model_name": (assistant.model_name or None) if assistant is not None and assistant.model_provider == "ollama" else None,
            "temperature": assistant.temperature if assistant is not None else 0.2,
            "system_prompt": assistant.system_prompt if assistant is not None else None,
            "deepseek_allowed": assistant.use_deepseek_allowed if assistant is not None else True,
            "default_deepseek_enabled": assistant.default_deepseek_enabled if assistant is not None else False,
            "deepseek_enabled": assistant.deepseek_enabled if assistant is not None else False,
            # P2-3 角色增强：默认答案模板、无答案策略与联网开关。
            "answer_template": assistant.answer_template if assistant is not None else "AUTO",
            "no_answer_policy": assistant.no_answer_policy if assistant is not None else "SUGGEST",
            "internet_enabled": assistant.internet_enabled if assistant is not None else False,
            # P2-4：助手绑定的已发布 Chatflow（未绑定/未发布时为 None，使用内置默认流程）。
            "chatflow": self._assistant_chatflow(assistant),
            "content_allows_external": True,
        }

    def _assistant_chatflow(self, assistant) -> dict | None:
        if assistant is None or assistant.chatflow_id is None:
            return None
        flow = self.search_service.session.get(Chatflow, assistant.chatflow_id)
        return ChatflowService.active_graph(flow)

    @staticmethod
    def _apply_plan(config: RetrievalConfig, plan: ChatflowPlan) -> RetrievalConfig:
        return replace(
            config,
            query_rewrite_enabled=plan.rewrite_enabled,
            multi_query_enabled=plan.multi_query_enabled,
            rerank_enabled=plan.rerank_enabled,
        )

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
        # 开启改写/多查询时结果可能随上下文变化，跳过缓存以保证每次真实检索。
        if self.config.query_rewrite_enabled or self.config.multi_query_enabled:
            return False
        return bool(
            self.settings.answer_cache_enabled and request.question.strip()
            and not cfg["deepseek_enabled"]
            and not request.use_harness and not request.regenerate_message_id
        )

    def _cache_key(self, request: AnswerRequest, cfg: dict) -> str:
        parts = [
            request.question.strip(),
            self.search_service.permission_cache_scope(),
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
        sources: list[AnswerSource], metrics: dict, quality: dict | None = None,
    ) -> None:
        _answer_cache[key] = {
            "answer": answer, "provider": provider, "scope": scope,
            "sources": sources, "metrics": metrics, "quality": quality or {},
        }
        _answer_cache.move_to_end(key)
        while len(_answer_cache) > self.settings.answer_cache_size:
            _answer_cache.popitem(last=False)

    async def _prepare_queries(
        self, request: AnswerRequest,
    ) -> tuple[QueryRewriteInfo | None, str, list[str], float]:
        """按配置执行上下文补全 / Query Rewrite / Multi-query；失败时回退原问题。"""
        question = request.question.strip()
        rewrite_enabled = (
            self.config.query_rewrite_enabled if request.use_query_rewrite is None
            else request.use_query_rewrite
        )
        multi_enabled = (
            self.config.multi_query_enabled if request.use_multi_query is None
            else request.use_multi_query
        )
        history = list(request.history or [])
        needs_context = self.config.context_completion_enabled and bool(history)
        if not rewrite_enabled and not multi_enabled and not needs_context:
            return None, question, [question], 0.0
        effective = replace(
            self.config, query_rewrite_enabled=rewrite_enabled, multi_query_enabled=multi_enabled,
        )
        rewriter = self.rewrite_factory(self.settings, effective, ollama=self.ollama)
        mark = perf_counter()
        outcome = await rewriter.rewrite(question, history)
        queries = await rewriter.multi_query(outcome.retrieval_query)
        if outcome.retrieval_query not in queries:
            queries.insert(0, outcome.retrieval_query)
        return QueryRewriteInfo(**outcome.to_info()), outcome.retrieval_query, queries, _seconds_since(mark)

    def _search_request(self, request: AnswerRequest, cfg: dict, query: str | None = None) -> SearchRequest:
        return SearchRequest(
            query=(query or request.question).strip(), extension=request.extension,
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
                extension=result.extension, document_version=result.document_version,
                sequence_number=result.sequence_number,
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

    def _unavailable_citations(self, sources: list[AnswerSource]) -> dict[int, str]:
        """返回引用编号 -> 不可用状态（删除/停用/无权），用于引用真实性校验。"""
        unavailable: dict[int, str] = {}
        resolver = self.search_service.resolver
        for source in sources:
            document = self.search_service.session.get(Document, source.document_id)
            if document is None:
                unavailable[source.citation_number] = "DELETED"
            elif resolver is not None and not resolver.can_read(document):
                unavailable[source.citation_number] = "FORBIDDEN"
            elif document.deleted_at is not None:
                unavailable[source.citation_number] = "DELETED"
            elif not document.enabled:
                unavailable[source.citation_number] = "DISABLED"
        return unavailable

    async def _follow_up_suggestions(self, request: AnswerRequest, answer: str, sources: list) -> list[str]:
        """生成 2~4 个推荐追问；默认启发式，开启后可用本地模型生成。"""
        if not self.settings.follow_up_enabled or not (answer or "").strip():
            return []
        if self.settings.follow_up_llm_enabled:
            try:
                data = await self.ollama.complete_json([
                    GenerationMessage(
                        role="system",
                        content="根据问题与答案生成 2~4 个用户可能继续追问的简短中文问题，只输出 JSON {\"questions\": [\"...\"]}。",
                    ),
                    GenerationMessage(role="user", content=f"问题：{request.question}\n答案：{answer[:1500]}"),
                ])
                raw = data.get("questions") if isinstance(data, dict) else None
                if isinstance(raw, list):
                    cleaned = [str(item).strip() for item in raw if str(item).strip()][:4]
                    if cleaned:
                        return cleaned
            except Exception:
                pass
        return self._heuristic_suggestions(request, sources)

    @staticmethod
    def _heuristic_suggestions(request: AnswerRequest, sources: list) -> list[str]:
        suggestions: list[str] = []
        names = list(dict.fromkeys(source.document_name for source in sources))[:1]
        if names:
            suggestions.append(f"《{names[0]}》还有哪些细节？")
        question = request.question.strip().rstrip("？?")
        if question:
            suggestions.append(f"{question} 的依据是什么？")
        suggestions.append("还有其他相关资料吗？")
        return list(dict.fromkeys(suggestions))[:4]

    def _recommended_documents(self, query: str, request: SearchRequest, limit: int = 3) -> list[dict]:
        """推荐用户有权访问的相关文档；只返回名称，不泄露无权访问的资料。"""
        try:
            candidates = self.search_service._keyword_candidates(query, request)
        except Exception:
            return []
        recommended: dict[uuid.UUID, dict] = {}
        for candidate in candidates:
            document = candidate.document
            recommended.setdefault(document.id, {"id": str(document.id), "name": document.original_name})
            if len(recommended) >= limit:
                break
        return list(recommended.values())

    def _no_answer_reason(self, outcome, query: str, request: SearchRequest) -> str:
        if self.search_service.restricted_candidate_ids(query, request):
            return PERMISSION_RESTRICTED
        if outcome.diagnostics.candidate_count > 0:
            return LOW_RELEVANCE
        return NO_RELEVANT_DOCUMENT

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
        system_prompt: str | None = None, question_type: str = GENERAL,
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
            + " " + template_instruction(question_type)
            + ("当前资料依据有限，必须在答案中明确说明。" if scope == KnowledgeScope.INTERNAL_LIMITED else "")
        )
        messages = [GenerationMessage(role="system", content=system), *self._history_messages(request)]
        messages.append(GenerationMessage(
            role="user", content=f"内部资料：\n{evidence}\n\n当前问题：{request.question.strip()}",
        ))
        return messages

    def _deepseek_messages(
        self, request: AnswerRequest, sources: list[AnswerSource], local_answer: str,
        system_prompt: str | None = None, question_type: str = GENERAL,
    ) -> list[GenerationMessage]:
        """有证据时合并初稿；无证据时要求明确标记为通用知识。"""
        if sources:
            editor_role = "你是公司知识答案编辑，负责根据内部资料生成准确的中文答案。"
            system = (
                system_prompt + "\n" + editor_role
                if system_prompt
                else editor_role
            )
            system += (
                "公司事实只能来自内部资料，保留并校正[n]引用，不得创造引用，不要描述合并过程。"
                + " " + template_instruction(question_type)
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
