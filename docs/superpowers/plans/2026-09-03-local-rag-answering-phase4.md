# Local and DeepSeek-Enhanced RAG Answering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add citation-grounded multi-turn RAG answers using local Ollama Qwen3 by default and optional DeepSeek enhancement with safe local fallback.

**Architecture:** A focused RAG orchestrator reuses the existing hybrid search service, converts at most six results into numbered evidence, asks an Ollama adapter for a local answer, and optionally asks an OpenAI-compatible DeepSeek adapter for the final merged answer. A FastAPI SSE endpoint streams stages, sources, answer deltas, warnings, and completion metadata to a session-only Vue chat page.

**Tech Stack:** Python 3.12/3.13, FastAPI, Pydantic, SQLAlchemy, HTTPX, Ollama Chat API, DeepSeek OpenAI-compatible Chat Completions API, Vue 3, TypeScript, Server-Sent Events over `fetch`.

**Spec:** `docs/superpowers/specs/2026-09-03-local-rag-answering-design.md`

## Global Constraints

- Default local endpoint is `http://127.0.0.1:11434` and default model is `qwen3:8b`.
- Every Ollama generation uses `keep_alive: 0` so model memory is released after the answer.
- DeepSeek defaults to `https://api.deepseek.com` and `deepseek-chat`; both are configurable.
- DeepSeek is called only when `use_deepseek=true` and a non-empty API Key exists.
- A missing or failed DeepSeek call must preserve the local answer and emit a visible warning.
- Chat history stays only in the current browser page and is limited to six turns.
- Every question performs fresh hybrid retrieval and supplies at most six source chunks.
- No internal source means no fabricated internal citation; DeepSeek general knowledge must be labeled as non-company knowledge.
- API Keys, full prompts, and source bodies must not be logged or returned as configuration.
- No live web search and no persistent chat history in this phase.
- Per user instruction, do not run server-side unit, frontend, database, Ollama, or DeepSeek tests; run syntax/static checks only and provide exact Mac validation steps.

---

### Task 1: Configuration and RAG contracts

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Create: `backend/app/schemas/answer.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `AnswerRequest`, `ConversationTurn`, `AnswerSource`, `AnswerWarning`, `KnowledgeScope`, and `AnswerProvider`.
- Produces settings for Ollama, DeepSeek, source limit, history limit, timeouts, and maximum context characters.

- [ ] **Step 1: Add HTTP client dependency**

Add `httpx>=0.28,<1` to backend dependencies. HTTPX is shared by the Ollama and DeepSeek adapters and supports streamed async responses.

- [ ] **Step 2: Add exact settings**

Add these fields to `Settings`:

```python
ollama_base_url: str = "http://127.0.0.1:11434"
ollama_model: str = "qwen3:8b"
ollama_keep_alive: int = 0
ollama_timeout_seconds: float = 180.0
deepseek_base_url: str = "https://api.deepseek.com"
deepseek_model: str = "deepseek-chat"
deepseek_api_key: str = ""
deepseek_timeout_seconds: float = 120.0
rag_source_limit: int = 6
rag_history_turns: int = 6
rag_max_context_chars: int = 18_000
```

- [ ] **Step 3: Define request and response contracts**

Define:

```python
class ConversationTurn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=12000)

class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    use_deepseek: bool = False
    history: list[ConversationTurn] = Field(default_factory=list, max_length=6)
    extension: str | None = Field(default=None, max_length=16)
    document_name: str | None = Field(default=None, max_length=200)
    created_from: date | None = None
    created_to: date | None = None

class KnowledgeScope(str, Enum):
    INTERNAL = "INTERNAL"
    INTERNAL_LIMITED = "INTERNAL_LIMITED"
    GENERAL = "GENERAL"
    NONE = "NONE"

class AnswerProvider(str, Enum):
    LOCAL = "LOCAL"
    DEEPSEEK = "DEEPSEEK"
