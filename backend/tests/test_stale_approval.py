import pytest

from app.db.models import Approval
from app.engine.contracts import SagaError, SimulatedWorkerCrashError
from conftest import approve, create_run


async def test_revision_invalidates_old_approval_and_releases_old_resources(runtime):
    trace = await create_run(runtime)
    old_hash = trace["run"]["state_hash"]
    run_id = trace["run"]["id"]
    await approve(runtime, trace, auto_execute_dispatch=False)
    trace = await runtime.revise(run_id, "14 x APL-001")
    assert trace["run"]["active_revision_no"] == 2
    assert trace["run"]["state_hash"] != old_hash
    assert trace["run"]["status"] == "AWAITING_APPROVAL"
    assert trace["approvals"][0]["status"] == "INVALIDATED_STALE"
    assert trace["revisions"][0]["agent_plan"]["line_items"][0]["qty"] == 10
    assert trace["revisions"][0]["status"] == "SUPERSEDED_COMPENSATED"
    assert not trace["external_records"]["emails"]
    assert sorted(h["status"] for h in trace["external_records"]["holds"]) == [
        "ACTIVE",
        "RELEASED",
    ]
    with pytest.raises(SagaError, match="stale"):
        await runtime.approve(run_id, "manager", 1, old_hash)
    trace = await approve(runtime, trace)
    assert trace["run"]["status"] == "COMPLETED"
    assert len(trace["external_records"]["emails"]) == 1
    assert '"qty":14' in trace["external_records"]["emails"][0]["body_summary"]


async def test_failed_superseding_compensation_blocks_new_revision(runtime):
    trace = await create_run(runtime)
    trace = await runtime.revise(
        trace["run"]["id"], "14 x APL-001", {"fail_compensation_on_step": 1}
    )
    assert trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
    assert len(trace["revisions"]) == 2
    assert not any(s["revision_no"] == 2 for s in trace["steps"])
    assert len(trace["external_records"]["holds"]) == 1


async def test_claim_blocks_revision_even_before_email_send(runtime):
    trace = await create_run(runtime)
    with pytest.raises(SimulatedWorkerCrashError):
        await approve(runtime, trace, chaos_config={"crash_after_dispatch_claim": True})
    current = await runtime.trace(trace["run"]["id"])
    assert current["run"]["status"] == "DISPATCHING_FINAL"
    assert not current["external_records"]["emails"]
    with pytest.raises(SagaError, match="Cannot revise"):
        await runtime.revise(trace["run"]["id"], "14 x APL-001")
    current = await runtime.resume(trace["run"]["id"])
    assert current["run"]["status"] == "COMPLETED"


async def test_tampered_frozen_payload_fails_hmac_bound_hash(runtime):
    trace = await create_run(runtime)
    trace = await approve(runtime, trace, auto_execute_dispatch=False)
    async with runtime.db.transaction() as session:
        row = await session.get(Approval, trace["approvals"][0]["id"])
        row.frozen_dispatch_payload = {
            **row.frozen_dispatch_payload,
            "recipient": "attacker@example.test",
        }
    with pytest.raises(SagaError, match="does not match"):
        await runtime.resume(trace["run"]["id"])
    assert not (await runtime.trace(trace["run"]["id"]))["external_records"]["emails"]
