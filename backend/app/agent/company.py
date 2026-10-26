from sqlalchemy import select

from app.agent.models import CompanyMemory
from app.db.models import Email, Quote, Stock
from app.engine.contracts import SagaError

POLICY = {
    "version": 1,
    "company": "Aplus Sandbox Company",
    "currency": "INR",
    "approved_categories": ["laptop", "monitor", "keyboard", "dock", "headset"],
    "category_selection": "lowest_price_in_stock",
    "allow_explicit_sku_substitution": False,
    "require_approval_before_dispatch": True,
    "max_quote_paise": 100000000,
    "max_quantity_per_sku": 10000,
    "notes": "Category requests use the cheapest approved in-stock option. Never replace an explicitly requested SKU without clarification. All business effects are sandbox/mock records.",
}
CUSTOMERS = [
    {
        "name": "Acme",
        "email": "procurement@acme.example.test",
        "notes": "Use approved catalogue prices; do not infer discounts.",
    },
    {
        "name": "Northstar",
        "email": "buyer@northstar.example.test",
        "notes": "Sending always requires reviewer approval.",
    },
]


async def seed_company(db):
    async with db.transaction() as session:
        for key, content in [("policy", POLICY), ("customers", {"records": CUSTOMERS})]:
            if not await session.get(CompanyMemory, (key, 1)):
                session.add(CompanyMemory(key=key, version=1, content=content))


async def memory(db, key):
    async with db.sessions() as session:
        record = await session.scalar(
            select(CompanyMemory)
            .where(CompanyMemory.key == key)
            .order_by(CompanyMemory.version.desc())
        )
        if not record:
            raise SagaError(
                "COMPANY_CONTEXT_MISSING",
                "Company context has not been initialized",
                503,
            )
        return record.content


async def company_snapshot(db):
    async with db.sessions() as session:
        stock = list(
            (
                await session.scalars(
                    select(Stock).where(Stock.namespace == "live").order_by(Stock.sku)
                )
            ).all()
        )
        quotes = list(
            (
                await session.scalars(
                    select(Quote)
                    .where(Quote.namespace == "live")
                    .order_by(Quote.created_at.desc())
                    .limit(30)
                )
            ).all()
        )
        emails = list(
            (
                await session.scalars(
                    select(Email)
                    .where(Email.namespace == "live")
                    .order_by(Email.sent_at.desc())
                    .limit(30)
                )
            ).all()
        )
    return {
        "policy": await memory(db, "policy"),
        "customers": (await memory(db, "customers"))["records"],
        "stock": stock,
        "quotes": quotes,
        "emails": emails,
    }


def validate_task_plan(plan, rfq):
    context = rfq.get("task_context")
    if not context:
        return
    policy = context["policy"]
    limit = min(
        policy["max_quote_paise"],
        context.get("budget_paise") or policy["max_quote_paise"],
    )
    if plan["total_amount"] > limit:
        raise SagaError(
            "TASK_BUDGET_EXCEEDED",
            "The plan exceeds the task's frozen budget or company limit",
            422,
        )
    if any(item["qty"] > policy["max_quantity_per_sku"] for item in plan["line_items"]):
        raise SagaError(
            "TASK_QUANTITY_EXCEEDED", "The plan exceeds the company quantity limit", 422
        )
