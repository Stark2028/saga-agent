import pytest

from app.engine.contracts import SagaError, SimulatedWorkerCrashError
from conftest import approve, create_run


@pytest.mark.parametrize("index", [4, 5])
async def test_uncertain_terminal_step_recovers_forward(runtime, index):
    trace = await create_run(runtime)
    trace = await approve(
        runtime, trace, chaos_config={"drop_response_after_write_on_step": index}
    )
    assert trace["run"]["status"] == "RECONCILING"
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "COMPLETED"
    assert len(trace["external_records"]["emails"]) == 1
    assert trace["external_records"]["quotes"][0]["status"] == "SENT"
    assert trace["external_records"]["holds"][0]["status"] == "COMMITTED_CONVERTED"
    stock = next(s for s in trace["external_records"]["stock"] if s["sku"] == "APL-001")
    assert (stock["available_qty"], stock["reserved_qty"], stock["fulfilled_qty"]) == (
        990,
        0,
        10,
    )


async def test_finalizer_prewrite_failure_resumes_without_resending(runtime):
    trace = await create_run(runtime)
    trace = await approve(runtime, trace, chaos_config={"fail_finalization_once": True})
    assert len(trace["external_records"]["emails"]) == 1
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "COMPLETED"
    assert trace["steps"][5]["attempt_count"] == 2
    assert len(trace["external_records"]["emails"]) == 1


async def test_unknown_email_outcome_blocks_revision_and_compensation(runtime):
    trace = await create_run(runtime)
    trace = await approve(
        runtime,
        trace,
        chaos_config={
            "drop_response_after_write_on_step": 4,
            "keep_verification_unknown": True,
        },
    )
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
    with pytest.raises(SagaError, match="Cannot revise"):
        await runtime.revise(trace["run"]["id"], "14 x APL-001")
    with pytest.raises(SagaError):
        await runtime.reject(trace["run"]["id"], "manager", "Stop")
    trace = await runtime.resume(trace["run"]["id"], {})
    assert trace["run"]["status"] == "COMPLETED"
    assert len(trace["external_records"]["emails"]) == 1


async def test_known_aborted_finalizer_can_be_repaired_and_retried_forward(runtime):
    trace = await create_run(runtime)
    finalizer = runtime.tools[5]
    original = finalizer.apply

    async def unavailable(*args, **kwargs):
        raise SagaError(
            "FINALIZER_UNAVAILABLE", "Known transaction abort before commit"
        )

    finalizer.apply = unavailable
    trace = await approve(runtime, trace)
    assert trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
    assert trace["steps"][5]["status"] == "FAILED_RETRYABLE"
    assert trace["external_records"]["holds"][0]["status"] == "ACTIVE"
    finalizer.apply = original
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "COMPLETED"
    assert len(trace["external_records"]["emails"]) == 1
    assert trace["steps"][5]["attempt_count"] == 2


@pytest.mark.parametrize("index", [4, 5])
async def test_crash_after_terminal_effect_recovers_without_resend(runtime, index):
    trace = await create_run(runtime)
    with pytest.raises(SimulatedWorkerCrashError):
        await approve(
            runtime, trace, chaos_config={"crash_after_external_commit_on_step": index}
        )
    trace = await runtime.resume(trace["run"]["id"])
    assert trace["run"]["status"] == "COMPLETED"
    assert len(trace["external_records"]["emails"]) == 1
