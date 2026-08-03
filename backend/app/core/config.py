"""Centralized application settings."""
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(), override=True)

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BACKEND_DIR / "chinook.db"


class Settings:
    """Environment-backed settings used across the app."""

    database_url = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")
    llm_provider = os.getenv("LLM_PROVIDER", "openrouter").lower()

    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "gemma3:4b")
    ollama_fast_model = os.getenv("OLLAMA_FAST_MODEL", "gemma3:4b")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    openrouter_fast_model = os.getenv("OPENROUTER_FAST_MODEL", "google/gemini-2.5-flash")
    openrouter_base_url = os.getenv(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
    )

    groq_api_key = os.getenv("GROQ_API_KEY", "")
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    groq_fast_model = os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant")
    groq_base_url = os.getenv(
        "GROQ_BASE_URL",
        "https://api.groq.com/openai/v1",
    )

    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
    openai_fast_model = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")
    openai_base_url = os.getenv(
        "OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    )

    # Self-consistency config
    sql_candidates = int(os.getenv("SQL_CANDIDATES", "3"))
    enable_self_consistency = os.getenv("ENABLE_SELF_CONSISTENCY", "false").lower() == "true"

    # Cost-saving options
    enable_report_verification = os.getenv("ENABLE_REPORT_VERIFICATION", "false").lower() == "true"
    enable_chart_suggestion = os.getenv("ENABLE_CHART_SUGGESTION", "true").lower() == "true"

    # Optional Redis URL for LangChain caching
    redis_url = os.getenv("REDIS_URL", None)

    # Caching config
    sql_cache_ttl = int(os.getenv("SQL_CACHE_TTL", "3600"))
    results_cache_ttl = int(os.getenv("RESULTS_CACHE_TTL", "300"))
    schema_cache_ttl = int(os.getenv("SCHEMA_CACHE_TTL", "3600"))

    # Connection pooling config for production (non-SQLite) DBs
    db_pool_size = int(os.getenv("DB_POOL_SIZE", "20"))
    db_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "0"))

    # Memory config
    memory_window_size = int(os.getenv("MEMORY_WINDOW_SIZE", "5"))
    memory_ttl_seconds = int(os.getenv("MEMORY_TTL_SECONDS", "3600"))

    # --- Rebuild Phase 1: LLM-based understanding layer ---
    # When true, question understanding (analysis type, entities/metrics,
    # aggregations, whether multi-step planning is genuinely needed, ...) is
    # produced by a single structured-output LLM call instead of the
    # regex-based SemanticQueryParser/classify_analysis_type. The regex path
    # is NEVER deleted - it stays as the automatic fallback whenever the LLM
    # call fails, times out, or returns low-confidence output, and as the
    # default when this flag is off. Toggle here (or per-request via env) to
    # A/B the two paths against the same golden dataset before fully cutting
    # over - see eval/run_understanding_eval.py.
    use_llm_understanding = os.getenv("USE_LLM_UNDERSTANDING", "false").lower() == "true"
    # Below this self-reported confidence, treat the LLM understanding as
    # unusable and fall back to the deterministic regex parser instead.
    llm_understanding_min_confidence = float(os.getenv("LLM_UNDERSTANDING_MIN_CONFIDENCE", "0.5"))

    # --- Rebuild Phase 2: LangGraph agentic orchestration ---
    # When true, AnalystAgent.ask() routes through a LangGraph StateGraph
    # (app/agents/graph_orchestrator.py) instead of the linear step-by-step
    # method body. The linear body is NEVER deleted - it's the default and
    # the automatic fallback if langgraph isn't installed. The graph adds one
    # real capability the linear pipeline can't do: a bounded reflect-and-retry
    # loop when execution fails, instead of always giving up after
    # execute_with_repair's own bounded SQL-level retries are exhausted.
    use_langgraph_orchestrator = os.getenv("USE_LANGGRAPH_ORCHESTRATOR", "false").lower() == "true"

    # --- Rebuild Phase 3: semantic (embedding) schema retrieval ---
    # "tfidf" (default, unchanged) = the existing pure-Python bag-of-words
    # retriever in schema_catalog/retrieval.py. "embedding" = real vector
    # similarity via schema_catalog/embedding_retrieval.py. Only takes effect
    # once a catalog's table embeddings have actually been computed
    # (CatalogBuilder.ensure_table_embeddings) - otherwise retrieve_relevant_tables()
    # transparently falls back to tfidf, so flipping this is always safe.
    schema_retrieval_method = os.getenv("SCHEMA_RETRIEVAL_METHOD", "tfidf").lower()
    # Embedding provider used to embed both table documents (once, offline)
    # and the user's question (once per query). "ollama" talks to the same
    # local server already used for LLM inference (no new network dependency,
    # works fully offline) - "openai_compatible" talks to any OpenAI-style
    # /embeddings endpoint via EMBEDDING_BASE_URL/EMBEDDING_API_KEY.
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "ollama").lower()
    embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "")
    embedding_api_key = os.getenv("EMBEDDING_API_KEY", "")
    embedding_request_timeout_seconds = float(os.getenv("EMBEDDING_REQUEST_TIMEOUT_SECONDS", "5"))

    # --- Rebuild Phase 4: automatic onboarding for a newly-connected DB ---
    # When true, connecting to a new database (via /connect/*) schedules a
    # background job that profiles the schema, generates the business
    # glossary, and (if SCHEMA_RETRIEVAL_METHOD=embedding) computes table
    # embeddings — all in one go, once per DB fingerprint, without blocking
    # the connect response. Safe to disable if you'd rather trigger these
    # explicitly (see app/services/onboarding.py).
    enable_auto_onboarding = os.getenv("ENABLE_AUTO_ONBOARDING", "true").lower() == "true"

    # --- Rebuild Phase 6: real model-tier routing for SQL generation ---
    # When true, simple/confident questions (see cost_router.choose_sql_generation_tier)
    # generate SQL with the fast/cheap model tier instead of always paying
    # for the primary model. Off by default: this changes cost, not just
    # behavior, so it's an explicit opt-in even though it's low-risk (a
    # wrong "fast" pick just means one extra auto-repair round-trip, not a
    # broken answer - execute_with_repair still catches it).
    enable_model_routing = os.getenv("ENABLE_MODEL_ROUTING", "false").lower() == "true"
    model_routing_min_confidence = float(os.getenv("MODEL_ROUTING_MIN_CONFIDENCE", "0.75"))

    # --- Phase 3: large-schema retrieval ---
    # Above this table count, prefer TF-IDF retrieval over the schema
    # catalog's glossary text instead of dumping/centrality-ranking every table.
    large_schema_table_threshold = int(os.getenv("LARGE_SCHEMA_TABLE_THRESHOLD", "30"))
    retrieval_top_k_tables = int(os.getenv("RETRIEVAL_TOP_K_TABLES", "12"))

    # --- Phase 5: safety (cost guard + data masking) ---
    enable_cost_guard = os.getenv("ENABLE_COST_GUARD", "true").lower() == "true"
    # Block (not just warn) a query that scans more than this many rows
    # across its tables with no WHERE/LIMIT at all. Sensible default: most
    # legitimate "read a bit of data" questions don't need more than this.
    cost_guard_max_unfiltered_rows = int(os.getenv("COST_GUARD_MAX_UNFILTERED_ROWS", "500000"))

    enable_data_masking = os.getenv("ENABLE_DATA_MASKING", "true").lower() == "true"
    # Comma-separated extra column-name substrings to mask, beyond the
    # built-in PII patterns (email, phone, ssn, password, credit card...).
    extra_masked_column_patterns = [
        p.strip() for p in os.getenv("EXTRA_MASKED_COLUMN_PATTERNS", "").split(",") if p.strip()
    ]

    # --- Phase 6: report cache ---
    report_cache_ttl = int(os.getenv("REPORT_CACHE_TTL", "600"))

    # --- Phase 8: cost dashboard ---
    enable_cost_dashboard = os.getenv("ENABLE_COST_DASHBOARD", "true").lower() == "true"

    # --- Phase 10: API rate limiting ---
    enable_rate_limit = os.getenv("ENABLE_RATE_LIMIT", "true").lower() == "true"
    rate_limit_requests_per_minute = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "30"))


settings = Settings()
