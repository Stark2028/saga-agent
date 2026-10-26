from sqlalchemy import select

from app.db.models import Revision, Step
from app.engine.contracts import (
    SagaError,
    SimulatedWorkerCrashError,
    UncertainWriteError,
)
from app.engine.state_machine import (
    CompensationStatus as C,
    RunStatus as R,
    StepStatus as S,
    VerificationStatus as V,
    transition,
)
from app.tools.chaos_middleware import ChaosConfig, consume_fault


async def compensate_revision(runtime, lease, revision_no, superseding=False):
    run = await runtime._run(lease.run_id)
    approval = await runtime._approval(run.id, revision_no)
    if approval and approval.status.value == "CONSUMED_FOR_DISPATCH":
        raise SagaError(
            "ROLL_FORWARD_REQUIRED",
            "Dispatch has been claimed; compensation is forbidden",
        )
    async with runtime.mutate(lease) as (_, current):
        transition(current, R.COMPENSATING)
    async with runtime.db.sessions() as session:
        steps = (
            await session.scalars(
                select(Step)
                .where(
                    Step.run_id == run.id,
                    Step.revision_no == revision_no,
                    Step.step_index.in_([1, 2]),
                )
                .order_by(Step.step_index.desc())
            )
        ).all()
    config = ChaosConfig.model_validate(run.chaos_config)
    for original in steps:
        step = original
        if step.compensation_status in (C.NOT_NEEDED, C.COMPENSATED):
            continue
        tool = runtime.tools[step.step_index]
        while True:
            if step.compensation_status in (
                C.IN_FLIGHT,
                C.OUTCOME_UNKNOWN,
                C.COMPENSATION_FAILED,
            ):
                verification = await tool.verify_compensation(
                    step.compensation_operation_id,
                    step.external_record_id,
                    run.sandbox_namespace,
                )
                async with runtime.mutate(lease) as (session, _):
                    row = await session.get(Step, step.id)
                    runtime.audit(
                        session,
                        row,
                        "COMPENSATE",
                        f"VERIFY_{verification.status.value}",
                        verification.model_dump(mode="json"),
                    )
                    if verification.status == V.APPLIED:
                        if row.status == S.COMPENSATION_FAILED:
                            transition(row, S.COMPENSATING)
                        transition(row, S.COMPENSATED)
                        row.compensation_status, row.compensation_evidence = (
                            C.COMPENSATED,
                            verification.model_dump(mode="json"),
                        )
                        break
                if verification.status == V.UNKNOWN:
                    await runtime.halt(
                        lease, f"UNRESOLVED_COMPENSATION: {step.external_record_id}"
                    )
                    return False
            if (
                step.compensation_attempt_count
                >= runtime.settings.max_compensation_attempts
            ):
                async with runtime.mutate(lease) as (session, _):
                    row = await session.get(Step, step.id)
                    if row.status != S.COMPENSATION_FAILED:
                        transition(row, S.COMPENSATION_FAILED)
                    row.compensation_status = C.COMPENSATION_FAILED
                await runtime.halt(
                    lease,
                    f"COMPENSATION_FAILED: uncompensated {step.external_record_id}",
                )
                return False
            async with runtime.mutate(lease) as (session, _):
                row = await session.get(Step, step.id)
                transition(row, S.COMPENSATING)
                row.compensation_status = C.IN_FLIGHT
                row.compensation_attempt_count += 1
                runtime.audit(session, row, "COMPENSATE", "STARTED")
            try:
                if config.fail_compensation_on_step == step.step_index:
                    raise SagaError(
                        "INJECTED_COMPENSATION_FAILURE",
                        "Injected corrective action failure",
                    )
                result = await tool.compensate(
                    run.sandbox_namespace,
                    step.compensation_operation_id,
                    step.external_record_id,
                )
                if (
                    config.crash_after_compensation_write_on_step == step.step_index
                    and await consume_fault(
                        runtime.db,
                        run.id,
                        revision_no,
                        "compensation_crash",
                        step.step_index,
                    )
                ):
                    raise SimulatedWorkerCrashError(
                        "Injected crash after corrective effect committed"
                    )
                if (
                    config.drop_compensation_response_on_step == step.step_index
                    and await consume_fault(
                        runtime.db,
                        run.id,
                        revision_no,
                        "compensation_drop",
                        step.step_index,
                    )
                ):
                    raise UncertainWriteError("Injected lost compensation response")
            except (SagaError, UncertainWriteError) as error:
                async with runtime.mutate(lease) as (session, _):
                    row = await session.get(Step, step.id)
                    row.compensation_status, row.error_detail = (
                        C.OUTCOME_UNKNOWN,
                        str(error),
                    )
                    runtime.audit(
                        session,
                        row,
                        "COMPENSATE",
                        "OUTCOME_UNKNOWN",
                        {"error": str(error)},
                    )
                step = await runtime._step(run.id, revision_no, step.step_index)
                continue
            async with runtime.mutate(lease) as (session, _):
                row = await session.get(Step, step.id)
                transition(row, S.COMPENSATED)
                row.compensation_status, row.compensation_evidence = (
                    C.COMPENSATED,
                    result.model_dump(mode="json"),
                )
                runtime.audit(
                    session, row, "COMPENSATE", "COMPENSATED", row.compensation_evidence
                )
            break
    async with runtime.mutate(lease) as (session, current):
        revision = await session.get(Revision, (run.id, revision_no))
        revision.status = "SUPERSEDED_COMPENSATED"
        transition(current, R.RUNNING if superseding else R.COMPENSATED_HALTED)
        current.error_summary = None
    return True
