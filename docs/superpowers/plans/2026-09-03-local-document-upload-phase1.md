# Local Document Upload Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Mac-local web application that securely uploads files into a managed library and supports listing, inspecting, downloading, duplicate detection, and deletion.

**Architecture:** A FastAPI service owns file validation, streaming persistence, metadata, and HTTP APIs; PostgreSQL with pgvector stores metadata and future processing jobs; a Vue 3 single-page interface consumes the API. PostgreSQL runs in Docker while Python and Node run natively on macOS. This phase creates `PENDING` processing jobs but does not execute parsing.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL 16 with pgvector, pytest, Vue 3, TypeScript, Vite, Vitest, Docker Compose

**Spec:** `docs/superpowers/specs/2026-09-03-local-document-search-design.md`

## Global Constraints

- Single-user local application; bind HTTP only to `127.0.0.1`.
- Managed files live below `~/Library/Application Support/CompanySearch/`; database paths are relative to this root.
- Accept only PDF, DOCX, XLSX, PPTX, TXT, Markdown, CSV, PNG, JPG, and JPEG.
- Maximum upload size is exactly 200 MiB (`209715200` bytes).
- Stream uploads to disk while hashing; never load a whole upload into memory.
- SHA-256 is unique across active documents; identical content is rejected as a duplicate.
- Stored filenames are UUIDs; preserve the original filename only as metadata.
- This phase does not parse, OCR, chunk, embed, or search document contents.

---

## File Map

```text
backend/
├── pyproject.toml                         Python dependencies and test configuration
├── alembic.ini                            Migration configuration
├── app/
│   ├── main.py                            FastAPI construction and router registration
│   ├── config.py                          Paths, limits, and environment configuration
│   ├── db.py                              SQLAlchemy engine and session dependency
│   ├── errors.py                          Stable application errors and HTTP mapping
│   ├── models/
│   │   ├── document.py                    Document ORM model and status enum
│   │   └── processing_job.py              Initial queued-job ORM model
│   ├── schemas/
│   │   └── documents.py                   API request and response models
│   ├── services/
│   │   ├── file_types.py                  Extension, signature, and MIME checks
│   │   ├── managed_storage.py             Streaming writes and atomic file operations
│   │   └── documents.py                   Upload/delete transaction orchestration
│   └── api/
│       ├── health.py                      Local health endpoint
│       └── documents.py                   Document HTTP endpoints
├── migrations/
│   ├── env.py
│   └── versions/0001_documents.py
└── tests/
    ├── conftest.py
    ├── unit/test_config.py
    ├── unit/test_file_types.py
    ├── unit/test_managed_storage.py
    ├── integration/test_documents_repository.py
    ├── api/test_health.py
    └── api/test_documents_api.py
frontend/
├── package.json
├── vite.config.ts
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── api/documents.ts
│   ├── types/documents.ts
│   └── features/documents/
│       ├── DocumentLibrary.vue
│       ├── UploadQueue.vue
│       └── DocumentTable.vue
└── src/features/documents/__tests__/
    ├── UploadQueue.test.ts
    └── DocumentLibrary.test.ts
docker-compose.yml                         PostgreSQL + pgvector only
.env.example                               Non-secret local defaults
.gitignore                                 Generated data and local environments
scripts/setup.sh                           Install and initialize local dependencies
scripts/start.sh                           Start database, API, and frontend
scripts/stop.sh                            Stop local processes and database
README.md                                  Phase-one operating instructions
```

### Task 1: Backend foundation and deterministic configuration

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Create: `backend/tests/unit/test_config.py`
- Create: `backend/tests/api/test_health.py`
- Create: `.env.example`

