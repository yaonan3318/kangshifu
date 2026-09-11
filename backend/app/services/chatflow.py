"""P2-4 Chatflow 执行引擎：真正按图执行节点、连线、条件与分支。

设计要点：
- 统一的 ``ChatflowRunner`` 按 ``next`` / ``on_success`` / ``branches`` 执行节点，
  调试运行与正式问答共用同一引擎，避免行为不一致；
- 每个节点接收上下文变量、输出上下文变量，并记录开始/结束时间、耗时、状态与安全摘要；
- 支持 ``on_failure`` / ``on_timeout`` / ``fallback_node``；
- 防止未知节点、无终止节点、超过最大节点数与死循环；
- 知识库越权由检索层权限过滤 + 助手知识库范围共同保证；
- Harness 写操作仍由 HarnessService 逐次人工确认。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.llm import DeepSeekClient, GenerationMessage, LlmError, OllamaClient
from app.models import Chatflow, ChatflowVersion
from app.schemas.search import SearchRequest
from app.services.answer_quality import (
    NO_RELEVANT_DOCUMENT, classify_question, compute_confidence, no_answer_payload,
    verify_answer,
)
from app.services.query_rewrite import QueryRewriteService
from app.services.retrieval_config import RetrievalConfig, load_active_config
from app.services.search import SearchService

# 固定画布节点目录：前端据此渲染节点与配置项。legacy 节点用于兼容旧图。
NODE_TYPES: list[dict] = [
    {"type": "start", "label": "开始", "category": "control", "config_fields": []},
    {"type": "classify", "label": "问题分类", "category": "understand", "config_fields": []},
    {"type": "context_completion", "label": "上下文补全", "category": "understand", "config_fields": [
        {"key": "history_turns", "type": "int", "label": "上下文轮数"},
    ]},
    {"type": "query_rewrite", "label": "问题改写", "category": "understand", "config_fields": []},
    {"type": "multi_query", "label": "Multi-query", "category": "understand", "config_fields": [
        {"key": "count", "type": "int", "label": "查询数量"},
    ]},
    {"type": "knowledge_search", "label": "知识库检索", "category": "retrieve", "config_fields": [
        {"key": "limit", "type": "int", "label": "最终片段数量"},
    ]},
    {"type": "reranker", "label": "Reranker 精排", "category": "retrieve", "config_fields": [
        {"key": "candidate_limit", "type": "int", "label": "候选数量"},
    ]},
    {"type": "condition", "label": "条件判断", "category": "control", "config_fields": [
        {"key": "branches", "type": "branches", "label": "分支"},
    ]},
    {"type": "local_model", "label": "本地模型", "category": "generate", "config_fields": [
        {"key": "timeout_seconds", "type": "int", "label": "超时秒数"},
    ]},
    {"type": "deepseek", "label": "DeepSeek", "category": "generate", "config_fields": [
        {"key": "timeout_seconds", "type": "int", "label": "超时秒数"},
    ]},
    {"type": "harness", "label": "Harness 运维", "category": "generate", "config_fields": []},
    {"type": "answer_check", "label": "答案校验", "category": "check", "config_fields": []},
    {"type": "no_answer", "label": "缺失知识提示", "category": "check", "config_fields": []},
    {"type": "final_answer", "label": "最终回答", "category": "control", "config_fields": []},
    # 兼容旧图节点类型。
    {"type": "question_classify", "label": "问题分类（旧）", "category": "understand", "config_fields": [], "legacy": True},
    {"type": "retrieval", "label": "知识库检索（旧）", "category": "retrieve", "config_fields": [], "legacy": True},
    {"type": "rerank", "label": "Reranker 精排（旧）", "category": "retrieve", "config_fields": [], "legacy": True},
]
NODE_TYPE_LABELS = {item["type"]: item["label"] for item in NODE_TYPES}
VALID_NODE_TYPES = set(NODE_TYPE_LABELS)

# 旧节点类型 -> 规范类型，保证旧图也能被新引擎执行。
LEGACY_ALIASES = {
    "question_classify": "classify",
    "retrieval": "knowledge_search",
    "rerank": "reranker",
}


def canonical_type(node_type: str | None) -> str | None:
    return LEGACY_ALIASES.get(node_type, node_type)


def map_condition_branch(node: dict, logical: str) -> str:
    """把逻辑分支名映射到图中实际配置的 when，兼容旧图的 sufficient/insufficient 命名。"""
    whens = {
        item.get("when")
        for item in (node.get("config") or {}).get("branches") or []
        if isinstance(item, dict)
    }
    aliases = {
        "evidence": ("evidence", "sufficient"),
        "deepseek_only": ("deepseek_only", "insufficient_and_deepseek"),
        "no_answer": ("no_answer",),
    }
    for name in aliases.get(logical, (logical,)):
        if name in whens:
            return name
    return logical


def default_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "enabled": True, "config": {}, "next": "classify"},
            {"id": "classify", "type": "classify", "name": "问题分类", "enabled": True, "config": {}, "next": "context_completion"},
            {"id": "context_completion", "type": "context_completion", "name": "上下文补全", "enabled": True,
             "config": {}, "next": "query_rewrite"},
            {"id": "query_rewrite", "type": "query_rewrite", "name": "问题改写", "enabled": True,
             "config": {}, "next": "multi_query"},
            {"id": "multi_query", "type": "multi_query", "name": "Multi-query", "enabled": True,
             "config": {}, "next": "knowledge_search"},
            {"id": "knowledge_search", "type": "knowledge_search", "name": "知识库检索", "enabled": True,
             "config": {}, "next": "reranker"},
            {"id": "reranker", "type": "reranker", "name": "Reranker 精排", "enabled": True, "config": {}, "next": "confidence"},
            {"id": "confidence", "type": "condition", "name": "置信度判断", "enabled": True, "config": {
                "branches": [
                    {"when": "evidence", "next": "local_model"},
                    {"when": "deepseek_only", "next": "deepseek"},
                    {"when": "ops", "next": "harness"},
                ],
                "default_next": "no_answer",
            }, "next": None},
            {"id": "local_model", "type": "local_model", "name": "本地千问", "enabled": True, "config": {}, "next": "deepseek_gate"},
            {"id": "deepseek_gate", "type": "condition", "name": "是否 DeepSeek 增强", "enabled": True, "config": {
                "branches": [{"when": "enhance", "next": "deepseek"}],
                "default_next": "answer_check",
            }, "next": None},
            {"id": "deepseek", "type": "deepseek", "name": "DeepSeek 增强", "enabled": True, "config": {}, "next": "answer_check"},
            {"id": "harness", "type": "harness", "name": "Harness 运维", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "answer_check", "type": "answer_check", "name": "答案校验", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "no_answer", "type": "no_answer", "name": "缺失知识提示", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "final_answer", "type": "final_answer", "name": "最终回答", "enabled": True, "config": {}, "next": None},
        ],
        "start_node_id": "start",
    }


def _outgoing(node: dict) -> list[str]:
    config = node.get("config") or {}
    result = [
        node.get("next"), node.get("on_success"), config.get("default_next"),
        config.get("on_failure"), config.get("on_timeout"), config.get("fallback_node"),
        config.get("on_error"),
    ]
    for branch in config.get("branches") or []:
        if isinstance(branch, dict):
            result.append(branch.get("next"))
    return [item for item in result if item]


def validate_graph(graph: dict) -> None:
    """校验节点类型、唯一 id、连线目标、终止节点与是否成环。"""
    if not isinstance(graph, dict):
        raise AppError("CHATFLOW_GRAPH_INVALID", "流程定义必须是对象", 422)
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise AppError("CHATFLOW_GRAPH_INVALID", "流程至少需要一个节点", 422)
    by_id: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            raise AppError("CHATFLOW_GRAPH_INVALID", "节点缺少 id", 422)
        node_id = str(node["id"])
        if node_id in by_id:
            raise AppError("CHATFLOW_GRAPH_INVALID", f"节点 id 重复：{node_id}", 422)
        if node.get("type") not in VALID_NODE_TYPES:
            raise AppError("CHATFLOW_GRAPH_INVALID", f"未知节点类型：{node.get('type')}", 422)
        by_id[node_id] = node
    start = graph.get("start_node_id") or "start"
    if start not in by_id:
        raise AppError("CHATFLOW_GRAPH_INVALID", "开始节点不存在", 422)
    has_terminal = False
    for node in nodes:
        targets = [node.get("next")]
        config = node.get("config") or {}
        for branch in config.get("branches") or []:
            targets.append(branch.get("next") if isinstance(branch, dict) else None)
        targets.extend([config.get("default_next"), config.get("on_error"),
                        config.get("on_failure"), config.get("on_timeout"), config.get("fallback_node")])
        for target in targets:
            if target and target not in by_id:
                raise AppError("CHATFLOW_GRAPH_INVALID", f"节点 {node.get('id')} 指向不存在的节点：{target}", 422)
        if not _outgoing(node):
            has_terminal = True
    if not has_terminal:
        raise AppError("CHATFLOW_GRAPH_INVALID", "流程缺少终止节点", 422)
    _assert_acyclic(by_id, start)


def _assert_acyclic(by_id: dict[str, dict], start: str) -> None:
    WHITE, GREY, BLACK = 0, 1, 2
    colors = {node_id: WHITE for node_id in by_id}

    def visit(node_id: str) -> None:
        colors[node_id] = GREY
        for target in _outgoing(by_id[node_id]):
            if colors.get(target) == GREY:
                raise AppError("CHATFLOW_GRAPH_CYCLE", "流程存在环，请检查分支连线", 422)
            if colors.get(target) == WHITE:
                visit(target)
        colors[node_id] = BLACK

    visit(start)


@dataclass
class ChatflowPlan:
    """轻量计划视图（兼容旧接口）：只反映关键阶段开关。"""

    graph: dict
    nodes: dict
    start_node_id: str
    rewrite_enabled: bool = False
    multi_query_enabled: bool = False
    rerank_enabled: bool = False
    answer_check_enabled: bool = False
    classify_enabled: bool = False
    deepseek_enabled: bool = False
    harness_enabled: bool = False
    final_enabled: bool = False


def build_plan(graph: dict | None) -> ChatflowPlan | None:
    if not graph or not graph.get("nodes"):
        return None
    nodes = {str(node["id"]): node for node in graph["nodes"] if node.get("enabled", True)}

    def find(node_type: str) -> dict | None:
        return next((node for node in nodes.values() if canonical_type(node.get("type")) == node_type), None)

    rewrite = find("query_rewrite")
    return ChatflowPlan(
        graph=graph, nodes=nodes, start_node_id=graph.get("start_node_id") or "start",
        rewrite_enabled=rewrite is not None,
        multi_query_enabled=find("multi_query") is not None,
        rerank_enabled=find("reranker") is not None,
        answer_check_enabled=find("answer_check") is not None,
        classify_enabled=find("classify") is not None,
        deepseek_enabled=find("deepseek") is not None,
        harness_enabled=find("harness") is not None,
        final_enabled=find("final_answer") is not None,
    )


class ChatflowService:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Chatflow]:
        return list(self.session.scalars(select(Chatflow).order_by(Chatflow.created_at)))

    def get(self, chatflow_id: uuid.UUID) -> Chatflow:
        value = self.session.get(Chatflow, chatflow_id)
        if value is None:
            raise AppError("CHATFLOW_NOT_FOUND", "流程不存在", 404)
        return value

    def create(self, name: str, description: str | None, graph: dict | None = None) -> Chatflow:
        cleaned = name.strip()
        if not cleaned:
            raise AppError("CHATFLOW_NAME_REQUIRED", "流程名称不能为空", 422)
        if self.session.scalar(select(Chatflow.id).where(Chatflow.name == cleaned)) is not None:
            raise AppError("CHATFLOW_NAME_EXISTS", "流程名称已存在", 409)
        flow_graph = graph or default_graph()
        validate_graph(flow_graph)
        value = Chatflow(name=cleaned, description=description, draft_graph=flow_graph)
        self.session.add(value)
        self.session.commit()
        self.session.refresh(value)
        return value

    def update(
        self, chatflow_id: uuid.UUID, *, name: str | None = None, description: str | None = None,
        graph: dict | None = None, enabled: bool | None = None, description_set: bool = False,
    ) -> Chatflow:
        value = self.get(chatflow_id)
        if name is not None:
            cleaned = name.strip()
            if not cleaned:
                raise AppError("CHATFLOW_NAME_REQUIRED", "流程名称不能为空", 422)
            if self.session.scalar(
                select(Chatflow.id).where(Chatflow.name == cleaned, Chatflow.id != chatflow_id)
            ) is not None:
                raise AppError("CHATFLOW_NAME_EXISTS", "流程名称已存在", 409)
            value.name = cleaned
        if description_set:
            value.description = description
        if graph is not None:
            validate_graph(graph)
            value.draft_graph = graph
        if enabled is not None:
            value.enabled = enabled
        self.session.commit()
        self.session.refresh(value)
        return value

    def delete(self, chatflow_id: uuid.UUID) -> None:
        self.session.delete(self.get(chatflow_id))
        self.session.commit()

    def publish(self, chatflow_id: uuid.UUID, note: str | None = None) -> ChatflowVersion:
        value = self.get(chatflow_id)
        validate_graph(value.draft_graph)
        version_number = (value.published_version or 0) + 1
        version = ChatflowVersion(
            chatflow_id=value.id, version=version_number, graph=value.draft_graph, note=note,
        )
        self.session.add(version)
        value.published_graph = value.draft_graph
        value.published_version = version_number
        self.session.commit()
        self.session.refresh(version)
        return version

    def rollback(self, chatflow_id: uuid.UUID, version_number: int) -> Chatflow:
        value = self.get(chatflow_id)
        version = self.session.scalar(
            select(ChatflowVersion).where(
                ChatflowVersion.chatflow_id == chatflow_id, ChatflowVersion.version == version_number
            )
        )
        if version is None:
            raise AppError("CHATFLOW_VERSION_NOT_FOUND", "流程版本不存在", 404)
        value.draft_graph = version.graph
        value.published_graph = version.graph
        value.published_version = version.version
        self.session.commit()
        self.session.refresh(value)
        return value

    def list_versions(self, chatflow_id: uuid.UUID) -> list[ChatflowVersion]:
        self.get(chatflow_id)
        return list(self.session.scalars(
            select(ChatflowVersion).where(ChatflowVersion.chatflow_id == chatflow_id)
            .order_by(ChatflowVersion.version.desc())
        ))

    def get_version(self, chatflow_id: uuid.UUID, version_number: int) -> ChatflowVersion:
        version = self.session.scalar(
            select(ChatflowVersion).where(
                ChatflowVersion.chatflow_id == chatflow_id, ChatflowVersion.version == version_number
            )
        )
        if version is None:
            raise AppError("CHATFLOW_VERSION_NOT_FOUND", "流程版本不存在", 404)
        return version

    @staticmethod
    def active_graph(chatflow: Chatflow | None) -> dict | None:
        """生产问答只使用已发布图；未发布时返回 None，由调用方使用安全默认流程。"""
        if chatflow is None or not chatflow.enabled:
            return None
        if chatflow.published_version and chatflow.published_graph:
            return chatflow.published_graph
        return None


# ---------------------------------------------------------------- 执行引擎

@dataclass
class NodeRecord:
    id: str
    type: str
    name: str
    status: str
    started_at: str
    ended_at: str
    duration_ms: float
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    error: str | None = None
    summary: str = ""

    def to_payload(self) -> dict:
        return {
            "id": self.id, "type": self.type, "name": self.name, "status": self.status,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "duration_ms": self.duration_ms, "input": self.input, "output": self.output,
            "error": self.error, "summary": self.summary,
        }


@dataclass
class FlowRunResult:
    records: list[NodeRecord]
    variables: dict
    total_ms: float

    def to_payload(self) -> dict:
        return {
            "nodes": [record.to_payload() for record in self.records],
            "total_ms": self.total_ms,
            "final": self.variables.get("final_output"),
        }


@dataclass
class FlowContext:
    variables: dict
    dry_run: bool = False
    emit: Callable[[Any], Awaitable[None]] | None = None

    async def send(self, event: Any) -> None:
        if self.emit is not None:
            await self.emit(event)

    def set(self, key: str, value: Any) -> None:
        self.variables[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)


NodeHandler = Callable[[FlowContext, dict], Awaitable[dict] | dict]


class ChatflowRunner:
    """按图执行节点的通用引擎；调试与正式问答共用。"""

    MAX_STEPS = 50

    def __init__(
        self, graph: dict, handlers: dict[str, NodeHandler], *,
        emit: Callable[[Any], Awaitable[None]] | None = None, max_steps: int | None = None,
    ):
        self.graph = graph
        self.handlers = handlers
        self.emit = emit
        self.max_steps = max_steps or self.MAX_STEPS

    async def run(self, variables: dict, *, dry_run: bool = False) -> FlowRunResult:
        validate_graph(self.graph)
        by_id = {str(node["id"]): node for node in self.graph["nodes"]}
        context = FlowContext(variables=dict(variables), dry_run=dry_run, emit=self.emit)
        records: list[NodeRecord] = []
        node_id = self.graph.get("start_node_id") or "start"
        steps = 0
        while node_id is not None:
            if steps >= self.max_steps:
                raise AppError("CHATFLOW_MAX_STEPS", f"流程执行超过最大节点数 {self.max_steps}", 422)
            node = by_id.get(node_id)
            if node is None:
                raise AppError("CHATFLOW_NODE_MISSING", f"节点不存在：{node_id}", 422)
            steps += 1
            if not node.get("enabled", True):
                node_id = self._resolve_next(node, {}, context)
                continue
            handler = self.handlers.get(canonical_type(node.get("type")))
            started_at = datetime.now(UTC)
            started = perf_counter()
            output: dict = {}
            error: str | None = None
            status = "succeeded"
            if handler is None:
                status, output = "skipped", {"reason": "无可用执行器"}
            else:
                timeout = self._timeout_seconds(node)
                try:
                    result = handler(context, node)
                    if asyncio.iscoroutine(result):
                        result = await (asyncio.wait_for(result, timeout) if timeout else result)
                    output = result or {}
                    if output.pop("__skipped__", False):
                        status = "skipped"
                except asyncio.TimeoutError:
                    status, error = "timeout", f"节点超时（>{timeout}s）"
                except Exception as exc:  # 节点失败由 on_failure / fallback 处理
                    status, error = "failed", str(exc)
            ended_at = datetime.now(UTC)
            duration = round((perf_counter() - started) * 1000, 2)
            records.append(NodeRecord(
                id=node_id, type=canonical_type(node.get("type")) or "", name=node.get("name") or NODE_TYPE_LABELS.get(node.get("type"), node_id),
                status=status, started_at=started_at.isoformat(), ended_at=ended_at.isoformat(),
                duration_ms=duration, input=self._safe_input(context), output=self._safe_output(output),
                error=error, summary=self._summary(node, output, status),
            ))
            if status in ("failed", "timeout"):
                next_id = self._failure_next(node, status)
                if next_id is None:
                    context.set("__failed_node__", node_id)
                    break
                node_id = next_id
                continue
            # 处理器显式标记的致命错误（如本地模型不可用）立即终止流程。
            if context.get("fatal_error"):
                break
            node_id = self._resolve_next(node, output, context)
        total = round(sum(record.duration_ms for record in records), 2)
        return FlowRunResult(records=records, variables=context.variables, total_ms=total)

    @staticmethod
    def _timeout_seconds(node: dict) -> float | None:
        value = (node.get("config") or {}).get("timeout_seconds")
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None

    @staticmethod
    def _failure_next(node: dict, status: str) -> str | None:
        config = node.get("config") or {}
        if status == "timeout":
            return config.get("on_timeout") or config.get("on_failure") or config.get("fallback_node") or config.get("on_error")
        return config.get("on_failure") or config.get("fallback_node") or config.get("on_error")

    @staticmethod
    def _resolve_next(node: dict, output: dict, context: FlowContext) -> str | None:
        config = node.get("config") or {}
        if canonical_type(node.get("type")) == "condition":
            branch = output.get("branch") or context.get("__branch__")
            for item in config.get("branches") or []:
                if isinstance(item, dict) and item.get("when") == branch:
                    return item.get("next")
            return config.get("default_next")
        return node.get("on_success") or node.get("next")

    @staticmethod
    def _safe_input(context: FlowContext) -> dict:
        question = str(context.get("question") or "")
        return {"question": question[:200], "question_type": context.get("question_type")}

    @staticmethod
    def _safe_output(output: dict) -> dict:
        safe: dict = {}
        for key, value in output.items():
            if key.startswith("__"):
                continue
            if isinstance(value, str):
                safe[key] = value[:200]
            elif isinstance(value, (int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, list):
                safe[key] = value[:10]
            elif isinstance(value, dict):
                safe[key] = {k: (v[:120] if isinstance(v, str) else v) for k, v in list(value.items())[:10]}
        return safe

    @staticmethod
    def _summary(node: dict, output: dict, status: str) -> str:
        label = NODE_TYPE_LABELS.get(node.get("type"), node.get("type"))
        if status != "succeeded":
            return f"{label}：{status}"
        for key in ("summary", "mode", "branch", "source_count", "candidate_count"):
            if key in output and output[key] is not None:
                return f"{label}：{output[key]}"
        return f"{label}：完成"


class ChatflowEngine:
    """调试运行：使用与生产相同的 ChatflowRunner，include_generation=true 时真实执行生成节点。"""

    def __init__(self, session: Session, settings: Settings, user=None):
        self.session = session
        self.settings = settings
        self.user = user
        self.config = load_active_config(session, settings)
        self.ollama = OllamaClient(settings)
        self.deepseek = DeepSeekClient(settings)

    async def debug_run(
        self, graph: dict, question: str, knowledge_base_id: uuid.UUID | None = None,
        include_generation: bool = False,
    ) -> dict:
        variables = {
            "question": (question or "").strip(),
            "knowledge_base_id": knowledge_base_id,
            "include_generation": include_generation,
            "question_type": None,
        }
        runner = ChatflowRunner(graph, self._handlers())
        result = await runner.run(variables, dry_run=not include_generation)
        return result.to_payload()

    def _handlers(self) -> dict[str, NodeHandler]:
        return {
            "start": self._start,
            "classify": self._classify,
            "context_completion": self._context_completion,
            "query_rewrite": self._query_rewrite,
            "multi_query": self._multi_query,
            "knowledge_search": self._knowledge_search,
            "reranker": self._reranker,
            "condition": self._condition,
            "local_model": self._local_model,
            "deepseek": self._deepseek,
            "harness": self._harness,
            "answer_check": self._answer_check,
            "no_answer": self._no_answer,
            "final_answer": self._final_answer,
        }

    # -- 通用节点 --
    def _start(self, context: FlowContext, node: dict) -> dict:
        return {"question": context.get("question")}

    def _classify(self, context: FlowContext, node: dict) -> dict:
        question_type = context.get("question_type") or classify_question(context.get("question") or "")
        context.set("question_type", question_type)
        return {"question_type": question_type, "summary": question_type}

    def _context_completion(self, context: FlowContext, node: dict) -> dict:
        return {"used_context": bool(context.get("history"))}

    async def _query_rewrite(self, context: FlowContext, node: dict) -> dict:
        rewriter = QueryRewriteService(self.settings, self.config, ollama=self.ollama)
        outcome = await rewriter.rewrite(context.get("question") or "", context.get("history"))
        context.set("retrieval_query", outcome.retrieval_query)
        context.set("rewrite_info", outcome)
        return {
            "retrieval_query": outcome.retrieval_query, "used_context": outcome.used_context,
            "warning": outcome.warning, "summary": outcome.retrieval_query[:80],
        }

    async def _multi_query(self, context: FlowContext, node: dict) -> dict:
        rewriter = QueryRewriteService(self.settings, self.config, ollama=self.ollama)
        queries = await rewriter.multi_query(context.get("retrieval_query") or context.get("question") or "")
        context.set("queries", queries)
        return {"queries": queries, "count": len(queries)}

    def _search_request(self, context: FlowContext, limit: int | None = None) -> SearchRequest:
        return SearchRequest(
            query=context.get("retrieval_query") or context.get("question") or "",
            knowledge_base_id=context.get("knowledge_base_id"),
            limit=limit or self.config.final_limit,
        )

    def _knowledge_search(self, context: FlowContext, node: dict) -> dict:
        service = SearchService(self.session, self.settings, user=self.user, config=self.config)
        request = self._search_request(context, (node.get("config") or {}).get("limit"))
        outcome = service.search_with_diagnostics(request, extra_queries=(context.get("queries") or [])[1:])
        context.set("results", outcome.items)
        context.set("diagnostics", outcome.diagnostics)
        context.set("candidate_count", outcome.diagnostics.candidate_count)
        return {
            "candidate_count": outcome.diagnostics.candidate_count,
            "source_count": len(outcome.items),
            "documents": list(dict.fromkeys(item.document_name for item in outcome.items))[:5],
            "mode": outcome.diagnostics.mode, "summary": f"{len(outcome.items)} 个片段",
        }

    def _reranker(self, context: FlowContext, node: dict) -> dict:
        diagnostics = context.get("diagnostics")
        applied = bool(diagnostics and diagnostics.rerank_applied)
        return {"rerank_applied": applied, "summary": "已精排" if applied else "未启用"}

    def _condition(self, context: FlowContext, node: dict) -> dict:
        results = context.get("results") or []
        evidence = [
            SimpleNamespace(citation_number=index + 1, content=item.content)
            for index, item in enumerate(results)
        ]
        confidence = compute_confidence(results, evidence, "")
        sufficient = bool(results) and confidence.score >= 0.42
        if sufficient:
            logical = "evidence"
        elif context.get("candidate_count", 0) > 0:
            logical = "deepseek_only"
        else:
            logical = "no_answer"
        branch = map_condition_branch(node, logical)
        context.set("branch", branch)
        context.set("confidence", confidence.to_payload())
        return {"branch": branch, "logical_branch": logical, "score": round(confidence.score, 4), "summary": logical}

    async def _local_model(self, context: FlowContext, node: dict) -> dict:
        if not context.get("include_generation") or context.dry_run:
            return {"__skipped__": True, "reason": "调试模式未开启生成"}
        results = context.get("results") or []
        if not results:
            return {"answer": "", "skipped_reason": "没有可用片段"}
        evidence = "\n\n".join(
            f"[{index + 1}] {item.document_name}：{item.content}" for index, item in enumerate(results)
        )
        messages = [
            GenerationMessage(role="system", content="只能依据给出的内部资料回答，使用[n]引用。"),
            GenerationMessage(role="user", content=f"内部资料：\n{evidence}\n\n问题：{context.get('question')}"),
        ]
        started = perf_counter()
        parts: list[str] = []
        first_token: float | None = None
        try:
            async for item in self.ollama.stream_with_stats(messages):
                delta = item.get("delta") or ""
                if not delta:
                    continue
                if first_token is None:
                    first_token = round((perf_counter() - started) * 1000, 2)
                parts.append(delta)
        except LlmError as exc:
            return {"answer": "".join(parts), "error": exc.message, "provider": "local"}
        answer = "".join(parts)
        context.set("answer", answer)
        return {
            "answer": answer[:400], "provider": "local", "first_token_ms": first_token,
            "summary": f"本地生成 {len(answer)} 字",
        }

    async def _deepseek(self, context: FlowContext, node: dict) -> dict:
        if not context.get("include_generation") or context.dry_run:
            return {"__skipped__": True, "reason": "调试模式未开启生成"}
        if not self.deepseek.configured:
            return {"answer": "", "warning": "尚未配置 DeepSeek API Key", "summary": "未配置"}
        started = perf_counter()
        parts: list[str] = []
        try:
            async for delta in self.deepseek.stream([GenerationMessage(role="user", content=context.get("question") or "")]):
                parts.append(delta)
        except LlmError as exc:
            return {"answer": "", "error": exc.message, "provider": "deepseek"}
        answer = "".join(parts)
        context.set("answer", answer)
        return {"answer": answer[:400], "provider": "deepseek", "duration_ms": round((perf_counter() - started) * 1000, 2)}

    def _harness(self, context: FlowContext, node: dict) -> dict:
        # 调试引擎不直接执行写操作；生产 Harness 由 HarnessService 逐次人工确认。
        return {"requires_approval": True, "summary": "写操作需人工确认"}

    def _answer_check(self, context: FlowContext, node: dict) -> dict:
        answer = context.get("answer") or ""
        results = context.get("results") or []
        sources = [
            SimpleNamespace(
                citation_number=index + 1, content=item.content, chunk_id=item.chunk_id,
                document_id=item.document_id, document_version=item.document_version,
                page_start=item.page_start, slide_number=item.slide_number, sheet_name=item.sheet_name,
            )
            for index, item in enumerate(results)
        ]
        report = verify_answer(answer, sources)
        context.set("citation_report", report)
        return {"checked": report.checked, "ok": report.ok, "summary": "引用通过" if report.ok else "存在待核对引用"}

    def _no_answer(self, context: FlowContext, node: dict) -> dict:
        payload = no_answer_payload(NO_RELEVANT_DOCUMENT)
        context.set("final_output", payload)
        context.set("answer", payload["message"])
        return payload

    def _final_answer(self, context: FlowContext, node: dict) -> dict:
        if context.get("final_output") is None:
            context.set("final_output", {
                "answer": context.get("answer") or context.get("retrieval_query") or context.get("question"),
                "provider": "local",
            })
        return {"final": context.get("final_output"), "summary": "回答完成"}
