# NoManual

**Stop reading manuals. Just ask.**

NoManual is a lightweight app that turns long, unreadable product user guides into
a conversation. Instead of digging through a 120-page PDF, you ask a question in
plain language and get the answer straight from the official documentation.

> *"How do I program this air conditioner?"*
> *"How do I set a delayed start on the washing machine?"*
> *"How do I tune the channels on this TV?"*

---

## The problem

Every appliance ships with a manual nobody reads. They are long, badly organised,
often only available as a scanned PDF, and usually lost within a week of buying
the product. When something goes wrong, users end up on forums, random YouTube
videos, or calling support — and manufacturers end up paying for support calls
that the manual already answered.

## The goal

NoManual sits between the two sides of that problem and serves both.

### For users and customers

- **Search a product** — find your appliance in the catalogue by brand and model.
- **Ask anything** — get direct, grounded answers with a reference back to the
  section of the manual the answer came from.
- **Bring your own manual** — if your product isn't in the database yet, upload
  its PDF and ask questions about it right away. That manual then helps the next
  person with the same appliance.

### For manufacturers

- **Publish official documentation** — upload official manuals, user guides and
  updates so customers get correct, up-to-date answers instead of guesses from
  third-party sources.
- **See what customers actually ask** — every question asked about your products
  becomes insight: which features confuse people, which steps generate the most
  support load, which models get the most queries.
- **Close the loop** — use that feedback to improve documentation, product design
  and support content.

The long-term goal is a shared, growing knowledge base of product documentation
that is useful to consult, contributed to by both the people who build the
products and the people who use them.

---

## How it works

1. A manual (uploaded by a user or published by a manufacturer) is ingested and
   split into searchable chunks.
2. Those chunks are embedded and stored in a vector database.
3. When a question comes in, the most relevant passages are retrieved and passed
   to an LLM, which answers using only that source material.
4. The question, the product it referred to and the quality of the answer are
   logged, feeding the manufacturer analytics.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| API | FastAPI, Pydantic |
| AI / RAG | LangChain, LangGraph, OpenAI |
| Observability | Langfuse |
| Database | PostgreSQL + pgvector, SQLAlchemy, Alembic |
| Background jobs | Celery + Redis (PDF ingestion) |
| Storage | S3 (manual files) |
| PDF parsing | pypdf |

## Project layout

```
src/nomanual/    Python backend (FastAPI, ingestion, RAG pipeline)
frontend/        Next.js web app
```

## Getting started

```bash
# Backend
uv sync
cp .env.example .env      # fill in your keys
uv run uvicorn nomanual.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Status

Early development. The scaffolding is in place; ingestion, retrieval and the
manufacturer dashboard are being built.
