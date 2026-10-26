from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import NAMESPACE_OID, uuid5

from sqlalchemy import select, update

from app.agent.planner import plan_rfq
from app.agent.company import validate_task_plan
from app.db.models import (
    Approval,
    Attempt,
    Checkpoint,
    Email,
    Hold,
    Quote,
    Revision,
    Run,
    Step,
    Stock,
    now,
    uid,
)
from app.engine.approval import signature, state_hash, verify_signature
from app.engine.contracts import (
    SagaError,
    SimulatedWorkerCrashError,
    UncertainWriteError,
)
from app.engine.state_machine import (
    ApprovalStatus as A,
    CompensationStatus as C,
    RunStatus as R,
    StepStatus as S,
    VerificationStatus as V,
    transition,
)
from app.tools.chaos_middleware import ChaosConfig, consume_fault
from app.tools.crm_tool import CRMTool
from app.tools.email_tool import EmailTool
from app.tools.finalizer_tool import FinalizerTool
from app.tools.inventory_tool import InventoryTool

STEP_NAMES = [
    "parse_and_match_rfq",
    "reserve_inventory",
    "create_crm_draft",
    "await_human_approval",
    "dispatch_quote_email",
    "finalize_quote_and_inventory",
]
TOOL_NAMES = [
    "planner",
    "inventory_tool",
    "crm_tool",
    "approval_gate",
    "email_tool",
    "finalizer_tool",
]


def operation_id(run_id, revision_no, index, compensation=False):
    return str(
        uuid5(
            NAMESPACE_OID,
            f"{'comp:' if compensation else ''}{run_id}:{revision_no}:{index}",
        )
    )


@dataclass
class Lease:
    run_id: str
    owner: str
    version: int


