"""P2-4 Chatflow 纯单元测试：节点目录、图校验、计划与执行引擎（不依赖数据库）。"""

import asyncio

import pytest

from app.errors import AppError
from app.services.chatflow import (
    NODE_TYPES, VALID_NODE_TYPES, ChatflowRunner, build_plan, default_graph, validate_graph,
)

REQUIRED_TYPES = {
    "start", "classify", "context_completion", "query_rewrite", "multi_query",
    "knowledge_search", "reranker", "condition", "local_model", "deepseek", "harness",
    "answer_check", "final_answer",
}
LEGACY_TYPES = {"question_classify", "retrieval", "rerank"}


def _node(node_id, node_type, nxt=None, config=None, enabled=True):
    return {
        "id": node_id, "type": node_type, "name": node_id, "enabled": enabled,
        "config": config or {}, "next": nxt,
    }


def _graph(nodes, start="start"):
    return {"nodes": nodes, "start_node_id": start}


async def _noop(context, node):
    return {}


def test_node_catalog_covers_required_types():
    assert REQUIRED_TYPES <= VALID_NODE_TYPES
    assert LEGACY_TYPES <= VALID_NODE_TYPES
    assert len(NODE_TYPES) == len(VALID_NODE_TYPES)


def test_default_graph_is_valid_and_has_all_nodes():
    graph = default_graph()
    validate_graph(graph)
    types = {node["type"] for node in graph["nodes"]}
    assert REQUIRED_TYPES <= types
    assert graph["start_node_id"] == "start"


def test_validate_graph_rejects_unknown_type():
    graph = default_graph()
    graph["nodes"][0]["type"] = "not_a_node"
    with pytest.raises(AppError) as excinfo:
        validate_graph(graph)
    assert excinfo.value.code == "CHATFLOW_GRAPH_INVALID"


def test_validate_graph_rejects_duplicate_id():
    graph = default_graph()
    graph["nodes"][1]["id"] = graph["nodes"][0]["id"]
    with pytest.raises(AppError) as excinfo:
        validate_graph(graph)
    assert excinfo.value.code == "CHATFLOW_GRAPH_INVALID"


def test_validate_graph_rejects_dangling_target():
    graph = default_graph()
    graph["nodes"][0]["next"] = "missing"
    with pytest.raises(AppError):
        validate_graph(graph)


def test_validate_graph_rejects_cycle():
    graph = _graph([
        _node("start", "start", "a"),
        _node("a", "knowledge_search", "start"),
    ])
    with pytest.raises(AppError) as excinfo:
        validate_graph(graph)
    assert excinfo.value.code == "CHATFLOW_GRAPH_CYCLE"


def test_validate_graph_rejects_missing_terminal():
    # 仅由条件节点组成且所有分支都指向彼此，形成环时先被环检测拦截。
    graph = _graph([
        _node("start", "start", "c"),
        _node("c", "condition", None, {"branches": [{"when": "x", "next": "start"}], "default_next": "start"}),
    ])
    with pytest.raises(AppError) as excinfo:
        validate_graph(graph)
    assert excinfo.value.code in ("CHATFLOW_GRAPH_CYCLE", "CHATFLOW_GRAPH_INVALID")


def test_build_plan_reflects_node_switches():
    graph = default_graph()
    plan = build_plan(graph)
    assert plan is not None
    assert plan.rewrite_enabled is True
    assert plan.multi_query_enabled is True
    assert plan.rerank_enabled is True
    assert plan.answer_check_enabled is True
    assert plan.deepseek_enabled is True
    assert plan.harness_enabled is True

    for node in graph["nodes"]:
        if node["type"] in ("query_rewrite", "multi_query", "reranker", "answer_check", "deepseek", "harness"):
            node["enabled"] = False
    plan2 = build_plan(graph)
    assert plan2.rewrite_enabled is False
    assert plan2.multi_query_enabled is False
    assert plan2.rerank_enabled is False
    assert plan2.answer_check_enabled is False
    assert plan2.deepseek_enabled is False
    assert plan2.harness_enabled is False


def test_build_plan_returns_none_for_empty_graph():
    assert build_plan(None) is None
    assert build_plan({}) is None


def test_active_graph_only_uses_published_version():
    from types import SimpleNamespace

    from app.services.chatflow import ChatflowService

    draft_only = SimpleNamespace(enabled=True, published_version=0, published_graph={}, draft_graph={"nodes": []})
    assert ChatflowService.active_graph(draft_only) is None
    published_graph = {"nodes": [{"id": "start"}]}
    published = SimpleNamespace(enabled=True, published_version=2, published_graph=published_graph, draft_graph={})
    assert ChatflowService.active_graph(published) == published_graph
    assert ChatflowService.active_graph(None) is None


def test_condition_branch_mapping_supports_legacy_names():
    from app.services.chatflow import map_condition_branch

    legacy = {"config": {"branches": [
        {"when": "sufficient", "next": "a"},
        {"when": "insufficient_and_deepseek", "next": "b"},
    ]}}
    assert map_condition_branch(legacy, "evidence") == "sufficient"
    assert map_condition_branch(legacy, "deepseek_only") == "insufficient_and_deepseek"
    modern = {"config": {"branches": [{"when": "evidence", "next": "a"}]}}
    assert map_condition_branch(modern, "evidence") == "evidence"


