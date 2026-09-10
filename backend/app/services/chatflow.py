"""P2-4 轻量 Chatflow：固定画布节点、草稿/发布版本、调试运行与助手绑定。

第一版不做自由拖拽：节点用 next / branches 串成固定流程；引擎按图执行并记录
每个节点的耗时、状态与输出摘要。生产问答由 RagService 读取已发布图来决定阶段开关。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from types import SimpleNamespace
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import Chatflow, ChatflowVersion
from app.schemas.search import SearchRequest
from app.services.answer_quality import (
    LOW_RELEVANCE, NO_RELEVANT_DOCUMENT, PERMISSION_RESTRICTED, classify_question,
    compute_confidence, no_answer_payload, verify_answer,
)
from app.services.query_rewrite import QueryRewriteService
from app.services.retrieval_config import RetrievalConfig, load_active_config
from app.services.search import SearchService

# 固定画布节点目录：前端据此渲染节点与配置项。
NODE_TYPES: list[dict] = [
    {"type": "start", "label": "开始", "category": "control", "config_fields": []},
    {"type": "question_classify", "label": "问题分类", "category": "understand", "config_fields": []},
    {"type": "query_rewrite", "label": "问题改写", "category": "understand", "config_fields": [
        {"key": "multi_query", "type": "bool", "label": "启用 Multi-query"},
        {"key": "history_turns", "type": "int", "label": "上下文轮数"},
    ]},
    {"type": "retrieval", "label": "知识库检索", "category": "retrieve", "config_fields": [
        {"key": "limit", "type": "int", "label": "最终片段数量"},
    ]},
    {"type": "rerank", "label": "Reranker 精排", "category": "retrieve", "config_fields": []},
    {"type": "condition", "label": "条件判断", "category": "control", "config_fields": [
        {"key": "branches", "type": "branches", "label": "分支"},
    ]},
    {"type": "local_model", "label": "本地模型", "category": "generate", "config_fields": [
        {"key": "timeout_seconds", "type": "int", "label": "超时秒数"},
    ]},
    {"type": "deepseek", "label": "DeepSeek", "category": "generate", "config_fields": []},
    {"type": "harness", "label": "Harness 运维", "category": "generate", "config_fields": []},
    {"type": "answer_check", "label": "答案校验", "category": "check", "config_fields": []},
    {"type": "no_answer", "label": "缺失知识提示", "category": "check", "config_fields": []},
    {"type": "final_answer", "label": "最终回答", "category": "control", "config_fields": []},
]
NODE_TYPE_LABELS = {item["type"]: item["label"] for item in NODE_TYPES}
VALID_NODE_TYPES = set(NODE_TYPE_LABELS)


def default_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "enabled": True, "config": {}, "next": "classify"},
            {"id": "classify", "type": "question_classify", "name": "问题分类", "enabled": True, "config": {}, "next": "rewrite"},
            {"id": "rewrite", "type": "query_rewrite", "name": "上下文补全与改写", "enabled": True,
             "config": {"multi_query": True}, "next": "retrieval"},
            {"id": "retrieval", "type": "retrieval", "name": "知识库检索", "enabled": True, "config": {}, "next": "rerank"},
            {"id": "rerank", "type": "rerank", "name": "Reranker 精排", "enabled": True, "config": {}, "next": "confidence"},
            {"id": "confidence", "type": "condition", "name": "置信度判断", "enabled": True, "config": {
                "branches": [
                    {"when": "sufficient", "next": "local_model"},
                    {"when": "insufficient_and_deepseek", "next": "deepseek"},
                    {"when": "ops", "next": "harness"},
                ],
                "default_next": "no_answer",
            }, "next": None},
            {"id": "local_model", "type": "local_model", "name": "本地千问", "enabled": True, "config": {}, "next": "answer_check"},
            {"id": "answer_check", "type": "answer_check", "name": "答案校验", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "deepseek", "type": "deepseek", "name": "DeepSeek 通用知识", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "harness", "type": "harness", "name": "Harness 运维", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "no_answer", "type": "no_answer", "name": "缺失知识提示", "enabled": True, "config": {}, "next": "final_answer"},
            {"id": "final_answer", "type": "final_answer", "name": "最终回答", "enabled": True, "config": {}, "next": None},
        ],
        "start_node_id": "start",
    }


def validate_graph(graph: dict) -> None:
    """校验节点类型、唯一 id、连线目标与是否成环。"""
    if not isinstance(graph, dict):
        raise AppError("CHATFLOW_GRAPH_INVALID", "流程定义必须是对象", 422)
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise AppError("CHATFLOW_GRAPH_INVALID", "流程至少需要一个节点", 422)
    ids: list[str] = []
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
        ids.append(node_id)
    start = graph.get("start_node_id") or "start"
    if start not in by_id:
        raise AppError("CHATFLOW_GRAPH_INVALID", "开始节点不存在", 422)
    for node in nodes:
        targets = [node.get("next")]
        config = node.get("config") or {}
        for branch in config.get("branches") or []:
            targets.append(branch.get("next") if isinstance(branch, dict) else None)
        targets.append(config.get("default_next"))
        targets.append(config.get("on_error"))
        for target in targets:
            if target and target not in by_id:
                raise AppError("CHATFLOW_GRAPH_INVALID", f"节点 {node.get('id')} 指向不存在的节点：{target}", 422)
    _assert_acyclic(by_id, start)


def _assert_acyclic(by_id: dict[str, dict], start: str) -> None:
    WHITE, GREY, BLACK = 0, 1, 2
    colors = {node_id: WHITE for node_id in by_id}

    def edges(node: dict) -> list[str]:
        config = node.get("config") or {}
        result = [node.get("next")]
        for branch in config.get("branches") or []:
            if isinstance(branch, dict):
                result.append(branch.get("next"))
        result.append(config.get("default_next"))
        return [item for item in result if item]

    def visit(node_id: str) -> None:
        colors[node_id] = GREY
        for target in edges(by_id[node_id]):
            if colors.get(target) == GREY:
                raise AppError("CHATFLOW_GRAPH_CYCLE", "流程存在环，请检查分支连线", 422)
            if colors.get(target) == WHITE:
                visit(target)
        colors[node_id] = BLACK

    visit(start)


@dataclass
class ChatflowPlan:
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
        return next((node for node in nodes.values() if node.get("type") == node_type), None)

    rewrite = find("query_rewrite")
    return ChatflowPlan(
        graph=graph, nodes=nodes, start_node_id=graph.get("start_node_id") or "start",
        rewrite_enabled=rewrite is not None,
        multi_query_enabled=bool(rewrite and (rewrite.get("config") or {}).get("multi_query")),
        rerank_enabled=find("rerank") is not None,
        answer_check_enabled=find("answer_check") is not None,
        classify_enabled=find("question_classify") is not None,
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
        if chatflow is None or not chatflow.enabled:
            return None
        if chatflow.published_version and chatflow.published_graph:
            return chatflow.published_graph
        return chatflow.draft_graph


@dataclass
class NodeResult:
    id: str
    type: str
    name: str
    status: str
    duration_ms: float
    output: dict = field(default_factory=dict)
    error: str | None = None

    def to_payload(self) -> dict:
        return {
            "id": self.id, "type": self.type, "name": self.name, "status": self.status,
            "duration_ms": self.duration_ms, "output": self.output, "error": self.error,
        }


class ChatflowEngine:
    """调试运行引擎：按图执行节点并记录耗时/状态；生产阶段开关由 ChatflowPlan 提供。"""

    MAX_STEPS = 50

    def __init__(self, session: Session, settings: Settings, user=None):
        self.session = session
        self.settings = settings
        self.user = user
        self.config = load_active_config(session, settings)

    async def debug_run(
        self, graph: dict, question: str, knowledge_base_id: uuid.UUID | None = None,
        include_generation: bool = False,
    ) -> dict:
        validate_graph(graph)
        by_id = {str(node["id"]): node for node in graph["nodes"]}
        context: dict = {"question": question.strip(), "knowledge_base_id": knowledge_base_id}
        results: list[NodeResult] = []
        node_id = graph.get("start_node_id") or "start"
        steps = 0
        while node_id and steps < self.MAX_STEPS:
            node = by_id.get(node_id)
            if node is None:
                break
            steps += 1
            started = perf_counter()
            try:
                output = await self._run_node(node, context, include_generation)
                status = "skipped" if output.get("__skipped__") else "succeeded"
                output = {key: value for key, value in output.items() if key != "__skipped__"}
                error = None
            except Exception as exc:  # 节点失败处理：按 on_error 跳转或终止。
                output = {}
                error = str(exc)
                status = "failed"
            duration = round((perf_counter() - started) * 1000, 2)
            timeout_seconds = (node.get("config") or {}).get("timeout_seconds")
            if status == "succeeded" and timeout_seconds and duration > float(timeout_seconds) * 1000:
                status, error = "failed", f"节点超时（>{timeout_seconds}s）"
            results.append(NodeResult(
                id=node_id, type=node.get("type", ""), name=node.get("name") or NODE_TYPE_LABELS.get(node.get("type", ""), node_id),
                status=status, duration_ms=duration, output=output, error=error,
            ))
            if status == "failed":
                node_id = (node.get("config") or {}).get("on_error") or None
                continue
            node_id = self._next_node(node, output)
        return {
            "nodes": [result.to_payload() for result in results],
            "total_ms": round(sum(result.duration_ms for result in results), 2),
            "final": context.get("final_output"),
        }

    async def _run_node(self, node: dict, context: dict, include_generation: bool) -> dict:
        node_type = node.get("type")
        config = node.get("config") or {}
        if node_type == "start":
            return {"question": context["question"]}
        if node_type == "question_classify":
            question_type = classify_question(context["question"])
            context["question_type"] = question_type
            return {"question_type": question_type}
        if node_type == "query_rewrite":
            rewriter = QueryRewriteService(self.settings, self.config)
            outcome = await rewriter.rewrite(context["question"], context.get("history"))
            queries = await rewriter.multi_query(outcome.retrieval_query)
            context["retrieval_query"] = outcome.retrieval_query
            context["queries"] = queries
            return {
                "retrieval_query": outcome.retrieval_query, "queries": queries,
                "used_context": outcome.used_context, "warning": outcome.warning,
            }
        if node_type == "retrieval":
            service = SearchService(self.session, self.settings, user=self.user, config=self.config)
            request = SearchRequest(
                query=context.get("retrieval_query") or context["question"],
                knowledge_base_id=context.get("knowledge_base_id"),
                limit=config.get("limit") or self.config.final_limit,
            )
            outcome = service.search_with_diagnostics(request, extra_queries=(context.get("queries") or [])[1:])
            context["results"] = outcome.items
            context["diagnostics"] = outcome.diagnostics
            context["candidate_count"] = outcome.diagnostics.candidate_count
            return {
                "candidate_count": outcome.diagnostics.candidate_count,
                "source_count": len(outcome.items),
                "documents": list(dict.fromkeys(item.document_name for item in outcome.items))[:5],
                "mode": outcome.diagnostics.mode,
            }
        if node_type == "rerank":
            diagnostics = context.get("diagnostics")
            return {"rerank_applied": bool(diagnostics and diagnostics.rerank_applied)}
        if node_type == "condition":
            results = context.get("results") or []
            evidence = [
                SimpleNamespace(citation_number=index + 1, content=item.content)
                for index, item in enumerate(results)
            ]
            confidence = compute_confidence(results, evidence, "")
            # 调试阶段用检索证据判断充分性。
            sufficient = bool(results) and confidence.score >= 0.42
            if sufficient:
                branch = "sufficient"
            elif self.config.multi_query_enabled and context.get("candidate_count", 0) > 0:
                branch = "insufficient_and_deepseek"
            else:
                branch = "no_answer"
            context["branch"] = branch
            context["confidence"] = confidence.to_payload()
            return {"branch": branch, "score": confidence.score}
        if node_type in ("local_model", "deepseek", "harness"):
            if not include_generation:
                return {"__skipped__": True, "reason": "调试模式不执行生成节点"}
            return {"__skipped__": True, "reason": "调试模式暂不执行生成节点"}
        if node_type == "answer_check":
            results = context.get("results") or []
            report = verify_answer("", [], {})
            return {"checked": report.checked, "ok": report.ok}
        if node_type == "no_answer":
            payload = no_answer_payload(NO_RELEVANT_DOCUMENT)
            context["final_output"] = payload
            return payload
        if node_type == "final_answer":
            context.setdefault("final_output", {"answer": context.get("retrieval_query") or context["question"]})
            return {"final": context["final_output"]}
        return {}

    @staticmethod
    def _next_node(node: dict, output: dict) -> str | None:
        if node.get("type") == "condition":
            config = node.get("config") or {}
            branch = output.get("branch")
            for item in config.get("branches") or []:
                if isinstance(item, dict) and item.get("when") == branch:
                    return item.get("next")
            return config.get("default_next")
        return node.get("next")
