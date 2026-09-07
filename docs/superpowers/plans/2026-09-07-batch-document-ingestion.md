# Batch Document Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resumable multi-file and folder ingestion with durable batches, per-file failures, retry, progress, and content deduplication while preserving the existing single-file workflow.

**Architecture:** PostgreSQL stores durable batch and batch-file state. Existing `Document` rows remain the canonical deduplicated stored/parsed object in this phase; multiple `BatchFile` rows may reference one document, which provides physical-file and processing-result reuse without destabilizing the current parser pipeline. FastAPI exposes batch lifecycle and file-upload endpoints; Vue uploads up to four files concurrently and lets users manually resume a batch by selecting the original files again.

**Tech Stack:** Python 3.12/3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/pgvector, Vue 3, TypeScript, XMLHttpRequest.

**Spec:** `docs/superpowers/specs/2026-09-07-batch-document-ingestion-design.md`

## Global Constraints

- Preserve all existing documents, downloads, processing jobs, search, RAG, DeepSeek, and Harness behavior.
- Preserve the existing single-file upload endpoint and UI.
- Keep original files local to the Mac.
- A failed file must not roll back successful files in the same batch.
- Resume is explicitly initiated by the user; browsers never regain file access automatically.
- Content SHA-256 is the idempotency key; duplicate content reuses the existing `Document` and its parsed chunks.
- Server development performs static checks only; runtime and browser verification occur on the user's Mac.

---

### Task 1: Durable batch models and migration

**Files:**
- Create: `backend/app/models/upload_batch.py`
- Modify: `backend/app/models/document.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/0005_upload_batches.py`

**Interfaces:**
- Produces `UploadBatch`, `BatchFile`, `BatchStatus`, `BatchUploadStatus`, and `BatchProcessingStatus`.
- Adds `Document.batch_files` relationship without changing existing document columns.
- Migration creates a deterministic “历史导入” batch and associates existing documents with it.

- [ ] Define enum-backed SQLAlchemy models, counters derived from related file rows, timestamps, error fields, and a unique `(batch_id, relative_path)` constraint.
- [ ] Add ORM exports and relationships.
- [ ] Create Alembic migration `0004_harness -> 0005_upload_batches`, including legacy backfill.
- [ ] Run Python compilation and Alembic module import checks.
- [ ] Commit the data model.

### Task 2: Batch schemas, service, and API

**Files:**
- Create: `backend/app/schemas/batches.py`
- Create: `backend/app/services/batches.py`
- Create: `backend/app/api/batches.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- `BatchService.create`, `list`, `get`, `upload`, `retry`, `ignore`, and `cancel` implement lifecycle rules.
- API provides `POST/GET /api/batches`, `GET /api/batches/{id}`, `POST /api/batches/{id}/files`, `POST /api/batches/{id}/files/{file_id}/retry`, `POST /api/batches/{id}/files/{file_id}/ignore`, and `POST /api/batches/{id}/cancel`.
- Upload accepts `relative_path` and a file; duplicate SHA-256 links the existing document and reports `DUPLICATE` without returning HTTP 409.

- [ ] Add validated request/response schemas with totals calculated from batch files.
- [ ] Implement path normalization, batch-state refresh, duplicate reuse, isolated file failure recording, and retry/ignore/cancel operations.
- [ ] Add configurable batch limits and disk-space preflight.
- [ ] Register routes and document status mapping.
- [ ] Compile all backend Python modules and run `git diff --check`.
- [ ] Commit the batch API.

### Task 3: Synchronize processing progress

**Files:**
- Modify: `backend/app/services/processing.py`
- Modify: `backend/app/services/batches.py`

**Interfaces:**
- `BatchService.synchronize_document(document_id)` maps document processing states to all related batch files.
- Worker processing completion and failure call synchronization after committing document state.

- [ ] Add status mapping from existing `DocumentStatus` to batch processing status.
- [ ] Synchronize every batch reference after processing success or failure.
- [ ] Recompute affected batch aggregate state transactionally.
- [ ] Compile backend modules and inspect processing error paths.
- [ ] Commit progress synchronization.

### Task 4: Frontend batch API and types

**Files:**
- Create: `frontend/src/types/batches.ts`
- Create: `frontend/src/api/batches.ts`

**Interfaces:**
- Typed APIs create/list/read/cancel batches, upload one file with progress, retry, and ignore.
- `uploadBatchFile` preserves the relative path supplied by folder selection.

- [ ] Define batch summary, batch detail, batch file, status, create request, and upload progress types.
- [ ] Implement fetch APIs and XHR upload with existing error-envelope handling semantics.
- [ ] Review TypeScript property names against backend schemas.
- [ ] Commit frontend contracts.

### Task 5: Batch list and creation UI

**Files:**
- Create: `frontend/src/features/documents/BatchImport.vue`
- Create: `frontend/src/features/documents/BatchList.vue`
- Modify: `frontend/src/features/documents/DocumentLibrary.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `BatchImport` collects batch metadata and multiple/folder files, creates the batch, and uploads four files concurrently.
- `BatchList` emits a selected batch for detail/resume.

- [ ] Add “单文件上传 / 批量导入 / 导入批次” navigation inside the library page.
- [ ] Add batch metadata, multi-file input, `webkitdirectory` folder input, file preflight summary, and removable staging rows.
- [ ] Upload four files concurrently and retain per-file progress after isolated failures.
- [ ] Poll only while a batch has active files; update data without remounting the page.
- [ ] Add responsive, accessible styles matching the current local-library design.
- [ ] Commit batch creation UI.

### Task 6: Resume and failure-management UI

**Files:**
- Create: `frontend/src/features/documents/BatchDetail.vue`
- Modify: `frontend/src/features/documents/BatchImport.vue`
- Modify: `frontend/src/features/documents/DocumentLibrary.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Batch detail filters file rows, retries processing failures, ignores unwanted failures, cancels batches, and starts manual resume.
- Manual resume asks for the original files/folder and sends only records not already terminal for matching relative paths.

- [ ] Present aggregate counters and progress.
- [ ] Add file status filters, relative paths, error stage, and readable error messages.
- [ ] Add manual “继续上传”, single retry, retry-all, ignore, and cancel actions.
- [ ] Match selected files to unresolved batch paths before enqueueing uploads.
- [ ] Ensure timers and XHR work stop when the component unmounts.
- [ ] Commit failure-management UI.

### Task 7: Documentation and final static verification

**Files:**
- Modify: `docs/api.md`
- Create: `docs/batch-import-mac-verification.md`
- Modify: `backend/.env.example`

**Interfaces:**
- Documents batch endpoints, configuration, migration, and Mac verification commands.

- [ ] Document request/response examples and batch state meanings.
- [ ] Document Mac migration, start, 200-file, interruption/resume, duplicate, retry, and regression checks.
- [ ] Run `python3 -m compileall backend/app backend/migrations/versions` and `git diff --check`.
- [ ] Record that Vue build remains a Mac-side verification if server `node_modules` is absent.
- [ ] Commit documentation and verification artifacts.
