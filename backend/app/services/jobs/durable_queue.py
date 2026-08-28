"""Durable Job Queue for database onboarding, profiling, and index generation.

Provides:
1. Persisted job lifecycle in SystemStore (pending -> running -> completed / failed)
2. Idempotent job submission (no duplicate execution for the same fingerprint)
3. Distributed mutual exclusion via RedisCoordinator locks
4. Resilient progress tracking surviving server restarts
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional
import structlog

from app.core.config.settings import settings
from app.services.database.system_store import system_store, SystemStore
from app.services.database.redis_store import get_redis_coordinator
from app.services.sql_service import SchemaService
from app.models.schema_catalog.catalog_builder import CatalogBuilder, set_build_progress, get_build_progress
from app.models.schema_catalog.glossary import build_glossary
from app.agent.llm.model import get_llm_client

logger = structlog.get_logger(__name__)


class DurableJobQueue:
    """Durable job manager for asynchronous database onboarding and profiling."""

    def __init__(self, store: Optional[SystemStore] = None):
        self.store = store or system_store

    def submit_onboarding_job(
        self,
        database_url: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        """
        Submit a database onboarding / profiling job.
        
        Idempotent: If an active job is already queued or running for this fingerprint,
        returns the existing job immediately.
        """
        # 1. Check for an active job
        active_job = self.store.get_active_job_for_fingerprint(fingerprint, job_type="onboarding")
        if active_job:
            logger.info("Found existing active onboarding job for fingerprint", fingerprint=fingerprint, job_id=active_job["job_id"])
            # A pending job can be left behind by a clean shutdown while its
            # coroutine was cancelled.  Dispatch it again when a request (or
            # startup recovery) encounters it; a running job is left alone.
            if active_job.get("status") == "pending":
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.run_onboarding_job(active_job["job_id"]))
                except RuntimeError:
                    asyncio.run(self.run_onboarding_job(active_job["job_id"]))
            return active_job

        # 2. Create durable job record
        job_id = str(uuid.uuid4())
        job = self.store.create_job(
            job_id=job_id,
            job_type="onboarding",
            target_fingerprint=fingerprint,
            database_url=database_url,
            status="pending",
            stage="queued",
        )
        logger.info("Created durable onboarding job", job_id=job_id, fingerprint=fingerprint)

        # 3. Dispatch execution
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.run_onboarding_job(job_id))
        except RuntimeError:
            # If outside active event loop, run in background thread or task
            asyncio.run(self.run_onboarding_job(job_id))

        return job

    async def run_onboarding_job(self, job_id: str) -> None:
        """Execute onboarding pipeline with stage-level durable checkpointing."""
        job = self.store.get_job(job_id)
        if not job:
            logger.warning("Job not found for execution", job_id=job_id)
            return

        fingerprint = job["target_fingerprint"]
        database_url = job["database_url"]
        redis_coord = get_redis_coordinator()

        # Distributed mutex to ensure only one worker processes this database at a time
        with redis_coord.acquire_lock(f"onboard:{fingerprint}", timeout_seconds=5.0, lock_timeout=600.0) as acquired:
            if not acquired:
                logger.info("Another worker is actively profiling this fingerprint, yielding.", fingerprint=fingerprint)
                return

            try:
                self.store.update_job_status(job_id, status="running", progress_percent=5.0, stage="structural")
                set_build_progress(fingerprint, {
                    "status": "structural",
                    "progress_percent": 5.0,
                    "job_id": job_id,
                })

                # Bind schema service to this database URL
                from sqlalchemy import create_engine
                from app.services.database.db import normalize_database_url
                norm_url = normalize_database_url(database_url)
                engine = create_engine(norm_url)
                schema_service = SchemaService(bind_engine=engine)
                db_name = schema_service.get_database_name()

                # Stage 1: Structural Profile
                catalog_builder = CatalogBuilder(schema_service)
                catalog = catalog_builder.get_or_build()
                self.store.update_job_status(job_id, status="running", progress_percent=15.0, stage="profiling")
                logger.info("Durable job: structural profile ready", job_id=job_id, tables=len(catalog.tables))

                # Stage 2: Background statistical profiling (row counts, values)
                await catalog_builder.build_async(catalog.fingerprint)
                catalog = catalog_builder.get_or_build()
                self.store.update_job_status(job_id, status="running", progress_percent=70.0, stage="glossary")

                # Stage 3: LLM Business Glossary
                if not catalog.glossary_enriched:
                    try:
                        llm_client = get_llm_client()
                        glossary = await build_glossary(catalog, llm_client)
                        catalog = catalog_builder.merge_glossary(catalog, glossary)
                        logger.info("Durable job: glossary enriched", job_id=job_id)
                    except Exception as ge:
                        logger.warning("Durable job glossary build warning (non-fatal)", error=str(ge))

                self.store.update_job_status(job_id, status="running", progress_percent=85.0, stage="embedding")

                # Stage 4: Semantic Embeddings
                if settings.schema_retrieval_method == "embedding" and not catalog.embeddings_built:
                    try:
                        catalog = await catalog_builder.enrich_with_embeddings(catalog)
                        logger.info("Durable job: embeddings enriched", job_id=job_id)
                    except Exception as ee:
                        logger.warning("Durable job embedding build warning (non-fatal)", error=str(ee))

                # Stage 5: RAM DatabaseContext Pre-Indexing
                self.store.update_job_status(job_id, status="running", progress_percent=95.0, stage="indexing")
                try:
                    db_ctx = schema_service.get_database_context()
                    db_ctx.catalog = catalog
                    db_ctx.ensure_indexes(force=True)
                except Exception as ie:
                    logger.debug("Durable job: RAM index warming note", error=str(ie))

                # Complete Job
                self.store.update_job_status(job_id, status="completed", progress_percent=100.0, stage="completed")
                set_build_progress(fingerprint, {
                    "status": "completed",
                    "progress_percent": 100.0,
                    "job_id": job_id,
                })
                logger.info("Durable job completed successfully", job_id=job_id, database=db_name)

            except asyncio.CancelledError:
                # Do not leave a job permanently marked as running when the
                # server is shut down.  It will be dispatched again after the
                # next connection request or startup recovery.
                self.store.update_job_status(
                    job_id,
                    status="pending",
                    stage="queued",
                    error="Onboarding interrupted by server shutdown; queued for resume.",
                )
                set_build_progress(fingerprint, {
                    "status": "pending",
                    "progress_percent": 0.0,
                    "job_id": job_id,
                })
                logger.info("Durable onboarding job cancelled and queued for resume", job_id=job_id)
                raise
            except Exception as exc:
                err_msg = str(exc)
                logger.error("Durable onboarding job failed", job_id=job_id, error=err_msg)
                self.store.update_job_status(job_id, status="failed", progress_percent=0.0, stage="error", error=err_msg)
                set_build_progress(fingerprint, {
                    "status": "failed",
                    "progress_percent": 0.0,
                    "error": err_msg,
                    "job_id": job_id,
                })

    def get_job_progress(self, fingerprint: str) -> dict[str, Any]:
        """Fetch durable job progress for the given database fingerprint."""
        active_job = self.store.get_active_job_for_fingerprint(fingerprint, job_type="onboarding")
        if active_job:
            return {
                "status": active_job["status"],
                "stage": active_job["stage"],
                "progress_percent": active_job["progress_percent"],
                "job_id": active_job["job_id"],
                "error": active_job["error"],
            }

        # Check catalog build progress cache/store
        prog = get_build_progress(fingerprint)
        if prog:
            return prog

        return {"status": "idle", "progress_percent": 100.0}

    def recover_stalled_jobs(self, stalled_threshold_seconds: float = 600.0) -> list[str]:
        """
        Identify and recover jobs that were running but have not updated their
        heartbeat within the threshold (e.g. crashed worker process).
        """
        now = time.time()
        cutoff = now - stalled_threshold_seconds
        recovered_ids: list[str] = []

        try:
            # Query running jobs older than cutoff
            with self.store.engine.connect() as conn:
                from sqlalchemy import text
                stmt = text("SELECT job_id, database_url, target_fingerprint FROM agent_jobs WHERE status = 'running' AND updated_at < :cutoff")
                rows = conn.execute(stmt, {"cutoff": cutoff}).fetchall()

                for row in rows:
                    jid = row[0]
                    db_url = row[1]
                    fp = row[2]
                    logger.warning("Recovering stalled onboarding job", job_id=jid, fingerprint=fp)
                    self.store.update_job_status(jid, status="pending", stage="recovered", error="Worker heartbeat timeout, re-queued.")
                    recovered_ids.append(jid)
                    # Re-dispatch
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self.run_onboarding_job(jid))
                    except RuntimeError:
                        pass
        except Exception as e:
            logger.error("Failed to recover stalled jobs", error=str(e))

        return recovered_ids

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Retrieve full details of a specific job."""
        return self.store.get_job(job_id)


_DURABLE_QUEUE: Optional[DurableJobQueue] = None


def get_durable_job_queue() -> DurableJobQueue:
    """Get singleton DurableJobQueue instance."""
    global _DURABLE_QUEUE
    if _DURABLE_QUEUE is None:
        _DURABLE_QUEUE = DurableJobQueue()
    return _DURABLE_QUEUE
