from sqlalchemy import select

from app.db.models import Quote, now
from app.engine.contracts import SagaError, ToolResult
from app.tools.base import LedgerTool, applied


class CRMTool(LedgerTool):
    name = "crm_tool"

    async def apply(self, session, namespace, operation_id, run_id, payload):
        quote = Quote(
            namespace=namespace,
            operation_id=operation_id,
            run_id=run_id,
            customer_email=payload["customer_email"],
            total_amount=payload["total_amount"],
            line_items=payload["line_items"],
        )
        session.add(quote)
        return ToolResult(
            external_record_id=quote.quote_id,
            output_payload={"quote_id": quote.quote_id},
            evidence={"status": "DRAFT"},
        )

    async def compensate(
        self, namespace, compensation_operation_id, external_record_id, **kwargs
    ):
        async with self.db.transaction() as session:
            quote = await session.scalar(
                select(Quote)
                .where(
                    Quote.quote_id == external_record_id, Quote.namespace == namespace
                )
                .with_for_update()
            )
            if not quote:
                raise SagaError(
                    "RESOURCE_MISSING", f"Missing quote {external_record_id}"
                )
            if (
                quote.status == "VOIDED"
                and quote.voided_by_op_id == compensation_operation_id
            ):
                return applied(
                    quote.quote_id, {"status": "VOIDED", "deduplicated": True}
                )
            if quote.status != "DRAFT":
                raise SagaError(
                    "COMPENSATION_CONFLICT", f"Cannot void quote in {quote.status}"
                )
            quote.status, quote.voided_by_op_id, quote.voided_at = (
                "VOIDED",
                compensation_operation_id,
                now(),
            )
            return applied(
                quote.quote_id,
                {
                    "status": "VOIDED",
                    "compensation_operation_id": compensation_operation_id,
                },
            )
