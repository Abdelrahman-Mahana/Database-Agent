import os
from pathlib import Path
from typing import List, Optional, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BACKEND_DIR / "chinook.db"

class Settings(BaseSettings):
    project_name: str = "AI Database Analyst Agent"
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    
    # Profiling Settings
    sampling_threshold: int = 100000
    random_sample_size: int = 10000
    max_top_values: int = 10
    entropy_threshold: float = 0.5
    max_concurrent_profiles: int = 5

    # Global DB
    database_url: str = Field(default=f"sqlite:///{DEFAULT_SQLITE_PATH}")
    
    # LLM Settings
    llm_provider: str = "openrouter"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_fast_model: str = "gemma3:4b"

    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_fast_model: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_pricing_refresh_seconds: int = 86400

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_fast_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Self-consistency config
    sql_candidates: int = 3
    enable_self_consistency: bool = False

    # Cost-saving options
    # Optional second-pass LLM refinement for complex synthesis only.
    # Deterministic claim verification is mandatory and is not controlled by
    # this flag.
    enable_report_verification: bool = False
    enable_chart_suggestion: bool = True

    # System Store (PostgreSQL for multi-user/multi-worker production, SQLite for local dev)
    system_store_database_url: Optional[str] = None
    system_store_path: str = Field(
        default=str(BACKEND_DIR / "data" / "system_store.db")
    )

    # Distributed Coordination & Caching (Redis)
    redis_url: Optional[str] = None
    redis_pool_size: int = 10
    redis_timeout_seconds: float = 2.0

    # Deprecated: Supabase Configuration (replaced by system store)
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None

    # Caching config
    sql_cache_ttl: int = 3600
    results_cache_ttl: int = 300
    schema_cache_ttl: int = 3600
    report_cache_ttl: int = 3600

    # Result set caching bounds & volatility controls
    enable_results_cache: bool = True
    cache_results_max_rows: int = 500       # max rows allowed in a cached query result
    cache_results_max_bytes: int = 512_000   # 500 KB max payload limit per cached query result
    results_cache_volatile_ttl: int = 30    # reduced TTL for queries touching volatile/transactional tables
    volatile_table_patterns: List[str] = Field(
        default_factory=lambda: ["logs", "events", "transactions", "audit", "stream", "queue", "temp"]
    )

    # Connection pooling config for production (non-SQLite) DBs
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_pool_timeout: int = 30

    introspection_query_timeout: int = 5

    # Memory config
    memory_window_size: int = 5
    memory_ttl_seconds: int = 3600

    # --- Rebuild Phase 1: LLM-based understanding layer ---
    use_llm_understanding: bool = False
    llm_understanding_min_confidence: float = 0.5

    # --- Rebuild Phase 2: canonical orchestrator selection ---
    # False (default): service pipeline (_run_service_pipeline)
    # True: LangGraph pipeline (run_graph_ask) — failures surface explicitly, no cross-architecture fallback
    use_langgraph_orchestrator: bool = False

    # --- Rebuild Phase 3: semantic (embedding) schema retrieval ---
    schema_retrieval_method: str = "embedding"
    embedding_provider: str = "openai_compatible"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_request_timeout_seconds: float = 5.0

    # --- Rebuild Phase 4: automatic onboarding for a newly-connected DB ---
    enable_auto_onboarding: bool = True

    # --- Background profiling budget controls ---
    # max_concurrent_profiles is defined above (default 5) and is now respected
    # by CatalogBuilder.build_async() instead of the previous hardcoded 15.
    profile_max_text_cols_per_table: int = 4       # max text columns to sample per table
    profile_max_date_cols_per_table: int = 2       # max date columns to range-check per table
    profile_timeout_seconds: int = 600             # max total wall-clock time for background profiling
    profile_use_batched_sampling: bool = True       # single-query batched sampling (fewer round-trips)

    # --- Rebuild Phase 6: real model-tier routing for SQL generation ---
    enable_model_routing: bool = True
    model_routing_min_confidence: float = 0.75
    max_fix_attempts: int = 1

    # --- Phase 3: schema grounding & retrieval bounds (adaptive table subset) ---
    large_schema_table_threshold: int = 10
    retrieval_top_k_tables: int = 5
    grounding_max_seed_tables: int = 5
    grounding_max_final_tables: int = 15
    grounding_max_cols_per_table: int = 12
    llm_prompt_max_tables: int = 15
    llm_prompt_max_cols_per_table: int = 12
    max_schema_tokens: int = 4000
    self_consistency_max_schema_tokens: int = 4000

    # --- Phase 5: safety (cost guard + data masking) ---
    enable_cost_guard: bool = True
    cost_guard_max_unfiltered_rows: int = 500000
    cost_guard_max_estimated_rows: int = 1000000
    cost_guard_max_returned_rows: int = 5000
    cost_guard_max_returned_bytes: int = 10485760  # 10 MB payload limit
    cost_guard_timeout_seconds: int = 15
    enforce_read_only_transactions: bool = True
    cost_guard_fail_closed_on_high_risk: bool = True
    enable_data_masking: bool = True
    extra_masked_column_patterns: List[str] = Field(default_factory=list)

    # --- Phase 6: report cache ---
    report_cache_ttl: int = 600
    report_prompt_version: str = "v1"

    # --- Phase 8: cost dashboard ---
    enable_cost_dashboard: bool = True

    # --- Phase 10: API rate limiting ---
    enable_rate_limit: bool = True
    rate_limit_requests_per_minute: int = 30

    # --- New Refactor Additions ---
    # --- New Refactor Additions ---
    schema_catalog_dir: str = Field(
        default=str(BACKEND_DIR / "data" / "schema_catalog")
    )
    connection_profiles_dir: str = Field(
        default=str(BACKEND_DIR / "data")
    )
    secret_key: str
    cors_origins: List[str] = ["http://localhost:3000"]

    @field_validator("llm_provider", "embedding_provider", "schema_retrieval_method")
    @classmethod
    def lowercase_providers(cls, v: str) -> str:
        return v.lower()

    @field_validator("extra_masked_column_patterns", mode="before")
    @classmethod
    def parse_extra_masked_columns(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

def get_settings() -> Settings:
    return Settings()

settings = get_settings()
