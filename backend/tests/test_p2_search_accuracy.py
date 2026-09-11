"""P2-1 检索准确性纯单元测试：查询扩展/拼写纠正/改写/多查询/融合（不依赖数据库）。"""

import asyncio
from types import SimpleNamespace

from app.llm import LlmUnavailable
from app.services.query_processing import QueryProcessor, _edit_distance
from app.services.query_rewrite import QueryRewriteService
from app.services.retrieval_config import RetrievalConfig
from app.services.search import Candidate, SearchService


# ---------------------------------------------------------------- 词典与拼写

def test_query_processor_expands_dictionary_bidirectionally():
    dictionary = {"k8s": ["kubernetes", "容器编排"]}
    processor = QueryProcessor("", dictionary=dictionary)
    processed = processor.process("请介绍 K8s 部署")
    assert "kubernetes" in processed.expanded_terms
    # 反向：用全称也能扩展到简称。
    reverse = processor.process("kubernetes 集群")
    assert "k8s" in reverse.expanded_terms


def test_query_processor_merges_config_and_dictionary():
    processor = QueryProcessor("日报|周报", dictionary={"日报": ["工作记录"]})
    processed = processor.process("看下日报")
    assert {"周报", "工作记录"} <= set(processed.expanded_terms)


def test_query_processor_spelling_correction():
    processor = QueryProcessor("", dictionary={"kubernetes": ["k8s"]}, spelling_correction=True)
    processed = processor.process("kubenetes 怎么部署")
    assert "kubernetes" in processed.expanded_terms
    assert "kubernetes" in processed.corrections


def test_query_processor_spelling_correction_disabled():
    processor = QueryProcessor("", dictionary={"kubernetes": ["k8s"]}, spelling_correction=False)
    assert processor.process("kubenetes").corrections == []


def test_edit_distance_limits():
    assert _edit_distance("kubenetes", "kubernetes", limit=2) == 1
    assert _edit_distance("abc", "xyz", limit=1) == 2


# ---------------------------------------------------------------- 改写 / 多查询

class _FakeOllama:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def complete_json(self, messages, model=None):
        self.calls.append((messages, model))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _run(coro):
    return asyncio.run(coro)


def test_rewrite_disabled_returns_original_without_calling_model():
    config = RetrievalConfig(query_rewrite_enabled=False, context_completion_enabled=False)
    ollama = _FakeOllama([{"retrieval_query": "不会用到"}])
    service = QueryRewriteService(SimpleNamespace(), config, ollama=ollama)
    outcome = _run(service.rewrite("日报中气泡后来怎么样了？"))
    assert outcome.retrieval_query == "日报中气泡后来怎么样了？"
    assert ollama.calls == []


def test_rewrite_uses_model_output_and_keeps_original():
    config = RetrievalConfig(query_rewrite_enabled=True, context_completion_enabled=True)
    ollama = _FakeOllama([{
        "standalone_question": "气泡检测项目后来进展如何？",
        "retrieval_query": "气泡检测 项目 进展",
        "used_context": True,
    }])
    service = QueryRewriteService(SimpleNamespace(), config, ollama=ollama)
    outcome = _run(service.rewrite("后来怎么样了？", [SimpleNamespace(question="气泡检测项目进展怎么样？", answer="进行中")]))
    assert outcome.original == "后来怎么样了？"
    assert outcome.retrieval_query == "气泡检测 项目 进展"
    assert outcome.standalone_question == "气泡检测项目后来进展如何？"
    assert outcome.used_context is True


def test_rewrite_falls_back_to_original_on_model_failure():
    config = RetrievalConfig(query_rewrite_enabled=True)
    ollama = _FakeOllama([LlmUnavailable("OLLAMA_UNAVAILABLE", "无法连接 Ollama")])
    service = QueryRewriteService(SimpleNamespace(), config, ollama=ollama)
    outcome = _run(service.rewrite("原始问题"))
    assert outcome.retrieval_query == "原始问题"
    assert outcome.warning


def test_multi_query_caps_and_includes_original():
    config = RetrievalConfig(multi_query_enabled=True, multi_query_count=3)
    ollama = _FakeOllama([{"queries": ["查询A", "查询B", "查询C", "查询D"]}])
    service = QueryRewriteService(SimpleNamespace(), config, ollama=ollama)
    queries = _run(service.multi_query("原始查询"))
    assert queries[0] == "原始查询"
    assert len(queries) == 3


def test_multi_query_disabled_returns_single_query():
    config = RetrievalConfig(multi_query_enabled=False)
    service = QueryRewriteService(SimpleNamespace(), config, ollama=_FakeOllama([]))
    assert _run(service.multi_query("原始查询")) == ["原始查询"]


# ---------------------------------------------------------------- 多查询 RRF 融合

def _candidate(chunk_id: str, document_name: str = "doc.txt") -> Candidate:
    chunk = SimpleNamespace(id=chunk_id, content="content", sequence_number=1)
    document = SimpleNamespace(id=f"doc-{chunk_id}", original_name=document_name)
    return Candidate(chunk=chunk, document=document)


