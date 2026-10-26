import pytest

from app.engine.contracts import SagaError
from conftest import approve, create_run


@pytest.mark.parametrize("index", [0, 1, 2, 3])
async def test_historical_fork_remaps_records_and_keeps_live_unchanged(runtime, index):
    trace = await create_run(runtime)
    trace = await approve(runtime, trace)
    parent_id = trace["run"]["id"]
    before = trace["external_records"]
    child = await runtime.fork(parent_id, index)
    assert child["run"]["execution_mode"] == "SANDBOX"
    assert child["run"]["status"] == "AWAITING_APPROVAL"
    assert child["run"]["parent_run_id"] == parent_id
    assert child["approvals"][0]["status"] == "PENDING"
    assert not child["external_records"]["emails"]
    for records in child["external_records"].values():
        assert all(r["namespace"] == child["run"]["sandbox_namespace"] for r in records)
    assert all(
        q["quote_id"] != before["quotes"][0]["quote_id"]
        for q in child["external_records"]["quotes"]
    )
    child = await approve(runtime, child)
    assert child["run"]["status"] == "COMPLETED"
    assert (await runtime.trace(parent_id))["external_records"] == before
    # The live run already consumed 10; its BEFORE_STEP checkpoint still had 1000.
    live_stock = next(s for s in before["stock"] if s["sku"] == "APL-001")
    child_stock = next(
        s for s in child["external_records"]["stock"] if s["sku"] == "APL-001"
    )
    assert live_stock["fulfilled_qty"] == child_stock["fulfilled_qty"] == 10
    assert child_stock["available_qty"] == 990


async def test_changed_plan_cannot_reuse_incompatible_prefix(runtime):
    trace = await create_run(runtime)
    plan = trace["run"]["agent_plan"]
    changed = {
        **plan,
        "line_items": [{**plan["line_items"][0], "qty": 14}],
        "total_amount": plan["total_amount"] // 10 * 14,
    }
    with pytest.raises(SagaError, match="Changed plan"):
        await runtime.fork(trace["run"]["id"], 2, override_plan=changed)
    child = await runtime.fork(trace["run"]["id"], 1, override_plan=changed)
    assert child["external_records"]["holds"][0]["items"][0]["qty"] == 14
    assert child["steps"][0]["output_payload"] == child["run"]["agent_plan"]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
async def test_fork_of_revised_run_keeps_distinct_historical_operations(runtime, index):
    trace = await create_run(runtime)
    trace = await runtime.revise(trace["run"]["id"], "14 x APL-001")
    before = trace["external_records"]
    child = await runtime.fork(trace["run"]["id"], index, revision_no=2)
    assert child["run"]["status"] == "AWAITING_APPROVAL"
    holds = child["external_records"]["holds"]
    assert len({h["operation_id"] for h in holds}) == len(holds)
    assert sum(h["status"] == "ACTIVE" for h in holds) == 1
    child = await approve(runtime, child)
    assert child["run"]["status"] == "COMPLETED"
    assert (await runtime.trace(trace["run"]["id"]))["external_records"] == before


async def test_fork_can_replay_old_revision_after_superseding(runtime):
    trace = await create_run(runtime)
    trace = await runtime.revise(trace["run"]["id"], "14 x APL-001")
    child = await runtime.fork(trace["run"]["id"], 2, revision_no=1)
    assert child["run"]["agent_plan"]["line_items"][0]["qty"] == 10
    assert child["external_records"]["holds"][0]["status"] == "ACTIVE"
