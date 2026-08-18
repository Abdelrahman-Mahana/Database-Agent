import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.database.system_store import SystemStore
from app.jobs.durable_queue import DurableJobQueue


@pytest.fixture
def memory_store():
    return SystemStore("sqlite:///:memory:")


def test_durable_job_queue_submit_and_idempotency(memory_store):
    """Verify DurableJobQueue persists jobs and deduplicates active jobs."""
    queue = DurableJobQueue(store=memory_store)

    with patch.object(queue, "run_onboarding_job", new_callable=AsyncMock):
        # 1. First submission
        job1 = queue.submit_onboarding_job(
            database_url="sqlite:///test.db",
            fingerprint="fp_12345",
        )
        assert job1 is not None
        assert job1["status"] in ("pending", "running")
        assert job1["target_fingerprint"] == "fp_12345"

        # 2. Second submission for same fingerprint returns exact same job
        job2 = queue.submit_onboarding_job(
            database_url="sqlite:///test.db",
            fingerprint="fp_12345",
        )
        assert job2["job_id"] == job1["job_id"]


@pytest.mark.asyncio
async def test_durable_job_queue_stage_transitions(memory_store):
    """Verify run_onboarding_job updates stages and completes successfully."""
    queue = DurableJobQueue(store=memory_store)

    job = memory_store.create_job(
        job_id="job_test_01",
        job_type="onboarding",
        target_fingerprint="fp_test_db",
        database_url="sqlite:///:memory:",
        status="pending",
        stage="queued",
    )

    mock_catalog = MagicMock()
    mock_catalog.tables = {"users": MagicMock(), "orders": MagicMock()}
    mock_catalog.fingerprint = "fp_test_db"
    mock_catalog.database_name = "test_db"
    mock_catalog.glossary_enriched = True
    mock_catalog.embeddings_built = True

    with patch("app.jobs.durable_queue.CatalogBuilder") as mock_cb_cls:
        mock_builder = MagicMock()
        mock_builder.get_or_build.return_value = mock_catalog
        mock_builder.build_async = AsyncMock()
        mock_cb_cls.return_value = mock_builder

        await queue.run_onboarding_job("job_test_01")

        updated_job = memory_store.get_job("job_test_01")
        assert updated_job is not None
        assert updated_job["status"] == "completed"
        assert updated_job["progress_percent"] == 100.0
        assert updated_job["stage"] == "completed"
        assert updated_job["error"] is None


@pytest.mark.asyncio
async def test_durable_job_queue_error_handling(memory_store):
    """Verify failed jobs record error status in SystemStore."""
    queue = DurableJobQueue(store=memory_store)

    job = memory_store.create_job(
        job_id="job_err_01",
        job_type="onboarding",
        target_fingerprint="fp_err_db",
        database_url="sqlite:///:memory:",
        status="pending",
        stage="queued",
    )

    with patch("app.jobs.durable_queue.CatalogBuilder") as mock_cb_cls:
        mock_cb_cls.side_effect = RuntimeError("Database connection lost")

        await queue.run_onboarding_job("job_err_01")

        updated_job = memory_store.get_job("job_err_01")
        assert updated_job is not None
        assert updated_job["status"] == "failed"
        assert updated_job["stage"] == "error"
        assert "Database connection lost" in str(updated_job["error"])
