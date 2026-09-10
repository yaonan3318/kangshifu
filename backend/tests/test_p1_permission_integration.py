"""P1-15 多用户权限集成测试。

默认跳过；设置 ``COMPANY_SEARCH_TEST_DATABASE_URL`` 指向一个**临时** PostgreSQL
测试库后运行。测试会在该库上执行 Alembic 迁移并写入隔离数据，绝不连接正式库。

    COMPANY_SEARCH_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:54329/cs_test \
        python -m pytest backend/tests/test_p1_permission_integration.py -v
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest

TEST_DB = os.environ.get("COMPANY_SEARCH_TEST_DATABASE_URL")
if not TEST_DB:
    pytest.skip(
        "set COMPANY_SEARCH_TEST_DATABASE_URL to run multi-user integration tests",
        allow_module_level=True,
    )

import tempfile  # noqa: E402

os.environ["COMPANY_SEARCH_DATABASE_URL"] = TEST_DB
os.environ["COMPANY_SEARCH_OLLAMA_WARMUP_ENABLED"] = "false"
os.environ["COMPANY_SEARCH_ANSWER_CACHE_ENABLED"] = "true"
os.environ["COMPANY_SEARCH_FEEDBACK_RANKING_ENABLED"] = "false"
# 集成测试会反复登录，放宽限流避免测试自身触发 429。
os.environ["COMPANY_SEARCH_AUTH_LOGIN_RATE_LIMIT"] = "100000"
os.environ.setdefault("COMPANY_SEARCH_LIBRARY_ROOT", tempfile.mkdtemp(prefix="company-search-test-"))

from pathlib import Path  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    DEFAULT_KNOWLEDGE_BASE_ID, AclPermission, AnswerFeedback, AnswerFeedbackDocument, AuditLog,
    ChatMessage, ChatMessageRole, ChatMessageSource, ChatMessageStatus, ChatSession, Department,
    Document, DocumentAcl, DocumentChunk, DocumentFeedbackStats, DocumentStatus, DocumentVisibility,
    FeedbackRating, Role, SubjectType, User,
)
from app.schemas.answer import AnswerProvider, AnswerRequest, KnowledgeScope  # noqa: E402
from app.schemas.search import SearchRequest  # noqa: E402
from app.services import identity  # noqa: E402
from app.services.auth import hash_password  # noqa: E402
from app.services.chat import AnswerRecorder, ChatService  # noqa: E402
from app.services.feedback_ranking import FeedbackRankingService  # noqa: E402
from app.services.permissions import PermissionResolver  # noqa: E402
from app.services.rag import RagService, _answer_cache  # noqa: E402
from app.services.search import SearchService  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

PASSWORD = "test-password-123"


@pytest.fixture(scope="module")
def client():
    config = AlembicConfig(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    try:
        command.downgrade(config, "base")
    except Exception:
        pass
    command.upgrade(config, "head")
    app = create_app(Settings())
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str = PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def _logout(client: TestClient):
    client.post("/api/auth/logout")


@pytest.fixture(scope="module")
def seeded(client):
    """建立测试账号矩阵与文档矩阵；直接写库以避免依赖上传/解析链路。"""
    ids: dict[str, object] = {}
    with SessionLocal() as session:
        company = session.scalar(select(Department).where(Department.name == "公司"))
        tech = Department(name="技术部", parent_id=company.id, enabled=True)
        hr = Department(name="人事部", parent_id=company.id, enabled=True)
        role = Role(name="技术角色", enabled=True)
        disabled_role = Role(name="停用角色", enabled=False)
        session.add_all([tech, hr, role, disabled_role])
        session.flush()

        def make_user(username: str, department_id, role_row=None, super_admin=False) -> User:
            user = User(
                username=username, display_name=username, password_hash=hash_password(PASSWORD),
                department_id=department_id, enabled=True, is_super_admin=super_admin,
            )
            if role_row is not None:
                user.roles.append(role_row)
            session.add(user)
            session.flush()
            return user

        admin = session.scalar(select(User).where(User.username == "admin"))
        tech_user = make_user("tech_user", tech.id)
        hr_user = make_user("hr_user", hr.id)
        role_user = make_user("role_user", None, role)
        other_user = make_user("other_user", None)
        session.commit()

        def make_document(name: str, visibility: DocumentVisibility, owner=None, **kwargs) -> Document:
            document = Document(
                id=uuid.uuid4(), original_name=name, stored_path=f"test/{name}",
                extension="txt", mime_type="text/plain", size_bytes=10, sha256=uuid.uuid4().hex,
                status=DocumentStatus.READY, knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                visibility=visibility, owner_user_id=owner.id if owner else None, enabled=True,
                **kwargs,
            )
            session.add(document)
            session.flush()
            session.add(DocumentChunk(
                document_id=document.id, sequence_number=1, content="alpha secret",
                search_vector=func.to_tsvector("simple", "alpha secret"),
            ))
            return document

        company_doc = make_document("company_doc.txt", DocumentVisibility.COMPANY)
        private_doc = make_document("private_doc.txt", DocumentVisibility.PRIVATE, owner=tech_user)
        department_doc = make_document("department_doc.txt", DocumentVisibility.DEPARTMENT)
        role_doc = make_document("role_doc.txt", DocumentVisibility.ROLE)
        disabled_role_doc = make_document("disabled_role_doc.txt", DocumentVisibility.ROLE)
        user_doc = make_document("user_doc.txt", DocumentVisibility.USER)
        managed_doc = make_document("managed_doc.txt", DocumentVisibility.USER)
        restricted_doc = make_document(
            "restricted_doc.txt", DocumentVisibility.COMPANY, sensitivity_level="CONFIDENTIAL",
        )
        external_disabled_doc = make_document(
            "external_disabled_doc.txt", DocumentVisibility.COMPANY, external_llm_allowed=False,
        )
        session.add_all([
            DocumentAcl(document_id=department_doc.id, subject_type=SubjectType.DEPARTMENT, subject_id=tech.id, permission=AclPermission.READ),
            DocumentAcl(document_id=role_doc.id, subject_type=SubjectType.ROLE, subject_id=role.id, permission=AclPermission.READ),
            DocumentAcl(document_id=disabled_role_doc.id, subject_type=SubjectType.ROLE, subject_id=disabled_role.id, permission=AclPermission.READ),
            DocumentAcl(document_id=user_doc.id, subject_type=SubjectType.USER, subject_id=tech_user.id, permission=AclPermission.READ),
            DocumentAcl(document_id=managed_doc.id, subject_type=SubjectType.USER, subject_id=tech_user.id, permission=AclPermission.MANAGE),
        ])
        session.commit()

        ids.update({
            "admin": admin, "tech_user": tech_user, "hr_user": hr_user,
            "role_user": role_user, "other_user": other_user, "role": role,
            "disabled_role": disabled_role, "tech": tech,
            "company_doc": company_doc, "private_doc": private_doc,
            "department_doc": department_doc, "role_doc": role_doc,
            "disabled_role_doc": disabled_role_doc,
            "user_doc": user_doc, "managed_doc": managed_doc, "restricted_doc": restricted_doc,
            "external_disabled_doc": external_disabled_doc,
        })
    return ids


def _resolver(user: User):
    with SessionLocal() as session:
        fresh = session.get(User, user.id)
        resolver = PermissionResolver(session, fresh)
        return resolver


def _search_document_ids(user: User) -> set[uuid.UUID]:
    """在 SQL 层验证关键词召回只包含当前用户可见的资料。"""
    with SessionLocal() as session:
        fresh = session.get(User, user.id)
        service = SearchService(session, Settings(), user=fresh)
        candidates = service._keyword_candidates("alpha", SearchRequest(query="alpha"))
        return {candidate.document.id for candidate in candidates}


def test_company_document_visible_to_everyone(seeded):
    assert seeded["company_doc"].id in _search_document_ids(seeded["hr_user"])
    assert seeded["company_doc"].id in _search_document_ids(seeded["other_user"])


def test_private_document_only_owner_and_admin(seeded):
    assert seeded["private_doc"].id in _search_document_ids(seeded["tech_user"])
    assert seeded["private_doc"].id not in _search_document_ids(seeded["hr_user"])
    assert seeded["private_doc"].id in _search_document_ids(seeded["admin"])


def test_department_document_hidden_from_other_departments(seeded):
    assert seeded["department_doc"].id in _search_document_ids(seeded["tech_user"])
    assert seeded["department_doc"].id not in _search_document_ids(seeded["hr_user"])


def test_role_document_requires_role(seeded):
    assert seeded["role_doc"].id in _search_document_ids(seeded["role_user"])
    assert seeded["role_doc"].id not in _search_document_ids(seeded["other_user"])


def test_user_document_is_scoped_to_subject(seeded):
    assert seeded["user_doc"].id in _search_document_ids(seeded["tech_user"])
    assert seeded["user_doc"].id not in _search_document_ids(seeded["hr_user"])


def test_disabled_role_does_not_grant_access(seeded):
    with SessionLocal() as session:
        user = session.get(User, seeded["other_user"].id)
        user.roles.append(session.get(Role, seeded["disabled_role"].id))
        session.commit()
    assert seeded["disabled_role_doc"].id not in _search_document_ids(seeded["other_user"])


def test_ordinary_user_cannot_call_assistant_or_harness(client, seeded):
    _login(client, "tech_user")
    assert client.post("/api/assistants", json={"name": "x"}).status_code == 403
    assert client.get("/api/harness/status").status_code == 403
    _logout(client)


def test_acl_read_requires_manage(client, seeded):
    _login(client, "hr_user")
    assert client.get(f"/api/documents/{seeded['company_doc'].id}/acl").status_code == 403
    _logout(client)

    _login(client, "tech_user")
    assert client.get(f"/api/documents/{seeded['managed_doc'].id}/acl").status_code == 200
    _logout(client)


def test_acl_write_rejects_disabled_subject(client, seeded):
    _login(client, "admin")
    response = client.put(
        f"/api/documents/{seeded['company_doc'].id}/access",
        json={
            "visibility": "ROLE",
            "acl": [{"subject_type": "ROLE", "subject_id": str(seeded["disabled_role"].id), "permission": "READ"}],
        },
    )
    assert response.status_code == 409
    _logout(client)


def test_cache_scope_differs_by_permission(seeded):
    with SessionLocal() as session:
        admin_scope = SearchService(session, Settings(), user=session.get(User, seeded["admin"].id)).permission_cache_scope()
        tech_scope = SearchService(session, Settings(), user=session.get(User, seeded["tech_user"].id)).permission_cache_scope()
    assert admin_scope != tech_scope


def test_restricted_document_blocks_external_model(seeded):
    with SessionLocal() as session:
        service = RagService(session, Settings(), user=session.get(User, seeded["admin"].id))
        blocked = service._restricted_document_ids([seeded["restricted_doc"].id, seeded["company_doc"].id])
    assert seeded["restricted_doc"].id in blocked
    assert seeded["company_doc"].id not in blocked


def test_disabling_user_invalidates_existing_session(client, seeded):
    _login(client, "other_user")
    assert client.get("/api/auth/me").json()["authenticated"] is True
    old_token = client.cookies.get("cs_session")

    _login(client, "admin")
    response = client.post(f"/api/users/{seeded['other_user'].id}/disable")
    assert response.status_code == 200, response.text
    _logout(client)

    # 换回停用用户的旧 Cookie，应被立即拒绝。
    client.cookies.set("cs_session", old_token)
    assert client.get("/api/documents").status_code == 401


def test_feedback_ranking_respects_sample_threshold(seeded):
    settings = Settings()
    settings.search_feedback_ranking_enabled = True
    settings.search_feedback_min_samples = 5
    settings.search_feedback_max_boost = 0.05
    with SessionLocal() as session:
        service = FeedbackRankingService(session, settings)
        # 尚未写入任何反馈时不应产生调整分。
        assert service.boosts([seeded["company_doc"].id]) == {}

    settings.search_feedback_ranking_enabled = False
    with SessionLocal() as session:
        assert FeedbackRankingService(session, settings).boosts([seeded["company_doc"].id]) == {}


# ======================================================================
# 测试替身：不访问真实 Ollama / DeepSeek / 嵌入模型
# ======================================================================

class _FakeEmbeddings:
    def __init__(self):
        self.vector = [1.0] + [0.0] * 1023

    def encode_query(self, _text):
        return list(self.vector)

    def encode_documents(self, texts):
        return [list(self.vector) for _ in texts]


class _FakeOllama:
    def __init__(self, answer: str = "内部答案 [1]"):
        self.answer = answer

    async def stream_with_stats(self, messages, model=None, temperature=None):
        for char in self.answer:
            yield {"delta": char, "prompt_eval_count": 5, "eval_count": 1, "done": False}
        yield {"delta": "", "prompt_eval_count": 5, "eval_count": 1, "done": True}

    async def warmup(self):
        return True


class _FakeDeepSeek:
    def __init__(self, configured: bool = True, deltas=("外部增强答案",)):
        self._configured = configured
        self._deltas = list(deltas)
        self.calls: list = []

    @property
    def configured(self):
        return self._configured

    async def stream(self, messages):
        self.calls.append(messages)
        for delta in self._deltas:
            yield delta


_OPEN_SESSIONS: list = []


@pytest.fixture(autouse=True)
def _close_test_sessions():
    yield
    while _OPEN_SESSIONS:
        _OPEN_SESSIONS.pop().close()


def _service_for(user_id, *, settings=None, answer="内部答案 [1]"):
    settings = settings or Settings()
    session = SessionLocal()
    _OPEN_SESSIONS.append(session)
    user = session.get(User, user_id)
    service = RagService(session, settings, user=user)
    service.search_service.embeddings = _FakeEmbeddings()
    service.ollama = _FakeOllama(answer)
    deepseek = _FakeDeepSeek()
    service.deepseek = deepseek
    return service, deepseek


async def _collect(service, request):
    return [event async for event in service.stream(request)]


def _events(events, event_type):
    return [event for event in events if event.type == event_type]


# ======================================================================
# 检索可见性：关键词、向量、RRF、RAG 引用、检索实验室
# ======================================================================

def _search_document_ids_with_vectors(user: User, query: str = "alpha") -> set[uuid.UUID]:
    with SessionLocal() as session:
        fresh = session.get(User, user.id)
        service = SearchService(session, Settings(), user=fresh)
        service.embeddings = _FakeEmbeddings()
        candidates = service._vector_candidates(query, SearchRequest(query=query))
        return {candidate.document.id for candidate in candidates}


def test_vector_recall_respects_permissions(seeded):
    with SessionLocal() as session:
        for name in ("company_doc", "private_doc", "department_doc", "role_doc", "user_doc"):
            document = session.get(Document, seeded[name].id)
            for chunk in session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)):
                chunk.embedding = [1.0] + [0.0] * 1023
        session.commit()
    tech = _search_document_ids_with_vectors(seeded["tech_user"])
    hr = _search_document_ids_with_vectors(seeded["hr_user"])
    assert seeded["company_doc"].id in tech
    assert seeded["private_doc"].id in tech
    assert seeded["private_doc"].id not in hr
    assert seeded["department_doc"].id in tech
    assert seeded["department_doc"].id not in hr
    assert seeded["role_doc"].id not in hr
    assert seeded["user_doc"].id in tech
    assert seeded["user_doc"].id not in hr


def test_rrf_fusion_keeps_permission_filter(seeded):
    with SessionLocal() as session:
        fresh = session.get(User, seeded["hr_user"].id)
        service = SearchService(session, Settings(), user=fresh)
        service.embeddings = _FakeEmbeddings()
        request = SearchRequest(query="alpha")
        keyword = service._keyword_candidates("alpha", request)
        vector = service._vector_candidates("alpha", request)
        fused = service._fuse(keyword, vector, "alpha")
    document_ids = {candidate.document.id for candidate in fused}
    assert seeded["role_doc"].id not in document_ids
    assert seeded["private_doc"].id not in document_ids
    assert seeded["company_doc"].id in document_ids


def test_rag_references_exclude_forbidden_documents(seeded):
    with SessionLocal() as session:
        fresh = session.get(User, seeded["hr_user"].id)
        service = RagService(session, Settings(), user=fresh)
        service.search_service.embeddings = _FakeEmbeddings()
        results = service.search_service.search(SearchRequest(query="alpha"))
        sources = service._sources(results)
    document_ids = {source.document_id for source in sources}
    assert seeded["role_doc"].id not in document_ids
    assert seeded["private_doc"].id not in document_ids
    assert seeded["department_doc"].id not in document_ids


def test_retrieval_lab_hides_forbidden_documents(client, seeded, monkeypatch):
    import app.services.search as search_module

    monkeypatch.setattr(search_module, "EmbeddingService", lambda settings: _FakeEmbeddings())
    _login(client, "admin")
    response = client.post("/api/retrieval-lab/inspect", json={"query": "alpha", "limit": 10})
    assert response.status_code == 200, response.text
    _logout(client)

    # 普通用户即便拿到 HR 的会话也不能访问检索实验室（仅管理员）。
    _login(client, "hr_user")
    assert client.post("/api/retrieval-lab/inspect", json={"query": "alpha", "limit": 10}).status_code == 403
    _logout(client)


# ======================================================================
# 缓存隔离：停用角色、跨用户、资料变更后立即失效
# ======================================================================

def test_cache_not_shared_between_users(seeded):
    _answer_cache.clear()
    settings = Settings()
    settings.answer_cache_enabled = True
    admin_service, _ = _service_for(seeded["admin"].id, settings=settings)
    request = AnswerRequest(question="alpha secret")
    asyncio.run(_collect(admin_service, request))
    assert len(_answer_cache) == 1
    admin_key = next(iter(_answer_cache))

    tech_service, _ = _service_for(seeded["tech_user"].id, settings=settings)
    events = asyncio.run(_collect(tech_service, request))
    metrics = _events(events, "metrics")[0].metrics
    assert metrics["cache_hit"] is False
    tech_key = tech_service._cache_key(request, tech_service._assistant_config(request))
    assert tech_key != admin_key
    assert seeded["role_doc"].id not in {source.document_id for source in _events(events, "sources")[0].sources}


def test_disabling_role_invalidates_cached_answer(seeded):
    _answer_cache.clear()
    settings = Settings()
    settings.answer_cache_enabled = True
    service, _ = _service_for(seeded["role_user"].id, settings=settings)
    request = AnswerRequest(question="alpha secret")
    first_events = asyncio.run(_collect(service, request))
    first_sources = _events(first_events, "sources")[0].sources
    assert seeded["role_doc"].id in {source.document_id for source in first_sources}
    old_key = service._cache_key(request, service._assistant_config(request))
    assert old_key in _answer_cache

    with SessionLocal() as session:
        session.get(Role, seeded["role"].id).enabled = False
        session.commit()
    try:
        second_service, _ = _service_for(seeded["role_user"].id, settings=settings)
        second_events = asyncio.run(_collect(second_service, request))
        metrics = _events(second_events, "metrics")[0].metrics
        assert metrics["cache_hit"] is False
        sources = _events(second_events, "sources")[0].sources
        assert seeded["role_doc"].id not in {source.document_id for source in sources}
        new_key = second_service._cache_key(request, second_service._assistant_config(request))
        assert new_key != old_key
    finally:
        with SessionLocal() as session:
            session.get(Role, seeded["role"].id).enabled = True
            session.commit()


def test_document_state_change_invalidates_cached_answer(seeded):
    _answer_cache.clear()
    settings = Settings()
    settings.answer_cache_enabled = True
    service, _ = _service_for(seeded["tech_user"].id, settings=settings)
    request = AnswerRequest(question="alpha secret")
    asyncio.run(_collect(service, request))
    old_key = service._cache_key(request, service._assistant_config(request))
    assert old_key in _answer_cache

    with SessionLocal() as session:
        session.get(Document, seeded["company_doc"].id).enabled = False
        session.commit()
    try:
        service2, _ = _service_for(seeded["tech_user"].id, settings=settings)
        new_key = service2._cache_key(request, service2._assistant_config(request))
        assert new_key != old_key
    finally:
        with SessionLocal() as session:
            session.get(Document, seeded["company_doc"].id).enabled = True
            session.commit()


def test_acl_change_invalidates_cached_answer(seeded):
    _answer_cache.clear()
    settings = Settings()
    settings.answer_cache_enabled = True
    service, _ = _service_for(seeded["hr_user"].id, settings=settings)
    request = AnswerRequest(question="alpha secret")
    asyncio.run(_collect(service, request))
    old_key = service._cache_key(request, service._assistant_config(request))

    with SessionLocal() as session:
        session.add(DocumentAcl(
            document_id=seeded["company_doc"].id, subject_type=SubjectType.DEPARTMENT,
            subject_id=seeded["tech"].id, permission=AclPermission.READ,
        ))
        session.commit()
    service2, _ = _service_for(seeded["hr_user"].id, settings=settings)
    new_key = service2._cache_key(request, service2._assistant_config(request))
    assert new_key != old_key


# ======================================================================
# DeepSeek 外发策略
# ======================================================================

@pytest.fixture(scope="module")
def external_docs(client, seeded):
    ids: dict[str, object] = {}
    with SessionLocal() as session:
        def make(name: str, **kwargs) -> Document:
            document = Document(
                id=uuid.uuid4(), original_name=name, stored_path=f"test/{name}",
                extension="txt", mime_type="text/plain", size_bytes=10, sha256=uuid.uuid4().hex,
                status=DocumentStatus.READY, knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                visibility=DocumentVisibility.COMPANY, enabled=True, **kwargs,
            )
            session.add(document)
            session.flush()
            session.add(DocumentChunk(
                document_id=document.id, sequence_number=1, content="alpha secret",
                search_vector=func.to_tsvector("simple", "alpha secret"),
            ))
            return document

        ids["allowed"] = make("ext_allowed.txt")
        ids["external_disabled"] = make("ext_disabled.txt", external_llm_allowed=False)
        ids["confidential"] = make("ext_confidential.txt", sensitivity_level="CONFIDENTIAL")
        ids["restricted"] = make("ext_restricted.txt", sensitivity_level="RESTRICTED")
        ids["mixed_allowed"] = make("ext_mixed.txt")
        ids["mixed_blocked"] = make("ext_mixed_blocked.txt", external_llm_allowed=False)
        session.commit()
    return ids


def _external_request(name: str) -> AnswerRequest:
    return AnswerRequest(question="alpha secret", document_name=name, use_deepseek=True)


def test_external_model_called_for_allowed_document(seeded, external_docs):
    settings = Settings()
    settings.answer_cache_enabled = False
    service, deepseek = _service_for(seeded["admin"].id, settings=settings)
    events = asyncio.run(_collect(service, _external_request("ext_allowed")))
    assert deepseek.calls, "允许外发时应当调用外部模型"
    assert _events(events, "done")[0].provider == AnswerProvider.DEEPSEEK


@pytest.mark.parametrize(
    "name",
    ["ext_disabled", "ext_confidential", "ext_restricted"],
)
def test_external_model_blocked_by_policy(seeded, external_docs, name):
    settings = Settings()
    settings.answer_cache_enabled = False
    service, deepseek = _service_for(seeded["admin"].id, settings=settings)
    events = asyncio.run(_collect(service, _external_request(name)))
    assert deepseek.calls == []
    warnings = _events(events, "warning")
    assert any(event.warning.code == "EXTERNAL_LLM_BLOCKED" for event in warnings)
    # 保留本地答案，provider 仍为本地模型。
    assert _events(events, "done")[0].provider == AnswerProvider.LOCAL
    assert any(event.type == "delta" and event.provider == AnswerProvider.LOCAL for event in events)


def test_external_model_blocked_when_any_citation_restricted(seeded, external_docs):
    settings = Settings()
    settings.answer_cache_enabled = False
    service, deepseek = _service_for(seeded["admin"].id, settings=settings)
    events = asyncio.run(_collect(service, _external_request("ext_mixed")))
    source_ids = {source.document_id for source in _events(events, "sources")[0].sources}
    assert external_docs["mixed_allowed"].id in source_ids
    assert external_docs["mixed_blocked"].id in source_ids
    assert deepseek.calls == []


def test_external_model_not_called_without_opt_in(seeded, external_docs):
    settings = Settings()
    settings.answer_cache_enabled = False
    service, deepseek = _service_for(seeded["admin"].id, settings=settings)
    events = asyncio.run(_collect(service, AnswerRequest(question="alpha secret", document_name="ext_allowed")))
    assert deepseek.calls == []
    assert _events(events, "done")[0].provider == AnswerProvider.LOCAL


# ======================================================================
# 审计：成功/失败、logout、写失败不影响业务、越权读取、敏感信息
# ======================================================================

def _latest_audit(action: str):
    with SessionLocal() as session:
        return session.scalar(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc()).limit(1)
        )


def test_login_failure_audited_with_error_code(client, seeded):
    client.post("/api/auth/login", json={"username": "tech_user", "password": "wrong-password"})
    log = _latest_audit("login_failed")
    assert log is not None
    assert log.success is False
    assert log.error_code == "LOGIN_FAILED"


def test_logout_audit_contains_user(client, seeded):
    _login(client, "tech_user")
    _logout(client)
    log = _latest_audit("logout")
    assert log is not None
    assert log.user_id == seeded["tech_user"].id
    assert log.username == "tech_user"


def test_audit_does_not_store_secrets(client, seeded):
    _login(client, "tech_user")
    _logout(client)
    for action in ("login_success", "logout"):
        log = _latest_audit(action)
        assert log is not None
        payload = str(log.detail)
        assert PASSWORD not in payload
        assert "password" not in payload.lower()
        assert "cs_session" not in payload
        assert "token" not in payload.lower()


def test_audit_write_failure_does_not_break_core(client, seeded, monkeypatch):
    import app.services.audit as audit_module

    _login(client, "admin")
    monkeypatch.setattr(audit_module, "SessionLocal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    response = client.post("/api/departments", json={"name": "审计降级部门", "enabled": True})
    assert response.status_code == 201, response.text
    _logout(client)


def test_ordinary_user_cannot_read_audit_logs(client, seeded):
    _login(client, "tech_user")
    assert client.get("/api/audit/logs").status_code == 403
    _logout(client)


# ======================================================================
# 会话归档
# ======================================================================

def _create_session(client, title: str) -> str:
    response = client.post("/api/chat/sessions", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_archive_hides_and_restore_shows_session(client, seeded):
    _login(client, "tech_user")
    session_id = _create_session(client, "归档测试")
    with SessionLocal() as session:
        session.add(ChatMessage(
            session_id=uuid.UUID(session_id), role=ChatMessageRole.USER,
            content="hello", status=ChatMessageStatus.COMPLETED,
        ))
        session.commit()

    assert client.post(f"/api/chat/sessions/{session_id}/archive").status_code == 200
    default_items = client.get("/api/chat/sessions").json()["items"]
    assert all(item["id"] != session_id for item in default_items)
    archived_items = client.get("/api/chat/sessions", params={"archived": "true"}).json()["items"]
    assert any(item["id"] == session_id for item in archived_items)

    detail = client.get(f"/api/chat/sessions/{session_id}").json()
    assert detail["archived_at"] is not None
    assert len(detail["messages"]) == 1

    assert client.post(f"/api/chat/sessions/{session_id}/restore").status_code == 200
    restored = client.get("/api/chat/sessions").json()["items"]
    assert any(item["id"] == session_id for item in restored)
    _logout(client)


def test_purge_only_with_explicit_flag(client, seeded):
    _login(client, "tech_user")
    session_id = _create_session(client, "永久删除测试")
    assert client.delete(f"/api/chat/sessions/{session_id}").json() == {"archived": True}
    assert client.get(f"/api/chat/sessions/{session_id}").json()["archived_at"] is not None
    assert client.delete(f"/api/chat/sessions/{session_id}", params={"purge": "true"}).json() == {"deleted": True}
    assert client.get(f"/api/chat/sessions/{session_id}").status_code == 404
    _logout(client)


def test_user_cannot_touch_other_users_session(client, seeded):
    _login(client, "tech_user")
    session_id = _create_session(client, "tech 私有会话")
    _logout(client)
    _login(client, "hr_user")
    assert client.get(f"/api/chat/sessions/{session_id}").status_code == 404
    assert client.post(f"/api/chat/sessions/{session_id}/archive").status_code == 404
    assert client.post(f"/api/chat/sessions/{session_id}/restore").status_code == 404
    assert client.delete(f"/api/chat/sessions/{session_id}").status_code == 404
    assert client.delete(f"/api/chat/sessions/{session_id}", params={"purge": "true"}).status_code == 404
    _logout(client)


def test_user_cannot_regenerate_other_users_answer(seeded):
    with SessionLocal() as session:
        chat = ChatService(session, user=session.get(User, seeded["tech_user"].id))
        row = chat.create("regenerate 测试")
        message = ChatMessage(
            session_id=row.id, role=ChatMessageRole.ASSISTANT, content="旧答案",
            status=ChatMessageStatus.COMPLETED,
        )
        session.add(message)
        session.commit()
        message_id = message.id
        other = session.get(User, seeded["hr_user"].id)
        recorder = AnswerRecorder(session, user=other)
        with pytest.raises(KeyError):
            recorder.begin_regenerate(message_id)


def test_user_cannot_rate_other_users_answer(client, seeded):
    with SessionLocal() as session:
        chat = ChatService(session, user=session.get(User, seeded["tech_user"].id))
        row = chat.create("评价测试")
        message = ChatMessage(
            session_id=row.id, role=ChatMessageRole.ASSISTANT, content="答案",
            status=ChatMessageStatus.COMPLETED,
        )
        session.add(message)
        session.commit()
        message_id = message.id

    _login(client, "hr_user")
    response = client.post("/api/feedback", json={"message_id": str(message_id), "rating": "UP"})
    assert response.status_code == 403
    _logout(client)


# ======================================================================
# 文档版本权限
# ======================================================================

@pytest.fixture(scope="module")
def version_chain(client, seeded):
    with SessionLocal() as session:
        def make(name: str, visibility, previous=None, version=1, owner=None) -> Document:
            document = Document(
                id=uuid.uuid4(), original_name=name, stored_path=f"test/{name}",
                extension="txt", mime_type="text/plain", size_bytes=10, sha256=uuid.uuid4().hex,
                status=DocumentStatus.READY, knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                visibility=visibility, enabled=True, previous_version_id=previous.id if previous else None,
                version_number=version, owner_user_id=owner.id if owner else None,
            )
            session.add(document)
            session.flush()
            session.add(DocumentChunk(
                document_id=document.id, sequence_number=1, content="alpha secret",
                search_vector=func.to_tsvector("simple", "alpha secret"),
            ))
            return document

        v1 = make("version_company.txt", DocumentVisibility.COMPANY, version=1)
        v2 = make("version_role.txt", DocumentVisibility.ROLE, previous=v1, version=2)
        v3 = make("version_user.txt", DocumentVisibility.USER, previous=v2, version=3, owner=seeded["tech_user"])
        session.add(DocumentAcl(
            document_id=v2.id, subject_type=SubjectType.ROLE, subject_id=seeded["role"].id,
            permission=AclPermission.READ,
        ))
        session.add(DocumentAcl(
            document_id=v3.id, subject_type=SubjectType.USER, subject_id=seeded["tech_user"].id,
            permission=AclPermission.READ,
        ))
        session.commit()
        return {"v1": v1.id, "v2": v2.id, "v3": v3.id}


def _versions_for(user: User, document_id: uuid.UUID) -> set[uuid.UUID]:
    from app.services.documents import DocumentService
    from app.services.managed_storage import ManagedStorage

    with SessionLocal() as session:
        fresh = session.get(User, user.id)
        service = DocumentService(session, ManagedStorage(Settings()), user=fresh)
        return {item.id for item in service.versions(document_id)}


def test_version_chain_filters_each_version_by_permission(seeded, version_chain):
    v1, v2, v3 = version_chain["v1"], version_chain["v2"], version_chain["v3"]
    assert _versions_for(seeded["hr_user"], v1) == {v1}
    assert _versions_for(seeded["role_user"], v1) == {v1, v2}
    # tech_user 看不到中间 ROLE 版本，但仍能看到后续 USER 版本。
    assert _versions_for(seeded["tech_user"], v1) == {v1, v3}
    assert _versions_for(seeded["admin"], v1) == {v1, v2, v3}


def test_version_entry_requires_read_permission(client, seeded, version_chain):
    _login(client, "hr_user")
    assert client.get(f"/api/documents/{version_chain['v3']}/versions").status_code == 403
    assert client.get(f"/api/documents/{version_chain['v1']}/versions").status_code == 200
    _logout(client)


# ======================================================================
# API 越权边界
# ======================================================================

def test_forbidden_document_endpoints(client, seeded):
    _login(client, "hr_user")
    role_doc = seeded["role_doc"].id
    assert client.get(f"/api/documents/{role_doc}").status_code == 403
    assert client.get(f"/api/documents/{role_doc}/download").status_code == 403
    assert client.get(f"/api/documents/{role_doc}/chunks").status_code == 403
    assert client.get(f"/api/documents/{role_doc}/versions").status_code == 403
    _logout(client)


def test_acl_edit_requires_manage_permission(client, seeded):
    _login(client, "tech_user")
    # managed_doc 授予 tech_user MANAGE，可以编辑。
    assert client.put(
        f"/api/documents/{seeded['managed_doc'].id}/access",
        json={"visibility": "USER"},
    ).status_code == 200
    # user_doc 只有 READ，不能编辑 ACL。
    assert client.put(
        f"/api/documents/{seeded['user_doc'].id}/access",
        json={"visibility": "USER"},
    ).status_code == 403
    _logout(client)

    _login(client, "hr_user")
    assert client.put(
        f"/api/documents/{seeded['company_doc'].id}/access",
        json={"visibility": "COMPANY"},
    ).status_code == 403
    _logout(client)


def test_ordinary_user_cannot_call_harness_task(client, seeded):
    _login(client, "tech_user")
    assert client.post("/api/assistants", json={"name": "越权助手"}).status_code == 403
    assert client.get("/api/harness/status").status_code == 403
    assert client.get("/api/harness/tasks/00000000-0000-0000-0000-000000000000").status_code == 403
    _logout(client)


# ======================================================================
# 多文档反馈归因
# ======================================================================

def test_feedback_links_all_cited_documents(seeded):
    settings = Settings()
    settings.search_feedback_ranking_enabled = True
    settings.search_feedback_min_samples = 1
    with SessionLocal() as session:
        user = session.get(User, seeded["tech_user"].id)
        chat = ChatService(session, user=user)
        row = chat.create("多文档反馈")
        message = ChatMessage(
            session_id=row.id, role=ChatMessageRole.ASSISTANT, content="答案 [1][2]",
            status=ChatMessageStatus.COMPLETED,
        )
        session.add(message)
        session.flush()
        session.add_all([
            ChatMessageSource(
                message_id=message.id, document_id=seeded["company_doc"].id, chunk_id=uuid.uuid4(),
                citation_number=1, document_name="company_doc.txt", content_snapshot="alpha",
                location_snapshot={}, score=0.9,
            ),
            ChatMessageSource(
                message_id=message.id, document_id=seeded["user_doc"].id, chunk_id=uuid.uuid4(),
                citation_number=2, document_name="user_doc.txt", content_snapshot="beta",
                location_snapshot={}, score=0.8,
            ),
        ])
        session.commit()
        message_id = message.id

        feedback = AnswerFeedback(
            message_id=message_id, user_id=user.id, rating=FeedbackRating.UP,
            reasons=[], comment=None, document_id=None,
        )
        session.add(feedback)
        session.flush()
        session.add_all([
            AnswerFeedbackDocument(feedback_id=feedback.id, document_id=seeded["company_doc"].id, citation_number=1),
            AnswerFeedbackDocument(feedback_id=feedback.id, document_id=seeded["user_doc"].id, citation_number=2),
        ])
        session.commit()

        links = session.scalars(
            select(AnswerFeedbackDocument).where(AnswerFeedbackDocument.feedback_id == feedback.id)
        ).all()
        assert {(link.document_id, link.citation_number) for link in links} == {
            (seeded["company_doc"].id, 1), (seeded["user_doc"].id, 2),
        }

        service = FeedbackRankingService(session, settings)
        service.recompute(seeded["company_doc"].id)
        service.recompute(seeded["user_doc"].id)
        assert session.get(DocumentFeedbackStats, seeded["company_doc"].id).sample_count == 1
        assert session.get(DocumentFeedbackStats, seeded["user_doc"].id).sample_count == 1
        boosts = service.boosts([seeded["company_doc"].id, seeded["user_doc"].id])
        assert set(boosts) == {seeded["company_doc"].id, seeded["user_doc"].id}
        assert all(abs(value) <= settings.search_feedback_max_boost for value in boosts.values())

        # 唯一约束保证同一回答同一文档只统计一次。
        session.add(AnswerFeedbackDocument(
            feedback_id=feedback.id, document_id=seeded["company_doc"].id, citation_number=1,
        ))
        with pytest.raises(Exception):
            session.commit()
        session.rollback()


def test_feedback_api_links_all_cited_documents(client, seeded):
    with SessionLocal() as session:
        user = session.get(User, seeded["tech_user"].id)
        chat = ChatService(session, user=user)
        row = chat.create("API 多文档反馈")
        message = ChatMessage(
            session_id=row.id, role=ChatMessageRole.ASSISTANT, content="答案 [1][2]",
            status=ChatMessageStatus.COMPLETED,
        )
        session.add(message)
        session.flush()
        session.add_all([
            ChatMessageSource(
                message_id=message.id, document_id=seeded["company_doc"].id, chunk_id=uuid.uuid4(),
                citation_number=1, document_name="company_doc.txt", content_snapshot="alpha",
                location_snapshot={}, score=0.9,
            ),
            ChatMessageSource(
                message_id=message.id, document_id=seeded["user_doc"].id, chunk_id=uuid.uuid4(),
                citation_number=2, document_name="user_doc.txt", content_snapshot="beta",
                location_snapshot={}, score=0.8,
            ),
        ])
        session.commit()
        message_id = message.id

    _login(client, "tech_user")
    response = client.post("/api/feedback", json={"message_id": str(message_id), "rating": "UP"})
    assert response.status_code == 201, response.text
    _logout(client)

    with SessionLocal() as session:
        feedback = session.scalar(select(AnswerFeedback).where(AnswerFeedback.message_id == message_id))
        assert feedback is not None
        links = session.scalars(
            select(AnswerFeedbackDocument).where(AnswerFeedbackDocument.feedback_id == feedback.id)
        ).all()
        assert {link.document_id for link in links} == {seeded["company_doc"].id, seeded["user_doc"].id}

        # 重复提交（更新）不会产生重复关联。
        _login(client, "tech_user")
        client.post("/api/feedback", json={"message_id": str(message_id), "rating": "DOWN"})
        _logout(client)
    with SessionLocal() as session:
        feedback = session.scalar(select(AnswerFeedback).where(AnswerFeedback.message_id == message_id))
        links = session.scalars(
            select(AnswerFeedbackDocument).where(AnswerFeedbackDocument.feedback_id == feedback.id)
        ).all()
        assert len(links) == 2


def test_answer_api_audits_external_block_without_leaking_content(client, seeded, external_docs):
    from fastapi import Request
    from fastapi.params import Depends

    from app.api.answer import get_rag_service
    from app.config import Settings as AppSettings, get_settings
    from app.db import get_session

    app = client.app

    def fake_service(
        request: Request,
        session=Depends(get_session),
        settings: AppSettings = Depends(get_settings),
    ):
        service = RagService(session, settings, user=getattr(request.state, "auth_user", None))
        service.search_service.embeddings = _FakeEmbeddings()
        service.ollama = _FakeOllama()
        service.deepseek = _FakeDeepSeek()
        return service

    app.dependency_overrides[get_rag_service] = fake_service
    try:
        _login(client, "admin")
        with client.stream(
            "POST", "/api/answer/stream",
            json={"question": "alpha secret", "document_name": "ext_disabled", "use_deepseek": True},
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
        assert "EXTERNAL_LLM_BLOCKED" in body
        _logout(client)
    finally:
        app.dependency_overrides.pop(get_rag_service, None)

    log = _latest_audit("external_llm_blocked")
    assert log is not None
    assert "EXTERNAL_LLM_BLOCKED" in str(log.detail)
    # 审计不得包含完整上下文正文或 API Key。
    assert "alpha secret" not in str(log.detail)
    assert "sk-" not in str(log.detail)
