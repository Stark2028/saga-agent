import pytest

from app.engine.contracts import SagaError
from app.engine.state_machine import VerificationStatus as V
from conftest import create_run


async def test_dropped_crm_response_reconciles_without_duplicates(runtime):
    trace = await create_run(runtime, {"drop_response_after_write_on_step": 2})
    assert trace["run"]["status"] == "RECONCILING"
    assert trace["steps"][2]["status"] == "OUTCOME_UNKNOWN"
    assert len(trace["external_records"]["quotes"]) == 1
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "AWAITING_APPROVAL"
    assert trace["steps"][2]["attempt_count"] == 1
    assert len(trace["external_records"]["quotes"]) == 1
    assert trace["steps"][2]["verification_evidence"]["status"] == "APPLIED"


async def test_fenced_prewrite_timeout_retries_new_generation(runtime):
    trace = await create_run(runtime, {"transient_timeout_before_write_on_step": 1})
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "AWAITING_APPROVAL"
    assert trace["steps"][1]["attempt_count"] == 2
    assert len(trace["external_records"]["holds"]) == 1
    assert any(a["event"] == "DEFINITIVELY_NOT_APPLIED" for a in trace["attempts"])


async def test_unknown_never_blindly_reexecutes(runtime):
    trace = await create_run(
        runtime,
        {"drop_response_after_write_on_step": 2, "keep_verification_unknown": True},
    )
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
    assert trace["run"]["error_summary"] == "UNRESOLVED_UNCERTAIN_SIDE_EFFECT"
    assert trace["steps"][2]["reconcile_polls"] == 3
    assert trace["steps"][2]["attempt_count"] == 1
    assert len(trace["external_records"]["quotes"]) == 1


async def test_destination_rejects_late_fenced_generation(runtime):
    tool = runtime.tools[2]
    await tool.prepare("live", "late-operation", 1, expired=True)
    result = await tool.verify("live", "late-operation")
    assert result.status == V.DEFINITIVELY_NOT_APPLIED
    payload = {"customer_email": "x@example.test", "total_amount": 1, "line_items": []}
    with pytest.raises(SagaError, match="Destination rejected"):
        await tool.execute("live", "late-operation", 1, "test", payload)
    await tool.prepare("live", "late-operation", 2)
    result = await tool.execute("live", "late-operation", 2, "test", payload)
    assert result.external_record_id
    with pytest.raises(SagaError):
        await tool.execute("live", "late-operation", 1, "test", payload)


async def test_unexpired_attempt_remains_unknown(runtime):
    await runtime.tools[2].prepare("live", "unexpired", 1)
    assert (await runtime.tools[2].verify("live", "unexpired")).status == V.UNKNOWN
