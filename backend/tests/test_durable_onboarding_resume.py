import asyncio

import pytest

from app.jobs.durable_queue import DurableJobQueue


class _Store:
    def __init__(self):
        self.status_updates = []

    def get_job(self, _job_id):
        return {
            "job_id": "job-1",
            "target_fingerprint": "fingerprint",
            "database_url": "sqlite:///ignored.db",
        }

    def update_job_status(self, job_id, **kwargs):
        self.status_updates.append((job_id, kwargs))


@pytest.mark.asyncio
async def test_cancelled_onboarding_job_is_queued_for_resume(monkeypatch):
    store = _Store()
    queue = DurableJobQueue(store=store)

    class _Lock:
        def __enter__(self):
            return True

        def __exit__(self, *_args):
            return False

    class _Redis:
        def acquire_lock(self, *_args, **_kwargs):
            return _Lock()

    class _CancelledCatalogBuilder:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_or_build(self):
            raise asyncio.CancelledError

    monkeypatch.setattr("app.jobs.durable_queue.get_redis_coordinator", lambda: _Redis())
    monkeypatch.setattr("app.jobs.durable_queue.set_build_progress", lambda *_args: None)
    monkeypatch.setattr("app.jobs.durable_queue.CatalogBuilder", _CancelledCatalogBuilder)

    with pytest.raises(asyncio.CancelledError):
        await queue.run_onboarding_job("job-1")

    assert store.status_updates[-1] == (
        "job-1",
        {
            "status": "pending",
            "stage": "queued",
            "error": "Onboarding interrupted by server shutdown; queued for resume.",
        },
    )
