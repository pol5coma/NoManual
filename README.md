# NoManual

**Stop reading manuals. Just ask.**

NoManual turns appliance manuals into a conversation. Pick your product, ask a
question in any language, and get an answer grounded in the official
documentation — with the pages it came from.

> *"¿Cómo programo el inicio diferido de la lavadora?"*
> *"What does error E4 mean on my fridge?"*

---

## Why

Every appliance ships with a manual nobody reads: 100+ pages, badly organised,
often split across a dozen languages, and lost within a week. When something
goes wrong, people end up on forums or calling support — and manufacturers pay
for support calls the manual already answered.

NoManual keeps the manual as the source of truth and makes it answer back.

## Features

- **Answers grounded in the manual.** Every answer cites the pages it is based
  on. If the manual doesn't cover the question, NoManual says so or escalates it
  — it does not guess.
- **Multilingual by design.** Manuals mix languages, and the most complete
  section is often not in the user's language. Questions are searched both as
  asked and translated to English, so a question in Spanish finds the answer in
  the English section, and the reply comes back in the user's language.
- **Product-aware.** Questions are scoped to one product and only search its
  manuals. One manual can cover a whole product family, so a single upload
  serves every model in it.
- **Bring your own manual.** Upload a PDF and it is processed in the background.
  Duplicate files are detected and linked to the new product instead of being
  processed twice.
- **Usable from any AI assistant.** NoManual exposes an MCP server, so Claude or
  any MCP client can search manuals and ask questions as tools.
- **Web app and REST API.** A React chat interface with manual upload, and a
  FastAPI backend for everything else.

---

## How it works

```
                 ┌──────────────┐     ┌──────────────┐
  React (Vite) ──▶   FastAPI    │◀────│  MCP server  │◀── Claude / MCP clients
                 │  /ask /search│     │   (/mcp/)    │
                 │  /manuals    │     └──────────────┘
                 └──────┬───────┘
          upload        │ question
            │           ▼
            │    ┌─────────────────── LangGraph workflow ───────────────────┐
            │    │ screen → route → retrieve → generate → verify ─┬─▶ answer │
            │    │            │                     ▲             │          │
            │    │            └─▶ small talk        └── retry ────┤          │
            │    │                refuse                          └─▶ escalate│
            │    └──────────────────────────┬───────────────────────────────┘
            ▼                               │ hybrid search, scoped to product
   ┌─────────────────┐              ┌───────▼────────────────────────┐
   │ Celery + Redis  │── chunks ───▶│ PostgreSQL + pgvector          │
   │ extract, clean, │  embeddings  │ tenants, products, manuals,    │
   │ chunk, embed    │              │ chunks (vector + tsvector),    │
   └─────────────────┘              │ query logs, escalations        │
                                    └────────────────────────────────┘
```

### 1. Ingestion

An uploaded PDF is queued and processed by a Celery worker:

- **Extraction** with PyMuPDF, followed by text cleaning and detection of
  garbled pages (scanned or badly encoded PDFs are rejected with a clear reason).
- **Language detection per page**, smoothed across neighbouring pages, since
  manuals switch language every few pages.
- **Chunking** with a recursive splitter, keeping the page and language of every
  chunk so answers can cite them.
- **Embedding** with OpenAI and storage in PostgreSQL, where each chunk has both
  a vector (pgvector, HNSW index) and a full-text index (tsvector, GIN).

Manuals are claimed with a conditional `UPDATE`, so concurrent requests can't
process the same file twice, and stalled jobs are reclaimed automatically. The
old chunks are replaced and the manual is marked ready in a single transaction.

### 2. Retrieval

