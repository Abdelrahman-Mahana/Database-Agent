-- Supabase Migration Schema
-- Run this in your Supabase SQL Editor

-- 1. Caching Table (Replaces Redis caching)
CREATE TABLE IF NOT EXISTS agent_cache (
    key text PRIMARY KEY,
    value text NOT NULL,
    expires_at timestamp with time zone NOT NULL
);

-- Index for fast expiration cleanup if you want to run a pg_cron job
CREATE INDEX IF NOT EXISTS idx_agent_cache_expires_at ON agent_cache (expires_at);

-- 2. Long-Term Memory Table (Replaces Redis memory)
CREATE TABLE IF NOT EXISTS agent_memory (
    user_id text NOT NULL,
    sub text NOT NULL, -- e.g., 'queries' or 'prefs'
    data jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (user_id, sub)
);

-- 3. Session Management Table (Replaces Redis session-to-url mapping)
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id text PRIMARY KEY,
    database_url text NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);

-- 4. Schema Catalog Progress Table
CREATE TABLE IF NOT EXISTS agent_catalog_progress (
    db_hash text PRIMARY KEY,
    progress jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);

-- 5. Schema Service Global Cache Table
CREATE TABLE IF NOT EXISTS agent_schema_cache (
    db_hash text PRIMARY KEY,
    data jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);
