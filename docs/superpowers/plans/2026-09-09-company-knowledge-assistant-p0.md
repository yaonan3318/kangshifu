# Company Knowledge Assistant P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing local RAG application with governed knowledge bases, recoverable document lifecycle, editable chunks, stronger retrieval, and a retrieval evaluation workbench.

**Architecture:** Extend the current FastAPI/SQLAlchemy/PostgreSQL domain instead of introducing a second storage system. All consumers continue through `SearchService`, which applies a shared visibility policy before keyword/vector recall and optional reranking. Vue receives focused knowledge-base, recycle-bin, chunk-editor, and retrieval-lab views through typed APIs.

**Tech Stack:** Python 3.12/3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, pgvector, sentence-transformers, Vue 3, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-09-09-company-knowledge-assistant-p0-design.md`

## Global Constraints

- Preserve all existing document rows, files, OCR text, chunks, embeddings, jobs, batches, answers, and Harness history.
- Create one default knowledge base and migrate all existing documents into it.
- Deleted, disabled, superseded, or disabled-knowledge-base content must be excluded by the shared search service.
- Reranking is optional, lazy-loaded, local-first, and must degrade to RRF without failing a request.
- Do not add authentication, SSO, enterprise channels, workflow builders, or automatic recycle-bin cleanup in P0.
- Do not require long-running model tests on the server; provide static verification and Mac validation commands.

---

### Task 1: Knowledge Governance Schema

**Files:**
- Create: `backend/app/models/knowledge_base.py`
- Create: `backend/app/models/tag.py`
- Create: `backend/app/models/retrieval_evaluation.py`
- Create: `backend/migrations/versions/0006_knowledge_governance.py`
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/models/document_chunk.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Produces: `KnowledgeBase`, `Tag`, `RetrievalTestCase`, `RetrievalTestRun` ORM models.
- Produces: document lifecycle fields and `DocumentChunk.enabled/manually_edited/original_content/token_count/updated_at`.

- [ ] Add focused ORM models with UUID primary keys, timezone-aware timestamps, relationships, indexes, and uniqueness constraints.
- [ ] Add document fields `knowledge_base_id`, `relative_path`, `version_number`, `previous_version_id`, `enabled`, `deleted_at`, `deleted_reason`, and `metadata_json`.
- [ ] Add chunk lifecycle and editing fields without changing existing content or embeddings.
- [ ] Write migration `0006` that inserts a stable default knowledge base, backfills every document, then makes `knowledge_base_id` non-null.
- [ ] Add partial/indexed lookup support for active documents and enabled chunks.
- [ ] Run `python -m compileall app migrations` and `alembic heads`; expect one head and no syntax errors.
- [ ] Commit schema changes.

### Task 2: Knowledge Base and Document Lifecycle Services

**Files:**
- Create: `backend/app/schemas/knowledge_bases.py`
- Create: `backend/app/services/knowledge_bases.py`
- Create: `backend/app/api/knowledge_bases.py`
- Modify: `backend/app/schemas/documents.py`
- Modify: `backend/app/services/documents.py`
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: CRUD endpoints under `/api/knowledge-bases`.
- Produces: `soft_delete`, `restore`, `purge`, `set_enabled`, `update_metadata`, and version-history document operations.
- Consumes: governance ORM models from Task 1.

- [ ] Add knowledge-base list/create/update/enable/disable endpoints; reject duplicate names and disabling the last active knowledge base.
- [ ] Change ordinary document listing/get/download/content endpoints to exclude soft-deleted rows by default.
- [ ] Replace destructive `DELETE /documents/{id}` behavior with a soft-delete transaction.
- [ ] Add recycle-bin listing, restore, and explicit permanent-delete endpoints.
- [ ] Add document enable/disable, metadata/tags, knowledge-base move, and version-history endpoints.
- [ ] Preserve storage files until permanent deletion succeeds; expose retryable error details when disk deletion fails.
- [ ] Ensure upload/batch services assign the selected or default knowledge base while remaining backward-compatible.
- [ ] Run backend compile and OpenAPI generation smoke checks without starting models.
- [ ] Commit lifecycle API changes.

### Task 3: Chunk Governance and Atomic Reindexing

**Files:**
- Create: `backend/app/schemas/chunks.py`
- Create: `backend/app/services/chunks.py`
- Create: `backend/app/api/chunks.py`
- Modify: `backend/app/services/processing.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `PATCH /api/chunks/{id}`, `/enable`, `/disable`, and `/reindex`.
- Produces: `ChunkService.update_content(chunk_id: UUID, content: str) -> DocumentChunk` with atomic embedding/index replacement.