**Interfaces:**
- Produces: `Settings` with `library_root: Path`, `database_url: str`, `max_upload_bytes: int`, and `bind_host: str`.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_settings_uses_mac_application_support(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.library_root == tmp_path / "Library/Application Support/CompanySearch"
    assert settings.max_upload_bytes == 209_715_200
    assert settings.bind_host == "127.0.0.1"
```

- [ ] **Step 2: Run the configuration test and verify failure**

Run: `cd backend && python -m pytest tests/unit/test_config.py -q`

Expected: FAIL because `app.config.Settings` does not exist.

- [ ] **Step 3: Implement settings and the application factory**

Use `pydantic-settings`; derive the default library root from `Path.home()`, expose only explicit configuration fields, and create `files/originals`, `files/quarantine`, `temp`, `logs`, `models`, and `backups` during application startup.

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://company_search:company_search@127.0.0.1:54329/company_search"
    library_root: Path = Field(default_factory=lambda: Path.home() / "Library/Application Support/CompanySearch")
    max_upload_bytes: int = 209_715_200
    bind_host: str = "127.0.0.1"
```

- [ ] **Step 4: Write and pass the health endpoint test**

```python
def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Run: `cd backend && python -m pytest tests/unit/test_config.py tests/api/test_health.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the backend foundation**

```bash
git add backend/pyproject.toml backend/app backend/tests .env.example
git commit -m "feat: scaffold local document service"
```

### Task 2: PostgreSQL schema and migration

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_documents.py`
- Create: `backend/app/db.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/document.py`
- Create: `backend/app/models/processing_job.py`
- Create: `backend/tests/integration/test_documents_repository.py`

**Interfaces:**
- Produces: `DocumentStatus` values `PENDING`, `DELETING`, and `DELETED` for this phase.
- Produces: `JobStatus.QUEUED` and `JobType.PARSE`.
- Produces: `get_session() -> Iterator[Session]` FastAPI dependency.

- [ ] **Step 1: Define a failing persistence test**

```python
def test_document_and_parse_job_are_persisted_together(db_session):
    document = Document(
        original_name="制度.pdf", stored_path="files/originals/2026/09/abc.pdf",
        extension="pdf", mime_type="application/pdf", size_bytes=10,
        sha256="a" * 64, status=DocumentStatus.PENDING,
    )
    document.jobs.append(ProcessingJob(job_type=JobType.PARSE, status=JobStatus.QUEUED))
    db_session.add(document)
    db_session.commit()
    assert db_session.scalar(select(Document).where(Document.sha256 == "a" * 64)).jobs[0].job_type is JobType.PARSE
```

- [ ] **Step 2: Start PostgreSQL and verify the test fails**

Run: `docker compose up -d db && cd backend && alembic upgrade head && python -m pytest tests/integration/test_documents_repository.py -q`

Expected: FAIL because the ORM models and migration do not exist.

- [ ] **Step 3: Implement models and migration**

The migration must enable `vector`, create UUID primary keys, use timezone-aware timestamps, enforce `size_bytes >= 0`, add a unique index on `documents.sha256`, and cascade jobs when a document is deleted. Store enum values as uppercase strings.

- [ ] **Step 4: Recreate the test database and pass the persistence test**

Run: `docker compose down -v && docker compose up -d db && cd backend && alembic upgrade head && python -m pytest tests/integration/test_documents_repository.py -q`

Expected: PASS and migration reaches head.

- [ ] **Step 5: Commit schema and persistence**

```bash
git add docker-compose.yml backend/alembic.ini backend/migrations backend/app/db.py backend/app/models backend/tests/integration
git commit -m "feat: add document metadata schema"
```

### Task 3: File-type validation and managed storage

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/file_types.py`
- Create: `backend/app/services/managed_storage.py`
- Create: `backend/app/errors.py`
- Create: `backend/tests/unit/test_file_types.py`
- Create: `backend/tests/unit/test_managed_storage.py`

**Interfaces:**
- Produces: `detect_allowed_type(path: Path, original_name: str) -> DetectedFileType`.
- Produces: `ManagedStorage.stage(stream: BinaryIO, original_name: str) -> StagedFile`.
- Produces: `ManagedStorage.promote(staged: StagedFile, document_id: UUID) -> str`, returning a relative path.
- Produces: `ManagedStorage.discard(staged: StagedFile) -> None` and `delete(relative_path: str) -> None`.

- [ ] **Step 1: Write parameterized failing signature tests**

```python
@pytest.mark.parametrize(("name", "header", "expected"), [
    ("a.pdf", b"%PDF-1.7", "application/pdf"),
    ("a.png", b"\x89PNG\r\n\x1a\n", "image/png"),
    ("a.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"),
])
def test_detect_allowed_signatures(tmp_path, name, header, expected):
    path = tmp_path / name
    path.write_bytes(header + b"payload")
    assert detect_allowed_type(path, name).mime_type == expected

def test_rejects_mismatched_extension(tmp_path):
    path = tmp_path / "malware.pdf"
    path.write_bytes(b"MZ" + b"payload")
    with pytest.raises(UnsupportedFileType):
        detect_allowed_type(path, path.name)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd backend && python -m pytest tests/unit/test_file_types.py -q`

Expected: FAIL because detection is undefined.

- [ ] **Step 3: Implement explicit allow-list validation**

Use `python-magic` for MIME detection plus container inspection for OOXML ZIP packages. DOCX must contain `word/`, XLSX `xl/`, and PPTX `ppt/`. TXT, Markdown, and CSV must decode as text and contain no NUL bytes. Never extract OOXML members during validation.

- [ ] **Step 4: Write failing streaming-storage tests**

```python
def test_stage_hashes_in_chunks_and_enforces_limit(storage):
    staged = storage.stage(BytesIO(b"abcdef"), "notes.txt")
    assert staged.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert staged.size_bytes == 6
    assert staged.temp_path.exists()

def test_stage_removes_partial_file_when_limit_exceeded(tiny_storage):
    with pytest.raises(UploadTooLarge):
        tiny_storage.stage(BytesIO(b"12345"), "notes.txt")
    assert list(tiny_storage.temp_root.iterdir()) == []
```

- [ ] **Step 5: Implement streaming stage, atomic promotion, and safe deletion**

Read fixed 1 MiB chunks, update SHA-256 and byte count per chunk, call `flush()` and `os.fsync()`, then use `os.replace()` to promote onto the same filesystem. Resolve every stored path below `library_root` before deletion and reject traversal.

- [ ] **Step 6: Run storage unit tests**

Run: `cd backend && python -m pytest tests/unit/test_file_types.py tests/unit/test_managed_storage.py -q`

Expected: PASS.

- [ ] **Step 7: Commit storage primitives**

```bash
git add backend/app/services backend/app/errors.py backend/tests/unit
git commit -m "feat: add safe managed file storage"
```

### Task 4: Transactional upload API and duplicate detection

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/documents.py`
- Create: `backend/app/services/documents.py`
- Create: `backend/app/api/documents.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_documents_api.py`

**Interfaces:**
- Produces: `DocumentService.upload(file: UploadFile) -> Document`.
- Produces: `POST /api/documents/upload`, multipart field name `file`.
- Error shape: `{"error":{"code":str,"message":str,"details":object|null}}`.

- [ ] **Step 1: Write the failing successful-upload API test**

```python
def test_upload_persists_file_document_and_job(client, library_root, db_session):
    response = client.post("/api/documents/upload", files={"file": ("制度.txt", b"hello", "text/plain")})
    assert response.status_code == 201
    body = response.json()
    assert body["original_name"] == "制度.txt"
    assert body["status"] == "PENDING"
    document = db_session.get(Document, UUID(body["id"]))
    assert (library_root / document.stored_path).read_bytes() == b"hello"
    assert document.jobs[0].job_type is JobType.PARSE
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd backend && python -m pytest tests/api/test_documents_api.py::test_upload_persists_file_document_and_job -q`

Expected: FAIL with 404 for the missing endpoint.

- [ ] **Step 3: Implement the upload transaction**

Stage and validate first; check SHA-256; generate a UUID; promote the file; create `Document` and `ProcessingJob` in one DB transaction. If DB commit fails after promotion, delete the promoted file. Always discard the staged file in `finally`.

- [ ] **Step 4: Add duplicate and invalid-upload tests**

```python
def test_duplicate_returns_existing_document(client):
    first = client.post("/api/documents/upload", files={"file": ("a.txt", b"same", "text/plain")})
    second = client.post("/api/documents/upload", files={"file": ("b.txt", b"same", "text/plain")})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_DOCUMENT"
    assert second.json()["error"]["details"]["document_id"] == first.json()["id"]

def test_executable_disguised_as_pdf_is_rejected(client):
    response = client.post("/api/documents/upload", files={"file": ("bad.pdf", b"MZpayload", "application/pdf")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
```

- [ ] **Step 5: Pass all upload tests**

Run: `cd backend && python -m pytest tests/api/test_documents_api.py -q`

Expected: PASS for success, duplicate, size limit, empty file, and invalid type cases.

- [ ] **Step 6: Commit upload API**

```bash
git add backend/app/schemas backend/app/services/documents.py backend/app/api/documents.py backend/app/main.py backend/tests/api/test_documents_api.py
git commit -m "feat: add transactional document uploads"
```

### Task 5: List, inspect, download, and delete APIs

**Files:**
- Modify: `backend/app/schemas/documents.py`
- Modify: `backend/app/services/documents.py`
- Modify: `backend/app/api/documents.py`
- Modify: `backend/tests/api/test_documents_api.py`

**Interfaces:**
- Produces: `GET /api/documents?query=&extension=&status=&page=1&page_size=25`.
- Produces: `GET /api/documents/{id}` and `GET /api/documents/{id}/download`.
- Produces: `DELETE /api/documents/{id}` returning HTTP 204.

- [ ] **Step 1: Write failing list and detail tests**

```python
def test_list_documents_filters_by_name_and_extension(client, uploaded_documents):
    response = client.get("/api/documents", params={"query": "差旅", "extension": "pdf"})
    assert response.status_code == 200
    assert [item["original_name"] for item in response.json()["items"]] == ["差旅制度.pdf"]

def test_document_detail_does_not_expose_absolute_path(client, uploaded_document):
    body = client.get(f"/api/documents/{uploaded_document.id}").json()
    assert "stored_path" not in body
```

- [ ] **Step 2: Implement paginated list and detail**

Order by `created_at DESC, id DESC`; cap `page_size` at 100; escape user text and use parameterized SQLAlchemy expressions. API schemas must never expose absolute or relative internal storage paths.

- [ ] **Step 3: Write failing download and deletion tests**

```python
def test_download_preserves_unicode_filename(client, uploaded_document):
    response = client.get(f"/api/documents/{uploaded_document.id}/download")
    assert response.status_code == 200
    assert "filename*=UTF-8''" in response.headers["content-disposition"]

def test_delete_removes_metadata_jobs_and_file(client, uploaded_document, library_root, db_session):
    path = library_root / uploaded_document.stored_path
    response = client.delete(f"/api/documents/{uploaded_document.id}")
    assert response.status_code == 204
    assert not path.exists()
    assert db_session.get(Document, uploaded_document.id) is None
```

- [ ] **Step 4: Implement safe download and deletion consistency**

Set `DELETING`, commit so the item is hidden, delete the managed file, then delete the database row and cascade jobs. If file deletion fails, retain `DELETING` with an error for retry; never restore it to active results.

- [ ] **Step 5: Run the complete backend suite**

Run: `cd backend && python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit document management APIs**

```bash
git add backend/app/schemas/documents.py backend/app/services/documents.py backend/app/api/documents.py backend/tests/api/test_documents_api.py
git commit -m "feat: add document library operations"
```

### Task 6: Vue document library interface

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api/documents.ts`
- Create: `frontend/src/types/documents.ts`
- Create: `frontend/src/features/documents/DocumentLibrary.vue`
- Create: `frontend/src/features/documents/UploadQueue.vue`
- Create: `frontend/src/features/documents/DocumentTable.vue`
- Create: `frontend/src/features/documents/__tests__/UploadQueue.test.ts`
- Create: `frontend/src/features/documents/__tests__/DocumentLibrary.test.ts`

**Interfaces:**
- Consumes: document upload, list, detail, download, and delete endpoints from Tasks 4–5.
- Produces: one local document-management page with accessible upload and table controls.

- [ ] **Step 1: Write a failing upload queue component test**

```typescript
it('uploads selected files and reports each result', async () => {
  const upload = vi.fn().mockResolvedValue({ id: '1', original_name: '制度.pdf', status: 'PENDING' })
  const wrapper = mount(UploadQueue, { props: { upload } })
  const file = new File(['%PDF-1.7'], '制度.pdf', { type: 'application/pdf' })
  await wrapper.get('input[type=file]').trigger('change', { target: { files: [file] } })
  await flushPromises()
  expect(upload).toHaveBeenCalledWith(file, expect.any(Function))
  expect(wrapper.text()).toContain('制度.pdf')
  expect(wrapper.text()).toContain('等待处理')
})
```

- [ ] **Step 2: Scaffold Vue and verify failure**

Run: `cd frontend && npm install && npm test -- --run`

Expected: FAIL because the components are missing.

- [ ] **Step 3: Implement the typed API client and upload queue**

Use `XMLHttpRequest` only for multipart upload progress; use `fetch` for other requests. Queue selected files and upload no more than two concurrently. Render progress, success, duplicate, unsupported-type, and failure states as text, not color alone.

- [ ] **Step 4: Write a failing library interaction test**

```typescript
it('refreshes the list after upload and confirms deletion', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const wrapper = mount(DocumentLibrary, { global: { stubs: { UploadQueue: true } } })
  await flushPromises()
  await wrapper.get('[data-test=delete-document]').trigger('click')
  expect(window.confirm).toHaveBeenCalled()
  expect(api.deleteDocument).toHaveBeenCalled()
  expect(api.listDocuments).toHaveBeenCalledTimes(2)
})
```

- [ ] **Step 5: Implement the library and table**

Include click/drag upload, filename search, type/status filters, pagination, explicit processing-state text, download links, and delete confirmation. Keep the UI responsive down to 320 px and preserve native keyboard focus behavior.

- [ ] **Step 6: Pass frontend tests and production build**

Run: `cd frontend && npm test -- --run && npm run build`

Expected: all Vitest tests PASS and Vite produces `dist/`.

- [ ] **Step 7: Commit the interface**

```bash
git add frontend
git commit -m "feat: add local document library interface"
```

### Task 7: Setup scripts, end-to-end smoke test, and operating guide

**Files:**
- Create: `scripts/setup.sh`
- Create: `scripts/start.sh`
- Create: `scripts/stop.sh`
- Create: `scripts/smoke-test.sh`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces: idempotent setup and lifecycle commands documented in the spec.
- Consumes: backend health and document endpoints plus frontend production build.

- [ ] **Step 1: Write the smoke test before lifecycle scripts**

`scripts/smoke-test.sh` must create its sample with `mktemp`, upload it, verify the returned status is `PENDING`, list it, download and byte-compare it, delete it, and verify a subsequent detail request returns 404. It must trap cleanup without touching any broad directory.

- [ ] **Step 2: Run the smoke test and verify failure**

Run: `bash scripts/smoke-test.sh`

Expected: FAIL because setup/start scripts and services are not available.

- [ ] **Step 3: Implement idempotent lifecycle scripts**

`setup.sh` verifies macOS, Python 3.12, Node, Docker, and available disk; creates a backend virtual environment; installs locked dependencies; installs frontend packages; starts the database; runs migrations; and downloads no OCR or Embedding model in phase one. `start.sh` binds API to `127.0.0.1`, starts Vite on loopback, writes PID files under the application data directory, and refuses duplicate starts. `stop.sh` terminates only validated PIDs created by `start.sh` and runs `docker compose stop db`.

- [ ] **Step 4: Document exact local operation**

README must contain prerequisites, `./scripts/setup.sh`, `./scripts/start.sh`, the local URL, `./scripts/stop.sh`, test commands, supported formats, the 200 MiB limit, data directory, backup warning, and a statement that files are not yet parsed or searchable in phase one.

- [ ] **Step 5: Run full verification**

Run:

```bash
cd backend && python -m pytest -q
cd ../frontend && npm test -- --run && npm run build
cd .. && bash scripts/start.sh && bash scripts/smoke-test.sh && bash scripts/stop.sh
git diff --check
```

Expected: backend and frontend tests PASS, build succeeds, smoke test completes all upload/list/download/delete checks, services stop cleanly, and `git diff --check` prints nothing.

- [ ] **Step 6: Commit phase-one operations**

```bash
git add scripts .gitignore README.md
git commit -m "docs: add local setup and smoke verification"
```

## Phase-One Completion Gate

Phase one is complete only when a fresh Mac-local setup can upload every allowed container type used by the API fixtures, reject mismatched or oversized files, report duplicates, persist metadata and a queued parse job, list and inspect documents, download identical bytes, delete consistently, and pass all backend, frontend, migration, build, and smoke checks.

After this gate, write a separate phase-two implementation plan for parsing, OCR, and chunking against the same specification. Do not add those features opportunistically to phase one.
