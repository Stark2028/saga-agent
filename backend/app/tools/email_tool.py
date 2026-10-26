import json
from sqlalchemy import select

from app.db.models import Approval, Email, Run
from app.engine.contracts import SagaError, ToolResult
from app.engine.state_machine import (
    ApprovalStatus,
    Compensatability,
    IdempotencyMode,
    RunStatus,
)
from app.tools.base import LedgerTool


class EmailTool(LedgerTool):
    name = "email_tool"
    idempotency_mode = IdempotencyMode.DEDUP_KEY_SUPPORTED
    compensatability = Compensatability.IRREVERSIBLE_TERMINAL

    async def apply(self, session, namespace, operation_id, run_id, payload):
        run = await session.get(Run, run_id)
        approval = await session.scalar(
            select(Approval).where(
                Approval.run_id == run_id,
                Approval.revision_no == run.active_revision_no,
            )
        )
        if (
            run.sandbox_namespace != namespace
            or run.status != RunStatus.DISPATCHING_FINAL
            or not approval
            or approval.status != ApprovalStatus.CONSUMED_FOR_DISPATCH
        ):
            raise SagaError(
                "DISPATCH_NOT_CLAIMED",
                "Email requires a claimed approval in the same namespace",
            )
        from app.engine.approval import verify_signature, state_hash

        frozen = approval.frozen_dispatch_payload
        if (
            not verify_signature(self.settings.hmac_secret, approval)
            or state_hash(
                run.active_revision_no, run.rfq_payload, run.agent_plan, frozen
            )
            != approval.bound_state_hash
        ):
            raise SagaError(
                "STALE_APPROVAL", "Frozen dispatch payload failed approval verification"
            )
        email = Email(
            namespace=namespace,
            operation_id=operation_id,
            run_id=run_id,
            recipient=frozen["recipient"],
            quote_id=frozen["quote_id"],
            bound_state_hash=approval.bound_state_hash,
            body_summary=json.dumps(frozen, sort_keys=True, separators=(",", ":")),
        )
        session.add(email)
        return ToolResult(
            external_record_id=email.email_id,
            output_payload={"email_id": email.email_id},
            evidence={"mock_delivery": True, "namespace": namespace},
        )
