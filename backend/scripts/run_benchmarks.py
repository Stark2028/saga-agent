"""100 seeded cases per runner, isolated databases, measured database outcomes."""

import argparse
import asyncio
import json
import random
from pathlib import Path

from sqlalchemy import select

from app.agent.planner import plan_rfq
from app.config import Settings
from app.db.models import Email, Run, uid
from app.db.session import Database
from app.engine.approval import canonical
from app.engine.contracts import SimulatedWorkerCrashError
from app.engine.runtime import Runtime
from app.tools.crm_tool import CRMTool
from app.tools.finalizer_tool import FinalizerTool
from app.tools.inventory_tool import InventoryTool
from scripts.seed_data import scenarios, seed

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
COHORTS = [
    ("A", "duplicate_crm_quotes_created"),
    ("B", "clean_recovery_without_duplicate_holds"),
    ("C", "orphaned_active_inventory_holds"),
    ("D", "accurately_halted_in_failed_needs_human_with_uncompensated_id"),
    ("E", "stale_emails_dispatched"),
]


class NaiveRetryRunner:
    """A deliberately weak baseline: no progress journal, rollback or bound approval.

    Calls the same stock/CRM operations. Email inserts model the unguarded provider
    send; the Saga email adapter additionally enforces its approval claim.
    """

    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.inventory = InventoryTool(db, settings)
        self.crm = CRMTool(db, settings)
        self.finalizer = FinalizerTool(db, settings)
        self.trace_reader = Runtime(db, settings)

    async def call(self, tool, run_id, payload):
        op = uid()
        await tool.prepare("live", op, 1)
        return op, await tool.execute("live", op, 1, run_id, payload)

    async def run_case(self, scenario, cohort):
        rfq = {
            key: scenario[key]
            for key in ("customer_name", "customer_email", "raw_request", "scenario_id")
        }
        plan = await plan_rfq(self.db, "live", rfq)
        run = Run(rfq_payload=rfq, agent_plan=plan)
        async with self.db.transaction() as session:
            session.add(run)
        _, hold = await self.call(self.inventory, run.id, plan)
        if cohort == "B":
            # Restarted naive loop has no durable knowledge of the first hold.
            _, hold = await self.call(self.inventory, run.id, plan)
        quote_payload = {**plan, "customer_email": rfq["customer_email"]}
        op, quote = await self.call(self.crm, run.id, quote_payload)
        if cohort == "A":
            # Server committed, client lost response and blindly repeats legacy write.
            quote = await self.crm.execute("live", op, 1, run.id, quote_payload)
        if cohort in ("C", "D"):
            # No semantic rollback and no surfaced corrective failure information.
            return await self.trace_reader.trace(run.id)
        boolean_approved = True
        if cohort == "E":
            async with self.db.transaction() as session:
                row = await session.get(Run, run.id)
                row.rfq_payload = {
                    **rfq,
                    "raw_request": scenario["revised_raw_request"],
                }
        if boolean_approved:
            frozen = {
                "recipient": rfq["customer_email"],
                "quote_id": quote.external_record_id,
                "line_items": plan["line_items"],
                "total_amount": plan["total_amount"],
                "currency": "INR",
            }
            async with self.db.transaction() as session:
                session.add(
                    Email(
                        namespace="live",
                        operation_id=uid(),
                        run_id=run.id,
                        recipient=rfq["customer_email"],
                        quote_id=quote.external_record_id,
                        bound_state_hash="boolean-approval",
                        body_summary=canonical(frozen),
                    )
                )
            await self.call(
                self.finalizer,
                run.id,
                {
                    "quote_id": quote.external_record_id,
                    "hold_id": hold.external_record_id,
                },
            )
        return await self.trace_reader.trace(run.id)


async def approved(runtime, trace, **kwargs):
    return await runtime.approve(
        trace["run"]["id"],
        "benchmark_manager",
        trace["run"]["active_revision_no"],
        trace["run"]["state_hash"],
        **kwargs,
    )


async def saga_case(runtime, scenario, cohort, crash_index):
    payload = {
        key: scenario[key]
        for key in ("scenario_id", "customer_name", "customer_email", "raw_request")
    }
    if cohort == "B":
        try:
            await runtime.create(
                **payload,
                chaos_config={"crash_after_external_commit_on_step": crash_index},
            )
        except SimulatedWorkerCrashError:
            async with runtime.db.sessions() as session:
                run = await session.scalar(select(Run).order_by(Run.created_at.desc()))
                run_id = run.id
            # A new runtime object opens new sessions and loads persisted progress.
            trace = await Runtime(runtime.db, runtime.settings).resume(run_id)
        else:
            raise AssertionError("Crash fault did not trigger")
    else:
        trace = await runtime.create(
            **payload,
            chaos_config={"drop_response_after_write_on_step": 2}
            if cohort == "A"
            else {},
        )
        if cohort == "A":
            trace = await runtime.resume(trace["run"]["id"])
    if cohort in ("C", "D"):
        return await runtime.reject(
            trace["run"]["id"],
            "benchmark_manager",
            "Benchmark rejection",
            {"fail_compensation_on_step": 1} if cohort == "D" else {},
        )
    if cohort == "E":
        trace = await approved(runtime, trace, auto_execute_dispatch=False)
        trace = await runtime.revise(
            trace["run"]["id"], scenario["revised_raw_request"]
        )
        # A fresh approval permits the revised quote; its email must match revision 2.
    return await approved(runtime, trace)


