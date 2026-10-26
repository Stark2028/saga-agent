from sqlalchemy import select, update

from app.db.models import Hold, Stock, now
from app.engine.contracts import SagaError, ToolResult
from app.tools.base import LedgerTool, applied


class InventoryTool(LedgerTool):
    name = "inventory_tool"

    async def apply(self, session, namespace, operation_id, run_id, payload):
        items = payload["line_items"]
        for item in items:
            result = await session.execute(
                update(Stock)
                .where(
                    Stock.namespace == namespace,
                    Stock.sku == item["sku"],
                    Stock.available_qty >= item["qty"],
                )
                .values(
                    available_qty=Stock.available_qty - item["qty"],
                    reserved_qty=Stock.reserved_qty + item["qty"],
                )
            )
            if result.rowcount != 1:
                raise SagaError(
                    "INSUFFICIENT_STOCK", f"Insufficient stock for {item['sku']}", 422
                )
        hold = Hold(
            namespace=namespace, operation_id=operation_id, run_id=run_id, items=items
        )
        session.add(hold)
        return ToolResult(
            external_record_id=hold.hold_id,
            output_payload={"hold_id": hold.hold_id},
            evidence={"status": "ACTIVE"},
        )

    async def compensate(
        self, namespace, compensation_operation_id, external_record_id, **kwargs
    ):
        async with self.db.transaction() as session:
            hold = await session.scalar(
                select(Hold)
                .where(Hold.hold_id == external_record_id, Hold.namespace == namespace)
                .with_for_update()
            )
            if not hold:
                raise SagaError(
                    "RESOURCE_MISSING", f"Missing hold {external_record_id}"
                )
            if (
                hold.status == "RELEASED"
                and hold.released_by_op_id == compensation_operation_id
            ):
                return applied(
                    hold.hold_id, {"status": "RELEASED", "deduplicated": True}
                )
            if hold.status != "ACTIVE":
                raise SagaError(
                    "COMPENSATION_CONFLICT", f"Cannot release hold in {hold.status}"
                )
            result = await session.execute(
                update(Hold)
                .where(
                    Hold.hold_id == hold.hold_id,
                    Hold.namespace == namespace,
                    Hold.status == "ACTIVE",
                )
                .values(
                    status="RELEASED",
                    released_by_op_id=compensation_operation_id,
                    released_at=now(),
                )
            )
            if result.rowcount != 1:
                raise SagaError(
                    "COMPENSATION_CONFLICT", "Hold release raced another writer"
                )
            for item in hold.items:
                result = await session.execute(
                    update(Stock)
                    .where(
                        Stock.namespace == namespace,
                        Stock.sku == item["sku"],
                        Stock.reserved_qty >= item["qty"],
                    )
                    .values(
                        available_qty=Stock.available_qty + item["qty"],
                        reserved_qty=Stock.reserved_qty - item["qty"],
                    )
                )
                if result.rowcount != 1:
                    raise SagaError(
                        "INVENTORY_INVARIANT", "Reserved quantity does not cover hold"
                    )
            return applied(
                hold.hold_id,
                {
                    "status": "RELEASED",
                    "compensation_operation_id": compensation_operation_id,
                },
            )
