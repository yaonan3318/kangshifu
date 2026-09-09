"""Static security regressions that run without a configured PostgreSQL server.

These checks intentionally guard the authorization calls at the HTTP/service
boundaries.  The Mac integration checklist still exercises the resulting SQL.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class P1SecurityRegressionTests(unittest.TestCase):
    def test_user_manage_acl_is_scoped_to_current_user(self) -> None:
        permissions = source("backend/app/services/permissions.py")
        self.assertIn(
            "(DocumentAcl.subject_type == SubjectType.USER) & (DocumentAcl.subject_id == self.user.id)",
            permissions,
        )

    def test_answer_cache_key_contains_permission_scope(self) -> None:
        rag = source("backend/app/services/rag.py")
        self.assertIn('self.search_service.permission_cache_scope()', rag)

    def test_assistant_mutations_require_admin(self) -> None:
        assistants = source("backend/app/api/assistants.py")
        self.assertGreaterEqual(assistants.count("require_admin(current_user(request))"), 6)

    def test_every_harness_endpoint_requires_admin(self) -> None:
        harness = source("backend/app/api/harness.py")
        self.assertGreaterEqual(harness.count("require_admin(current_user(request))"), 6)

    def test_regeneration_checks_session_owner(self) -> None:
        chat = source("backend/app/services/chat.py")
        self.assertIn("service.get(assistant.session_id, include_archived=True)", chat)

    def test_history_turn_has_explicit_type_for_stable_frontend_build(self) -> None:
        answer_page = source("frontend/src/features/answer/AnswerPage.vue")
        self.assertIn("const turn: AnswerTurn = pending ??", answer_page)

    def test_harness_controls_are_admin_only_in_frontend(self) -> None:
        answer_page = source("frontend/src/features/answer/AnswerPage.vue")
        self.assertIn('v-if="isAdmin" class="deepseek-toggle"', answer_page)
        self.assertIn("if (isAdmin.value)", answer_page)

    def test_fastapi_query_parameters_do_not_use_pydantic_field(self) -> None:
        chat_api = source("backend/app/api/chat.py")
        self.assertIn("page: int = Query(default=1, ge=1)", chat_api)
        self.assertIn(
            "page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100)",
            chat_api,
        )


if __name__ == "__main__":
    unittest.main()