class Runtime:
    def __init__(self, db, settings):
        settings.validate()
        self.db, self.settings = db, settings
        self.tools = {
            1: InventoryTool(db, settings),
            2: CRMTool(db, settings),
            4: EmailTool(db, settings),
            5: FinalizerTool(db, settings),
        }

    async def acquire(self, run_id):
        owner = uid()
        async with self.db.transaction() as session:
            result = await session.execute(
                update(Run)
                .where(
                    Run.id == run_id,
                    (Run.lease_owner.is_(None)) | (Run.lease_expires_at < now()),
                )
                .values(
                    lease_owner=owner,
                    lease_expires_at=now()
                    + timedelta(seconds=self.settings.lease_seconds),
                    version=Run.version + 1,
                )
            )
            if result.rowcount != 1:
                if await session.get(Run, run_id) is None:
                    raise SagaError("RUN_NOT_FOUND", "Run does not exist", 404)
                raise SagaError("RUN_LOCKED", "Run is locked by an active worker")
            run = await session.get(Run, run_id)
            return Lease(run_id, owner, run.version)

    @asynccontextmanager
    async def mutate(self, lease):
        async with self.db.transaction() as session:
            run = await session.get(Run, lease.run_id, with_for_update=True)
            if (
                not run
                or run.lease_owner != lease.owner
                or run.version != lease.version
                or run.lease_expires_at <= now()
            ):
                raise SagaError(
                    "LEASE_LOST", "Worker lease expired or run version changed"
                )
            yield session, run
            await session.flush()
            result = await session.execute(
                update(Run)
                .where(
                    Run.id == lease.run_id,
                    Run.version == lease.version,
                    Run.lease_owner == lease.owner,
                    Run.lease_expires_at > now(),
                )
                .values(
                    version=Run.version + 1,
                    lease_expires_at=now()
                    + timedelta(seconds=self.settings.lease_seconds),
                    updated_at=now(),
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise SagaError("LEASE_LOST", "Run changed before commit")
        lease.version += 1

    async def release(self, lease):
        async with self.db.transaction() as session:
            await session.execute(
                update(Run)
                .where(Run.id == lease.run_id, Run.lease_owner == lease.owner)
                .values(
                    lease_owner=None, lease_expires_at=None, version=Run.version + 1
                )
            )

    @asynccontextmanager
    async def invocation(self, run_id, chaos_config=None):
        lease = await self.acquire(run_id)
        try:
            if chaos_config is not None:
                async with self.mutate(lease) as (_, run):
                    run.chaos_config = ChaosConfig.model_validate(
                        chaos_config
                    ).model_dump()
            yield lease
        except SimulatedWorkerCrashError as error:
            error.run_id = run_id
            raise
        finally:
            # Simulated crashes release the invocation lease for immediate demonstrations.
            # A genuinely killed process leaves the lease until its 30-second expiry.
            await self.release(lease)

    async def _run(self, run_id):
        async with self.db.sessions() as session:
            run = await session.get(Run, run_id)
            if not run:
                raise SagaError("RUN_NOT_FOUND", "Run does not exist", 404)
            return run

    async def _step(self, run_id, revision_no, index):
        async with self.db.sessions() as session:
            return await session.scalar(
                select(Step).where(
                    Step.run_id == run_id,
                    Step.revision_no == revision_no,
                    Step.step_index == index,
                )
            )

    async def _approval(self, run_id, revision_no):
        async with self.db.sessions() as session:
            return await session.scalar(
                select(Approval).where(
                    Approval.run_id == run_id, Approval.revision_no == revision_no
                )
            )

    async def create(
        self,
        customer_name,
        customer_email,
        raw_request,
        chaos_config=None,
        scenario_id=None,
        auto_pause_at_approval=True,
        run_id=None,
        task_context=None,
    ):
        rfq = {
            "customer_name": customer_name,
            "customer_email": customer_email,
            "raw_request": raw_request,
            "scenario_id": scenario_id,
        }
        if task_context is not None:
            rfq["task_context"] = task_context
        if run_id is not None:
            async with self.db.sessions() as session:
                existing = await session.get(Run, run_id)
            if existing:
                if existing.rfq_payload != rfq:
                    raise SagaError("TASK_RUN_CONFLICT", "Allocated run has a different immutable request")
                return await self.trace(run_id)
        # Validate before allocating a run. Persist the plan exactly once.
        plan = await plan_rfq(self.db, "live", rfq)
        validate_task_plan(plan, rfq)
        run = Run(
            **({"id": run_id} if run_id is not None else {}),
            rfq_payload=rfq,
            agent_plan=plan,
            chaos_config=ChaosConfig.model_validate(chaos_config or {}).model_dump(),
        )
        async with self.db.transaction() as session:
            session.add(run)
            await session.flush()
            session.add(
                Revision(run_id=run.id, revision_no=1, rfq_payload=rfq, agent_plan=plan)
            )
        await self.resume(run.id)
        return await self.trace(run.id)

    async def resume(self, run_id, chaos_config=None):
        async with self.invocation(run_id, chaos_config) as lease:
            await self.drive(lease)
        return await self.trace(run_id)

    async def ensure_steps(self, lease):
        async with self.mutate(lease) as (session, run):
            for index, name in enumerate(STEP_NAMES):
                existing = await session.scalar(
                    select(Step).where(
                        Step.run_id == run.id,
                        Step.revision_no == run.active_revision_no,
                        Step.step_index == index,
                    )
                )
                if not existing:
                    session.add(
                        Step(
                            run_id=run.id,
                            revision_no=run.active_revision_no,
                            step_index=index,
                            step_name=name,
                            tool_name=TOOL_NAMES[index],
                            operation_id=operation_id(
                                run.id, run.active_revision_no, index
                            ),
                            compensation_operation_id=operation_id(
                                run.id, run.active_revision_no, index, True
                            ),
                        )
                    )

    async def checkpoint(self, lease, index, phase):
        async with self.mutate(lease) as (session, run):
            key = (run.id, run.active_revision_no, index, phase)
            if await session.get(Checkpoint, key):
                return
            stock = (
                await session.scalars(
                    select(Stock).where(Stock.namespace == run.sandbox_namespace)
                )
            ).all()
            holds = (
                await session.scalars(
                    select(Hold).where(
                        Hold.namespace == run.sandbox_namespace, Hold.run_id == run.id
                    )
                )
            ).all()
            quotes = (
                await session.scalars(
                    select(Quote).where(
                        Quote.namespace == run.sandbox_namespace, Quote.run_id == run.id
                    )
                )
            ).all()
            steps = (
                await session.scalars(
                    select(Step)
                    .where(
                        Step.run_id == run.id,
                        Step.revision_no == run.active_revision_no,
                    )
                    .order_by(Step.step_index)
                )
            ).all()
            session.add(
                Checkpoint(
                    run_id=run.id,
                    revision_no=run.active_revision_no,
                    step_index=index,
                    phase=phase,
                    inventory_snapshot={
                        "stock": [s.model_dump(mode="json") for s in stock],
                        "holds": [s.model_dump(mode="json") for s in holds],
                    },
                    crm_quotes_snapshot=[q.model_dump(mode="json") for q in quotes],
                    revision_snapshot={
                        "rfq_payload": run.rfq_payload,
                        "agent_plan": run.agent_plan,
                        "state_hash": run.state_hash,
                        "steps": [s.model_dump(mode="json") for s in steps],
                    },
                )
            )

    async def halt(self, lease, reason):
        async with self.mutate(lease) as (_, run):
            transition(run, R.FAILED_NEEDS_HUMAN)
            run.error_summary = reason

    def audit(self, session, step, kind, event, evidence=None):
        session.add(
            Attempt(
                run_id=step.run_id,
                step_id=step.id,
                kind=kind,
                attempt_no=step.compensation_attempt_count
                if kind == "COMPENSATE"
                else step.attempt_count,
                event=event,
                evidence=evidence or {},
            )
        )

    async def payload(self, run, index):
        if index == 1:
            return run.agent_plan
        if index == 2:
            return {
                **run.agent_plan,
                "customer_email": run.rfq_payload["customer_email"],
            }
        if index == 4:
            return (
                await self._approval(run.id, run.active_revision_no)
            ).frozen_dispatch_payload
        return {
            "quote_id": (
                await self._step(run.id, run.active_revision_no, 2)
            ).external_record_id,
            "hold_id": (
                await self._step(run.id, run.active_revision_no, 1)
            ).external_record_id,
        }

    async def reconcile(self, lease, index):
        run = await self._run(lease.run_id)
        step = await self._step(run.id, run.active_revision_no, index)
        config = ChaosConfig.model_validate(run.chaos_config)
        for _ in range(self.settings.max_reconcile_polls):
            result = await self.tools[index].verify(
                run.sandbox_namespace,
                step.operation_id,
                keep_unknown=config.keep_verification_unknown,
                attempt_no=step.attempt_count,
                deadline_at=(step.started_at or now())
                + timedelta(seconds=self.settings.operation_timeout_seconds),
            )
            async with self.mutate(lease) as (session, current):
                row = await session.get(Step, step.id)
                if row.status == S.IN_FLIGHT:
                    transition(row, S.OUTCOME_UNKNOWN)
                row.verification_evidence = result.model_dump(mode="json")
                self.audit(
                    session,
                    row,
                    "VERIFY",
                    result.status.value,
                    row.verification_evidence,
                )
                if result.status == V.APPLIED:
                    transition(row, S.COMMITTED)
                    row.external_record_id, row.output_payload, row.completed_at = (
                        result.external_record_id,
                        result.output_payload,
                        now(),
                    )
                    row.compensation_status = (
                        C.PENDING if index in (1, 2) else C.NOT_NEEDED
                    )
                    row.error_detail = None
                    transition(
                        current, R.DISPATCHING_FINAL if index >= 4 else R.RUNNING
                    )
                    return True
                if result.status == V.DEFINITIVELY_NOT_APPLIED:
                    transition(row, S.FAILED_RETRYABLE)
                    return True
                row.reconcile_polls += 1
                transition(current, R.RECONCILING)
            # Polls are bounded. No wall-clock sleep in deterministic mock execution.
        await self.halt(lease, "UNRESOLVED_UNCERTAIN_SIDE_EFFECT")
        return False

    async def execute_step(self, lease, index):
        while True:
            run = await self._run(lease.run_id)
            step = await self._step(run.id, run.active_revision_no, index)
            if step.status == S.COMMITTED:
                return True
            if step.status in (S.IN_FLIGHT, S.OUTCOME_UNKNOWN):
                if not await self.reconcile(lease, index):
                    return False
                continue
            if step.status == S.FAILED_TERMINAL:
                return False
            if step.attempt_count >= self.settings.max_execute_attempts:
                async with self.mutate(lease) as (session, _):
                    row = await session.get(Step, step.id)
                    transition(row, S.FAILED_TERMINAL)
                await self.halt(lease, f"EXECUTE_ATTEMPTS_EXHAUSTED: step={index}")
                return False
            config = ChaosConfig.model_validate(run.chaos_config)
            payload = await self.payload(run, index)
            await self.checkpoint(lease, index, "BEFORE_STEP")
            async with self.mutate(lease) as (session, current):
                row = await session.get(Step, step.id)
                transition(row, S.IN_FLIGHT)
                row.attempt_count += 1
                row.started_at, row.input_payload = now(), payload
                self.audit(session, row, "EXECUTE", "STARTED")
                if index >= 4:
                    transition(current, R.DISPATCHING_FINAL)
                elif current.status == R.RECONCILING:
                    transition(current, R.RUNNING)
                attempt = row.attempt_count
            timeout = (
                config.transient_timeout_before_write_on_step == index
                and await consume_fault(
                    self.db, run.id, run.active_revision_no, "timeout", index
                )
            )
            crash_before = (
                config.crash_worker_after_step_in_flight == index
                and await consume_fault(
                    self.db, run.id, run.active_revision_no, "crash_before", index
                )
            )
            fail_finalizer = (
                index == 5
                and config.fail_finalization_once
                and await consume_fault(
                    self.db, run.id, run.active_revision_no, "finalizer_timeout", index
                )
            )
            await self.tools[index].prepare(
                run.sandbox_namespace,
                step.operation_id,
                attempt,
                expired=timeout or crash_before or fail_finalizer,
            )
            if crash_before:
                raise SimulatedWorkerCrashError(
                    f"Injected crash before external effect at step {index}"
                )
            try:
                result = await self.tools[index].execute(
                    run.sandbox_namespace,
                    step.operation_id,
                    attempt,
                    run.id,
                    payload,
                    timeout_before_write=timeout or fail_finalizer,
                )
                if (
                    config.crash_after_external_commit_on_step == index
                    and await consume_fault(
                        self.db,
                        run.id,
                        run.active_revision_no,
                        "crash_after_write",
                        index,
                    )
                ):
                    raise SimulatedWorkerCrashError(
                        f"Injected crash after external commit at step {index}"
                    )
                if (
                    config.drop_response_after_write_on_step == index
                    and await consume_fault(
                        self.db, run.id, run.active_revision_no, "drop_response", index
                    )
                ):
                    raise UncertainWriteError(
                        "Injected response drop after external commit"
                    )
            except UncertainWriteError as error:
                async with self.mutate(lease) as (session, current):
                    row = await session.get(Step, step.id)
                    transition(row, S.OUTCOME_UNKNOWN)
                    row.error_detail = str(error)
                    transition(current, R.RECONCILING)
                    self.audit(
                        session,
                        row,
                        "EXECUTE",
                        "OUTCOME_UNKNOWN",
                        {"error": str(error)},
                    )
                return False
            except SagaError as error:
                # These errors are destination-validated before commit, not network ambiguity.
                async with self.mutate(lease) as (session, current):
                    row = await session.get(Step, step.id)
                    transition(
                        row, S.FAILED_RETRYABLE if index == 5 else S.FAILED_TERMINAL
                    )
                    row.error_detail = error.message
                    self.audit(
                        session,
                        row,
                        "EXECUTE",
                        row.status.value,
                        {"code": error.code, "error": error.message},
                    )
                    transition(current, R.FAILED_NEEDS_HUMAN)
                    current.error_summary = (
                        f"{error.code}: step={index}; {error.message}"
                    )
                if index < 4:
                    await self.rollback(lease, run.active_revision_no)
                return False
            async with self.mutate(lease) as (session, _):
                row = await session.get(Step, step.id)
                transition(row, S.COMMITTED)
                row.external_record_id, row.output_payload = (
                    result.external_record_id,
                    result.output_payload,
                )
                row.verification_evidence, row.completed_at = result.evidence, now()
                row.compensation_status = C.PENDING if index in (1, 2) else C.NOT_NEEDED
                self.audit(
                    session, row, "EXECUTE", "COMMITTED", result.model_dump(mode="json")
                )
            await self.checkpoint(lease, index, "AFTER_STEP")
            return True

    async def gate(self, lease):
        run = await self._run(lease.run_id)
        await self.checkpoint(lease, 3, "BEFORE_STEP")
        quote = await self._step(run.id, run.active_revision_no, 2)
        frozen = {
            "recipient": run.rfq_payload["customer_email"],
            "quote_id": quote.external_record_id,
            "line_items": run.agent_plan["line_items"],
            "total_amount": run.agent_plan["total_amount"],
            "currency": "INR",
        }
        async with self.mutate(lease) as (session, current):
            approval = await session.scalar(
                select(Approval).where(
                    Approval.run_id == current.id,
                    Approval.revision_no == current.active_revision_no,
                )
            )
            if not approval:
                digest = state_hash(
                    current.active_revision_no,
                    current.rfq_payload,
                    current.agent_plan,
                    frozen,
                )
                current.state_hash = digest
                revision = await session.get(
                    Revision, (current.id, current.active_revision_no)
                )
                revision.state_hash = digest
                session.add(
                    Approval(
                        run_id=current.id,
                        revision_no=current.active_revision_no,
                        bound_state_hash=digest,
                        frozen_dispatch_payload=frozen,
                    )
                )
            step = await session.scalar(
                select(Step).where(
                    Step.run_id == current.id,
                    Step.revision_no == current.active_revision_no,
                    Step.step_index == 3,
                )
            )
            transition(step, S.COMMITTED)
            step.output_payload, step.completed_at = {"approval_required": True}, now()
            transition(current, R.AWAITING_APPROVAL)
        await self.checkpoint(lease, 3, "AFTER_STEP")

    async def claim_dispatch(self, lease):
        async with self.mutate(lease) as (session, run):
            approval = await session.scalar(
                select(Approval)
                .where(
                    Approval.run_id == run.id,
                    Approval.revision_no == run.active_revision_no,
                )
                .with_for_update()
            )
            if approval and approval.status == A.CONSUMED_FOR_DISPATCH:
                transition(run, R.DISPATCHING_FINAL)
                return
            if not approval or approval.status != A.APPROVED:
                raise SagaError(
                    "APPROVAL_REQUIRED", "An approved current revision is required"
                )
            digest = state_hash(
                run.active_revision_no,
                run.rfq_payload,
                run.agent_plan,
                approval.frozen_dispatch_payload,
            )
            if (
                digest != run.state_hash
                or digest != approval.bound_state_hash
                or not verify_signature(self.settings.hmac_secret, approval)
            ):
                raise SagaError(
                    "STALE_APPROVAL",
                    "Approval hash or signature does not match the current payload",
                )
            approval.status = A.CONSUMED_FOR_DISPATCH
            transition(run, R.DISPATCHING_FINAL)
        run = await self._run(lease.run_id)
        config = ChaosConfig.model_validate(run.chaos_config)
        if config.crash_after_dispatch_claim and await consume_fault(
            self.db, run.id, run.active_revision_no, "dispatch_claim_crash", 4
        ):
            raise SimulatedWorkerCrashError(
                "Injected crash after atomic approval claim"
            )

    async def drive(self, lease):
        run = await self._run(lease.run_id)
        if run.status in (R.COMPLETED, R.COMPENSATED_HALTED):
            return
        async with self.db.sessions() as session:
            superseding = (
                await session.scalars(
                    select(Revision)
                    .where(
                        Revision.run_id == run.id,
                        Revision.status == "SUPERSEDING_COMPENSATING",
                    )
                    .order_by(Revision.revision_no)
                )
            ).all()
        for revision in superseding:
            if not await self.rollback(lease, revision.revision_no, superseding=True):
                return
        run = await self._run(lease.run_id)
        if run.status == R.COMPENSATING:
            await self.rollback(lease, run.active_revision_no)
            return
        if run.status == R.FAILED_NEEDS_HUMAN:
            approval = await self._approval(run.id, run.active_revision_no)
            if approval and approval.status == A.REJECTED:
                await self.rollback(lease, run.active_revision_no)
                return
        await self.ensure_steps(lease)
        approval = await self._approval(run.id, run.active_revision_no)
        if approval and approval.status == A.CONSUMED_FOR_DISPATCH:
            await self.claim_dispatch(lease)
        else:
            async with self.mutate(lease) as (_, current):
                if current.status == R.FAILED_NEEDS_HUMAN:
                    transition(current, R.RUNNING)
            await self.checkpoint(lease, 0, "BEFORE_STEP")
            step = await self._step(run.id, run.active_revision_no, 0)
            if step.status != S.COMMITTED:
                async with self.mutate(lease) as (session, current):
                    row = await session.get(Step, step.id)
                    transition(row, S.COMMITTED)
                    row.input_payload, row.output_payload, row.completed_at = (
                        current.rfq_payload,
                        current.agent_plan,
                        now(),
                    )
                await self.checkpoint(lease, 0, "AFTER_STEP")
            for index in (1, 2):
                if not await self.execute_step(lease, index):
                    return
            run = await self._run(lease.run_id)
            approval = await self._approval(run.id, run.active_revision_no)
            if not approval:
                await self.gate(lease)
                return
            if approval.status == A.PENDING:
                async with self.mutate(lease) as (_, current):
                    transition(current, R.AWAITING_APPROVAL)
                return
            if approval.status != A.APPROVED:
                return
            await self.claim_dispatch(lease)
        for index in (4, 5):
            if not await self.execute_step(lease, index):
                return
        async with self.mutate(lease) as (session, current):
            transition(current, R.COMPLETED)
            current.error_summary = None
            revision = await session.get(
                Revision, (current.id, current.active_revision_no)
            )
            revision.status = "COMPLETED"

    async def approve(
        self,
        run_id,
        reviewer_id,
        bound_revision_no,
        bound_state_hash,
        reviewer_note=None,
        auto_execute_dispatch=True,
        chaos_config=None,
    ):
        async with self.invocation(run_id, chaos_config) as lease:
            async with self.mutate(lease) as (session, run):
                approval = await session.scalar(
                    select(Approval).where(
                        Approval.run_id == run.id,
                        Approval.revision_no == run.active_revision_no,
                    )
                )
                if (
                    run.status != R.AWAITING_APPROVAL
                    or not approval
                    or approval.status != A.PENDING
                ):
                    raise SagaError(
                        "APPROVAL_NOT_PENDING", "Run is not awaiting a pending approval"
                    )
                if (
                    bound_revision_no != run.active_revision_no
                    or bound_state_hash != run.state_hash
                ):
                    raise SagaError(
                        "STALE_APPROVAL", "Submitted revision/hash is stale"
                    )
                approval.status, approval.reviewer_id, approval.reviewer_note = (
                    A.APPROVED,
                    reviewer_id,
                    reviewer_note,
                )
                approval.reviewer_signature = signature(
                    self.settings.hmac_secret,
                    run.id,
                    run.active_revision_no,
                    run.state_hash,
                    reviewer_id,
                )
                approval.decided_at = now()
            if auto_execute_dispatch:
                await self.drive(lease)
        return await self.trace(run_id)

    async def reject(self, run_id, reviewer_id, reviewer_note, chaos_config=None):
        async with self.invocation(run_id, chaos_config) as lease:
            async with self.mutate(lease) as (session, run):
                approval = await session.scalar(
                    select(Approval).where(
                        Approval.run_id == run.id,
                        Approval.revision_no == run.active_revision_no,
                    )
                )
                if (
                    run.status != R.AWAITING_APPROVAL
                    or not approval
                    or approval.status not in (A.PENDING, A.APPROVED)
                ):
                    raise SagaError(
                        "REJECTION_NOT_ALLOWED",
                        "Only an unclaimed approval can be rejected",
                    )
                (
                    approval.status,
                    approval.reviewer_id,
                    approval.reviewer_note,
                    approval.decided_at,
                ) = A.REJECTED, reviewer_id, reviewer_note, now()
                transition(run, R.COMPENSATING)
            await self.rollback(lease, run.active_revision_no)
        return await self.trace(run_id)

    async def revise(self, run_id, raw_request, chaos_config=None):
        async with self.invocation(run_id, chaos_config) as lease:
            run = await self._run(run_id)
            approval = await self._approval(run_id, run.active_revision_no)
            if run.status in (R.DISPATCHING_FINAL, R.COMPLETED) or (
                approval and approval.status == A.CONSUMED_FOR_DISPATCH
            ):
                raise SagaError(
                    "DISPATCH_ALREADY_CLAIMED",
                    "Cannot revise RFQ after terminal dispatch has been claimed",
                )
            if run.status not in (R.AWAITING_APPROVAL, R.RUNNING, R.RECONCILING):
                raise SagaError(
                    "REVISION_NOT_ALLOWED",
                    "Run cannot accept a revision in its current state",
                )
            rfq = {**run.rfq_payload, "raw_request": raw_request}
            plan = await plan_rfq(self.db, run.sandbox_namespace, rfq)
            validate_task_plan(plan, rfq)
            # Resolve in-flight effects before any rollback/new revision allocation.
            for index in (1, 2):
                step = await self._step(run.id, run.active_revision_no, index)
                if (
                    step
                    and step.status in (S.IN_FLIGHT, S.OUTCOME_UNKNOWN)
                    and not await self.execute_step(lease, index)
                ):
                    return await self.trace(run_id)
            async with self.mutate(lease) as (session, current):
                old = await session.get(Revision, (run_id, current.active_revision_no))
                old.status = "SUPERSEDING_COMPENSATING"
                approvals = (
                    await session.scalars(
                        select(Approval).where(
                            Approval.run_id == run_id,
                            Approval.revision_no == current.active_revision_no,
                            Approval.status.in_([A.PENDING, A.APPROVED]),
                        )
                    )
                ).all()
                for record in approvals:
                    record.status = A.INVALIDATED_STALE
                current.active_revision_no += 1
                current.rfq_payload, current.agent_plan, current.state_hash = (
                    rfq,
                    plan,
                    "",
                )
                transition(current, R.COMPENSATING)
                session.add(
                    Revision(
                        run_id=run_id,
                        revision_no=current.active_revision_no,
                        rfq_payload=rfq,
                        agent_plan=plan,
                    )
                )
            await self.drive(lease)
        return await self.trace(run_id)

    async def rollback(self, lease, revision_no, superseding=False):
        from app.engine.compensator import compensate_revision

        return await compensate_revision(self, lease, revision_no, superseding)

    async def trace(self, run_id):
        # A read transaction provides a consistent trace while commands mutate it.
        async with self.db.transaction() as session:
            run = await session.get(Run, run_id)
            if not run:
                raise SagaError("RUN_NOT_FOUND", "Run does not exist", 404)
            result = {"run": run.model_dump(mode="json")}
            for name, model, order in [
                ("revisions", Revision, Revision.revision_no),
                ("steps", Step, Step.step_index),
                ("approvals", Approval, Approval.revision_no),
                ("attempts", Attempt, Attempt.created_at),
            ]:
                records = (
                    await session.scalars(
                        select(model).where(model.run_id == run_id).order_by(order)
                    )
                ).all()
                result[name] = [r.model_dump(mode="json") for r in records]
            checkpoints = (
                await session.scalars(
                    select(Checkpoint).where(Checkpoint.run_id == run_id)
                )
            ).all()
            result["checkpoints_count"] = len(checkpoints)
            result["external_records"] = {}
            for name, model in [
                ("stock", Stock),
                ("holds", Hold),
                ("quotes", Quote),
                ("emails", Email),
            ]:
                query = select(model).where(model.namespace == run.sandbox_namespace)
                if model is not Stock:
                    query = query.where(model.run_id == run_id)
                result["external_records"][name] = [
                    r.model_dump(mode="json")
                    for r in (await session.scalars(query)).all()
                ]
            return result

    async def fork(self, run_id, from_step_index, revision_no=None, override_plan=None):
        from app.engine.fork_sandbox import fork_run

        return await fork_run(self, run_id, from_step_index, revision_no, override_plan)