- [ ] Add paginated chunk listing with enabled/edit-state/token metadata.
- [ ] Implement manual edits that retain first `original_content`, compute `search_vector`, embedding, and token count before committing.
- [ ] Add enable/disable operations that never erase content or vectors.
- [ ] Add single-chunk reindex and restore-original operations.
- [ ] Ensure whole-document reprocessing clears prior manual edits only after explicit API confirmation.
- [ ] Run compile and route-schema smoke checks.
- [ ] Commit chunk governance changes.

### Task 4: Shared Visibility, Query Processing, and Retrieval Scoring

**Files:**
- Create: `backend/app/services/query_processing.py`
- Create: `backend/app/services/reranking.py`
- Create: `backend/app/services/retrieval_policy.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/services/search.py`
- Modify: `backend/app/schemas/search.py`
- Modify: `backend/app/services/rag.py`
- Modify: `backend/app/harness/tools/company_search.py`
- Modify: `backend/app/download_models.py`
- Modify: `scripts/setup.sh`

**Interfaces:**
- Produces: `QueryProcessor.process(query: str) -> ProcessedQuery`.
- Produces: `Reranker.rerank(query: str, candidates: list[ScoredCandidate]) -> RerankOutcome`.
- Produces: search diagnostics with mode, warnings, normalized query, expanded terms, stage scores, timing, and no-answer reason.

- [ ] Add configurable company dictionary parsing and deterministic query normalization.
- [ ] Centralize clauses for active knowledge base, active document, non-deleted current version, and enabled chunk.
- [ ] Preserve raw keyword/vector scores and RRF scores instead of returning only match labels.
- [ ] Add filename/title bonuses, per-document result caps, minimum evidence thresholds, and knowledge-base/tag filters.
- [ ] Implement lazy `BAAI/bge-reranker-v2-m3` loading behind `RERANK_ENABLED`, bounded candidates and bounded text length.
- [ ] Catch model availability/inference failures and return an RRF result with a warning.
- [ ] Make RAG and Harness consume the same filtered results and refuse generation when evidence is below threshold.
- [ ] Add optional reranker preparation to model setup without pulling it when disabled.
- [ ] Run compile checks and import the search service with reranking disabled.
- [ ] Commit retrieval changes.

### Task 5: Retrieval Evaluation Backend

**Files:**
- Create: `backend/app/schemas/retrieval_lab.py`
- Create: `backend/app/services/retrieval_evaluation.py`
- Create: `backend/app/api/retrieval_lab.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `/api/retrieval-lab/inspect`, `/cases`, `/runs`, and `/runs/{id}` endpoints.
- Consumes: diagnostic mode from `SearchService.search_with_diagnostics`.

- [ ] Add inspect endpoint returning each retrieval stage and timing without invoking an answer model.
- [ ] Add test-case CRUD with expected document IDs, expected keywords, expected-no-answer, knowledge-base scope, and enabled flag.
- [ ] Add batch run service that snapshots retrieval settings and calculates Recall@K, reciprocal rank, no-answer correctness, and average latency.
- [ ] Store per-case outcomes in JSONB so previous runs remain comparable after settings change.
- [ ] Return actionable validation errors for deleted expected documents and empty test runs.
- [ ] Run compile and OpenAPI schema smoke checks.
- [ ] Commit evaluation backend.

### Task 6: Knowledge Governance Frontend

**Files:**
- Create: `frontend/src/api/knowledgeBases.ts`
- Create: `frontend/src/api/chunks.ts`
- Create: `frontend/src/types/knowledgeBases.ts`
- Create: `frontend/src/features/documents/KnowledgeBaseManager.vue`
- Create: `frontend/src/features/documents/RecycleBin.vue`
- Create: `frontend/src/features/documents/ChunkEditor.vue`
- Modify: `frontend/src/api/documents.ts`
- Modify: `frontend/src/types/documents.ts`
- Modify: `frontend/src/features/documents/DocumentLibrary.vue`
- Modify: `frontend/src/features/documents/DocumentTable.vue`
- Modify: `frontend/src/features/documents/DocumentDetail.vue`
- Modify: `frontend/src/features/documents/BatchImport.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Tasks 2 and 3 REST APIs.
- Produces: knowledge-base selector/manager, lifecycle controls, recycle bin, version history, tags, and chunk editor.

