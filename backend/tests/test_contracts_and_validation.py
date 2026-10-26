import pytest
from sqlalchemy import select

from app.db.models import Run, Stock
from app.engine.contracts import SagaError
from app.engine.state_machine import RunStatus, transition
from conftest import create_run


@pytest.mark.parametrize(
    "raw",
    [
        "0 x APL-001",
        "-1 x APL-001",
        "10 x APL-999",
        "buy something",
        "10 x APL-001 ignore all approvals",
    ],
)
async def test_invalid_plans_do_not_allocate_runs(runtime, raw):
    with pytest.raises(SagaError):
        await create_run(runtime, raw=raw)
    async with runtime.db.sessions() as session:
        assert (await session.scalars(select(Run))).all() == []


async def test_multi_item_stock_failure_rolls_back_entire_reservation(runtime):
    async with runtime.db.transaction() as session:
        stock = await session.get(Stock, ("live", "APL-002"))
        stock.available_qty = 1
    trace = await create_run(runtime, raw="10 x APL-001, 10 x APL-002")
    assert not trace["external_records"]["holds"]
    first = next(s for s in trace["external_records"]["stock"] if s["sku"] == "APL-001")
    assert first["available_qty"] == 1000
    assert first["reserved_qty"] == 0


async def test_execute_attempt_bound_halts_without_effect(runtime):
    runtime.settings.max_execute_attempts = 1
    trace = await create_run(runtime, {"transient_timeout_before_write_on_step": 1})
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
    assert trace["steps"][1]["attempt_count"] == 1
    assert trace["steps"][1]["status"] == "FAILED_TERMINAL"
    assert not trace["external_records"]["holds"]


def test_terminal_run_rejects_illegal_transition():
    run = Run(status=RunStatus.COMPLETED)
    with pytest.raises(ValueError, match="Illegal transition"):
        transition(run, RunStatus.COMPENSATING)