```

`AnswerSource` mirrors search provenance and includes `citation_number`, `chunk_id`, `document_id`, `document_name`, `content`, page/slide/sheet/row fields, section path, and OCR confidence. `AnswerWarning` contains stable `code` and Chinese `message`.

- [ ] **Step 4: Add local-only example configuration**

Append all `COMPANY_SEARCH_OLLAMA_*`, `COMPANY_SEARCH_DEEPSEEK_*`, and `COMPANY_SEARCH_RAG_*` names to `.env.example`, keeping `COMPANY_SEARCH_DEEPSEEK_API_KEY=` empty.

- [ ] **Step 5: Run static validation and commit**

Run:

```bash
python3 -m compileall -q backend/app
git diff --check
```

Expected: both commands exit 0. Commit only Task 1 files with `feat: add rag configuration and contracts`.

---

### Task 2: Ollama and DeepSeek provider adapters

**Files:**
- Create: `backend/app/llm/__init__.py`
- Create: `backend/app/llm/base.py`
- Create: `backend/app/llm/ollama.py`
- Create: `backend/app/llm/deepseek.py`

**Interfaces:**
- Produces: `GenerationMessage(role: str, content: str)`.
- Produces: `OllamaClient.status() -> OllamaStatus` and `OllamaClient.stream(messages) -> AsyncIterator[str]`.
- Produces: `DeepSeekClient.configured -> bool` and `DeepSeekClient.stream(messages) -> AsyncIterator[str]`.
- Raises typed `LlmUnavailable`, `LlmTimeout`, `LlmRateLimited`, and `LlmAuthenticationFailed` exceptions without including secrets.

- [ ] **Step 1: Define provider-neutral messages and errors**

Keep provider inputs limited to a list of role/content messages. Error classes expose a stable code and safe Chinese message; they never retain response authorization headers or full request bodies.

- [ ] **Step 2: Implement Ollama status inspection**

Call `GET {base_url}/api/tags`, compare returned model names with `settings.ollama_model`, and return:

```python
OllamaStatus(reachable: bool, model: str, installed: bool)
```

Connection errors return `reachable=False`; they do not raise from the status endpoint.

- [ ] **Step 3: Implement streamed Ollama generation**

POST to `/api/chat` with:

```python
{
    "model": settings.ollama_model,
    "messages": [message.model_dump() for message in messages],
    "stream": True,
    "think": False,
    "keep_alive": settings.ollama_keep_alive,
    "options": {"temperature": 0.2},
}
```

Parse newline-delimited JSON and yield non-empty `message.content`. On normal completion, close the HTTP stream; `keep_alive: 0` instructs Ollama to unload the model.

- [ ] **Step 4: Implement DeepSeek configuration guard**

`configured` returns `bool(settings.deepseek_api_key.strip())`. `stream()` refuses to call the network when false and raises `LlmUnavailable("DEEPSEEK_NOT_CONFIGURED", ...)`.

- [ ] **Step 5: Implement streamed DeepSeek generation**

POST to `{base_url}/chat/completions` using Bearer authorization, the configured model, messages, `stream=true`, and temperature `0.2`. Parse `data:` lines, stop on `[DONE]`, and yield `choices[0].delta.content`. Map HTTP 401/403 to authentication failure, 429 to rate limited, timeouts to timeout, and remaining non-2xx responses to a safe unavailable error.

- [ ] **Step 6: Run static validation and commit**

Run `python3 -m compileall -q backend/app && git diff --check`. Expected: exit 0. Commit Task 2 with `feat: add ollama and deepseek adapters`.

---

### Task 3: Evidence selection and RAG orchestration

**Files:**
- Modify: `backend/app/services/search.py`
- Create: `backend/app/services/rag.py`

**Interfaces:**
- Consumes: `SearchService.search(SearchRequest) -> list[SearchResult]`.
- Consumes: both provider adapters from Task 2.
- Produces: `RagService.status() -> AnswerStatusResponse`.
- Produces: `RagService.stream(AnswerRequest) -> AsyncIterator[AnswerEvent]`.

- [ ] **Step 1: Add an internal search limit path**

Construct `SearchRequest` from the answer request with `limit=settings.rag_source_limit` and the same extension/name/date filters. Preserve the existing `0.55` vector similarity floor so RAG never receives the previously observed unrelated filler results.

- [ ] **Step 2: Convert results to numbered evidence**

Deduplicate by chunk ID, preserve RRF order, assign stable citation numbers starting at 1, and truncate cumulative content at `rag_max_context_chars`. Format prompt evidence as:

```text
[1] 文件：日报汇总.txt；位置：片段 1
<chunk content>
```

- [ ] **Step 3: Classify knowledge scope**

Use `NONE` when no source survives filtering. Use `INTERNAL` when at least one result is `keyword` or `hybrid`; use `INTERNAL_LIMITED` when all retained results are vector-only. `GENERAL` is selected only when there are no sources, DeepSeek was requested, and DeepSeek is configured and succeeds.

- [ ] **Step 4: Build local grounded prompt**

The system prompt must say: answer in Chinese, use only supplied company evidence for company claims, cite statements with provided `[n]`, never invent a citation, explicitly say when evidence is limited, and do not reveal hidden reasoning. Include no more than the configured six recent turns.

- [ ] **Step 5: Stream local answer**

Emit `stage: retrieving`, then `sources`, then `stage: local_generating`. Accumulate Ollama deltas while forwarding them as `delta` events with `provider=LOCAL`. If there are no sources and DeepSeek is off or unavailable, emit the deterministic NONE answer without calling Ollama.

- [ ] **Step 6: Implement DeepSeek merge and fallback**

When requested and configured, emit `stage: deepseek_enhancing` and give DeepSeek the question, evidence, local draft, citation rules, and knowledge-scope rules. Stream a replacement answer using a `replace` event before DeepSeek deltas. If there are no sources, ask for clearly labeled general knowledge without citations. On any DeepSeek exception, emit a warning and retain the complete local answer.

When requested but not configured, emit exactly:

```json
{"code":"DEEPSEEK_NOT_CONFIGURED","message":"尚未配置 DeepSeek API Key，本次使用本地模型回答。"}
```

- [ ] **Step 7: Emit completion metadata**

The final `done` event contains the provider actually shown, knowledge scope, whether DeepSeek was requested, whether it was used, and source count. Never report DeepSeek as used after fallback.

- [ ] **Step 8: Run static validation and commit**

Run `python3 -m compileall -q backend/app && git diff --check`. Expected: exit 0. Commit Task 3 with `feat: orchestrate grounded rag answers`.

---

### Task 4: FastAPI status and streaming endpoints

**Files:**
- Create: `backend/app/api/answer.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `RagService.status()` and `RagService.stream(request)`.
- Produces: `GET /api/answer/status` JSON and `POST /api/answer/stream` SSE.

