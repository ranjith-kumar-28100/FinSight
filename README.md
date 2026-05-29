# FinSight — Personal Finance Intelligence

A production-ready personal finance app that turns your bank and wallet
statements into precise, queryable insights — with hybrid RAG chat on top.

- **Source of truth:** the HDFC statement is the single source of truth for every
  total. GPay / Paytm rows are kept for traceability and used purely to enrich
  cryptic UPI merchant names on the bank side.
- **LangGraph pipeline:** ingest → reconcile → categorise → recurring →
  analytics → anomalies, with a validate step that asserts monthly totals match
  the bank debit total.
- **Hybrid RAG chat:** Qdrant in-memory store with dense vectors from Azure
  `text-embedding-3-small` and sparse BM25 vectors via FastEmbed, fused with
  RRF. The chat agent uses tool-calling for hard numbers and search for fuzzy
  semantic questions.
- **Production architecture:** FastAPI backend exposes the full feature set as
  a REST API; a Vite + React + TypeScript + Tailwind frontend ships a modern,
  finance-themed dark UI.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                React + Vite (frontend/)                      │
│  Dashboard · Transactions · Insights · Monthly Map           │
│  Recurring · Forecast · Goals · Anomalies · Chat · Upload    │
└──────────────────────────────────────────────────────────────┘
                          ▲  REST  ▼
┌──────────────────────────────────────────────────────────────┐
│                FastAPI (backend/)                            │
│  /api/upload · /api/transactions · /api/analytics            │
│  /api/recurring · /api/forecast · /api/goals · /api/chat …   │
└──────────────────────────────────────────────────────────────┘
                          ▲       ▼
┌──────────────────────────────────────────────────────────────┐
│                LangGraph pipeline (src/agents/)              │
│  ingest → reconcile → categorise → recurring →               │
│  analytics → anomalies                                       │
└──────────────────────────────────────────────────────────────┘
                          ▲       ▼
┌──────────────────────────────────────────────────────────────┐
│        SQLite (data/finance.db)  ·  Qdrant in-memory RAG     │
└──────────────────────────────────────────────────────────────┘
```

## Setup

### 1. Conda env + Python deps

```bash
conda env create -f environment.yml  # or: conda env update -f environment.yml --prune
conda activate genai
pip install -e .                     # installs the new fastapi + uvicorn etc.
```

### 2. Configure environment

Edit `.env`:

```
AZURE_OPENAI_ENDPOINT="https://<your>.openai.azure.com/"
AZURE_OPENAI_API_KEY="..."
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT_CATEGORISATION=gpt-4o
AZURE_OPENAI_DEPLOYMENT_REASONING=gpt-4o
AZURE_OPENAI_DEPLOYMENT_EMBEDDING=text-embedding-3-small
```

### 3. Frontend deps

```bash
cd frontend
npm install      # ~1 min
cd ..
```

## Running

The easiest way to start both the API and the frontend concurrently is using the provided script:

```bash
./scripts/dev.sh
```

Alternatively, you can run them in two separate terminals (or via `tmux` / `concurrently`):

```bash
# Terminal 1 — API
conda activate genai
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — Frontend
cd frontend
npm run dev      # http://127.0.0.1:5173
```

Open <http://127.0.0.1:5173> — the Vite dev server proxies `/api/*` to
the FastAPI backend. The OpenAPI explorer is at
<http://127.0.0.1:8000/docs>.

## Production build

```bash
cd frontend
npm run build    # outputs to frontend/dist
```

Serve `frontend/dist` from any static host (nginx, S3+CloudFront, Vercel, etc.)
and point its `/api/*` path at your FastAPI process (uvicorn behind a reverse
proxy, or `gunicorn -k uvicorn.workers.UvicornWorker`).

`FINSIGHT_CORS_ORIGINS` (env var on the API) restricts allowed origins —
defaults to `http://localhost:5173,http://127.0.0.1:5173`.

## Tests

```bash
# Backend
pytest tests/

# Frontend
cd frontend && npm test
```

Tests cover the FastAPI routers, the domain modules (repository, RAG,
reconciliation, categorisation, analytics), and the React components +
utilities.

## Project Structure

```
backend/                     # FastAPI app (NEW)
  main.py                    # CORS, routers, lifespan
  dependencies.py            # Singleton config / repo / chat agent
  schemas.py                 # Pydantic request/response models
  routers/                   # One module per resource                        # Domain code (shared with Streamlit + API)
  agents/
    orchestrator.py          # LangGraph pipeline graph
    ingestion.py             # HDFC / Paytm / GPay parsers
    reconciliation.py        # Bank-driven matching + enrichment write-back
    categorisation.py        # Rules + LLM fallback
    recurring.py             # Cadence / fixed-amount clustering
    analytics.py             # Monthly maps (persisted + on-the-fly)
    forecast.py              # Savings forecast with confidence band
    goal.py                  # Goal assessment + what-if
    anomaly.py               # IQR / first-time / spike rules
    chat.py                  # LangChain tool-calling agent
  db/                        # SQLite schema + parameterised repository
  llm/                       # Azure OpenAI provider (chat + embeddings)
  rag/                       # Qdrant in-memory hybrid index
frontend/                    # React + Vite + TS + Tailwind (NEW)
  src/
    pages/                   # One per route
    components/              # Layout, Cards, KPI, charts
    api/                     # Typed REST client

data/                        # finance.db + uploaded statements
```
