"""P1-15 多用户权限集成测试。

默认跳过；设置 ``COMPANY_SEARCH_TEST_DATABASE_URL`` 指向一个**临时** PostgreSQL
测试库后运行。测试会在该库上执行 Alembic 迁移并写入隔离数据，绝不连接正式库。

    COMPANY_SEARCH_TEST_DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:54329/cs_test \
        python -m pytest backend/tests/test_p1_permission_integration.py -v
"""

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
    DEFAULT_KNOWLEDGE_BASE_ID, AclPermission, Department, Document, DocumentAcl, DocumentChunk,
    DocumentStatus, DocumentVisibility, Role, SubjectType, User,
)
from app.schemas.search import SearchRequest  # noqa: E402
from app.services.auth import hash_password  # noqa: E402
from app.services.feedback_ranking import FeedbackRankingService  # noqa: E402
from app.services.permissions import PermissionResolver  # noqa: E402
from app.services.rag import RagService  # noqa: E402
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