- [ ] **Step 1: Add dependencies and status route**

Construct `RagService` from the request-scoped SQLAlchemy session and settings. The status response exposes only Ollama reachability, installed model name/status, and `deepseek_configured: bool`.

- [ ] **Step 2: Encode SSE events**

Serialize every event as compact UTF-8 JSON:

```python
def encode_sse(event: AnswerEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
```

Return `StreamingResponse(generator(), media_type="text/event-stream")` with `Cache-Control: no-cache` and `X-Accel-Buffering: no`.

- [ ] **Step 3: Handle cancellation and safe failures**

Check `await request.is_disconnected()` between yielded events. Convert typed LLM errors into safe `warning` or `error` events. Do not let an exception after headers are sent become an HTML or generic JSON response.

- [ ] **Step 4: Register router**

Include the answer router in `create_app()` after the search router. Existing health, documents, and search APIs remain unchanged.

- [ ] **Step 5: Run static validation and commit**

Run `python3 -m compileall -q backend/app && git diff --check`. Expected: exit 0. Commit Task 4 with `feat: expose streaming rag api`.

---

### Task 5: Vue session-only knowledge assistant

**Files:**
- Create: `frontend/src/types/answer.ts`
- Create: `frontend/src/api/answer.ts`
- Create: `frontend/src/features/answer/AnswerPage.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: answer status and SSE endpoints from Task 4.
- Produces: session-only chat UI with DeepSeek opt-in, streamed answer, warnings, status stages, and expandable citations.

- [ ] **Step 1: Define frontend contracts**

Mirror backend provider, scope, source, warning, status, and SSE event shapes. A message contains question, rendered answer text, sources, warnings, provider, scope, pending stage, and an `AbortController` owned by the active request only.

- [ ] **Step 2: Implement fetch-based SSE parser**

Use `fetch('/api/answer/stream', {method:'POST', ...})`, read `response.body` with `getReader()`, preserve incomplete chunks between reads, split events on blank lines, and dispatch parsed event/data pairs. Do not use `EventSource`, because the endpoint requires a POST body.

- [ ] **Step 3: Build the chat flow**

On submit, append the question, send at most six prior completed turns, and update the assistant card as events arrive. `replace` clears the local draft before DeepSeek deltas. `warning` remains visible beside the final answer. Disable duplicate submission while a response is active and provide a stop button that aborts the request.

- [ ] **Step 4: Build the DeepSeek switch behavior**

Default it to off. On first activation, show: “开启后，本次问题、检索到的内部资料片段和本地初稿将发送给 DeepSeek。” If status says not configured, keep the switch operable so the server-side fallback is exercised, but show the persistent configuration hint and never claim DeepSeek is active.

- [ ] **Step 5: Render source and scope distinctions**

Show `LOCAL` as“千问本地回答”, `DEEPSEEK` as“DeepSeek 增强”, `GENERAL` as“通用知识，不来自公司资料库”, and limited evidence as“内部资料依据有限”. Citation cards display `[n]`, filename, provenance, OCR confidence, and expandable source content.

- [ ] **Step 6: Add navigation and session clearing**

Extend the App page union to `'answer' | 'search' | 'library'`, make“知识问答”the default landing page, and add a clear-session button that only empties Vue memory. Do not add localStorage, IndexedDB, or server persistence.

- [ ] **Step 7: Add responsive styling**

Reuse the existing green/cream visual language. Keep messages readable at 320px width, stack controls on small screens, preserve keyboard focus states, and avoid intervals or rerender loops that could reintroduce page flashing.

- [ ] **Step 8: Run allowed static checks and commit**

Run `git diff --check`. Do not run frontend tests or the Vite build on the server per user instruction. Commit Task 5 with `feat: add local rag chat interface`.

---

### Task 6: Setup safeguards, documentation, and handoff

**Files:**
- Modify: `scripts/setup.sh`
- Create: `scripts/check-llm.sh`
- Modify: `README.md`

**Interfaces:**
- Produces a non-destructive Ollama readiness check and exact Mac configuration instructions.

- [ ] **Step 1: Keep setup isolated**

Do not install Ollama through pip or modify Conda environments. `setup.sh` may report whether `ollama` is present, but it must not automatically sign in, start cloud models, overwrite global Python, or delete any model.

- [ ] **Step 2: Add readiness script**

`scripts/check-llm.sh` checks, in order: `ollama` command exists, `http://127.0.0.1:11434/api/tags` responds, and `qwen3:8b` appears in `ollama list`. Each failure prints one exact remediation command; success prints the configured local model as ready.

