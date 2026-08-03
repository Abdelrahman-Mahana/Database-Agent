# 📊 Database Agent AI

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![LangChain](https://img.shields.io/badge/LangChain-0.2-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://www.langchain.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

An AI-powered **database analyst agent** that turns natural-language questions (English & Arabic) into safe, validated SQL, runs it, and returns an executive-style written report with charts — instead of a raw result grid. It inspects the target schema on the fly, so it isn't hard-coded to one database: point it at a SQLite, PostgreSQL, or MySQL/MariaDB database and start asking questions.

The system is split into a **FastAPI + LangChain backend** (the agent, SQL safety pipeline, analytics, and 20+ REST modules) and a **Next.js dashboard** (chat, schema explorer, connection manager, query execution & analytics views).

---

## Table of Contents

- [Key Features](#key-features)
- [How a Question Becomes an Answer](#how-a-question-becomes-an-answer)
- [Project Structure](#project-structure)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
  - [Option 1: Docker Compose (recommended)](#option-1-docker-compose-recommended)
  - [Option 2: Run locally](#option-2-run-locally)
- [Configuration](#configuration)
- [Connecting a Database](#connecting-a-database)
- [REST API Overview](#rest-api-overview)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security Notes](#security-notes)
- [License](#license)

---

## Key Features

**Conversational agent**
- Multi-turn memory per session (sliding window + TTL), so follow-ups like *"break that down by month"* resolve against the previous turn.
- Bilingual (Arabic/English) intent classification that routes questions to `database`, `schema`, or `off_topic` handling, with a graceful refusal for out-of-scope questions.
- Multi-step **plan-and-execute** decomposition for compound questions (e.g. "show monthly sales of the best-selling artist"), executing sub-queries and synthesizing one consolidated report.

**Schema-aware, database-agnostic SQL generation**
- No hard-coded example queries for any particular schema — SQL generation is grounded in the *actual* introspected schema, sample column values, and real min/max date ranges of the connected database.
- Self-consistency SQL voting (multiple candidates, majority vote) and bounded auto-repair on execution errors, with fuzzy table/column-name suggestions.
- An `UNANSWERABLE` sentinel path for questions the active schema genuinely can't answer, instead of hallucinated SQL.

**Safety-first execution**
- AST-level SQL validation (`sqlglot`) enforcing SELECT-only queries, dialect transpilation, and automatic `LIMIT` enforcement.
- Cost guard against unbounded full-table scans, and optional data masking for sensitive columns.
- Optional per-minute rate limiting.

**Reporting & analytics**
- Deterministic statistical analyzers (aggregations, outliers, distributions, correlations) feed an analyst-voice report writer — a direct answer followed by the 2–4 findings that matter, not a raw data dump.
- Automatic chart-type suggestion for the result set.
- A self-scoring **evaluation framework** (`app/evaluation`) grades every `/chat` request for SQL success, repair attempts, and estimated latency/cost, producing a `quality_score` / `confidence_score` per request — queryable via `GET /evaluation/stats` and `GET /evaluation/history` (see [Recently Connected](#recently-connected-the-evaluation-framework) below).

**Multi-database connectivity**
- Connect to SQLite, PostgreSQL, or MySQL/MariaDB by URL or by uploading a `.db`/`.sqlite` file, with connection profiles encrypted at rest and hot-swappable without restarting the API.

---

## How a Question Becomes an Answer

```
User question (AR/EN)
        │
        ▼
Intent Classification ──► off_topic → guided refusal
        │ database / schema
        ▼
Schema Grounding  (prune full schema to the relevant tables/columns)
        │
        ▼
Simple? ── Planner (multi-step decomposition for compound questions)
        │
        ▼
SQL Generation (self-consistency candidates) ──► AST Validation ──► Execute
        │                                              │
        │                                     on failure: Auto-Repair (bounded)
        ▼
Analytics Engine (stats, outliers) + Chart Suggestion
        │
        ▼
Report Synthesis (analyst-voice) ──► optional Verification pass
        │
        ▼
Evaluation Framework scores the request (quality / confidence)
        │
        ▼
ChatResponse → frontend
```

---

## Recently Connected: the Evaluation Framework

While reviewing the codebase we found a complete, well-tested **AI Evaluation Framework** (`backend/app/evaluation/`) — metrics collection, confidence/quality scoring, and telemetry — that existed in the code but was never wired into the app or exposed via the API. It's now connected:

- Every `POST /chat` call is scored automatically (best-effort, never blocks the response) and the score is attached to the response as `quality_score` / `confidence_score`.
- New endpoints expose the results: `GET /evaluation/history`, `GET /evaluation/stats`, `DELETE /evaluation/history`.

See [`app/api/evaluation.py`](backend/app/api/evaluation.py) and the updated [`app/api/chat.py`](backend/app/api/chat.py).

---

## Project Structure

```
Database-Agent-AI/
├── docker-compose.yml           # Dev stack (backend + frontend, live-mounted)
├── docker-compose.prod.yml      # Production stack (standalone images)
├── .gitignore
├── assets/                      # README screenshots (add dashboard.png here)
│
├── backend/                     # FastAPI + LangChain service
│   ├── app/
│   │   ├── main.py                  # FastAPI entry point, DI container, middleware
│   │   ├── agents/                  # AnalystAgent pipeline: intent → plan → SQL → repair
│   │   ├── ai_reasoning/            # LLM reasoning/explanation/confidence engines
│   │   ├── analytics/               # Deterministic stats & insight engines
│   │   ├── api/                     # One router module per REST resource (20+)
│   │   ├── config/ & core/          # Settings, DI container, structured logging
│   │   ├── context_builder/         # Prompt-context assembly & ranking
│   │   ├── conversation/            # Session memory service
│   │   ├── database/                # SQLAlchemy engine/session, seed helpers
│   │   ├── dialect/                 # Cross-dialect SQL transpilation
│   │   ├── evaluation/              # Request scoring framework (see above)
│   │   ├── execution/               # Safe query execution
│   │   ├── llm/                     # Provider clients (OpenAI/OpenRouter/Groq/Ollama) & prompts
│   │   ├── logical_query/           # Logical query IR
│   │   ├── orchestrator/            # LangGraph-based orchestration (feature-flagged)
│   │   ├── planning/                # Plan-and-execute decomposition
│   │   ├── plugins/                 # Plugin discovery system
│   │   ├── query_understanding/     # NL question parsing (entities/metrics/intent)
│   │   ├── result_processing/       # Result shaping & chart suggestion
│   │   ├── schema_catalog/          # Cached schema catalogs per connected DB
│   │   ├── schema_grounding/        # Prunes full schema to question-relevant subset
│   │   ├── schemas/                 # Pydantic request/response models
│   │   ├── security/                # Cost guard & data masking
│   │   ├── semantic/ & semantic_analysis/  # Deterministic question/column understanding
│   │   ├── services/                # Domain services (memory, reports, SQL, onboarding)
│   │   ├── sql/, sql_renderer/, sql_validation/  # SQL build → render → AST-validate pipeline
│   │   ├── telemetry/                # Structured logging setup
│   │   └── utils/                    # Caching, cost routing, token tracking, validators
│   ├── data/schema_catalog/         # Cached per-database schema catalogs (generated)
│   ├── eval/                        # Offline golden-dataset evaluation scripts
│   ├── scripts/                     # Manual dev utilities (not part of pytest)
│   ├── tests/                       # Pytest suite
│   ├── chinook.db                   # Packaged demo SQLite database (Chinook music store)
│   ├── .env.example                 # Copy to backend/.env and fill in
│   ├── Dockerfile / docker-compose.yml / railway.json
│   └── requirements.txt
│
└── frontend/                    # Next.js dashboard
    ├── src/
    │   ├── app/                     # Routes: chat, connect, explorer, execution, analytics, history, settings
    │   ├── components/              # UI components (schema explorer, layout, shared UI)
    │   ├── services/, store/, lib/, providers/, types/
    ├── Dockerfile / railway.json
    └── package.json
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI, dependency-injector (DI container), Uvicorn |
| Agent / LLM orchestration | LangChain, LangGraph (optional graph orchestrator) |
| LLM providers | OpenAI, OpenRouter, Groq, local Ollama |
| SQL safety | sqlglot (AST validation & dialect transpilation), sqlparse |
| Data layer | SQLAlchemy 2.x — SQLite, PostgreSQL (`psycopg2`), MySQL/MariaDB (`pymysql`) |
| Logging | structlog, loguru |
| Testing | pytest, pytest-asyncio |
| Frontend | Next.js 16, React, TypeScript, Tailwind, shadcn/ui, TanStack Query, Zustand, Recharts, Framer Motion |
| Packaging / deploy | Docker, Docker Compose, Railway |

---

## Getting Started

### Prerequisites
- Python 3.12+ and `pip` (or `uv`)
- Node.js 18+ and `npm`
- Docker & Docker Compose (optional, recommended)
- An API key for at least one LLM provider (OpenAI, OpenRouter, or Groq), or a local Ollama install

### Option 1: Docker Compose (recommended)

```bash
cp backend/.env.example backend/.env
# edit backend/.env and add your OPENAI_API_KEY (or configure Groq/OpenRouter/Ollama)

docker compose up --build
```

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:3000

### Option 2: Run locally

**Backend**
```bash
cd backend
cp .env.example .env        # then edit .env
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
(or, if you use `uv`: `make install && make run`, see `backend/Makefile`.)

**Frontend**
```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

The backend ships with `backend/chinook.db` (a sample music-store database) so you can start asking questions immediately with no setup.

---

## Configuration

All configuration is environment-variable driven — see [`backend/.env.example`](backend/.env.example) for the full list with defaults, including:

- `DATABASE_URL`, `LLM_PROVIDER` (`openai` | `openrouter` | `groq` | `ollama`) and per-provider keys/models
- SQL generation knobs: `SQL_CANDIDATES`, `ENABLE_SELF_CONSISTENCY`, `ENABLE_REPORT_VERIFICATION`
- Caching: `REDIS_URL` (optional; falls back to in-memory) and per-resource TTLs
- Memory: `MEMORY_WINDOW_SIZE`, `MEMORY_TTL_SECONDS`
- Safety: `ENABLE_COST_GUARD`, `COST_GUARD_MAX_UNFILTERED_ROWS`, `ENABLE_DATA_MASKING`, `ENABLE_RATE_LIMIT`

## Connecting a Database

Use the dashboard's **Connect** page, or call the API directly:

- `POST /connect/url` — connect via a database URL (SQLite/PostgreSQL/MySQL)
- `POST /connect/upload` — connect by uploading a `.db`/`.sqlite` file

Connections are stored as encrypted profiles and can be switched without restarting the service.

---

## REST API Overview

The full interactive reference is always available at `/docs` (Swagger) once the backend is running. Highlights:

| Endpoint | Purpose |
|---|---|
| `POST /chat` | Ask a natural-language question, get back SQL + results + report + chart suggestion + evaluation score |
| `GET /chat/history` / `DELETE /chat/history` | Session conversation history |
| `POST /connect/url` / `POST /connect/upload` | Connect a database |
| `GET /schema` | Full schema tree of the active database |
| `GET /database/*`, `/database/profile/*`, `/database/intelligence/*` | Discovery & profiling of the connected database |
| `GET /evaluation/history`, `GET /evaluation/stats` | Per-request quality/confidence scores and aggregates |
| `GET /stats`, `GET /health` | Usage/cost dashboard and health check |

Other routers (`/query`, `/planning`, `/logical-query`, `/dialect`, `/sql`, `/sql_validation`, `/execution`, `/results`, `/semantic-analysis`, `/context`, `/ai`, `/conversation`, `/agent`, `/memory`) expose the individual pipeline stages directly — useful for debugging or building alternative frontends against the same building blocks.

---

## Testing

```bash
cd backend
pytest tests/
```

Test suite covers the agent pipeline end-to-end, the REST API, memory TTL/windowing, the planner, schema grounding, semantic parsing, and the SQL build/validate/repair package. `backend/eval/` additionally holds an offline golden-dataset evaluation harness (`run_understanding_eval.py`, `compare_baseline.py`) separate from the runtime evaluation framework described above.

---

## Deployment

Both `backend/` and `frontend/` include `railway.json` for one-service-per-app deployment on Railway, and standalone `Dockerfile`s for any container platform. Use `docker-compose.prod.yml` for a self-contained two-container deployment (no bind mounts, DB baked into the image).

---

## Security Notes

- `backend/.env` and `backend/connection_profiles.json` (encrypted DB connection profiles) are git-ignored — never commit real credentials. A `connection_profiles.json` containing live encrypted profiles was found in this repo during cleanup and has been removed; rotate any credentials that were stored there before this point.
- `ENABLE_DATA_MASKING` and `ENABLE_COST_GUARD` are on by default — keep them enabled in any environment where the agent has access to a real production database.

---

## License

MIT — see [LICENSE](LICENSE).