def metric_value(cohort, trace, scenario):
    records = trace["external_records"]
    if cohort == "A":
        return int(len(records["quotes"]) > 1)
    if cohort == "B":
        return int(
            len(records["holds"]) == 1
            and len(records["quotes"]) == 1
            and len(records["emails"]) == 1
            and records["holds"][0]["status"] == "COMMITTED_CONVERTED"
        )
    if cohort == "C":
        return int(any(h["status"] == "ACTIVE" for h in records["holds"]))
    if cohort == "D":
        remaining = [h["hold_id"] for h in records["holds"] if h["status"] == "ACTIVE"]
        return int(
            bool(remaining)
            and trace["run"]["status"] == "FAILED_NEEDS_HUMAN"
            and all(
                value in (trace["run"]["error_summary"] or "") for value in remaining
            )
        )
    revised_qty = int(scenario["revised_raw_request"].split()[0])
    return int(
        any(
            json.loads(email["body_summary"])["line_items"][0]["qty"] != revised_qty
            for email in records["emails"]
        )
    )


async def run_benchmarks(
    seed_value=20261026, cases_per_cohort=20, work_dir=None, progress=False
):
    if not 1 <= cases_per_cohort <= 20:
        raise ValueError("cases_per_cohort must be between 1 and 20")
    work_dir = Path(work_dir or BACKEND / ".benchmark-runs") / uid()
    work_dir.mkdir(parents=True)
    saga_db = Database(f"sqlite+aiosqlite:///{work_dir / 'saga.db'}")
    naive_db = Database(f"sqlite+aiosqlite:///{work_dir / 'naive.db'}")
    settings = Settings(hmac_secret="benchmark-only-secret-32-characters-or-longer")
    rng = random.Random(seed_value)
    dataset = scenarios()[:cases_per_cohort]
    metrics, case_evidence = [], []
    try:
        for db in (saga_db, naive_db):
            await db.init()
            await seed(db)
        runtime, naive = (
            Runtime(saga_db, settings),
            NaiveRetryRunner(naive_db, settings),
        )
        for cohort, metric in COHORTS:
            saga_count = naive_count = 0
            for scenario in dataset:
                crash_index = rng.choice([1, 2])
                saga_trace = await saga_case(runtime, scenario, cohort, crash_index)
                naive_trace = await naive.run_case(scenario, cohort)
                saga_value, naive_value = (
                    metric_value(cohort, saga_trace, scenario),
                    metric_value(cohort, naive_trace, scenario),
                )
                saga_count += saga_value
                naive_count += naive_value
                case_evidence.append(
                    {
                        "cohort": cohort,
                        "scenario_id": scenario["scenario_id"],
                        "crash_index": crash_index if cohort == "B" else None,
                        "saga_run_id": saga_trace["run"]["id"],
                        "naive_run_id": naive_trace["run"]["id"],
                        "saga_metric": saga_value,
                        "naive_metric": naive_value,
                    }
                )
            row = {
                "cohort": cohort,
                "metric": metric,
                "denominator": len(dataset),
                "saga": saga_count,
                "naive": naive_count,
            }
            metrics.append(row)
            if progress:
                print(
                    f"Cohort {cohort}: Saga {saga_count}/{len(dataset)}, naive {naive_count}/{len(dataset)}",
                    flush=True,
                )
        result = {
            "seed": seed_value,
            "cases_per_runner": len(dataset) * 5,
            "total_executions": len(dataset) * 10,
            "metrics": metrics,
        }
        (work_dir / "case_evidence.json").write_text(
            json.dumps(case_evidence, indent=2) + "\n", encoding="utf-8"
        )
        return result, work_dir
    finally:
        await saga_db.close()
        await naive_db.close()


async def main(seed_value):
    result, work_dir = await run_benchmarks(seed_value, progress=True)
    (BACKEND / "BENCHMARK_RESULTS.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# SagaAgent Benchmark Results",
        "",
        f"Seed: {seed_value}. 100 cases per runner; 200 total executions. Counts are runs exhibiting the metric, with 20 cases per cohort.",
        "",
        "| Cohort | Metric | SagaAgent | NaiveRetryRunner |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in result["metrics"]:
        lines.append(
            f"| {row['cohort']} | {row['metric']} | {row['saga']}/{row['denominator']} | {row['naive']}/{row['denominator']} |"
        )
    lines += [
        "",
        "A/C/E: lower is better. B/D: higher is better. Cohort D intentionally retains the failed hold and measures whether its ID is surfaced, rather than counting it as a clean rollback.",
        "",
        "Both runners use isolated SQLite databases seeded with the same catalogue and RFQs. The baseline intentionally lacks durable progress, compensation and payload-bound approvals. Results describe this deterministic mock harness, not real-provider performance.",
        "",
        f"Raw databases and per-case evidence: `{work_dir.relative_to(ROOT).as_posix()}`.",
        "",
    ]
    (ROOT / "BENCHMARK_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261026)
    asyncio.run(main(parser.parse_args().seed))
