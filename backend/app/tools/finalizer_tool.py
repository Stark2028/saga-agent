from sqlalchemy import select, update

from app.db.models import Email, Hold, Quote, Stock
from app.engine.contracts import SagaError, ToolResult
from app.engine.state_machine import Compensatability, IdempotencyMode
from app.tools.base import LedgerTool


class FinalizerTool(LedgerTool):
    name = "finalizer_tool"
    idempotency_mode = IdempotencyMode.DEDUP_KEY_SUPPORTED
    compensatability = Compensatability.IRREVERSIBLE_TERMINAL

    async def apply(self, session, namespace, operation_id, run_id, payload):
        quote = await session.scalar(
            select(Quote)
            .where(
                Quote.quote_id == payload["quote_id"],
                Quote.namespace == namespace,
                Quote.run_id == run_id,
            )
            .with_for_update()
        )
        hold = await session.scalar(
            select(Hold)
            .where(
                Hold.hold_id == payload["hold_id"],
                Hold.namespace == namespace,
                Hold.run_id == run_id,
            )
            .with_for_update()
        )
        email = await session.scalar(
            select(Email).where(
                Email.namespace == namespace,
                Email.run_id == run_id,
                Email.quote_id == payload["quote_id"],
            )
        )
        if (
            not quote
            or not hold
            or not email
            or quote.status not in {"DRAFT", "SENT"}
            or hold.status not in {"ACTIVE", "COMMITTED_CONVERTED"}
        ):
            raise SagaError(
                "FINALIZATION_CONFLICT",
                "Expected sent email, draft quote and active hold",
            )
        if hold.status == "ACTIVE":
            for item in hold.items:
                result = await session.execute(
                    update(Stock)
                    .where(
                        Stock.namespace == namespace,
                        Stock.sku == item["sku"],
                        Stock.reserved_qty >= item["qty"],
                    )
                    .values(
                        reserved_qty=Stock.reserved_qty - item["qty"],
                        fulfilled_qty=Stock.fulfilled_qty + item["qty"],
                    )
                )
                if result.rowcount != 1:
                    raise SagaError(
                        "INVENTORY_INVARIANT",
                        "Reserved quantity does not cover fulfillment",
                    )
            hold.status = "COMMITTED_CONVERTED"
        quote.status = "SENT"
        return ToolResult(
            external_record_id=quote.quote_id,
            output_payload={"quote_id": quote.quote_id, "hold_id": hold.hold_id},
            evidence={"quote_status": "SENT", "hold_status": "COMMITTED_CONVERTED"},
        )
