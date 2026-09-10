"""P2-4 轻量 Chatflow 纯单元测试：节点目录、图校验与流程计划（不依赖数据库）。"""

import pytest

from app.errors import AppError
from app.services.chatflow import (
    NODE_TYPES, VALID_NODE_TYPES, build_plan, default_graph, validate_graph,
)

REQUIRED_TYPES = {
    "start", "question_classify", "query_rewrite", "retrieval", "rerank", "condition",
    "local_model", "deepseek", "harness", "answer_check", "final_answer",
}


def test_node_catalog_covers_required_types():
    assert REQUIRED_TYPES <= VALID_NODE_TYPES
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
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "enabled": True, "config": {}, "next": "a"},
            {"id": "a", "type": "retrieval", "name": "A", "enabled": True, "config": {}, "next": "start"},
        ],
        "start_node_id": "start",
    }
    with pytest.raises(AppError) as excinfo:
        validate_graph(graph)
    assert excinfo.value.code == "CHATFLOW_GRAPH_CYCLE"


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
        if node["type"] in ("query_rewrite", "rerank", "answer_check", "deepseek", "harness"):
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
