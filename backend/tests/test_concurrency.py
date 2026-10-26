import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.db.models import Run, Stock, now
from app.engine.contracts import SagaError
from conftest import approve, create_run


async def test_concurrent_lease_acquisition_has_one_winner(runtime):
    trace = await create_run(runtime)
    results = await asyncio.gather(
        runtime.acquire(trace["run"]["id"]),
        runtime.acquire(trace["run"]["id"]),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, SagaError)]
    assert len(winners) == len(failures) == 1
    assert failures[0].code == "RUN_LOCKED"
    await runtime.release(winners[0])


async def test_expired_owner_cannot_commit_after_takeover(runtime):
    trace = await create_run(runtime)
    first = await runtime.acquire(trace["run"]["id"])
    async with runtime.db.transaction() as session:
        await session.execute(
            update(Run)
            .where(Run.id == first.run_id)
            .values(lease_expires_at=now() - timedelta(seconds=1))
        )
    second = await runtime.acquire(first.run_id)
    with pytest.raises(SagaError, match="expired or run version changed"):
        async with runtime.mutate(first) as (_, run):
            run.error_summary = "stale writer"
    await runtime.release(first)
    async with runtime.mutate(second) as (_, run):
        assert run.error_summary is None
    await runtime.release(second)


async def test_version_conflict_blocks_commit(runtime):
    trace = await create_run(runtime)
    lease = await runtime.acquire(trace["run"]["id"])
    async with runtime.db.transaction() as session:
        await session.execute(
            update(Run).where(Run.id == lease.run_id).values(version=Run.version + 1)
        )
    with pytest.raises(SagaError, match="version changed"):
        async with runtime.mutate(lease):
            pass
    await runtime.release(lease)


async def test_concurrent_approve_and_revise_cannot_send_stale_email(runtime):
    trace = await create_run(runtime)
    results = await asyncio.gather(
        approve(runtime, trace),
        runtime.revise(trace["run"]["id"], "14 x APL-001"),
        return_exceptions=True,
    )
    current = await runtime.trace(trace["run"]["id"])
    for result in results:
        if isinstance(result, Exception):
            assert isinstance(result, SagaError)
            assert result.status_code == 409
    if current["run"]["active_revision_no"] == 2:
        assert not current["external_records"]["emails"]
    else:
        assert current["run"]["status"] == "COMPLETED"
        assert len(current["external_records"]["emails"]) == 1


async def test_concurrent_reservations_cannot_oversell(runtime):
    async with runtime.db.transaction() as session:
        row = await session.get(Stock, ("live", "APL-001"))
        row.available_qty = 10
    results = await asyncio.gather(create_run(runtime), create_run(runtime))
    assert sum(t["run"]["status"] == "AWAITING_APPROVAL" for t in results) == 1
    stock = next(
        s for s in results[-1]["external_records"]["stock"] if s["sku"] == "APL-001"
    )
    assert stock["available_qty"] == 0
    assert stock["reserved_qty"] == 10
