import re
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.db.models import Stock
from app.engine.contracts import SagaError


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str
    qty: int = Field(gt=0, le=10000)
    unit_price: int = Field(ge=0)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_items: list[PlanItem] = Field(min_length=1)
    total_amount: int = Field(ge=0)
    currency: str = "INR"
    exceptions: list[str] = Field(default_factory=list)


async def plan_rfq(db, namespace, rfq, override=None):
    async with db.sessions() as session:
        stock = {
            r.sku: r
            for r in (
                await session.scalars(select(Stock).where(Stock.namespace == namespace))
            ).all()
        }
    return build_plan(stock, rfq, override)


def build_plan(stock, rfq, override=None):
    quantities = {}
    text = rfq["raw_request"].upper()
    if override is None:
        matches = list(re.finditer(r"\b([1-9]\d*)\s*(?:X\s*)?(APL-\d{3})\b", text))
        remainder = re.sub(r"\b([1-9]\d*)\s*(?:X\s*)?(APL-\d{3})\b", "", text)
        if not matches or remainder.strip(" ,;\n\t"):
            raise SagaError(
                "INVALID_RFQ",
                "Use explicit lines such as '10 x APL-001'; unsupported text requires human clarification",
                422,
            )
        for match in matches:
            sku, qty = match.group(2), int(match.group(1))
            quantities[sku] = quantities.get(sku, 0) + qty
    else:
        try:
            candidate = Plan.model_validate(override)
        except ValidationError as error:
            raise SagaError(
                "INVALID_OVERRIDE", "Override must conform to the Plan schema", 422
            ) from error
        for item in candidate.line_items:
            quantities[item.sku] = quantities.get(item.sku, 0) + item.qty
    items = []
    for sku, qty in sorted(quantities.items()):
        if sku not in stock:
            raise SagaError("UNKNOWN_SKU", f"Unknown SKU {sku}", 422)
        if not 0 < qty <= 10000:
            raise SagaError("INVALID_QUANTITY", f"Invalid quantity for {sku}", 422)
        items.append(PlanItem(sku=sku, qty=qty, unit_price=stock[sku].unit_price))
    result = Plan(
        line_items=items, total_amount=sum(x.qty * x.unit_price for x in items)
    )
    if override is not None and result.model_dump() != candidate.model_dump():
        raise SagaError(
            "INVALID_OVERRIDE",
            "Override totals and prices must match the checkpoint catalogue",
            422,
        )
    return result.model_dump()