- **Hybrid search.** Semantic search catches paraphrases ("the machine won't
  drain"); full-text search catches exact tokens such as error codes and button
  labels. Both run over the product's manuals only.
- **Multi-query.** The question is searched as asked and translated to English.
- **Reciprocal Rank Fusion** merges all result lists by rank, because cosine
  similarity and `ts_rank` live on scales that can't be compared directly.

### 3. Answering

A LangGraph **workflow** — not a free-running agent — handles every question:

1. **Screen** — cheap deterministic guardrails (length, prompt-injection
   patterns) before any model call.
2. **Route** — classify the intent (error code, how-to, safety, small talk,
   out of scope) and send it down the right path.
3. **Retrieve** — hybrid search, with a minimum relevance threshold.
4. **Generate** — structured output: the answer plus the chunks it cites.
5. **Verify** — a deterministic check that every citation points to a chunk
   that was actually retrieved. A failed check triggers one retry with feedback;
   a second failure escalates the question instead of returning a guess.

The steps are known in advance and every answer must be checked, so a fixed
graph is cheaper, more predictable and easier to test than an agent picking its
own tools.

### Why PostgreSQL for vectors

Retrieval is always filtered by tenant and product through joins, and chunks are
swapped in the same transaction that marks a manual ready. Keeping vectors next
to the relational data makes both trivial, with one database to run.

---

## Decisions backed by measurements

Design choices were tested on real manuals before being kept.

| Decision | Measurement |
| --- | --- |
| PyMuPDF over pdfplumber for extraction | 42 vs 374 glued words (0.1% vs 0.7%) on a 130-page manual, 1.5 s vs 85 s |
| Translate the query to English as a second search | +0.08 to +0.14 top similarity, Spanish questions over an English manual |
| No language filter on retrieval | Filtering by the user's language hid the English sections that held the answer |
| Scope retrieval to the selected product | Unanswerable questions correctly declined went from 1 in 3 to 3 in 3 |
| Judge sees the source text and scores coverage and invention separately | Identical verdicts across repeated runs |

---

## Evaluation

Answer quality is measured with a golden set of real questions per manual, each
labelled with the pages that hold the answer, the expected answer and its key
facts. It includes questions the manual **cannot** answer, because declining
correctly matters as much as answering.

Each run reports:

- **Recall@k by page** — did retrieval find the right pages?
- **Correctness, coverage and invention rate** — scored by an LLM judge that
  reads the source pages, so "incomplete" and "made up" are measured separately.
- **Abstention** — did it decline the questions it should decline?
- **Escalation rate and latency.**

Results are stored with the configuration that produced them (models, chunk
size, thresholds) and every run is compared against the previous one. The
judge's own consistency is checked separately.

```bash
uv run python -m nomanual.evals             # run the golden set
uv run python -m nomanual.evals --case ID   # a single case
uv run python -m nomanual.evals.validate    # judge consistency
```

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, TypeScript, Vite |
| API | FastAPI, Pydantic |
| AI orchestration | LangGraph, LangChain |
| Models | OpenAI chat models, `text-embedding-3-small` |
| Retrieval | pgvector (HNSW) + PostgreSQL full-text search, RRF |
| Database | PostgreSQL 17, SQLAlchemy 2.0 async, Alembic |
| Background jobs | Celery + Redis |
| PDF extraction | PyMuPDF |
| Interoperability | MCP (streamable HTTP) |

---

## Getting started

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker, Node 20+,
an OpenAI API key.

```bash
cp .env.example .env              # database, Redis and OpenAI settings
uv sync
docker compose up -d --wait       # PostgreSQL (pgvector) + Redis
uv run alembic upgrade head       # schema + public tenant

./run.sh                          # API on :8000 + Celery worker

cd frontend && npm install && npm run dev   # web app on http://localhost:5174
```

Connect Claude Code to the MCP server:

```bash
claude mcp add --transport http nomanual http://127.0.0.1:8000/mcp/
```

Run the tests:

```bash
uv run pytest
```

> `DEBUG_ENDPOINTS` enables extraction diagnostics. Keep it off outside local
> development.

---

## Project layout

```
backend/
  alembic/             migrations
  nomanual/
    api/               FastAPI routers
    agent/             LangGraph workflow, guardrails, prompts
    searching/         hybrid search, RRF, query translation
    ingestion/         extraction, chunking, embeddings, Celery tasks
    models/            SQLAlchemy models
    schemas/           Pydantic request/response models
    evals/             golden-set runner and LLM judge
    mcp_server.py      MCP tools over the same search and answer functions
evals/
  cases/               golden set (YAML)
  results/             eval runs (JSON)
frontend/              React + TypeScript + Vite
tests/
```

---

## Current scope and vision

Today NoManual runs as a **shared, public library**: anyone can upload a manual
under a single public tenant, and every upload helps the next person with the
same appliance.

The data model is multi-tenant from the start — tenants, API keys, and products
and manuals owned by a tenant — so the same system can grow into a product for
manufacturers:

- **Official documentation.** Manufacturers publish their own manuals and
  updates, so customers get correct answers instead of guesses from third-party
  sources.
- **Customer insight.** Every question is logged against a product. Aggregated,
  that shows which features confuse people, which models generate the most
  questions, and what the manual fails to answer.
- **Model-level precision.** When one manual covers a whole family, answers
  filtered to the exact model the user owns.
- **Closing the loop.** Escalated questions become input to improve the
  documentation, the product and support content.