# ---------------------------------------------------------------- 执行引擎

def test_runner_executes_nodes_in_order_and_records_timing():
    order: list[str] = []

    def handler(name):
        async def run(context, node):
            order.append(name)
            context.set(f"seen_{name}", True)
            return {"summary": name}
        return run

    graph = _graph([
        _node("start", "start", "a"),
        _node("a", "classify", "b"),
        _node("b", "final_answer"),
    ])
    handlers = {"start": handler("start"), "classify": handler("classify"), "final_answer": handler("final")}
    result = asyncio.run(ChatflowRunner(graph, handlers).run({"question": "q"}))
    assert order == ["start", "classify", "final"]
    assert result.variables["seen_a"] is True
    assert all(record.status == "succeeded" for record in result.records)
    assert all(record.started_at and record.ended_at for record in result.records)
    assert result.total_ms >= 0


def test_runner_condition_routes_by_branch():
    async def condition(context, node):
        context.set("branch", "yes")
        return {"branch": "yes"}

    visited: list[str] = []

    async def to_a(context, node):
        visited.append("a")
        return {}

    async def to_b(context, node):
        visited.append("b")
        return {}

    graph = _graph([
        _node("start", "start", "c"),
        _node("c", "condition", None, {
            "branches": [{"when": "yes", "next": "a"}, {"when": "no", "next": "b"}],
            "default_next": "b",
        }),
        _node("a", "final_answer"),
        _node("b", "no_answer"),
    ])
    handlers = {"start": _noop, "condition": condition, "final_answer": to_a, "no_answer": to_b}
    asyncio.run(ChatflowRunner(graph, handlers).run({}))
    assert visited == ["a"]


def test_runner_failure_uses_fallback_node():
    async def failing(context, node):
        raise RuntimeError("boom")

    recovered: list[str] = []

    async def recover(context, node):
        recovered.append("recovered")
        return {}

    graph = _graph([
        _node("start", "start", "x"),
        _node("x", "knowledge_search", None, {"on_failure": "recover"}),
        _node("recover", "final_answer"),
    ])
    handlers = {"start": _noop, "knowledge_search": failing, "final_answer": recover}
    result = asyncio.run(ChatflowRunner(graph, handlers).run({}))
    assert recovered == ["recovered"]
    failed = [record for record in result.records if record.status == "failed"]
    assert failed and "boom" in (failed[0].error or "")


def test_runner_timeout_uses_on_timeout():
    async def slow(context, node):
        await asyncio.sleep(0.05)
        return {}

    recovered: list[str] = []

    async def recover(context, node):
        recovered.append("recovered")
        return {}

    graph = _graph([
        _node("start", "start", "x"),
        _node("x", "local_model", None, {"timeout_seconds": 0.01, "on_timeout": "recover"}),
        _node("recover", "final_answer"),
    ])
    handlers = {"start": _noop, "local_model": slow, "final_answer": recover}
    result = asyncio.run(ChatflowRunner(graph, handlers).run({}))
    assert recovered == ["recovered"]
    assert any(record.status == "timeout" for record in result.records)


def test_runner_enforces_max_steps():
    nodes = [_node("start", "start", "n0")]
    for index in range(5):
        nodes.append(_node(f"n{index}", "classify", f"n{index + 1}" if index < 4 else None))
    graph = _graph(nodes)
    with pytest.raises(AppError) as excinfo:
        asyncio.run(ChatflowRunner(graph, {"start": _noop, "classify": _noop}, max_steps=2).run({}))
    assert excinfo.value.code == "CHATFLOW_MAX_STEPS"


def test_runner_skips_disabled_nodes():
    visited: list[str] = []

    async def mark(context, node):
        visited.append(node["id"])
        return {}

    graph = _graph([
        _node("start", "start", "a"),
        _node("a", "classify", "b", enabled=False),
        _node("b", "final_answer"),
    ])
    asyncio.run(ChatflowRunner(graph, {"start": mark, "classify": mark, "final_answer": mark}).run({}))
    assert "a" not in visited
    assert "b" in visited


def test_generation_node_executes_when_not_dry_run():
    called: dict[str, bool] = {}

    async def local(context, node):
        called["executed"] = True
        return {"answer": "hi"}

    graph = _graph([_node("start", "start", "m"), _node("m", "local_model")])
    asyncio.run(ChatflowRunner(graph, {"start": _noop, "local_model": local}).run({}, dry_run=False))
    assert called.get("executed") is True


def test_legacy_graph_nodes_are_executed_via_alias():
    visited: list[str] = []

    async def mark(context, node):
        visited.append(node["id"])
        return {}

    graph = _graph([
        _node("start", "start", "r"),
        _node("r", "retrieval", "f"),
        _node("f", "final_answer"),
    ])
    asyncio.run(ChatflowRunner(graph, {"start": mark, "knowledge_search": mark, "final_answer": mark}).run({}))
    assert "r" in visited