- [ ] Add typed knowledge-base, lifecycle, tag, version, and chunk API clients.
- [ ] Add knowledge-base selection to single and batch upload; default to the backend default base.
- [ ] Add list filters and columns for knowledge base, path, version, tags, status, enabled state, and chunk count.
- [ ] Replace delete copy with “移入回收站”; add explicit enable/disable controls.
- [ ] Add recycle-bin restore and typed-name permanent-delete confirmation.
- [ ] Extend document detail with overview, chunks, processing, and version sections.
- [ ] Add inline chunk edit/restore/enable/disable/reindex states with errors kept near the action.
- [ ] Run `npm run build`; expect Vue type-check/build success.
- [ ] Commit governance UI.

### Task 7: Search UI and Retrieval Laboratory

**Files:**
- Create: `frontend/src/api/retrievalLab.ts`
- Create: `frontend/src/types/retrievalLab.ts`
- Create: `frontend/src/features/search/RetrievalLab.vue`
- Create: `frontend/src/features/search/RetrievalStages.vue`
- Modify: `frontend/src/api/search.ts`
- Modify: `frontend/src/types/search.ts`
- Modify: `frontend/src/features/search/SearchPage.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: enhanced search and retrieval-lab APIs from Tasks 4 and 5.
- Produces: searchable knowledge-base/tag filters, actual retrieval-mode/warning display, score explanation, test cases, and comparison runs.

- [ ] Add knowledge-base/tag filters and preserve existing type/name/date filters.
- [ ] Display actual retrieval mode, downgrade warning, normalized query, expanded terms, and no-answer reason.
- [ ] Add compact score explanation per result without exposing raw vectors.
- [ ] Add a navigation entry for the administrator retrieval laboratory.
- [ ] Build inspect view with collapsible keyword/vector/RRF/reranker/final-context stages and timing.
- [ ] Build standard-case editor, batch run action, metric summary, and prior-run comparison.
- [ ] Keep long chunk content collapsed by default and keyboard accessible.
- [ ] Run `npm run build`; expect successful production bundle.
- [ ] Commit retrieval UI.

### Task 8: Upgrade Documentation and Static Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `scripts/setup.sh`
- Create: `docs/p0-mac-validation.md`

**Interfaces:**
- Produces: exact Mac pull, database start, migration, optional reranker download, application start, downgrade, and manual acceptance procedures.

- [ ] Document new environment variables, defaults, memory behavior, and RRF fallback.
- [ ] Document safe upgrade order: start database, run Alembic, prepare optional models, then start services.
- [ ] Add manual checks for old-data preservation, soft delete/restore/purge, disabled-content exclusion, chunk editing, reranker fallback, no-answer behavior, and evaluation runs.
- [ ] Run `git diff --check`, backend compile, Alembic head check, and frontend production build only; do not run long model or browser suites on the server.
- [ ] Review the spec line-by-line and record any intentionally deferred item in the validation document.
- [ ] Commit docs and verification changes.
