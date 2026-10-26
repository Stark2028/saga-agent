from datetime import timedelta

from sqlalchemy import select

from app.db.models import Hold, OperationLedger, Quote, now
from app.engine.contracts import (
    BaseToolContract,
    CompensateResult,
    SagaError,
    ToolResult,
    UncertainWriteError,
    VerifyResult,
)
from app.engine.state_machine import (
    Compensatability,
    IdempotencyMode,
    VerificationStatus as V,
)


class LedgerTool(BaseToolContract):
    idempotency_mode = IdempotencyMode.VERIFY_THEN_FENCE
    compensatability = Compensatability.COMPENSATABLE
    name = ""

    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    async def prepare(self, namespace, operation_id, attempt_no, expired=False):
        async with self.db.transaction() as session:
            ledger = await session.get(
                OperationLedger,
                (namespace, self.name, operation_id),
                with_for_update=True,
            )
            if ledger:
                if ledger.status == "COMMITTED":
                    return
                if ledger.status != "FENCED_ABORTED" or attempt_no <= ledger.attempt_no:
                    raise SagaError(
                        "ATTEMPT_FENCED",
                        "Prior external attempt has not been safely fenced",
                    )
                ledger.attempt_no = attempt_no
                ledger.status = "IN_FLIGHT_EXTERNAL"
                ledger.deadline_at = now() + timedelta(
                    seconds=0 if expired else self.settings.operation_timeout_seconds
                )
                ledger.updated_at = now()
            else:
                session.add(
                    OperationLedger(
                        namespace=namespace,
                        tool_name=self.name,
                        operation_id=operation_id,
                        attempt_no=attempt_no,
                        deadline_at=now()
                        + timedelta(
                            seconds=0
                            if expired
                            else self.settings.operation_timeout_seconds
                        ),
                    )
                )

    async def execute(
        self,
        namespace,
        operation_id,
        attempt_no,
        run_id,
        payload,
        timeout_before_write=False,
        **kwargs,
    ):
        if timeout_before_write:
            raise UncertainWriteError(
                "Injected pre-write timeout; destination attempt must be fenced"
            )
        try:
            async with self.db.transaction() as session:
                ledger = await session.get(
                    OperationLedger,
                    (namespace, self.name, operation_id),
                    with_for_update=True,
                )
                if (
                    not ledger
                    or ledger.attempt_no != attempt_no
                    or ledger.status == "FENCED_ABORTED"
                ):
                    raise SagaError(
                        "ATTEMPT_FENCED",
                        "Destination rejected an absent, stale or aborted attempt",
                    )
                if ledger.status == "COMMITTED":
                    if (
                        self.idempotency_mode == IdempotencyMode.DEDUP_KEY_SUPPORTED
                        or self.name == "inventory_tool"
                    ):
                        return ToolResult(
                            external_record_id=ledger.external_record_id,
                            output_payload=ledger.output_payload,
                            evidence={"deduplicated": True},
                        )
                    # Legacy CRM deliberately creates duplicates on blind retry.
                result = await self.apply(
                    session, namespace, operation_id, run_id, payload
                )
                ledger.status, ledger.external_record_id = (
                    "COMMITTED",
                    result.external_record_id,
                )
                ledger.output_payload, ledger.updated_at = result.output_payload, now()
                return result
        except SagaError:
            # The destination transaction rolled back. Close this generation so
            # a repaired finalizer may be retried without a late-write race.
            async with self.db.transaction() as session:
                ledger = await session.get(
                    OperationLedger,
                    (namespace, self.name, operation_id),
                    with_for_update=True,
                )
                if (
                    ledger
                    and ledger.attempt_no == attempt_no
                    and ledger.status == "IN_FLIGHT_EXTERNAL"
                ):
                    ledger.status, ledger.updated_at = "FENCED_ABORTED", now()
            raise

    async def verify(
        self,
        namespace,
        operation_id,
        fence_if_missing=True,
        keep_unknown=False,
        attempt_no=1,
        deadline_at=None,
        **kwargs,
    ):
        async with self.db.transaction() as session:
            ledger = await session.get(
                OperationLedger,
                (namespace, self.name, operation_id),
                with_for_update=True,
            )
            if keep_unknown:
                return VerifyResult(
                    status=V.UNKNOWN,
                    evidence={"reason": "Injected inconclusive destination read"},
                )
            if ledger and ledger.status == "COMMITTED":
                return VerifyResult(
                    status=V.APPLIED,
                    external_record_id=ledger.external_record_id,
                    output_payload=ledger.output_payload,
                    evidence={
                        "ledger_status": ledger.status,
                        "attempt_no": ledger.attempt_no,
                    },
                )
            if not ledger:
                ledger = OperationLedger(
                    namespace=namespace,
                    tool_name=self.name,
                    operation_id=operation_id,
                    attempt_no=attempt_no,
                    deadline_at=deadline_at or now(),
                )
                session.add(ledger)
            if ledger.status == "FENCED_ABORTED" or (
                fence_if_missing and ledger.deadline_at <= now()
            ):
                ledger.status, ledger.updated_at = "FENCED_ABORTED", now()
                return VerifyResult(
                    status=V.DEFINITIVELY_NOT_APPLIED,
                    evidence={
                        "ledger_status": "FENCED_ABORTED",
                        "fenced_attempt_no": ledger.attempt_no,
                    },
                )
            return VerifyResult(
                status=V.UNKNOWN,
                evidence={
                    "ledger_status": ledger.status,
                    "deadline_at": ledger.deadline_at.isoformat(),
                },
            )

    async def apply(self, session, namespace, operation_id, run_id, payload):
        raise NotImplementedError

    async def verify_compensation(
        self, compensation_operation_id, external_record_id, namespace
    ):
        if self.compensatability == Compensatability.IRREVERSIBLE_TERMINAL:
            raise SagaError(
                "NON_COMPENSATABLE", "Terminal effects cannot be compensated"
            )
        model, key, target, op_field = (
            (Hold, "hold_id", "RELEASED", "released_by_op_id")
            if self.name == "inventory_tool"
            else (Quote, "quote_id", "VOIDED", "voided_by_op_id")
        )
        async with self.db.transaction() as session:
            record = await session.scalar(
                select(model)
                .where(
                    getattr(model, key) == external_record_id,
                    model.namespace == namespace,
                )
                .with_for_update()
            )
            if record is None:
                return VerifyResult(
                    status=V.UNKNOWN, evidence={"reason": "Resource missing"}
                )
            if (
                record.status == target
                and getattr(record, op_field) == compensation_operation_id
            ):
                return VerifyResult(
                    status=V.APPLIED,
                    external_record_id=external_record_id,
                    evidence={
                        "status": target,
                        "compensation_operation_id": compensation_operation_id,
                    },
                )
            if record.status in {"ACTIVE", "DRAFT"}:
                # Mock corrective commands are synchronous and conditional/idempotent.
                return VerifyResult(
                    status=V.DEFINITIVELY_NOT_APPLIED,
                    external_record_id=external_record_id,
                    evidence={"status": record.status},
                )
            return VerifyResult(
                status=V.UNKNOWN,
                external_record_id=external_record_id,
                evidence={
                    "status": record.status,
                    "reason": "Conflicting corrective action",
                },
            )

    async def compensate(
        self, namespace, compensation_operation_id, external_record_id, **kwargs
    ):
        raise SagaError("NON_COMPENSATABLE", "Terminal effects cannot be compensated")


def applied(record_id, evidence):
    return CompensateResult(
        status=V.APPLIED, external_record_id=record_id, evidence=evidence
    )
