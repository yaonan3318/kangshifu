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

    # ---- P1-9 ~ P1-15 收尾新增的边界 ----

    def test_disabled_roles_are_excluded_from_permission_resolution(self) -> None:
        permissions = source("backend/app/services/permissions.py")
        self.assertIn("if role.enabled", permissions)
        self.assertIn("if row is not None and row.enabled", permissions)

    def test_acl_read_requires_manage(self) -> None:
        documents = source("backend/app/api/documents.py")
        self.assertIn("service.get_managed(document_id)", documents)

    def test_acl_write_validates_subjects_and_deduplicates(self) -> None:
        documents = source("backend/app/services/documents.py")
        self.assertIn("def _validate_acl", documents)
        self.assertIn("ACL_SUBJECT_DISABLED", documents)
        self.assertIn("merged[key] = AclPermission.MANAGE", documents)

    def test_password_reset_and_disable_revoke_sessions(self) -> None:
        identity = source("backend/app/services/identity.py")
        self.assertIn("def revoke_user_sessions", identity)
        self.assertIn("def reset_password", identity)
        self.assertIn("def _guard_last_super_admin", identity)

    def test_historical_reference_rechecks_permission(self) -> None:
        chat = source("backend/app/services/chat.py")
        self.assertIn("PermissionResolver(self.session, self.user)", chat)
        self.assertIn('"FORBIDDEN"', chat)

    def test_audit_write_is_best_effort(self) -> None:
        audit = source("backend/app/services/audit.py")
        self.assertIn("logger.exception", audit)
        self.assertIn("success", audit)
        self.assertIn("request_id", audit)

    def test_feedback_ranking_is_default_off_and_capped(self) -> None:
        config = source("backend/app/config.py")
        self.assertIn("search_feedback_ranking_enabled: bool = False", config)
        self.assertIn("search_feedback_max_boost: float = 0.05", config)
        ranking = source("backend/app/services/feedback_ranking.py")
        self.assertIn("search_feedback_min_samples", ranking)
        self.assertIn("max(-cap, min(cap, net * cap))", ranking)

    def test_feedback_boost_never_bypasses_evidence_threshold(self) -> None:
        search = source("backend/app/services/search.py")
        self.assertIn("def _apply_feedback", search)
        # 阈值判断仍使用未叠加反馈的 final_score。
        self.assertIn("if item.final_score < self.settings.search_min_evidence_score", search)

    def test_external_policy_blocks_sensitive_documents(self) -> None:
        audit = source("backend/app/services/audit.py")
        self.assertIn('SENSITIVE_LEVELS_EXTERNAL_BLOCKED = ("CONFIDENTIAL", "RESTRICTED")', audit)
        rag = source("backend/app/services/rag.py")
        self.assertIn("_restricted_document_ids", rag)

    def test_document_chunks_use_permission_resolver(self) -> None:
        chunks = source("backend/app/services/chunks.py")
        self.assertIn("require_read(self.resolver, document)", chunks)
        self.assertIn("require_manage(self.resolver, document)", chunks)

    def test_new_migrations_are_linear_and_have_downgrade(self) -> None:
        versions = ROOT / "backend/migrations/versions"
        for filename, revision, down_revision in (
            ("0013_identity_management.py", "0013_identity_management", "0012_answer_feedback"),
            ("0014_audit_completion.py", "0014_audit_completion", "0013_identity_management"),
            ("0015_feedback_ranking.py", "0015_feedback_ranking", "0014_audit_completion"),
            ("0016_feedback_documents.py", "0016_feedback_documents", "0015_feedback_ranking"),
        ):
            content = (versions / filename).read_text(encoding="utf-8")
            self.assertIn(f'revision = "{revision}"', content)
            self.assertIn(f'down_revision = "{down_revision}"', content)
            self.assertIn("def downgrade()", content)

    def test_frontend_dependencies_are_pinned(self) -> None:
        package = source("frontend/package.json")
        self.assertNotIn('"latest"', package)


if __name__ == "__main__":
    unittest.main()
