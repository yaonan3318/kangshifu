"""P2-4 生产问答流程：用 Chatflow 执行引擎驱动正式 RAG。

正式问答与调试运行共用 ``ChatflowRunner``；这里提供生产节点处理器，
把检索、生成、校验、无答案等阶段接到真实服务上，并通过 SSE 事件流式输出。
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from types import SimpleNamespace
from typing import Any, AsyncIterator

from app.schemas.answer import (
    AnswerEvent, AnswerProvider, AnswerRequest, AnswerWarning, KnowledgeScope,
)
from app.services.answer_quality import (
    GENERAL, KB_SCOPE_UNCONFIGURED, LOW_RELEVANCE, MODEL_UNAVAILABLE, NO_RELEVANT_DOCUMENT,
    QUESTION_TYPES, classify_question, compute_confidence, mark_unsupported,
    no_answer_payload, verify_answer,
)
from app.llm import LlmError
from app.services.chatflow import ChatflowRunner, build_plan, default_graph, map_condition_branch
from app.services.rag import NO_INTERNAL_ANSWER, _seconds_since


def build_handlers(rag: Any, request: AnswerRequest, cfg: dict) -> dict:
    """构造生产节点处理器；闭包捕获 rag/request/cfg。"""

    async def start(context, node):
        await context.send(AnswerEvent(type="stage", stage="understanding"))
        if cfg.get("internet_enabled") and not cfg.get("internet_configured"):
            await context.send(AnswerEvent(type="warning", warning=AnswerWarning(
                code="INTERNET_NOT_CONFIGURED",
                message="联网服务未配置，本次仅使用内部资料回答。",
            )))
        return {"summary": "开始"}

    async def classify(context, node):
        configured = cfg.get("answer_template") or "AUTO"
        if configured != "AUTO":
            question_type = configured
        elif not cfg.get("classify_enabled", True):
            question_type = GENERAL
        else:
            question_type = classify_question(request.question)
        context.set("question_type", question_type)
        return {"question_type": question_type, "summary": question_type}

    async def context_completion(context, node):
        context.set("history", list(request.history or []))
        return {
            "used_context": bool(request.history),
            "summary": "使用上下文" if request.history else "无上下文",
        }

    async def query_rewrite(context, node):
        rewrite_info, retrieval_query, queries, rewrite_ms = await rag._prepare_queries(request)
        context.set("rewrite_info", rewrite_info)
        context.set("retrieval_query", retrieval_query)
        context.set("queries", queries)
        context.set("rewrite_ms", rewrite_ms)
        if rewrite_info is not None:
            await context.send(AnswerEvent(type="query_rewrite", query_rewrite=rewrite_info))
        await context.send(AnswerEvent(type="stage", stage="rewriting", detail={"queries": queries}))
        return {"retrieval_query": retrieval_query, "queries": queries, "summary": retrieval_query[:80]}

    async def multi_query(context, node):
        queries = context.get("queries") or [context.get("retrieval_query") or request.question]
        return {"queries": queries, "summary": f"{len(queries)} 个查询"}

    async def knowledge_search(context, node):
        if cfg.get("kb_scope") == "NONE":
            await context.send(AnswerEvent(type="stage", stage="retrieving", detail={"knowledge_base_count": 0}))
            context.set("results", [])
            context.set("sources", [])
            context.set("diagnostics", None)
            context.set("scope", KnowledgeScope.NONE)
            return {"candidate_count": 0, "source_count": 0, "summary": "尚未配置资料范围"}
        kb_ids = cfg.get("kb_ids")
        await context.send(AnswerEvent(
            type="stage", stage="retrieving",
            detail={"knowledge_base_count": len(kb_ids) if kb_ids else None},
        ))
        search_request = rag._search_request(request, cfg, query=context.get("retrieval_query"))
        context.set("search_request", search_request)
        outcome = rag.search_service.search_with_diagnostics(
            search_request, extra_queries=(context.get("queries") or [])[1:],
        )
        results = outcome.items
        sources = rag._sources(results)
        cfg["content_allows_external"] = not bool(
            rag._restricted_document_ids([item.document_id for item in sources])
        )
        context.set("results", results)
        context.set("sources", sources)
        context.set("diagnostics", outcome.diagnostics)
        context.set("scope", rag._internal_scope(results))
        if outcome.diagnostics.rerank_applied:
            await context.send(AnswerEvent(type="stage", stage="reranking"))
        await context.send(AnswerEvent(type="stage", stage="candidates", detail={
            "candidate_count": outcome.diagnostics.candidate_count, "source_count": len(sources),
        }))
        await context.send(AnswerEvent(type="sources", sources=sources))
        return {
            "candidate_count": outcome.diagnostics.candidate_count, "source_count": len(sources),
            "documents": list(dict.fromkeys(item.document_name for item in sources))[:5],
            "mode": outcome.diagnostics.mode, "summary": f"{len(sources)} 个片段",
        }

    async def reranker(context, node):
        diagnostics = context.get("diagnostics")
        applied = bool(diagnostics and diagnostics.rerank_applied)
        return {"rerank_applied": applied, "summary": "已精排" if applied else "未启用"}

    async def condition(context, node):
        sources = context.get("sources") or []
        results = context.get("results") or []
        preliminary = compute_confidence(results, sources, "")
        context.set("preliminary_confidence", preliminary)
        if sources and preliminary.score >= 0.42:
            logical = "evidence"
        elif (
            cfg.get("deepseek_enabled") and cfg.get("deepseek_allowed", True)
            and cfg.get("content_allows_external", True)
            and (cfg.get("no_answer_policy") or "SUGGEST") != "STRICT"
        ):
            logical = "deepseek_only"
        else:
            logical = "no_answer"
        branch = map_condition_branch(node, logical)
        context.set("branch", branch)
        return {"branch": branch, "logical_branch": logical, "score": round(preliminary.score, 4), "summary": logical}

    async def deepseek_gate(context, node):
        sources = context.get("sources") or []
        deepseek_blocked = bool(cfg.get("deepseek_enabled") and not cfg.get("deepseek_allowed", True))
        content_blocked = bool(sources) and not cfg.get("content_allows_external", True)
        if deepseek_blocked:
            await context.send(AnswerEvent(type="warning", warning=AnswerWarning(
                code="ASSISTANT_DEEPSEEK_BLOCKED",
                message="当前助手策略不允许调用外部模型，本次使用本地模型回答。",
            )))
        elif content_blocked:
            await context.send(AnswerEvent(type="warning", warning=AnswerWarning(
                code="EXTERNAL_LLM_BLOCKED",
                message="资料策略禁止将检索到的资料发送到外部模型，本次使用本地模型回答。",
            )))
        enhance = bool(
            cfg.get("deepseek_enabled") and cfg.get("content_allows_external", True)
            and (bool(sources) or (cfg.get("no_answer_policy") or "SUGGEST") != "STRICT")
            and not deepseek_blocked
        )
        branch = "enhance" if enhance else "skip"
        context.set("deepseek_branch", branch)
        return {"branch": branch, "summary": branch}

    async def route_condition(context, node):
        """条件节点既支持通用证据判断，也支持默认流程中的 DeepSeek 门控。"""
        if node.get("id") == "deepseek_gate":
            return await deepseek_gate(context, node)
        return await condition(context, node)

    async def local_model(context, node):
        sources = context.get("sources") or []
        local_stats = {"first_token_ms": None, "generation_ms": None, "prompt_tokens": None, "completion_tokens": None}
        if not sources:
            answer = NO_INTERNAL_ANSWER
            context.set("local_answer", answer)
            context.set("provider", AnswerProvider.LOCAL)
            await context.send(AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=answer))
            return {"answer": answer, "summary": "无内部资料"}
        await context.send(AnswerEvent(type="stage", stage="local_generating"))
        generation_started = perf_counter()
        first_token = None
        prompt_tokens = None
        completion_tokens = 0
        local_answer = ""
        try:
            async for item in rag.ollama.stream_with_stats(
                rag._local_messages(
                    request, sources, context.get("scope"), cfg["system_prompt"], context.get("question_type"),
                ),
                model=cfg["model_name"], temperature=cfg["temperature"],
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
                await context.send(AnswerEvent(type="delta", provider=AnswerProvider.LOCAL, text=delta))
            local_stats = {
                "first_token_ms": _seconds_since(generation_started) if first_token is None else round(first_token * 1000, 2),
                "generation_ms": _seconds_since(generation_started),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        except LlmError as exc:
            context.set("local_stats", local_stats)
            context.set("provider", AnswerProvider.LOCAL)
            await context.send(AnswerEvent(type="no_answer", no_answer=no_answer_payload(
                MODEL_UNAVAILABLE, allow_deepseek=cfg["deepseek_enabled"],
                deepseek_configured=rag.deepseek.configured,
            )))
            context.set("fatal_error", {"code": exc.code, "message": exc.message})
            return {"error": exc.message, "summary": "本地模型不可用"}
        context.set("local_stats", local_stats)
        context.set("local_answer", local_answer)
        context.set("provider", AnswerProvider.LOCAL)
        return {
            "answer": local_answer[:200], "first_token_ms": local_stats["first_token_ms"],
            "summary": f"本地生成 {len(local_answer)} 字",
        }

    async def deepseek(context, node):
        sources = context.get("sources") or []
        local_answer = context.get("local_answer") or ""
        deepseek_stats = {"first_token_ms": None, "generation_ms": None, "prompt_tokens": None, "completion_tokens": None}
        if not rag.deepseek.configured:
            await context.send(AnswerEvent(type="warning", warning=AnswerWarning(
                code="DEEPSEEK_NOT_CONFIGURED", message="尚未配置 DeepSeek API Key，本次使用本地模型回答。",
            )))
            context.set("deepseek_stats", deepseek_stats)
            return {"configured": False, "summary": "未配置"}
        await context.send(AnswerEvent(type="stage", stage="deepseek_enhancing"))
        enhanced_parts: list[str] = []
        ds_first = None
        ds_started = perf_counter()
        try:
            async for delta in rag.deepseek.stream(rag._deepseek_messages(
                request, sources, local_answer, cfg["system_prompt"], context.get("question_type"),
            )):
                if ds_first is None:
                    ds_first = perf_counter() - ds_started
                enhanced_parts.append(delta)
        except LlmError as exc:
            await context.send(AnswerEvent(type="warning", warning=AnswerWarning(code=exc.code, message=exc.message)))
            context.set("deepseek_stats", deepseek_stats)
            return {"error": exc.message, "summary": "失败降级"}
        combined = "".join(enhanced_parts)
        deepseek_stats = {
            "first_token_ms": None if ds_first is None else round(ds_first * 1000, 2),
            "generation_ms": _seconds_since(ds_started),
            "prompt_tokens": None,
            "completion_tokens": rag._estimate_tokens(combined),
        }
        enhanced = combined.strip()
        if enhanced:
            context.set("provider", AnswerProvider.DEEPSEEK)
            context.set("deepseek_used", True)
            context.set("enhanced_answer", enhanced)
            context.set("scope", context.get("scope") if sources else KnowledgeScope.GENERAL)
            await context.send(AnswerEvent(type="replace", provider=AnswerProvider.DEEPSEEK, text=""))
            await context.send(AnswerEvent(type="delta", provider=AnswerProvider.DEEPSEEK, text=enhanced))
        context.set("deepseek_stats", deepseek_stats)
        return {"enhanced": bool(enhanced), "summary": "DeepSeek 增强" if enhanced else "无增强"}

    async def harness(context, node):
        # 生产 Harness 由 HarnessService 逐次人工确认；引擎节点只标记需要审批。
        return {"requires_approval": True, "summary": "写操作需人工确认"}

    async def answer_check(context, node):
        sources = context.get("sources") or []
        final_text = (
            context.get("enhanced_answer") if context.get("deepseek_used") else context.get("local_answer")
        ) or ""
        if not final_text and not sources:
            # 无内部资料且外部模型不可用时，给出固定提示，避免空白回答。
            final_text = NO_INTERNAL_ANSWER
        citation_report = None
        answer_check_ms = 0.0
        if sources and cfg.get("answer_check_enabled", True):
            await context.send(AnswerEvent(type="stage", stage="checking"))
            check_started = perf_counter()
            citation_report = verify_answer(
                final_text, sources,
                rag._unavailable_citations(sources), rag._stale_citations(sources),
            )
            marked = mark_unsupported(final_text, citation_report)
            if marked != final_text:
                final_text = marked
                provider = context.get("provider") or AnswerProvider.LOCAL
                await context.send(AnswerEvent(type="replace", provider=provider, text=""))
                await context.send(AnswerEvent(type="delta", provider=provider, text=final_text))
            answer_check_ms = _seconds_since(check_started)
            await context.send(AnswerEvent(type="citation_check", citation_check=citation_report.to_payload()))
        context.set("final_text", final_text)
        context.set("citation_report", citation_report)
        context.set("answer_check_ms", answer_check_ms)
        ok = citation_report.ok if citation_report else True
        return {
            "checked": citation_report.checked if citation_report else 0, "ok": ok,
            "summary": "引用通过" if ok else "存在待核对引用",
        }

    async def no_answer(context, node):
        sources = context.get("sources") or []
        diagnostics = context.get("diagnostics")
        search_request = context.get("search_request")
        retrieval_query = context.get("retrieval_query") or request.question
        if cfg.get("kb_scope") == "NONE":
            reason = KB_SCOPE_UNCONFIGURED
        elif search_request is not None and diagnostics is not None:
            reason = rag._no_answer_reason(
                SimpleNamespace(diagnostics=diagnostics), retrieval_query, search_request,
            )
        elif not sources:
            reason = NO_RELEVANT_DOCUMENT
        else:
            reason = LOW_RELEVANCE
        policy = cfg.get("no_answer_policy") or "SUGGEST"
        payload = no_answer_payload(
            reason,
            recommended_documents=(
                [] if policy == "STRICT" or search_request is None
                else rag._recommended_documents(retrieval_query, search_request)
            ),
            allow_deepseek=cfg["deepseek_enabled"] and policy != "STRICT",
            deepseek_configured=rag.deepseek.configured,
        )
        final_text = payload["message"]
        if context.get("deepseek_used") and not sources:
            final_text = context.get("enhanced_answer") or final_text
        context.set("no_answer", payload)
        context.set("final_text", final_text)
        provider = context.get("provider") or AnswerProvider.LOCAL
        await context.send(AnswerEvent(type="replace", provider=provider, text=""))
        await context.send(AnswerEvent(type="delta", provider=provider, text=final_text))
        await context.send(AnswerEvent(type="no_answer", no_answer=payload))
        return {"reason": reason, "summary": reason}

    async def final_answer(context, node):
        final_text = context.get("final_text") or ""
        provider = context.get("provider") or AnswerProvider.LOCAL
        context.set("final_output", {"answer": final_text, "provider": provider.value})
        return {"summary": "回答完成"}

    return {
        "start": start,
        "classify": classify,
        "context_completion": context_completion,
        "query_rewrite": query_rewrite,
        "multi_query": multi_query,
        "knowledge_search": knowledge_search,
        "reranker": reranker,
        "condition": route_condition,
        "local_model": local_model,
        "deepseek": deepseek,
        "harness": harness,
        "answer_check": answer_check,
        "no_answer": no_answer,
        "final_answer": final_answer,
    }


async def _finalize(rag: Any, request: AnswerRequest, cfg: dict, result, cache_key, started) -> AsyncIterator[AnswerEvent]:
    variables = result.variables
    if variables.get("fatal_error"):
        yield AnswerEvent(type="error", error=variables["fatal_error"])
        return
    if variables.get("__failed_node__"):
        yield AnswerEvent(type="error", error={
            "code": "CHATFLOW_NODE_FAILED",
            "message": f"流程节点执行失败：{variables['__failed_node__']}",
        })
        return
    results = variables.get("results") or []
    sources = variables.get("sources") or []
    final_text = variables.get("final_text") or ""
    provider = variables.get("provider") or AnswerProvider.LOCAL
    scope = variables.get("scope") or KnowledgeScope.NONE
    question_type = variables.get("question_type")
    confidence = compute_confidence(results, sources, final_text)
    if not variables.get("no_answer") and not variables.get("deepseek_used") and confidence.tier == INSUFFICIENT:
        # 资料不足且没有可用通用知识答案时，统一给出固定提示，禁止模型猜测。
        reason = LOW_RELEVANCE if sources else NO_RELEVANT_DOCUMENT
        policy = cfg.get("no_answer_policy") or "SUGGEST"
        search_request = variables.get("search_request")
        payload = no_answer_payload(
            reason,
            recommended_documents=(
                [] if policy == "STRICT" or search_request is None
                else rag._recommended_documents(variables.get("retrieval_query") or request.question, search_request)
            ),
            allow_deepseek=cfg["deepseek_enabled"] and policy != "STRICT",
            deepseek_configured=rag.deepseek.configured,
        )
        variables["no_answer"] = payload
        final_text = payload["message"]
        variables["final_text"] = final_text
        yield AnswerEvent(type="replace", provider=provider, text="")
        yield AnswerEvent(type="delta", provider=provider, text=final_text)
        yield AnswerEvent(type="no_answer", no_answer=payload)
        confidence = compute_confidence(results, sources, final_text)
    yield AnswerEvent(type="confidence", confidence=confidence.to_payload(), question_type=question_type)
    suggestions = await rag._follow_up_suggestions(request, final_text, sources)
    if suggestions:
        yield AnswerEvent(type="suggestions", suggestions=suggestions)
    diagnostics = variables.get("diagnostics")
    stage_timings = dict(diagnostics.timings_ms) if diagnostics is not None else {}
    stage_timings["query_rewrite"] = variables.get("rewrite_ms") or 0.0
    local_stats = variables.get("local_stats") or {}
    deepseek_stats = variables.get("deepseek_stats") or {}
    deepseek_used = bool(variables.get("deepseek_used"))
    flow_steps = [record.to_payload() for record in result.records]
    node_timings: dict[str, float] = {}
    for record in result.records:
        key = record.type or record.id
        node_timings[key] = round(node_timings.get(key, 0.0) + record.duration_ms, 2)
    citation_report = variables.get("citation_report")
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
        "retrieval_query": variables.get("retrieval_query"),
        "retrieval_queries": variables.get("queries"),
        "query_rewrite": variables.get("rewrite_info").model_dump() if variables.get("rewrite_info") is not None else None,
        "question_type": question_type,
        "question_type_label": (
            QUESTION_TYPES.get(question_type, QUESTION_TYPES[GENERAL])["label"] if question_type else None
        ),
        "confidence": confidence.to_payload(),
        "citation_check": citation_report.to_payload() if citation_report is not None else None,
        "no_answer": variables.get("no_answer"),
        "suggestions": suggestions,
        "flow_steps": flow_steps,
        "node_timings": node_timings,
        "chatflow_id": (cfg.get("assistant").chatflow_id if cfg.get("assistant") else None),
    }
    quality = {
        "question_type": question_type,
        "confidence": confidence.to_payload(),
        "citation_check": citation_report.to_payload() if citation_report is not None else None,
        "no_answer": variables.get("no_answer"),
    }
    if cache_key is not None:
        rag._store_cache(cache_key, final_text, provider, scope, sources, metrics, quality)
    yield AnswerEvent(type="metrics", metrics=metrics)
    yield AnswerEvent(
        type="done", provider=provider, scope=scope,
        deepseek_requested=cfg["deepseek_enabled"], deepseek_used=deepseek_used,
        source_count=len(sources), question_type=question_type,
    )


async def run_production_flow(rag: Any, request: AnswerRequest, cfg: dict, cache_key: str | None = None) -> AsyncIterator[AnswerEvent]:
    """运行生产问答流程，逐事件流式返回；调试与生产共用 ChatflowRunner。"""
    started = perf_counter()
    graph = cfg.get("chatflow") or default_graph()
    plan = build_plan(graph)
    cfg.setdefault("classify_enabled", plan.classify_enabled if plan else True)
    cfg.setdefault("answer_check_enabled", plan.answer_check_enabled if plan else True)
    variables = {
        "question": request.question.strip(),
        "history": list(request.history or []),
        "knowledge_base_id": request.knowledge_base_id,
    }
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    async def emit(event):
        await queue.put(event)

    runner = ChatflowRunner(graph, build_handlers(rag, request, cfg), emit=emit)

    async def run():
        try:
            return await runner.run(variables, dry_run=False)
        finally:
            await queue.put(sentinel)

    task = asyncio.create_task(run())
    completed = False
    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                completed = True
                break
            yield item
    finally:
        if not completed and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    if not completed or task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        code = getattr(exc, "code", "CHATFLOW_FLOW_FAILED")
        message = getattr(exc, "message", str(exc))
        yield AnswerEvent(type="error", error={"code": code, "message": message})
        return
    result = task.result()
    async for event in _finalize(rag, request, cfg, result, cache_key, started):
        yield event
