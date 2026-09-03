# Local Document Processing Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn queued local documents into structured, inspectable text chunks using format-aware parsers and local Chinese-English OCR.

**Architecture:** A native macOS Python worker claims PostgreSQL jobs with row locking, dispatches files to isolated parsers, chunks normalized blocks, and atomically replaces document chunks. Tesseract is hidden behind an OCR interface so a later PaddleOCR adapter does not affect parsing or persistence.

**Tech Stack:** Python 3.12/3.13, SQLAlchemy 2, PyMuPDF, python-docx, openpyxl, python-pptx, Pillow, pytesseract, chardet, PostgreSQL 16

**Spec:** `docs/superpowers/specs/2026-09-03-local-document-search-design.md`

## Global Constraints

- Run parsing and OCR locally; never send content to an external service.
- Process one job at a time on the M3 Pro to limit memory pressure.
- Do not execute macros, formulas, scripts, or external links.
- Preserve page, slide, sheet, row, section, and OCR-confidence provenance.
- A failed document must retain its original file and expose a stable user-facing error.
- Phase two ends at `PARSED`; Embedding, indexing, and search remain phase three.

### Task 1: Processing schema and states

**Files:** update document/job models and schemas; add `document_chunks`; add Alembic migration `0002_processing.py`.

- [ ] Add document states `PARSING`, `CHUNKING`, `PARSED`, `PARSE_FAILED`, `OCR_FAILED`.
- [ ] Add job states `RUNNING`, `SUCCEEDED`, `FAILED` and attempt/timestamp transitions.
- [ ] Add provenance-complete `document_chunks` table with cascade deletion.
- [ ] Expose chunk count and processing information without storage paths.

### Task 2: Parser contracts and format adapters

**Files:** create `app/parsers/base.py`, `text.py`, `pdf.py`, `docx.py`, `spreadsheet.py`, `presentation.py`, `image.py`, and `registry.py`.

- [ ] Define `ParsedBlock` and `DocumentParser.parse(path) -> list[ParsedBlock]`.
- [ ] Parse TXT/Markdown with UTF-8/GB18030 detection and heading context.
- [ ] Parse CSV/XLSX with sheet, header, and row provenance in read-only/data-only mode.
- [ ] Parse DOCX headings, paragraphs, and tables without embedded-image OCR.
- [ ] Parse PPTX text, tables, and notes by slide.
- [ ] Parse PDF per page; use extracted text when valid and OCR otherwise.
- [ ] Parse PNG/JPG with OCR and confidence.

### Task 3: OCR and chunking

**Files:** create `app/ocr/base.py`, `app/ocr/tesseract.py`, `app/services/chunking.py`, and text normalization helpers.

- [ ] Configure Tesseract for Simplified Chinese plus English and return ordered lines with confidence.
- [ ] Normalize whitespace and control characters without changing meaningful punctuation.
- [ ] Chunk narrative text at paragraph/sentence boundaries with 400–800 target, 1,200 maximum, and 100-character overlap.
- [ ] Keep spreadsheet records with headers and keep slide/page provenance intact.

### Task 4: Worker and reprocessing APIs

**Files:** create `app/worker.py` and `app/services/processing.py`; extend document APIs.

- [ ] Claim the oldest queued job with `FOR UPDATE SKIP LOCKED`.
- [ ] Persist state transitions and replace all chunks in one transaction.
- [ ] Convert encrypted/corrupt/empty/OCR failures into stable error codes.
- [ ] Recover abandoned running jobs after a configurable timeout.
- [ ] Add content pagination, job status, and manual reprocess endpoints.

### Task 5: Detail UI and local lifecycle

**Files:** extend Vue document types/API/table; add document detail component; update setup/start/stop scripts and README.

- [ ] Show live states, errors, chunk counts, and retry action.
- [ ] Add a detail view with paginated chunks and provenance labels.
- [ ] Install parser libraries plus `tesseract` and `tesseract-lang` on macOS.
- [ ] Start and stop the worker with validated PID handling.
- [ ] Document that phase-two `PARSED` documents are ready for phase-three indexing but not yet searchable.

## Mac Verification Gate

After pulling the generated code, the user verifies setup and processing on representative TXT, Markdown, CSV, PDF, scanned PDF, DOCX, XLSX, PPTX, PNG, and JPG files. Evidence required: jobs leave `QUEUED`, parsed documents show chunks and correct provenance, failures show actionable messages, reprocessing replaces rather than duplicates chunks, and restart recovers queued work.