def test_fuse_lists_merges_multiple_query_rankings():
    config = RetrievalConfig(dictionary_enabled=False)
    service = SearchService(session=None, settings=SimpleNamespace(), config=config)
    keyword_a = [_candidate("a"), _candidate("b")]
    vector_a = [_candidate("b"), _candidate("c")]
    keyword_b = [_candidate("b")]
    fused = service._fuse_lists(
        [("keyword", keyword_a, 1.0), ("vector", vector_a, 1.0), ("keyword", keyword_b, 1.0)], "query",
    )
    ids = [item.chunk.id for item in fused]
    assert set(ids) == {"a", "b", "c"}
    # b 同时出现在三组排序中，融合分最高。
    assert ids[0] == "b"


def test_rerank_records_before_after_ranks():
    config = RetrievalConfig(dictionary_enabled=False, rerank_enabled=True, rerank_candidate_limit=10)
    service = SearchService(session=None, settings=SimpleNamespace(), config=config)

    class _FakeReranker:
        def rerank(self, query, texts, enabled=None, model=None):
            from app.services.reranking import RerankOutcome
            return RerankOutcome([0.1, 0.9, 0.5])

    service.reranker = _FakeReranker()
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    ranked, warning, mode = service._rerank("q", candidates)
    assert mode == "hybrid_rerank"
    assert warning is None
    assert ranked[0].chunk.id == "b"
    # 重排前 b/c/a，重排后 b/a/c：记录重排前后名次用于展示。
    assert [item.post_rerank_rank for item in ranked] == [1, 2, 3]
    assert [item.pre_rerank_rank for item in ranked] == [2, 3, 1]
    assert ranked[0].pre_rerank_rank == 2 and ranked[0].post_rerank_rank == 1


def test_rerank_degrades_to_rrf_when_model_unavailable():
    config = RetrievalConfig(dictionary_enabled=False, rerank_enabled=True)
    service = SearchService(session=None, settings=SimpleNamespace(), config=config)

    class _BrokenReranker:
        def rerank(self, query, texts, enabled=None, model=None):
            from app.services.reranking import RerankOutcome
            return RerankOutcome(None, "本地精排模型不可用，本次已自动降级为混合检索")

    service.reranker = _BrokenReranker()
    candidates = [_candidate("a"), _candidate("b")]
    ranked, warning, mode = service._rerank("q", candidates)
    assert mode == "hybrid_rrf"
    assert warning
    assert [item.pre_rerank_rank for item in ranked] == [item.post_rerank_rank for item in ranked]


def test_retrieval_config_has_new_p2_fields():
    config = RetrievalConfig.from_dict({
        "query_rewrite_enabled": "true", "multi_query_enabled": 1, "multi_query_count": "4",
        "dictionary_enabled": "false", "spelling_correction_enabled": True,
    })
    assert config.query_rewrite_enabled is True
    assert config.multi_query_enabled is True
    assert config.multi_query_count == 4
    assert config.dictionary_enabled is False
    assert config.spelling_correction_enabled is True


# ---------------------------------------------------------------- 生产链路接线

def test_dictionary_expansion_reaches_both_keyword_and_vector_recall():
    """管理员词典扩展必须真正进入生产检索的两路召回，而不是只记录在诊断里。"""
    from app.schemas.search import SearchRequest

    config = RetrievalConfig(
        query_rewrite_synonyms="k8s|kubernetes|容器编排", dictionary_enabled=False,
    )
    service = SearchService(
        session=None, settings=SimpleNamespace(search_feedback_ranking_enabled=False), config=config,
    )
    captured: dict[str, str] = {}
    service._keyword_candidates = lambda query, request: captured.__setitem__("keyword", query) or []
    service._vector_candidates = lambda query, request: captured.__setitem__("vector", query) or []
    service.search_with_diagnostics(SearchRequest(query="k8s 部署"))
    assert "kubernetes" in captured["keyword"]
    assert "kubernetes" in captured["vector"]


def test_answer_search_request_forwards_metadata_filters():
    """生产问答路径必须把结构化过滤条件传给检索服务。"""
    import uuid as uuid_module

    from app.schemas.answer import AnswerRequest
    from app.services.rag import RagService

    department_id = uuid_module.uuid4()
    owner_id = uuid_module.uuid4()
    request = AnswerRequest(
        question="问题", tags=["财务", "制度"], department_id=department_id, owner_user_id=owner_id,
        relative_path="制度/", version_number=3, valid_only=True,
    )
    search_request = RagService._search_request(None, request, {"kb_ids": [], "search_limit": 4})
    assert search_request.tags == ["财务", "制度"]
    assert search_request.department_id == department_id
    assert search_request.owner_user_id == owner_id
    assert search_request.relative_path == "制度/"
    assert search_request.version_number == 3
    assert search_request.valid_only is True
    assert search_request.limit == 4
