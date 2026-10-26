import pytest
from sqlalchemy import select

from app.db.models import Run
from app.db.session import Database
from app.engine.contracts import SimulatedWorkerCrashError
from app.engine.runtime import Runtime
from conftest import create_run


async def test_abrupt_process_exit_preserves_lease_and_committed_effect(runtime):
    import asyncio
    import subprocess
    import sys
    from datetime import timedelta
    from app.db.models import now
    from app.engine.contracts import SagaError

    program = """
import asyncio, os, sys
from app.config import Settings
from app.db.session import Database
from app.engine.runtime import Runtime
async def main():
    db = Database(sys.argv[1])
    runtime = Runtime(db, Settings(hmac_secret="test-secret-for-approvals-at-least-32-chars"))
    execute = runtime.tools[1].execute
    async def kill_after_commit(*args, **kwargs):
        await execute(*args, **kwargs)
        os._exit(17)
    runtime.tools[1].execute = kill_after_commit
    await runtime.create("Crash customer", "buyer@example.test", "10 x APL-001")
asyncio.run(main())
"""
    process = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program, str(runtime.db.engine.url)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 17, process.stderr
    async with runtime.db.sessions() as session:
        run = await session.scalar(select(Run))
        run_id = run.id
        assert run.lease_owner is not None
    with pytest.raises(SagaError, match="locked by an active worker"):
        await runtime.resume(run_id)
    # Advance the durable expiry instead of sleeping through the 30-second lease.
    async with runtime.db.transaction() as session:
        row = await session.get(Run, run_id)
        row.lease_expires_at = now() - timedelta(seconds=1)
    trace = await runtime.resume(run_id)
    assert trace["run"]["status"] == "AWAITING_APPROVAL"
    assert len(trace["external_records"]["holds"]) == 1
    assert trace["steps"][1]["attempt_count"] == 1


@pytest.mark.parametrize(
    "fault,index",
    [
        ("crash_worker_after_step_in_flight", 1),
        ("crash_after_external_commit_on_step", 1),
        ("crash_after_external_commit_on_step", 2),
    ],
)
async def test_crash_recovers_in_fresh_engine(runtime, settings, fault, index):
    with pytest.raises(SimulatedWorkerCrashError):
        await create_run(runtime, {fault: index})
    async with runtime.db.sessions() as session:
        run_id = (await session.scalar(select(Run))).id
    database = Database(str(runtime.db.engine.url))
    try:
        fresh = Runtime(database, settings)
        trace = await fresh.resume(run_id)
        assert trace["run"]["status"] == "AWAITING_APPROVAL"
        assert len(trace["external_records"]["holds"]) == 1
        assert len(trace["external_records"]["quotes"]) == 1
        assert trace["steps"][0]["output_payload"] == trace["run"]["agent_plan"]
    finally:
        await database.close()
