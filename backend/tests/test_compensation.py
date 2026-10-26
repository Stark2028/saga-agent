import pytest

from app.engine.contracts import SimulatedWorkerCrashError
from conftest import create_run


def stock(trace):
    return next(s for s in trace["external_records"]["stock"] if s["sku"] == "APL-001")


async def test_rejection_compensates_in_reverse_order(runtime):
    trace = await create_run(runtime)
    trace = await runtime.reject(trace["run"]["id"], "manager", "Margin too low")
    assert trace["run"]["status"] == "COMPENSATED_HALTED"
    assert trace["external_records"]["quotes"][0]["status"] == "VOIDED"
    assert trace["external_records"]["holds"][0]["status"] == "RELEASED"
    assert stock(trace)["available_qty"] == 1000
    step_by_id = {s["id"]: s["step_index"] for s in trace["steps"]}
    order = [
        step_by_id[a["step_id"]]
        for a in trace["attempts"]
        if a["kind"] == "COMPENSATE" and a["event"] == "STARTED"
    ]
    assert order == [2, 1]


async def test_failed_compensation_surfaces_exact_resource(runtime):
    trace = await create_run(runtime)
    hold_id = trace["external_records"]["holds"][0]["hold_id"]
    trace = await runtime.reject(
        trace["run"]["id"], "manager", "No", {"fail_compensation_on_step": 1}
    )
    assert trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
    assert hold_id in trace["run"]["error_summary"]
    assert trace["steps"][1]["compensation_attempt_count"] == 3
    assert trace["steps"][1]["compensation_status"] == "COMPENSATION_FAILED"
    assert trace["external_records"]["quotes"][0]["status"] == "VOIDED"
    assert trace["external_records"]["holds"][0]["status"] == "ACTIVE"


@pytest.mark.parametrize("index", [1, 2])
async def test_crash_after_compensation_commit_is_reconciled(runtime, index):
    trace = await create_run(runtime)
    run_id = trace["run"]["id"]
    with pytest.raises(SimulatedWorkerCrashError):
        await runtime.reject(
            run_id, "manager", "No", {"crash_after_compensation_write_on_step": index}
        )
    trace = await runtime.resume(run_id)
    assert trace["run"]["status"] == "COMPENSATED_HALTED"
    assert stock(trace)["available_qty"] == 1000
    assert stock(trace)["reserved_qty"] == 0
    step = trace["steps"][1]
    await runtime.tools[1].compensate(
        "live", step["compensation_operation_id"], step["external_record_id"]
    )
    assert stock(await runtime.trace(run_id))["available_qty"] == 1000


async def test_lost_compensation_response_does_not_repeat_release(runtime):
    trace = await create_run(runtime)
    trace = await runtime.reject(
        trace["run"]["id"], "manager", "No", {"drop_compensation_response_on_step": 1}
    )
    assert trace["run"]["status"] == "COMPENSATED_HALTED"
    assert trace["steps"][1]["compensation_attempt_count"] == 1
    assert stock(trace)["available_qty"] == 1000