- [ ] **Step 3: Document DeepSeek configuration**

Explain copying the Key only into `backend/.env`:

```env
COMPANY_SEARCH_DEEPSEEK_API_KEY=replace-with-local-secret
```

State that changing `.env` requires restarting the backend, the Key must never be committed, and the UI intentionally falls back to local Qwen when missing.

- [ ] **Step 4: Document all acceptance paths**

Provide Mac steps for: local cited answer, DeepSeek enhanced answer, missing-Key fallback, DeepSeek error fallback, no-internal-source local response, no-internal-source DeepSeek general answer, multi-turn follow-up, cancellation, and `ollama ps` memory release.

- [ ] **Step 5: Perform final permitted verification**

Run:

```bash
python3 -m compileall -q backend/app
bash -n scripts/setup.sh scripts/start.sh scripts/stop.sh scripts/check-llm.sh
git diff --check
git status --short
```

Expected: syntax commands exit 0; status lists only intended Phase 4 files. Do not claim runtime success until the user completes Mac validation.

- [ ] **Step 6: Commit documentation and safeguards**

Commit Task 6 with `docs: add phase 4 rag setup and validation guide`.

---

## Mac Validation Sequence

After pulling all Phase 4 commits:

```bash
conda activate company-search
./scripts/stop.sh
./scripts/setup.sh
./scripts/check-llm.sh
./scripts/start.sh
```

For DeepSeek, add the Key only to `backend/.env`, restart, and verify `GET /api/answer/status` reports `deepseek_configured: true`. Validate every acceptance path from Task 6 while monitoring `.run/backend.log`; never paste the Key into logs, screenshots, Git, or chat.
