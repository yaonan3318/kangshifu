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

    def test_assistant_mutations_require_assistant_manage(self) -> None:
        assistants = source("backend/app/api/assistants.py")
        self.assertGreaterEqual(
            assistants.count("require_permission(current_user(request), ASSISTANT_MANAGE)"), 6,
        )

    def test_every_harness_endpoint_requires_admin_and_harness_permission(self) -> None:
        harness = source("backend/app/api/harness.py")
        # 每个端点都经过统一的 super admin + HARNESS_USE 校验。
        self.assertGreaterEqual(harness.count("_require_harness(request)"), 6)
        self.assertIn("require_admin(current_user(request))", harness)
        self.assertIn("require_permission(user, HARNESS_USE)", harness)

    def test_regeneration_checks_session_owner(self) -> None:
        chat = source("backend/app/services/chat.py")
        self.assertIn("service.get(assistant.session_id, include_archived=True)", chat)

    def test_history_turn_has_explicit_type_for_stable_frontend_build(self) -> None:
        answer_page = source("frontend/src/features/answer/AnswerPage.vue")
        self.assertIn("const turn: AnswerTurn = pending ??", answer_page)

    def test_harness_controls_are_not_exposed_in_answer_frontend(self) -> None:
        answer_page = source("frontend/src/features/answer/AnswerPage.vue")
        self.assertNotIn("使用 Harness", answer_page)
        self.assertNotIn("选择 Kubernetes context", answer_page)

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

    def test_harness_audit_wraps_stream_iteration(self) -> None:
        harness = source("backend/app/api/harness.py")
        self.assertIn("async def _audited_stream", harness)
        self.assertIn("async for event in stream", harness)
        self.assertIn('"harness_completed"', harness)
        self.assertIn('"harness_failed"', harness)

    def test_denials_are_audited_globally(self) -> None:
        main = source("backend/app/main.py")
        self.assertIn('"PERMISSION_DENIED"', main)
        self.assertIn('"authorization_denied"', main)
        self.assertIn('"document_upload_denied"', main)
        self.assertIn('"knowledge_base_manage_denied"', main)
        self.assertIn('success=False', main)

    # ---- 功能级 RBAC ----

    def test_rbac_service_resolution_rules(self) -> None:
        rbac = source("backend/app/services/rbac.py")
        for snippet in (
            "def effective_permissions",
            "def has_permission",
            "def require_permission",
            "if not role.enabled",
            "if user.is_super_admin",
            "codes.discard(HARNESS_USE)",
            '"PERMISSION_DENIED", "当前账号没有此功能权限", 403',
        ):
            self.assertIn(snippet, rbac)

    def test_rbac_migration_is_linear_and_idempotent(self) -> None:
        migration = source("backend/migrations/versions/0018_function_rbac.py")
        self.assertIn('revision = "0018_function_rbac"', migration)
        self.assertIn('down_revision = "0017_assistant_runtime_policy"', migration)
        self.assertIn("def downgrade()", migration)
        self.assertIn("ON CONFLICT DO NOTHING", migration)
        for code in ("ANSWER_USE", "DOCUMENT_MANAGE", "IDENTITY_MANAGE", "HARNESS_USE"):
            self.assertIn(code, migration)

    def test_rbac_permissions_are_enforced_on_key_endpoints(self) -> None:
        expectations = {
            "backend/app/api/answer.py": "ANSWER_USE",
            "backend/app/api/search.py": "SEARCH_USE",
            "backend/app/api/documents.py": "DOCUMENT_VIEW",
            "backend/app/api/batches.py": "DOCUMENT_UPLOAD",
            "backend/app/api/knowledge_bases.py": "KNOWLEDGE_BASE_MANAGE",
            "backend/app/api/retrieval_lab.py": "RETRIEVAL_LAB_USE",
            "backend/app/api/assistants.py": "ASSISTANT_MANAGE",
            "backend/app/api/users.py": "IDENTITY_MANAGE",
            "backend/app/api/roles.py": "IDENTITY_MANAGE",
            "backend/app/api/departments.py": "IDENTITY_MANAGE",
            "backend/app/api/audit.py": "AUDIT_VIEW",
            "backend/app/api/stats.py": "STATS_VIEW",
        }
        for path, code in expectations.items():
            self.assertIn(code, source(path))

    def test_stats_service_does_not_override_stats_view_permission(self) -> None:
        """接口层通过 STATS_VIEW 后，服务层不能再次限定为超级管理员。"""
        stats_service = source("backend/app/services/stats.py")
        self.assertNotIn("not user.is_super_admin", stats_service)

    def test_document_acl_remains_independent_of_function_permission(self) -> None:
        documents = source("backend/app/api/documents.py")
        self.assertIn("require_permission", documents)
        # 管理接口仍调用服务层文档级 MANAGE 校验。
        service = source("backend/app/services/documents.py")
        self.assertIn("require_manage(self.resolver, document)", service)

    # ---- P2-0 质量基线 ----

    def test_retrieval_config_is_versionable(self) -> None:
        config = source("backend/app/services/retrieval_config.py")
        for field in (
            "keyword_limit", "vector_limit", "rrf_k", "rerank_enabled", "final_limit",
            "similarity_threshold", "query_rewrite_synonyms",
        ):
            self.assertIn(field, config)
        self.assertIn("def config_diff", config)

    def test_search_service_reads_versioned_config(self) -> None:
        search = source("backend/app/services/search.py")
        self.assertIn("self.config.keyword_limit", search)
        self.assertIn("self.config.vector_limit", search)
        self.assertIn("self.config.similarity_threshold", search)
        self.assertIn("self.config.min_evidence_score", search)
        self.assertIn("config: RetrievalConfig | None = None", search)

    def test_evaluation_service_exposes_metrics_and_compare(self) -> None:
        service = source("backend/app/services/retrieval_evaluation.py")
        for metric in (
            "document_recall", "chunk_recall", "hit_rate_at_1", "hit_rate_at_3", "hit_rate_at_5",
            "keypoint_coverage", "citation_accuracy", "no_answer_accuracy",
            "first_token_latency_ms", "answer_latency_ms",
        ):
            self.assertIn(metric, service)
        self.assertIn("async def run_evaluation", service)
        self.assertIn("def compare_runs", service)
        self.assertIn("def import_cases", service)

    def test_evaluation_endpoints_are_gated_and_linear(self) -> None:
        api = source("backend/app/api/retrieval_lab.py")
        self.assertIn("RETRIEVAL_LAB_USE", api)
        self.assertIn("/evaluation-sets", api)
        self.assertIn("/config-versions", api)
        self.assertIn("/runs/compare", api)
        migration = source("backend/migrations/versions/0019_evaluation_sets.py")
        self.assertIn('revision = "0019_evaluation_sets"', migration)
        self.assertIn("def downgrade()", migration)

    # ---- P2-1 检索准确性 ----

    def test_query_rewrite_falls_back_and_keeps_original(self) -> None:
        rewrite = source("backend/app/services/query_rewrite.py")
        self.assertIn("async def rewrite", rewrite)
        self.assertIn("async def multi_query", rewrite)
        self.assertIn("except LlmError", rewrite)
        self.assertIn("original", rewrite)
        # 提示词要求不得改变用户原意。
        self.assertIn("不得改变用户原意", rewrite)

    def test_multi_query_rrf_and_metadata_filters(self) -> None:
        search = source("backend/app/services/search.py")
        self.assertIn("def _fuse_lists", search)
        self.assertIn("def search_with_diagnostics", search)
        for field in (
            "department_id", "owner_user_id", "document_status", "relative_path",
            "version_number", "valid_only",
        ):
            self.assertIn(f"request.{field}", search)

    def test_dictionary_is_admin_maintained_not_hardcoded(self) -> None:
        model = source("backend/app/models/dictionary.py")
        self.assertIn("retrieval_dictionary_entries", model)
        service = source("backend/app/services/dictionaries.py")
        self.assertIn("def load_expansions", service)
        processor = source("backend/app/services/query_processing.py")
        self.assertIn("_spelling_corrections", processor)
        api = source("backend/app/api/retrieval_lab.py")
        self.assertIn("/dictionaries", api)

    def test_rerank_records_before_after_ranks(self) -> None:
        search = source("backend/app/services/search.py")
        self.assertIn("pre_rerank_rank", search)
        self.assertIn("post_rerank_rank", search)

    # ---- P2-2 回答可靠性 ----

    def test_answer_quality_confidence_and_citation_check(self) -> None:
        quality = source("backend/app/services/answer_quality.py")
        for snippet in (
            "def compute_confidence", "def verify_answer", "def classify_question",
            "def mark_unsupported", "INSUFFICIENT", "NO_RELEVANT_DOCUMENT",
            "PERMISSION_RESTRICTED", "LOW_RELEVANCE", "MODEL_UNAVAILABLE",
        ):
            self.assertIn(snippet, quality)
        self.assertIn("当前可访问的公司资料中没有找到足够依据。", quality)

    def test_answer_quality_has_structure_templates(self) -> None:
        quality = source("backend/app/services/answer_quality.py")
        for section in ("适用范围", "办理步骤", "实施步骤", "时间线", "对比表格", "主题归类"):
            self.assertIn(section, quality)

    def test_rag_emits_quality_events_and_marks_inference(self) -> None:
        flow = source("backend/app/services/rag_flow.py")
        for snippet in (
            'type="confidence"', 'type="citation_check"', 'type="no_answer"',
            "compute_confidence", "verify_answer", "mark_unsupported",
        ):
            self.assertIn(snippet, flow)
        rag = source("backend/app/services/rag.py")
        self.assertIn("template_instruction", rag)

    def test_hydrate_source_exposes_traceability(self) -> None:
        chat = source("backend/app/services/chat.py")
        for field in ("version_number", "matched_keywords", "can_download", "extension"):
            self.assertIn(field, chat)

    # ---- P2-3 助手角色增强 ----

    def test_assistant_model_has_role_fields(self) -> None:
        model = source("backend/app/models/assistant.py")
        for field in (
            "answer_template", "internet_enabled", "no_answer_policy", "capabilities", "limitations",
        ):
            self.assertIn(field, model)

    def test_assistant_presets_seeded_idempotently(self) -> None:
        migration = source("backend/migrations/versions/0021_assistant_roles.py")
        for preset in (
            "康师傅综合助手", "人事制度助手", "技术研发助手",
            "产品资料助手", "运维助手", "项目进度助手",
        ):
            self.assertIn(preset, migration)
        self.assertIn("ON CONFLICT (name) DO NOTHING", migration)
        self.assertIn("def downgrade()", migration)

    def test_assistant_welcome_endpoint_and_policy(self) -> None:
        api = source("backend/app/api/assistants.py")
        self.assertIn("/welcome", api)
        for field in ("capabilities", "limitations", "recent_questions", "knowledge_scope",
                      "general_knowledge_allowed", "operations_allowed"):
            self.assertIn(field, api)
        rag = source("backend/app/services/rag.py")
        self.assertIn("answer_template", rag)
        self.assertIn("no_answer_policy", rag)

    # ---- P2-4 轻量 Chatflow ----

    def test_chatflow_nodes_and_graph_validation(self) -> None:
        service = source("backend/app/services/chatflow.py")
        for node_type in (
            "start", "classify", "context_completion", "query_rewrite", "multi_query",
            "knowledge_search", "reranker", "condition", "local_model", "deepseek", "harness",
            "answer_check", "final_answer",
            # 兼容旧图节点类型
            "question_classify", "retrieval", "rerank",
        ):
            self.assertIn(f'"{node_type}"', service)
        self.assertIn("def validate_graph", service)
        self.assertIn("def build_plan", service)
        self.assertIn("def debug_run", service)
        self.assertIn("class ChatflowRunner", service)
        self.assertIn("CHATFLOW_GRAPH_CYCLE", service)

    def test_chatflow_versions_and_assistant_binding(self) -> None:
        model = source("backend/app/models/chatflow.py")
        self.assertIn("class Chatflow", model)
        self.assertIn("class ChatflowVersion", model)
        assistant = source("backend/app/models/assistant.py")
        self.assertIn("chatflow_id", assistant)
        api = source("backend/app/api/chatflows.py")
        for path in ("/publish", "/rollback", "/versions", "/debug", "/node-types"):
            self.assertIn(path, api)

    def test_rag_service_uses_chatflow_plan_and_node_timings(self) -> None:
        rag = source("backend/app/services/rag.py")
        self.assertIn("run_production_flow", rag)
        self.assertIn("ChatflowService", rag)
        flow = source("backend/app/services/rag_flow.py")
        self.assertIn("ChatflowRunner", flow)
        self.assertIn("build_plan", flow)
        self.assertIn("node_timings", flow)
        self.assertIn("flow_steps", flow)

    # ---- P2-5 用户体验与比赛展示 ----

    def test_knowledge_gap_center(self) -> None:
        model = source("backend/app/models/knowledge_gap.py")
        self.assertIn("class KnowledgeGap", model)
        for reason in ("NO_ANSWER", "LOW_CONFIDENCE", "NEGATIVE_FEEDBACK", "WRONG_DOCUMENT"):
            self.assertIn(reason, model)
        service = source("backend/app/services/knowledge_gaps.py")
        self.assertIn("def record_gap", service)
        self.assertIn("async def rerun", service)
        api = source("backend/app/api/knowledge_gaps.py")
        for path in ("/statistics", "/rerun"):
            self.assertIn(path, api)

    def test_dashboard_and_stage_visualization(self) -> None:
        stats = source("backend/app/services/stats.py")
        self.assertIn("def compute_dashboard", stats)
        for field in ("knowledge_base_count", "document_count", "chunk_count", "citation_coverage",
                      "satisfaction", "knowledge_gap_count"):
            self.assertIn(field, stats)
        api = source("backend/app/api/stats.py")
        self.assertIn("/dashboard", api)
        flow = source("backend/app/services/rag_flow.py")
        for stage in ('"understanding"', '"retrieving"', '"candidates"', '"checking"'):
            self.assertIn(stage, flow)
        rag = source("backend/app/services/rag.py")
        self.assertIn("_follow_up_suggestions", rag)

    # ---- P2-6 文档理解能力 ----

    def test_chunking_strategies_and_config(self) -> None:
        chunking = source("backend/app/services/chunking.py")
        for strategy in ("fixed", "heading", "paragraph", "page", "table", "parent_child"):
            self.assertIn(f'"{strategy}"', chunking)
        self.assertIn("class ChunkingConfig", chunking)
        for field in ("target", "maximum", "overlap", "min_chars", "row_batch"):
            self.assertIn(field, chunking)
        self.assertIn("def chunk_blocks", chunking)

    def test_parsers_support_p2_6_features(self) -> None:
        pdf = source("backend/app/parsers/pdf.py")
        for feature in ("_repeated_lines", "_tables", "_sort_columns", "_is_heading", "_dedupe"):
            self.assertIn(feature, pdf)
        docx = source("backend/app/parsers/docx.py")
        self.assertIn("_row_values", docx)
        self.assertIn("_image_blocks", docx)
        xlsx = source("backend/app/parsers/spreadsheet.py")
        self.assertIn("_merged_values", xlsx)
        pptx = source("backend/app/parsers/presentation.py")
        self.assertIn("_ocr_picture", pptx)

    def test_document_graph_metadata_and_preview(self) -> None:
        model = source("backend/app/models/document.py")
        for field in ("author", "department_id", "topic", "related_document_ids"):
            self.assertIn(field, model)
        kb_model = source("backend/app/models/knowledge_base.py")
        self.assertIn("chunking_config", kb_model)
        api = source("backend/app/api/documents.py")
        self.assertIn("/chunk-preview", api)
        service = source("backend/app/services/documents.py")
        self.assertIn("def preview_chunks", service)

    def test_me_returns_permissions_from_enabled_roles(self) -> None:
        auth_api = source("backend/app/api/auth.py")
        self.assertIn("effective_permissions(user)", auth_api)
        schema = source("backend/app/schemas/auth.py")
        self.assertIn("permissions: list[str]", schema)

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
        self.assertIn("if item.final_score < self.config.min_evidence_score", search)

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
            ("0017_assistant_runtime_policy.py", "0017_assistant_runtime_policy", "0016_feedback_documents"),
            ("0018_function_rbac.py", "0018_function_rbac", "0017_assistant_runtime_policy"),
            ("0019_evaluation_sets.py", "0019_evaluation_sets", "0018_function_rbac"),
            ("0020_search_accuracy.py", "0020_search_accuracy", "0019_evaluation_sets"),
            ("0021_assistant_roles.py", "0021_assistant_roles", "0020_search_accuracy"),
            ("0022_chatflow.py", "0022_chatflow", "0021_assistant_roles"),
            ("0023_knowledge_gaps.py", "0023_knowledge_gaps", "0022_chatflow"),
            ("0024_document_understanding.py", "0024_document_understanding", "0023_knowledge_gaps"),
            ("0025_expected_chunks.py", "0025_expected_chunks", "0024_document_understanding"),
            ("0026_retrieval_log_ranks.py", "0026_retrieval_log_ranks", "0025_expected_chunks"),
            ("0027_reliability_and_scope.py", "0027_reliability_and_scope", "0026_retrieval_log_ranks"),
            ("0028_answer_jobs.py", "0028_answer_jobs", "0027_reliability_and_scope"),
        ):
            content = (versions / filename).read_text(encoding="utf-8")
            self.assertIn(f'revision = "{revision}"', content)
            self.assertIn(f'down_revision = "{down_revision}"', content)
            self.assertIn("def downgrade()", content)

    def test_answer_job_migration_backfills_existing_relationships(self) -> None:
        migration = source("backend/migrations/versions/0028_answer_jobs.py")
        self.assertIn("current.previous_version_id = previous.id", migration)
        self.assertIn("child.parent_sequence_number = parent.sequence_number", migration)

    def test_retrieval_evaluation_imports_search_result_annotation(self) -> None:
        evaluation = source("backend/app/services/retrieval_evaluation.py")
        self.assertIn("from app.schemas.search import SearchRequest, SearchResult", evaluation)

    def test_frontend_dependencies_are_pinned(self) -> None:
        package = source("frontend/package.json")
        self.assertNotIn('"latest"', package)

    def test_assistant_owns_external_and_harness_runtime_policy(self) -> None:
        model = source("backend/app/models/assistant.py")
        for field in ("deepseek_enabled", "harness_enabled", "harness_context", "harness_namespace"):
            self.assertIn(field, model)
        answer_api = source("backend/app/api/answer.py")
        self.assertIn("apply_assistant_runtime_policy", answer_api)

    def test_answer_runtime_policy_checks_both_deepseek_flags(self) -> None:
        answer_api = source("backend/app/api/answer.py")
        self.assertIn(
            "assistant.deepseek_enabled and assistant.use_deepseek_allowed",
            answer_api,
        )

    def test_production_flow_dispatches_deepseek_gate_condition(self) -> None:
        flow = source("backend/app/services/rag_flow.py")
        self.assertIn('if node.get("id") == "deepseek_gate"', flow)
        self.assertIn("return await deepseek_gate(context, node)", flow)

    def test_parent_expansion_uses_persisted_parent_chunk_id(self) -> None:
        search = source("backend/app/services/search.py")
        self.assertIn("item.chunk.parent_chunk_id is not None", search)
        self.assertIn("self.session.get(DocumentChunk, parent_id)", search)

    def test_historical_reference_uses_superseded_by_relation(self) -> None:
        chat = source("backend/app/services/chat.py")
        self.assertIn("bool(document.superseded_by_id)", chat)

    def test_answer_page_hides_runtime_policy_controls(self) -> None:
        answer_page = source("frontend/src/features/answer/AnswerPage.vue")
        self.assertNotIn("使用 DeepSeek 增强", answer_page)
        self.assertNotIn("使用 Harness", answer_page)
        self.assertNotIn("选择 Kubernetes context", answer_page)

    def test_role_list_uses_full_width_layout_and_drawer(self) -> None:
        role_page = source("frontend/src/features/admin/RoleAdmin.vue")
        self.assertIn('class="role-admin-layout"', role_page)
        self.assertIn('class="role-editor-backdrop"', role_page)

    def test_user_list_uses_full_width_layout_and_drawer(self) -> None:
        user_page = source("frontend/src/features/admin/UserAdmin.vue")
        self.assertIn('class="user-admin-layout"', user_page)
        self.assertIn('class="user-editor-backdrop"', user_page)

    def test_department_tree_uses_full_width_layout_and_drawer(self) -> None:
        department_page = source("frontend/src/features/admin/DepartmentAdmin.vue")
        self.assertIn('class="department-admin-layout"', department_page)
        self.assertIn('class="department-editor-backdrop"', department_page)

    def test_assistant_list_uses_full_width_layout_and_drawer(self) -> None:
        assistant_page = source("frontend/src/features/assistants/AssistantManager.vue")
        self.assertIn('class="assistant-admin-layout"', assistant_page)
        self.assertIn('class="assistant-editor-backdrop"', assistant_page)

    def test_navigation_state_is_restored_per_user(self) -> None:
        app = source("frontend/src/App.vue")
        system_admin = source("frontend/src/features/admin/SystemAdmin.vue")
        self.assertIn("company-search:last-page:", appocha := app)
        self.assertIn("restorePageForUser", appocha)
        self.assertIn("isPageAllowed", appocha)
        self.assertIn("company-search:last-system-tab:", system_admin)

    def test_user_form_error_is_rendered_inside_drawer(self) -> None:
        user_page = source("frontend/src/features/admin/UserAdmin.vue")
        backdrop_at = user_page.index('class="user-editor-backdrop"')
        drawer_error_at = user_page.index('v-if="error" class="error"', backdrop_at)
        form_at = user_page.index('class="assistant-form"', backdrop_at)
        self.assertLess(drawer_error_at, form_at)

    def test_single_admin_checkboxes_use_inline_alignment(self) -> None:
        role_page = source("frontend/src/features/admin/RoleAdmin.vue")
        department_page = source("frontend/src/features/admin/DepartmentAdmin.vue")
        self.assertIn('class="admin-check-row"', role_page)
        self.assertIn('class="admin-check-row"', department_page)


if __name__ == "__main__":
    unittest.main()
