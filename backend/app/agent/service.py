"""Bounded goal -> context -> interpret -> observe -> act -> verify controller."""

import hashlib
import re
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import select

from app.agent.company import memory, validate_task_plan
from app.agent.interpret import offline_intent, openai_intent
from app.agent.models import AgentTask
from app.agent.schemas import TaskIntent, TaskRecordResponse, TaskResponse
from app.db.models import Stock, now, uid
from app.engine.contracts import SagaError, SimulatedWorkerCrashError


class TaskWorker:
    def __init__(self, runtime):
        self.runtime, self.db, self.settings = runtime, runtime.db, runtime.settings

    async def get(self, task_id):
        async with self.db.sessions() as session:
            task = await session.get(AgentTask, task_id)
        if not task:
            raise SagaError("TASK_NOT_FOUND", "Task does not exist", 404)
        return task

    @asynccontextmanager
    async def invocation(self, task_id):
        owner = uid()
        async with self.db.transaction() as session:
            task = await session.get(AgentTask, task_id, with_for_update=True)
            if not task:
                raise SagaError("TASK_NOT_FOUND", "Task does not exist", 404)
            if task.lease_owner and task.lease_expires_at > now():
                raise SagaError("TASK_LOCKED", "Another worker is handling this task")
            task.lease_owner, task.lease_expires_at = (
                owner,
                now() + timedelta(seconds=90),
            )
            task.version += 1
        try:
            yield owner
        finally:
            async with self.db.transaction() as session:
                task = await session.get(AgentTask, task_id)
                if task.lease_owner == owner:
                    task.lease_owner = task.lease_expires_at = None
                    task.version += 1

    async def change(self, task_id, owner, **fields):
        async with self.db.transaction() as session:
            task = await session.get(AgentTask, task_id, with_for_update=True)
            if task.lease_owner != owner or task.lease_expires_at <= now():
                raise SagaError(
                    "TASK_LEASE_LOST",
                    "Task ownership expired; reload before continuing",
                )
            for key, value in fields.items():
                setattr(task, key, value)
            task.version += 1
            task.updated_at = now()
            task.lease_expires_at = now() + timedelta(seconds=90)

    async def observe(self, task_id, owner, action, summary, evidence):
        task = await self.get(task_id)
        observations = [
            *task.observations,
            {
                "sequence": len(task.observations) + 1,
                "action": action,
                "summary": summary,
                "evidence": evidence,
                "created_at": now().isoformat(),
            },
        ]
        await self.change(task_id, owner, observations=observations)

    async def create(self, body):
        policy = await memory(self.db, "policy")
        task = AgentTask(
            goal=body.goal,
            source_document=body.source_document,
            source_name=body.source_name,
            source_sha256=hashlib.sha256(body.source_document.encode()).hexdigest(),
            planner_mode=body.planner_mode,
            customer_name=body.customer_name,
            customer_email=body.customer_email,
            policy_snapshot=policy,
            chaos_config=body.chaos_config.model_dump() if body.chaos_config else {},
        )
        async with self.db.transaction() as session:
            session.add(task)
        return await self.continue_task(task.id)

    async def continue_task(self, task_id, answer="", chaos_config=None):
        async with self.invocation(task_id) as owner:
            task = await self.get(task_id)
            if answer:
                if task.run_id or task.status not in (
                    "NEEDS_CLARIFICATION",
                    "BLOCKED",
                    "PLANNING",
                ):
                    raise SagaError(
                        "CLARIFICATION_NOT_ALLOWED",
                        "This task has started execution; revise its bound RFQ instead",
                    )
                await self.change(
                    task_id,
                    owner,
                    conversation=[
                        *task.conversation,
                        {"answer": answer, "created_at": now().isoformat()},
                    ],
                )
            if chaos_config is not None:
                await self.change(task_id, owner, chaos_config=chaos_config)
            await self.change(task_id, owner, error_code=None, questions=[])
            try:
                task = await self.get(task_id)
                if not task.run_id:
                    await self.plan(task_id, owner)
                task = await self.get(task_id)
                if task.run_id:
                    await self.execute(task_id, owner)
            except SagaError as error:
                await self.observe(
                    task_id, owner, "blocked", error.message, {"code": error.code}
                )
                await self.change(
                    task_id, owner, status="BLOCKED", error_code=error.code
                )
        return await self.snapshot(task_id)

    async def plan(self, task_id, owner):
        task = await self.get(task_id)
        customers = (await memory(self.db, "customers"))["records"]
        await self.observe(
            task_id,
            owner,
            "read_document",
            "Read the goal and supplied text; source material is task data, not permission to bypass company policy.",
            {
                "source_name": task.source_name,
                "sha256": task.source_sha256,
                "characters": len(task.source_document),
            },
        )
        await self.observe(
            task_id,
            owner,
            "load_company_context",
            "Loaded the persisted company policy and customer directory.",
            {
                "policy_version": task.policy_snapshot["version"],
                "customers": [row["name"] for row in customers],
            },
        )
        text = f"Source document:\n{task.source_document}\nGoal: {task.goal}"
        for message in task.conversation:
            text += "\nClarification: " + message["answer"]
        if task.planner_mode == "openai":
            intent = await openai_intent(
                self.settings, text, task.policy_snapshot, customers
            )
        else:
            intent = offline_intent(text, customers)
            if task.conversation:
                correction = offline_intent(task.conversation[-1]["answer"], customers)
                if correction.items:
                    intent.items = correction.items
        if task.customer_name:
            intent.customer_name = task.customer_name
        if task.customer_email:
            intent.customer_email = task.customer_email
        customer = next(
            (
                row
                for row in customers
                if (intent.customer_name or "").casefold() == row["name"].casefold()
            ),
            None,
        )
        if customer and not intent.customer_email:
            intent.customer_email = customer["email"]
        await self.change(task_id, owner, intent=intent.model_dump())
        await self.observe(
            task_id,
            owner,
            "interpret_goal",
            intent.decision_summary[:1000],
            {"planner_mode": task.planner_mode, "intent": intent.model_dump()},
        )
        async with self.db.sessions() as session:
            stock = list(
                (
                    await session.scalars(
                        select(Stock)
                        .where(Stock.namespace == "live")
                        .order_by(Stock.unit_price, Stock.sku)
                    )
                ).all()
            )
        if intent.action == "inventory":
            requested = {item.category for item in intent.items if item.category}
            rows = [row for row in stock if not requested or row.category in requested]
            await self.observe(
                task_id,
                owner,
                "inspect_inventory",
                "Read current catalogue quantities without creating a quote or reserving stock.",
                {
                    "items": [
                        {
                            "sku": row.sku,
                            "category": row.category,
                            "available_qty": row.available_qty,
                            "unit_price": row.unit_price,
                        }
                        for row in rows
                    ]
                },
            )
            await self.change(task_id, owner, status="COMPLETED")
            return
        questions = list(intent.questions)
        if re.search(r"\b(USD|EUR|GBP|dollars?|euros?)\b|[$€£]", text, re.I):
            questions.append(
                "Only INR budgets are supported. Restate the request in INR before execution."
            )
        if intent.action == "clarify":
            questions.append(
                "Please describe a quotation or inventory task supported by this company workspace."
            )
        if not intent.items:
            questions.append("Specify a product category/SKU and quantity.")
        if not intent.customer_name:
            questions.append(
                "Who is the customer? Acme and Northstar are in the company directory."
            )
        if not intent.customer_email or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", intent.customer_email
        ):
            questions.append(
                "Provide a valid customer email, or choose a customer in the company directory."
            )
        quantities = {}
        selections = []
        for item in intent.items:
            if (
                item.quantity is None
                or not 0 < item.quantity <= task.policy_snapshot["max_quantity_per_sku"]
            ):
                questions.append(
                    f"Provide a quantity from 1 to {task.policy_snapshot['max_quantity_per_sku']} for {item.sku or item.category or 'the requested item'}."
                )
                continue
            candidates = [
                row
                for row in stock
                if (
                    row.sku == item.sku.upper()
                    if item.sku
                    else row.category == item.category
                )
                and row.category in task.policy_snapshot["approved_categories"]
            ]
            available = [
                row
                for row in candidates
                if row.available_qty >= item.quantity + quantities.get(row.sku, 0)
            ]
            if not available:
                questions.append(
                    f"{item.sku or item.category or 'Requested product'} is unknown or has insufficient stock. Specify an approved alternative; no substitution has been made."
                )
                continue
            row = available[0]
            quantities[row.sku] = quantities.get(row.sku, 0) + item.quantity
            selections.append(
                {
                    "sku": row.sku,
                    "quantity": item.quantity,
                    "unit_price": row.unit_price,
                    "basis": "explicit SKU"
                    if item.sku
                    else task.policy_snapshot["category_selection"],
                }
            )
        if intent.budget_paise is not None and intent.budget_paise <= 0:
            questions.append("The budget must be a positive INR amount.")
        if questions:
            await self.change(
                task_id,
                owner,
                status="NEEDS_CLARIFICATION",
                questions=list(dict.fromkeys(questions)),
            )
            await self.observe(
                task_id,
                owner,
                "ask_clarification",
                "Missing or unsafe details prevent execution; no stock or CRM records were changed.",
                {"questions": list(dict.fromkeys(questions))},
            )
            return
        prices = {row.sku: row.unit_price for row in stock}
        plan = {
            "line_items": [
                {"sku": sku, "qty": qty, "unit_price": prices[sku]}
                for sku, qty in sorted(quantities.items())
            ],
            "total_amount": sum(prices[sku] * qty for sku, qty in quantities.items()),
            "currency": "INR",
            "exceptions": [],
        }
        validate_task_plan(
            plan,
            {
                "task_context": {
                    "policy": task.policy_snapshot,
                    "budget_paise": intent.budget_paise,
                }
            },
        )
        await self.observe(
            task_id,
            owner,
            "select_catalogue_items",
            "Selected approved in-stock products using company policy; all prices and totals were calculated by code.",
            {
                "selections": selections,
                "total_amount": plan["total_amount"],
                "budget_paise": intent.budget_paise,
            },
        )
        raw = ", ".join(f"{qty} x {sku}" for sku, qty in sorted(quantities.items()))
        await self.change(
            task_id,
            owner,
            status="RUNNING",
            run_id=uid(),
            raw_request=raw,
            selected_plan=plan,
        )

    async def execute(self, task_id, owner):
        task = await self.get(task_id)
        intent = TaskIntent.model_validate(task.intent)
        context = {
            "task_id": task.id,
            "goal": task.goal,
            "source_sha256": task.source_sha256,
            "policy": task.policy_snapshot,
            "budget_paise": intent.budget_paise,
        }
        try:
            trace = await self.runtime.create(
                intent.customer_name,
                intent.customer_email,
                task.raw_request,
                chaos_config=task.chaos_config,
                run_id=task.run_id,
                task_context=context,
            )
        except SimulatedWorkerCrashError:
            trace = await self.runtime.trace(task.run_id)
            await self.observe(
                task_id,
                owner,
                "recover_worker",
                "The worker stopped after durable intent. Loaded the existing run instead of allocating another.",
                {"run_id": task.run_id},
            )
        for attempt in range(self.settings.agent_max_recoveries):
            status = trace["run"]["status"]
            await self.observe(
                task_id,
                owner,
                "observe_run",
                "Observed persisted runtime state before choosing the next permitted action.",
                {
                    "run_id": task.run_id,
                    "status": status,
                    "revision_no": trace["run"]["active_revision_no"],
                },
            )
            approved = any(
                row["revision_no"] == trace["run"]["active_revision_no"]
                and row["status"] == "APPROVED"
                for row in trace["approvals"]
            )
            if status not in ("RUNNING", "RECONCILING", "DISPATCHING_FINAL") and not (
                status == "AWAITING_APPROVAL" and approved
            ):
                break
            await self.observe(
                task_id,
                owner,
                "resume_and_verify",
                "Reconcile prior effects before permitting another execution attempt.",
                {"recovery_attempt": attempt + 1},
            )
            try:
                trace = await self.runtime.resume(task.run_id)
            except SimulatedWorkerCrashError:
                trace = await self.runtime.trace(task.run_id)
        await self.change(task_id, owner, status=str(trace["run"]["status"]))

    async def snapshot(self, task_id):
        task = await self.get(task_id)
        record = TaskRecordResponse.model_validate(
            {**task.model_dump(), "intent": task.intent or None}
        )
        checks = []
        trace = None
        summary = "The task is waiting to be planned."
        if task.run_id:
            try:
                trace = await self.runtime.trace(task.run_id)
            except SagaError as error:
                if error.code != "RUN_NOT_FOUND":
                    raise
            if trace:
                run = trace["run"]
                record.status = str(run["status"])
                external = trace["external_records"]
                active = next(
                    row
                    for row in trace["revisions"]
                    if row["revision_no"] == run["active_revision_no"]
                )
                plan = active["agent_plan"]
                approvals = [
                    row
                    for row in trace["approvals"]
                    if row["revision_no"] == run["active_revision_no"]
                ]
                approval = approvals[0] if approvals else None
                frozen = approval["frozen_dispatch_payload"] if approval else {}
                quote = next(
                    (
                        row
                        for row in external["quotes"]
                        if row["quote_id"] == frozen.get("quote_id")
                    ),
                    None,
                )
                checks.append(
                    {
                        "name": "Draft quote matches the frozen dispatch payload",
                        "passed": bool(
                            quote
                            and quote["total_amount"] == plan["total_amount"]
                            and quote["line_items"] == plan["line_items"]
                        ),
                        "evidence": {
                            "quote_id": quote["quote_id"] if quote else None,
                            "total_amount": plan["total_amount"],
                        },
                    }
                )
                hold = next(
                    (
                        row
                        for row in external["holds"]
                        if row["status"] in ("ACTIVE", "COMMITTED_CONVERTED")
                        and row["items"] == plan["line_items"]
                    ),
                    None,
                )
                checks.append(
                    {
                        "name": "Inventory hold exists for the active plan",
                        "passed": hold is not None,
                        "evidence": {
                            "hold_id": hold["hold_id"] if hold else None,
                            "status": hold["status"] if hold else None,
                        },
                    }
                )
                if record.status == "COMPLETED":
                    emails = [
                        row
                        for row in external["emails"]
                        if row["bound_state_hash"] == run["state_hash"]
                        and row["quote_id"] == frozen.get("quote_id")
                        and row["recipient"] == frozen.get("recipient")
                    ]
                    checks.append(
                        {
                            "name": "One dispatch matches the consumed approval",
                            "passed": len(emails) == 1
                            and bool(
                                approval
                                and approval["status"] == "CONSUMED_FOR_DISPATCH"
                            ),
                            "evidence": {
                                "email_ids": [row["email_id"] for row in emails],
                                "bound_state_hash": run["state_hash"],
                            },
                        }
                    )
                    checks.append(
                        {
                            "name": "Quote and inventory finalization are recorded",
                            "passed": bool(
                                quote
                                and quote["status"] == "SENT"
                                and hold
                                and hold["status"] == "COMMITTED_CONVERTED"
                            ),
                            "evidence": {
                                "quote_status": quote["status"] if quote else None,
                                "hold_status": hold["status"] if hold else None,
                            },
                        }
                    )
                    summary = "The quote was dispatched and finalized in the company sandbox. Completion was checked against the CRM quote, inventory hold and approval-bound email."
                    if not all(row["passed"] for row in checks):
                        record.status = "FAILED_VERIFICATION"
                        summary = "The runtime reported completion, but independent record checks failed. Inspect the evidence before declaring success."
                elif record.status == "AWAITING_APPROVAL":
                    summary = f"Created draft quote {frozen.get('quote_id', 'pending')} and checked its persisted records. Sending is paused for explicit reviewer approval."
                    if approval and approval["status"] == "APPROVED":
                        summary = "Approval is recorded, and dispatch is paused. Continue execution to send the exact approved payload."
                elif record.status == "COMPENSATED_HALTED":
                    summary = "The reviewer rejected the quote. The runtime halted after compensation; inspect the released/voided records in the trace."
                else:
                    summary = "Execution needs attention. Inspect the persisted run and the last observed action before continuing."
        elif task.status == "NEEDS_CLARIFICATION":
            summary = "I need the details below before changing inventory or creating a quote."
        elif task.status == "BLOCKED":
            summary = (
                task.observations[-1]["summary"]
                if task.observations
                else "The task is blocked."
            )
        elif task.status == "COMPLETED":
            summary = "Inspected current inventory. No reservations, quotes or emails were created."
            checks = [
                {
                    "name": "Inventory observation persisted",
                    "passed": any(
                        row["action"] == "inspect_inventory"
                        for row in task.observations
                    ),
                    "evidence": {"task_id": task.id},
                }
            ]
        return TaskResponse(task=record, trace=trace, summary=summary, checks=checks)
