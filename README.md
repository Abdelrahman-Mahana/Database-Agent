# 📊 AI Database Analyst Agent

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.31-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![LangChain](https://img.shields.io/badge/LangChain-0.2.0-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://www.langchain.com/)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

An autonomous, enterprise-grade **AI Database Analyst Agent** designed to bridge the gap between non-technical stakeholders and complex relational databases. By converting natural-language queries into safe, multi-step executable SQL, the system automatically inspects database schemas, validates query safety at the AST level, executes analytics across multiple database engines (SQLite, PostgreSQL, MySQL/MariaDB), and generates fact-grounded executive reports accompanied by interactive visualizations.

Powered by multi-tier LLM orchestrations (**OpenRouter**, **Groq**, or local **Ollama**), built on **FastAPI** and **LangChain**, and presented through an executive-styled **Streamlit** dashboard featuring dual English and Arabic (RTL) typography.

![Database Analyst Agent Dashboard](assets/dashboard.png)

---

## Table of Contents

- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Project Directory Structure](#project-directory-structure)
- [Technology Stack](#technology-stack)
- [Environment Configuration](#environment-configuration)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Option 1: Docker Compose (Recommended)](#option-1-docker-compose-recommended)
  - [Option 2: Local Development (uv / pip)](#option-2-local-development-uv--pip)
- [Database Connection & Management](#database-connection--management)
- [REST API Reference](#rest-api-reference)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [Deployment](#deployment)
- [License](#license)

---

## Key Features

### 💬 Conversational Intelligence & Memory
- **Session-Based Sliding Window Memory**: Retains multi-turn conversation context (`MEMORY_WINDOW_SIZE`, default 5 turns) with automatic TTL eviction (`MEMORY_TTL_SECONDS`). Resolves ambiguous follow-up requests like *"break that down by month"* or *"filter out the US customers"* seamlessly.
- **Context-Aware Intent Routing**: Employs a fast-model intent classifier that evaluates user queries against current conversation history, categorizing input into `database`, `schema`, or `off_topic`.
- **Guided Off-Topic Refusal**: Gracefully handles out-of-scope prompts by analyzing actual database tables and providing helpful recommendations of questions the agent *can* answer.
- **Session Lifecycle Management**: Session history can be dynamically cleared on demand via `DELETE /chat/history?session_id=<id>`.

### 🧩 Advanced Agent Architecture
- **Offline Schema Exploration Routing**: Intercepts schema metadata queries (e.g., *"list all tables"*, *"describe table Customers"*, *"what are foreign keys for Invoices"*) and answers instantly from a local cache without invoking LLM tokens.
- **Dynamic Schema Grounding Engine**: Filters and extracts minimal relevant table sub-schemas (`SchemaGroundingEngine`) using a `SemanticQueryParser` to prevent context window bloat and reduce token usage. For schemas with 30+ tables where no table can be confidently matched to the question, falls back to the most FK-central tables (by join-graph degree) instead of dumping the entire schema into the prompt.
- **Database-Agnostic (Zero-Shot) SQL Generation**: SQL is generated with no hardcoded example queries tied to any specific schema - relying instead on a strong schema description plus real sample column values and date ranges (see below), so accuracy doesn't depend on how closely a new database resembles the original demo schema.
- **Schema-Grounded Value & Date Awareness**: Text columns are introspected for a few real sample values (e.g. `status (VARCHAR) -- Sample values: 'A', 'I'`), and date/datetime columns for their actual min/max range (e.g. `OrderDate (DATETIME) -- Data range: 2012-07-10 to 2023-10-28`) - so the model writes `WHERE status = 'A'` and resolves relative time periods against data that's actually there, instead of guessing.
- **Deterministic Temporal Grounding**: When a question references a bare month with no year (in Arabic or English - "يناير", "January"), the system deterministically resolves it against the schema's actual date range and pins the year in the prompt, rather than relying on the LLM to notice a hint or falling back on assumptions from its training data about what the schema "usually" looks like.
- **Bilingual Complexity Classification**: Recognizes comparison/trend/root-cause/multi-step question patterns in both Arabic and English, so compound analytical questions get routed to the Planner regardless of the language they're asked in.
- **Multi-Step Plan-and-Execute Decomposition**: Decomposes complex compound analytical questions (e.g., *"Show the monthly sales of the best-selling artist"*) into ordered, dependent sub-steps (`Planner`), executing intermediate queries and synthesizing a consolidated final report.
- **Off-Schema Sentinel (`UNANSWERABLE`)**: Emits a `UNANSWERABLE: <reason>` sentinel when requested data does not exist in the active schema, surfacing an honest, LLM-humanized explanation (in the user's own language) rather than hallucinating SQL or returning a flat English error string.
- **Self-Consistency SQL Voting**: Generates multiple SQL candidate queries in parallel (`SQL_CANDIDATES`, default 3) and applies normalized majority voting to select the most reliable execution path. Every candidate is dialect-transpiled and LIMIT-enforced *before* its validation dry-run, not just the final winner.
- **Bounded Auto-Repair & Fuzzy Suggestions**: Automatically captures database execution errors and prompts the LLM to fix syntax up to `MAX_FIX_ATTEMPTS` (default 2). If errors persist, it performs Levenshtein fuzzy matching to suggest closest valid table/column names.

### 🗣️ Human-Voiced, Cost-Aware Reporting
- **Analyst-Voice Report Writing**: Reports read like a senior analyst's spoken summary (direct answer first, then the 2-4 findings that matter) rather than a mechanical dump of dataset statistics, with an explicit rule against relabeling entities found in the results (e.g. never turning "February" into "March" mid-report).
- **Language-Safe Verification**: The optional fact-checking/citation pass is instructed to preserve the draft's language, and a deterministic script-detection safety net discards the verification pass (falling back to the draft) if it ever silently switches scripts (e.g. an Arabic draft coming back in English).
- **Cost-Gated Verification**: The extra verification LLM call only runs for comparison/trend/root-cause/multi-step questions - the analysis types where synthesizing across multiple figures creates real risk of drift. Simple lookup/count/aggregation/ranking questions skip it, roughly halving report-generation LLM cost for the majority of everyday questions.
- **Humanized No-Answer Responses**: Unanswerable questions, empty result sets, and post-repair execution failures are explained by a fast LLM call in the user's own language and tone, with a plain-text fallback if that call itself fails - never a flat hardcoded English string.

### 🛡️ Zero-Trust SQL Engine & Safety
- **AST Safety Parsing (`sqlglot`)**: Validates every generated query against an Abstract Syntax Tree (AST) whitelist/blacklist. Strictly enforces read-only operations (`SELECT`, `WITH`/CTEs, window functions) while blocking destructive operations (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `CREATE`, etc.).
- **Automatic LIMIT Enforcement**: Any generated `SELECT`/`UNION` query with no explicit `LIMIT` gets one appended (default 500 rows) during dialect transpilation - applied before validation dry-runs, the real execution, and any auto-repaired query - so an unbounded query against a large table can't silently pull millions of rows.
- **Multi-Dialect Transpilation**: Normalizes generated SQL to match the target database dialect (`sqlite`, `postgres`, `mysql`) based on the active `DATABASE_URL`, with identifiers safely quoted per-dialect (so table/column names with spaces or reserved words - e.g. Northwind's `Order Details` - work correctly).
- **Multi-Level Caching**: Implements multi-tier caching for generated SQL queries and database result sets using in-memory TTL caches or Redis (`REDIS_URL`).

### 📈 Fact-Grounded Reports & Data Visualization
- **Fact Verification & Row Citations**: A two-stage report generation pipeline cross-references written summaries against raw query result sets, tagging claims with precise row citations (e.g., `[Row 1]`).
- **Deterministic Analytics Engine**: Computes statistical aggregations, outlier detection, and metric trends (`AnalyticsEngine`, `InsightEngine`) to ground reports in verified empirical math.
- **Interactive Plotly Visualizations**: Automatically detects optimal chart types (Bar, Line, Scatter, Pie) and renders interactive Plotly figures alongside dynamic KPI metric cards.
- **Bilingual & Auto-RTL UI**: Native support for English and Arabic typography with automatic Right-to-Left (RTL) layout switching in the Streamlit frontend.

---

## System Architecture

### Component Dataflow

```mermaid
flowchart TD
    User([User / Browser]) <--> UI[Streamlit Frontend Dashboard\n:8501]
    UI <--> API[FastAPI Backend REST API\n:8000]

    subgraph Backend_App [FastAPI Application Core]
        API --> IntentClass[Intent Classifier]
        API --> SchemaExplorer[Offline Schema Explorer]
        API --> Agent[Analyst Agent Core]

        subgraph Agent_Pipeline [Agent Pipeline]
            Agent --> Grounding[Schema Grounding Engine]
            Grounding --> Planner[Plan & Execute Planner]
            Planner --> SQLGen[SQL Candidate Generator]
            SQLGen --> Validator[Zero-Trust Safety Engine\nsqlglot AST Check]
            Validator --> DBExec[SQL Execution & Auto-Repair]
            DBExec --> Analytics[Analytics & Insight Engine]
            Analytics --> ReportGen[Fact-Grounded Report Service]
        end

        Agent <--> Memory[Session Memory Manager\nSliding Window + TTL]
        Agent <--> Cache[Caching Layer\nIn-Memory / Redis]
    end

    subgraph Storage_LLM [Database & LLM Providers]
        DBExec <--> DB[(Database Engine\nSQLite / PostgreSQL / MySQL)]
        SQLGen <--> LLM[LLM Providers\nOpenRouter / Groq / Ollama]
        ReportGen <--> LLM
    end
```

### Text Architecture Overview

```
                      [ Streamlit Dashboard ] (Port 8501)
                                │
          (Interactive Chat, KPI Cards, Plotly Charts, Schema Explorer, DB Switcher)
                                │
                                ▼
                       [ FastAPI Backend ] (Port 8000)
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
 [ Analyst Agent ]     [ Session Memory ]       [ Safety Validator ]
 (Intent Router,       (Sliding Window,         (DML Whitelist Scan,
  Schema Grounding,     Per-Session TTL,         SELECT-only AST Check,
  Plan & Execute,       History Injection)       Dialect Transpiler)
  Self-Consistency,            │                        │
  Fact Grounding)              │                        │
        │                      │                        │
        └──────────────────────┼────────────────────────┘
                               │
                               ▼
         ┌─────────────────────┴─────────────────────┐
         ▼                                           ▼
  [ Database Layer ]                         [ LLM Providers ]
 (SQLite / PostgreSQL / MySQL)             (OpenRouter / Groq / Ollama)
              ▲
              │
      [ Caching Layer ]
     (In-Memory or Redis)
```

---

## Project Directory Structure

```directory
Database-Analyst-Agent/
├── .env                       # Local environment variables (git-ignored)
├── .env.example               # Template environment configuration file
├── docker-compose.yml         # Development docker-compose setup (live mounts)
├── docker-compose.prod.yml    # Production docker-compose setup (standalone images)
├── README.md                  # Project documentation
├── assets/
│   └── dashboard.png          # System UI dashboard preview screenshot
├── backend/
│   ├── app/
│   │   ├── agents/            # Core AI Agent orchestration sub-modules
│   │   │   ├── analyst_agent.py      # Master pipeline executor
│   │   │   ├── intent_classifier.py  # Intent routing & off-topic handling
│   │   │   ├── planner.py            # Plan-and-execute decomposition
│   │   │   ├── schema_explorer.py    # Zero-LLM offline metadata resolver
│   │   │   └── sql_generator.py      # Self-consistency SQL generation & repair
│   │   ├── analytics/         # Deterministic statistical engines
│   │   │   ├── engine.py             # Row aggregations, summary stats
│   │   │   ├── insight_engine.py     # Outlier detection, metric highlights
│   │   │   ├── analyzers/            # Per-metric statistical analyzers
│   │   │   └── insights/             # Insight generation strategies
│   │   ├── api/               # FastAPI REST endpoint routes
│   │   │   ├── chat.py               # POST /chat, DELETE /chat/history
│   │   │   ├── connect.py            # Database hot-swapping & file uploads
│   │   │   ├── health.py             # GET /health
│   │   │   └── schema.py             # GET /schema
│   │   ├── core/              # System settings & logging setup
│   │   │   ├── config.py             # Environment-backed settings
│   │   │   └── logging_config.py     # Loguru JSON structured logger
│   │   ├── database/          # SQLAlchemy engine & session pool
│   │   │   ├── db.py                 # Dynamic database connection manager
│   │   │   ├── models.py             # Internal database ORM models
│   │   │   └── seed.py               # Database seeder utility
│   │   ├── evaluation/        # Benchmarking & scoring utilities
│   │   ├── llm/                # Provider client wrappers & prompt templates
│   │   │   ├── model.py              # OpenRouter, Groq, Ollama client factories
│   │   │   └── prompts.py            # Zero-shot SQL, report, and no-answer templates
│   │   ├── schema_grounding/   # Question-scoped schema pruning
│   │   │   ├── grounding_engine.py   # SchemaGroundingEngine: seed-table + FK-graph resolution
│   │   │   ├── relationship_graph.py # FK join graph + centrality ranking (large-schema fallback)
│   │   │   ├── schema_pruner.py      # Renders the pruned schema subset to prompt text
│   │   │   └── models.py             # GroundedSchema result model
│   │   ├── schemas/            # Pydantic request/response models
│   │   │   └── chat.py               # API schemas for requests & responses
│   │   ├── semantic/           # Deterministic question understanding
│   │   │   ├── parser.py             # SemanticQueryParser: entities/metrics/analysis type
│   │   │   └── models.py             # QueryUnderstanding result model
│   │   ├── services/           # Core domain business logic
│   │   │   ├── memory.py             # Conversation memory manager & TTL
│   │   │   ├── report_service.py     # Fact-grounded, human-voiced report synthesis & charts
│   │   │   └── sql_service.py        # Schema introspection (incl. sample values/date ranges) & SQL executor
│   │   ├── sql/                 # SQL prompt building, safety validation & repair
│   │   │   ├── prompt_builder.py     # Builds generation input incl. temporal grounding hints
│   │   │   ├── validator.py          # SELECT-only safety check + dialect transpile + LIMIT enforcement
│   │   │   ├── repair_engine.py      # Fuzzy table/column suggestions on execution failure
│   │   │   ├── grounding_engine.py   # UNANSWERABLE sentinel detection helper
│   │   │   └── models.py             # ValidationResult / GroundingResult / ExecutionRepairResult
│   │   ├── utils/               # Utilities for parsing, safety, and caching
│   │   │   ├── cache.py              # In-memory / Redis cache manager
│   │   │   ├── text_processor.py     # Bilingual (AR/EN) analysis-type classification, temporal hint resolution
│   │   │   ├── validator.py          # AST sqlglot safety validator, dialect transpiler, LIMIT enforcement
│   │   │   └── token_tracker.py      # LLM token usage accounting
│   │   └── main.py              # FastAPI entry point, CORS & middleware
│   ├── scripts/                 # Standalone dev utilities (not part of the pytest suite)
│   │   ├── check_db_connection.py    # Print configured DB + verify it's reachable
│   │   └── manual_smoke_test.py      # Run a handful of representative questions end-to-end
│   ├── tests/                 # Automated Pytest suite
│   │   ├── conftest.py               # Test fixtures (API client, mock LLM, DB)
│   │   ├── test_agent.py             # End-to-end agent logic tests
│   │   ├── test_api.py               # REST API endpoint tests
│   │   ├── test_memory.py            # Memory TTL & sliding window tests
│   │   ├── test_planner.py           # Plan-and-execute decomposition tests
│   │   ├── test_schema_grounding.py  # Schema grounding/pruning tests
│   │   ├── test_semantic_parser.py   # SemanticQueryParser tests
│   │   ├── test_sql_package.py       # SQL prompt/validation/repair package tests
│   │   └── test_validation.py        # AST SQL safety & transpilation tests
│   ├── chinook.db             # Default sample SQLite database (Music Store)
│   ├── Northwind.db           # Preset sample SQLite database (Enterprise ERP)
│   ├── Dockerfile             # Backend production Docker container recipe
│   ├── railway.json           # Railway deployment specification
│   └── requirements.txt       # Backend Python dependencies
└── frontend/
    ├── app.py                 # Streamlit UI dashboard application
    ├── Dockerfile             # Frontend production Docker container recipe
    ├── railway.json           # Railway deployment specification
    └── requirements.txt       # Frontend Python dependencies
```

---

## Technology Stack

| Layer | Technologies & Libraries |
| :--- | :--- |
| **Backend Core** | Python 3.12, FastAPI, Uvicorn, Pydantic v2, Pydantic-Settings |
| **Data & ORM** | SQLAlchemy 2.0, PyMySQL, Psycopg2-binary, SQLite |
| **Agent Orchestration** | LangChain, LangChain-Core, LangChain-Community, LangChain-OpenAI, LangChain-Ollama |
| **SQL Safety & AST** | `sqlglot` (AST parsing & dialect transpilation), `sqlparse` |
| **LLM Integrations** | OpenRouter API, Groq Cloud API, Ollama (Local models: Gemma 3, Llama 3.3) |
| **Frontend Dashboard** | Streamlit, Plotly Express, Pandas, HTML5 / CSS3 (Vanilla design system) |
| **Logging & Cache** | Loguru (Structured JSON logging), Cachetools, Redis (Optional) |
| **Testing & Tools** | Pytest, Pytest-Asyncio, HTTPX, `uv` / `pip` |
| **Containerization** | Docker, Docker Compose, Railway |

---

## Environment Configuration

Copy `.env.example` to `.env` in the root workspace directory before launching the application:

```bash
cp .env.example .env
```

### Supported Configuration Variables

| Variable | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| **`LLM_PROVIDER`** | *string* | `openrouter` | Active provider: `openrouter`, `groq`, or `ollama`. |
| **`OPENROUTER_API_KEY`** | *string* | `""` | OpenRouter API Key (required when `LLM_PROVIDER=openrouter`). |
| **`OPENROUTER_MODEL`** | *string* | `google/gemini-2.5-flash` | Primary model for SQL generation on OpenRouter. |
| **`OPENROUTER_FAST_MODEL`** | *string* | `google/gemini-2.5-flash` | Fast model for intent, planning, and report synthesis. |
| **`OPENROUTER_BASE_URL`** | *string* | `https://openrouter.ai/api/v1` | Base API URL for OpenRouter endpoint. |
| **`GROQ_API_KEY`** | *string* | `""` | Groq Cloud API Key (required when `LLM_PROVIDER=groq`). |
| **`GROQ_MODEL`** | *string* | `llama-3.3-70b-versatile` | Primary model for Groq provider. |
| **`GROQ_FAST_MODEL`** | *string* | `llama-3.1-8b-instant` | Fast model for Groq provider. |
| **`OLLAMA_BASE_URL`** | *string* | `http://localhost:11434` | Base URL for local Ollama service. |
| **`OLLAMA_MODEL`** | *string* | `gemma3:4b` | Default Ollama model name. |
| **`DATABASE_URL`** | *string* | `sqlite:///./chinook.db` | SQLAlchemy connection string (SQLite, PostgreSQL, MySQL). |
| **`ENABLE_SELF_CONSISTENCY`**| *boolean*| `false` | Enable parallel multi-query SQL voting. |
| **`SQL_CANDIDATES`** | *integer*| `3` | Number of candidate queries generated during self-consistency. |
| **`ENABLE_REPORT_VERIFICATION`**| *boolean*| `false` | Enable two-stage LLM verification of final report text. |
| **`ENABLE_CHART_SUGGESTION`**| *boolean*| `true` | Enable LLM chart visualization recommendations. |
| **`REDIS_URL`** | *string* | `None` | (Optional) Redis connection URL for distributed caching. |
| **`SQL_CACHE_TTL`** | *integer* | `3600` | Expiration time (seconds) for cached SQL queries. |
| **`RESULTS_CACHE_TTL`** | *integer* | `300` | Expiration time (seconds) for cached query results. |
| **`MEMORY_WINDOW_SIZE`** | *integer*| `5` | Sliding window count of conversation turns retained per session. |
| **`MEMORY_TTL_SECONDS`** | *integer*| `3600` | Idle session memory eviction timeout (seconds). |
| **`DB_POOL_SIZE`** | *integer* | `20` | Database connection pool size (PostgreSQL/MySQL). |
| **`DB_MAX_OVERFLOW`** | *integer* | `0` | Database connection pool max overflow limit. |

---

## Getting Started

### Prerequisites
- **Python 3.12+** or **Docker & Docker Compose** installed.
- API key for **OpenRouter** or **Groq**, or a running local instance of **Ollama**.

---

### Option 1: Docker Compose (Recommended)

To spin up both backend and frontend services inside containers:

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Abdelrahman-Mahana/Database-Analyst-Agent.git
   cd Database-Analyst-Agent
   ```

2. **Setup Environment**:
   ```bash
   cp .env.example .env
   # Open .env and insert your OPENROUTER_API_KEY or GROQ_API_KEY
   ```

3. **Launch Containers**:
   - **Development Mode** (with live volume reloads):
     ```bash
     docker-compose up --build
     ```
   - **Production Mode** (standalone build):
     ```bash
     docker-compose -f docker-compose.prod.yml up --build -d
     ```

4. **Access Applications**:
   - **Frontend UI Dashboard**: [`http://localhost:8501`](http://localhost:8501)
   - **Backend REST API**: [`http://localhost:8000`](http://localhost:8000)
   - **Interactive API Docs (Swagger)**: [`http://localhost:8000/docs`](http://localhost:8000/docs)

---

### Option 2: Local Development (uv / pip)

We support package management using **`uv`** (fast Rust-based Python package manager) or standard **`pip`**.

#### 1. Start the Backend API

```bash
cd backend

# Create & activate virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -r requirements.txt

# Start Uvicorn development server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 2. Start the Frontend Dashboard

Open a separate terminal window:

```bash
cd frontend

# Create & activate virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -r requirements.txt

# Launch Streamlit server
python -m streamlit run app.py
```

---

## Database Connection & Management

The application features dynamic database switching without restarting the backend:

1. **Local SQLite Presets**:
   - **Chinook**: Sample digital music store database (tracks, albums, invoices, customers).
   - **Northwind**: Classic ERP enterprise database (orders, products, suppliers, employees).

2. **Custom SQLite File Upload**:
   - Upload any `.db` or `.sqlite` file directly through the UI sidebar or `POST /connect/upload` endpoint.

3. **Remote Database Connection Strings**:
   - Pass any standard SQLAlchemy database URI (PostgreSQL, MySQL, MariaDB, etc.) via the UI or `POST /connect/url`.
   - *Example PostgreSQL URL*: `postgresql://user:password@localhost:5432/analytics_db`

---

## REST API Reference

Full interactive documentation is available at `http://localhost:8000/docs`. Key API endpoints include:

### `POST /chat`
Submits a natural-language query to the Analyst Agent pipeline.

**Request Body**:
```json
{
  "message": "Who are the top 5 customers by total spending?",
  "session_id": "session-uuid-1234"
}
```

**Response Body (200 OK)**:
```json
{
  "question": "Who are the top 5 customers by total spending?",
  "sql": "SELECT c.FirstName, c.LastName, SUM(i.Total) AS TotalSpent FROM Customer c JOIN Invoice i ON c.CustomerId = i.CustomerId GROUP BY c.CustomerId ORDER BY TotalSpent DESC LIMIT 5;",
  "results": [
    { "FirstName": "Helena", "LastName": "Holý", "TotalSpent": 49.62 },
    { "FirstName": "Richard", "LastName": "Cunningham", "TotalSpent": 47.62 },
    { "FirstName": "Luis", "LastName": "Rojas", "TotalSpent": 46.62 },
    { "FirstName": "Ladislav", "LastName": "Kovács", "TotalSpent": 45.62 },
    { "FirstName": "Hugh", "LastName": "O'Reilly", "TotalSpent": 45.62 }
  ],
  "report": "## Executive Summary\nBased on invoice records, **Helena Holý** is the top spending customer with a total of **$49.62** [Row 1], closely followed by **Richard Cunningham** with **$47.62** [Row 2].",
  "chart_suggestion": {
    "should_chart": true,
    "chart_type": "bar",
    "x_column": "LastName",
    "y_column": "TotalSpent"
  },
  "intent": "database",
  "attempted_sql": null,
  "error_type": null,
  "suggestions": [],
  "success": true,
  "error": null
}
```

---

### `POST /connect/url`
Switches active database connection to a target connection URI.

**Request Body**:
```json
{
  "database_url": "postgresql://user:password@localhost:5432/analytics_db"
}
```

---

### `POST /connect/upload`
Uploads a SQLite `.db` or `.sqlite` file and instantly sets it as active.

---

### `DELETE /chat/history?session_id=<id>`
Clears all sliding window conversation turns for the specified session ID.

---

### `GET /schema`
Extracts and returns the full introspected active database schema metadata (tables, columns, primary keys, foreign key relations, indexes).

---

### `GET /health`
Returns system health status, active provider, model name, and live real-time LLM ping latency.

---

## Testing & Quality Assurance

The backend repository includes unit and integration tests written using `pytest` and `pytest-asyncio`. Tests utilize mock LLM chains to execute deterministically without making external API calls.

To run the complete test suite:

```bash
cd backend
pytest tests/ -v
```

### Test Suite Coverage

- **`test_agent.py`**: Validates agent intent routing, SQL generation fallback, `UNANSWERABLE` sentinels, and report formatting.
- **`test_validation.py`**: Tests `sqlglot` AST safety rules (blocking `DROP`, `DELETE`, `UPDATE`), whitelist enforcing, LIMIT enforcement, and SQL dialect transpilation.
- **`test_memory.py`**: Verifies per-session memory state retention, sliding window turn eviction, and TTL expiration logic.
- **`test_api.py`**: Tests FastAPI REST routes (`/chat`, `/schema`, `/health`, `/connect/*`).
- **`test_planner.py`**: Tests multi-step plan decomposition and execution.
- **`test_schema_grounding.py`**: Tests seed-table resolution and schema pruning.
- **`test_semantic_parser.py`**: Tests entity/metric/analysis-type extraction from questions.
- **`test_sql_package.py`**: Tests the SQL prompt builder, validator, and repair engine as a package.

Two standalone scripts in `backend/scripts/` (not part of the pytest suite) are also available for manual checks:
- `check_db_connection.py` - prints the configured `DATABASE_URL` and lists its tables.
- `manual_smoke_test.py` - runs a handful of representative questions (Arabic + English, simple + Planner + off-topic) end-to-end and prints the full response for eyeballing.

---

## Deployment

### Railway Deployment

Each service contains a `railway.json` configuration file ready for zero-config Railway deployment:

1. **Backend Service**:
   - Build Context: `backend/`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Healthcheck Path: `/health`

2. **Frontend Service**:
   - Build Context: `frontend/`
   - Start Command: `streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`
   - Environment Variable: `API_BASE_URL` set to the deployed backend Railway URL.

---

## License

This project is open-source software licensed under the **[MIT License](LICENSE)**.
