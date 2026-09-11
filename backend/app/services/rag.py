"""RAG 编排层：检索证据、构造提示词、调用千问，并可选调用 DeepSeek 增强。

同时负责：
- 记录每次问答各阶段耗时与 token 数（answer/stream 把 metrics 持久化到 chat_messages）
- 相同问题、资料版本与检索配置未变化时命中内存缓存，避免重复检索与生成
- 上下文裁剪限制片段数量，保证本地模型在 Mac M3 Pro 上可用
- P2-4：正式问答由助手绑定的已发布 Chatflow 驱动，未绑定时使用安全默认流程，
  与调试运行共用同一执行引擎（app/services/rag_flow.py）。
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
from app.models import Assistant, Chatflow, Document, DocumentChunk, DocumentStatus, KnowledgeBase
from app.schemas.answer import (
    AnswerEvent, AnswerProvider, AnswerRequest, AnswerSource, AnswerStatusResponse, KnowledgeScope,
)
from app.schemas.search import QueryRewriteInfo, SearchRequest, SearchResult
from app.services.answer_quality import (
    GENERAL, LOW_RELEVANCE, NO_RELEVANT_DOCUMENT, PERMISSION_RESTRICTED, template_instruction,
)
from app.services.audit import SENSITIVE_LEVELS_EXTERNAL_BLOCKED
from app.services.chatflow import ChatflowPlan, ChatflowService
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
        """按助手绑定的已发布 Chatflow（未绑定时安全默认流程）执行问答并流式返回事件。"""
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
        from app.services.rag_flow import run_production_flow

        async for event in run_production_flow(self, request, cfg, cache_key=cache_key):
            yield event

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
        # 知识库范围语义：ALL=全部启用知识库，SELECTED=指定知识库，NONE=尚未配置（不可检索）。
        kb_ids: list | None = None
        kb_scope = "ALL"
        if assistant is not None:
            bound = [kb.id for kb in assistant.knowledge_bases]
            if assistant.allow_all_knowledge_bases:
                kb_ids = list(self.search_service.session.scalars(
                    select(KnowledgeBase.id).where(KnowledgeBase.enabled.is_(True))
                ))
                # 没有任何启用知识库时等同“未配置”，避免无过滤地检索到停用知识库。
                kb_scope = "ALL" if kb_ids else "NONE"
            elif bound:
                kb_scope, kb_ids = "SELECTED", bound
            else:
                kb_scope, kb_ids = "NONE", []
        return {
            "assistant": assistant,
            "kb_ids": kb_ids,
            "kb_scope": kb_scope,
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
            # 联网服务尚未接入：明确返回状态，绝不假装已联网。
            "internet_configured": bool(getattr(self.settings, "internet_search_enabled", False)),
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
            str(cfg.get("kb_scope") or ""),
            self._filter_fingerprint(request),
            self._version_fingerprint(request, cfg),
        ]
        return uuid.uuid5(uuid.NAMESPACE_URL, "|".join(parts)).hex

    @staticmethod
    def _filter_fingerprint(request: AnswerRequest) -> str:
        """结构化过滤条件指纹；不同过滤组合不能复用同一缓存答案。"""
        return "|".join([
            str(request.document_name or ""),
            ",".join(sorted(tag.strip() for tag in request.tags if tag.strip())),
            str(request.department_id or ""),
            str(request.owner_user_id or ""),
            getattr(request.document_status, "value", request.document_status) or "",
            str(request.relative_path or ""),
            str(request.version_number or ""),
            str(int(request.valid_only)),
        ])

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
            tags=request.tags, department_id=request.department_id,
            owner_user_id=request.owner_user_id, document_status=request.document_status,
            relative_path=request.relative_path, version_number=request.version_number,
            valid_only=request.valid_only,
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
                retrieval_rank=result.pre_rerank_rank, pre_rerank_rank=result.pre_rerank_rank,
                post_rerank_rank=result.post_rerank_rank,
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

    def _stale_citations(self, sources: list[AnswerSource]) -> dict[int, str]:
        """返回引用编号 -> 版本/位置不一致状态，供前端提示“版本已更新”。"""
        stale: dict[int, str] = {}
        for source in sources:
            document = self.search_service.session.get(Document, source.document_id)
            if document is not None and source.document_version is not None \
                    and document.version_number != source.document_version:
                stale[source.citation_number] = "VERSION_CHANGED"
                continue
            chunk = self.search_service.session.get(DocumentChunk, source.chunk_id)
            if chunk is None:
                continue
            if (
                chunk.page_start != source.page_start or chunk.page_end != source.page_end
                or chunk.slide_number != source.slide_number or chunk.sheet_name != source.sheet_name
            ):
                stale[source.citation_number] = "LOCATION_CHANGED"
        return stale

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
            + "每个关键结论使用真实的数字编号引用，例如[1]或[2]；绝对不要输出[n]或[n1]。"
            + "不得创造不存在的引用，也不要输出隐藏推理过程。"
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
                "公司事实只能来自内部资料，保留并校正[1]、[2]格式的引用，绝对不要输出[n]或[n1]；"
                "不得创造引用，不要描述合并过程。"
                + " " + template_instruction(question_type)
            )
            content = (
                f"内部资料：\n{self._format_evidence(sources)}\n\n"
                f"千问本地初稿：\n{local_answer}\n\n当前问题：{request.question.strip()}"
            )
        else:
            system = (
                "内部资料库没有找到答案。请使用通用知识用中文回答，但开头必须明确写："
                "“以下内容来自 DeepSeek 通用知识，不是公司资料结论。”不得添加任何内部引用。"
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
