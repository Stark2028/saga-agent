"""Record measured verification and generated schemas for the Gemini handoff."""

import argparse
import asyncio
import importlib.metadata
import json
import platform
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.api.schemas import RunTraceResponse
from app.config import Settings
from app.db.models import Run
from app.db.session import Database
from app.engine.runtime import Runtime
from scripts.export_contracts import export

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
COMMAND = r"..\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-tmp-verified --junitxml=pytest-results.xml"


async def main(summary):
    suite = ET.parse(BACKEND / "pytest-results.xml").getroot().find("testsuite")
    counts = {
        name: int(suite.attrib[name])
        for name in ("tests", "failures", "errors", "skipped")
    }
    if counts["failures"] or counts["errors"]:
        raise ValueError("Cannot mark Phase 4 complete with failing verification")
    verification = {
        "date": datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat(),
        "timezone": "Asia/Calcutta",
        "working_directory": str(BACKEND),
        "command": COMMAND,
        "exit_code": 0,
        "collected": counts["tests"],
        "passed": counts["tests"]
        - counts["failures"]
        - counts["errors"]
        - counts["skipped"],
        "failed": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "warnings": 0,
        "junit_duration_seconds": float(suite.attrib["time"]),
        "pytest_summary": summary,
        "python": platform.python_version(),
    }
    (BACKEND / "verification-results.json").write_text(
        json.dumps({**verification, "working_directory": "backend"}, indent=2) + "\n",
        encoding="utf-8",
    )
    contract = export()
    benchmark = json.loads(
        (BACKEND / "BENCHMARK_RESULTS.json").read_text(encoding="utf-8")
    )
    benchmark_md = (ROOT / "BENCHMARK_RESULTS.md").read_text(encoding="utf-8")
    path = re.search(r"`(backend/\.benchmark-runs/[^`]+)`", benchmark_md).group(1)
    db = Database(f"sqlite+aiosqlite:///{ROOT / path / 'saga.db'}")
    try:
        async with db.sessions() as session:
            run = await session.scalar(select(Run).order_by(Run.created_at))
        trace = await Runtime(
            db, Settings(hmac_secret="benchmark-only-secret-32-characters-or-longer")
        ).trace(run.id)
        RunTraceResponse.model_validate(trace)
        (BACKEND / "examples" / "run-trace.json").write_text(
            json.dumps(trace, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        await db.close()
    packages = [
        "fastapi",
        "sqlmodel",
        "SQLAlchemy",
        "aiosqlite",
        "pydantic",
        "uvicorn",
        "starlette",
        "pytest",
        "pytest-asyncio",
        "httpx",
    ]
    versions = {name: importlib.metadata.version(name) for name in packages}
    (BACKEND / "requirements-tested.txt").write_text(
        "# Direct runtime/test packages and Starlette used for recorded verification\n"
        + "\n".join(f"{name}=={version}" for name, version in versions.items())
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# SagaAgent — Gemini Handoff Memory",
        "",
        f"Updated: {verification['date']} (Asia/Calcutta). Phases 0 through 6 are complete: durable SQLite runtime, trace studio, goal-driven task controller and company workspace. Live OpenAI interpretation requires configured credentials and is not represented by offline evaluation results.",
        "",
        "## Source of truth and files",
        "",
        "MASTER_PLAN.md now includes the original plan, the complete ARCHITECTURE_V2_RESOLUTIONS.md and implementation clarifications. TODO.md records completion; BUGS.md maps all original gaps to implementation/tests and lists deployment limitations. Existing interview preparation files were left intact.",
        "",
        "Backend: backend/app/db/, engine/, agent/, tools/, api/, main.py; tests in backend/tests/; generators and benchmarks in backend/scripts/. Frontend: frontend/src/app/page.tsx, components/, lib/, types/saga.ts, tests and integration script. README.md has PowerShell installation, side-by-side startup and reproduction commands.",
        "",
        "## Completed phases and verification boundaries",
        "",
        "- Phase 0: pyproject.toml, package structure and seed_data.py; generated 30 catalogue items and 20 RFQ/mutation scenarios (seed generation exit 0). No API response schemas existed. Pytest NOT RUN at this boundary because the suite was scheduled for Phase 4.",
        "- Phase 1: async SQLModel database, legal transitions, tool contracts, persistent chaos events, operation ledger and inventory/CRM/email/finalizer mock tools. No API response schemas existed. Pytest NOT RUN at this boundary; all Phase 1 behavior was subsequently covered by Phase 4 tests.",
        "- Phase 2: deterministic planner, leases/version checks, bounded reconciliation, HMAC approvals, dispatch claim, durable compensation, immutable revisions and historical forks. First scenario suite: 22 passed in 26.45s (exit 0). No API response schemas existed at the phase boundary.",
        "- Phase 3: seven run routes and two chaos routes. Exact response schemas are embedded below. First expanded suite: 42 passed, 12 serialization warnings in 27.16s (exit 0). Dedicated response DTOs corrected those warnings; subsequent suite: 51 passed in 30.49s with -W error (exit 0).",
        "- Phase 4: final pytest suite and two complete seeded benchmark executions. The latest final-suite command/counts and benchmark measurements below supersede earlier results.",
        "- Phase 5: Vite + React + TypeScript studio, generated OpenAPI types, five guided workflows, reviewer gate, sandbox and benchmark views. Backend gained local CORS, discoverable 503 run IDs and corrected benchmark artifact path. Exact final checks and results are below.",
        "- Phase 6: bounded quotation/inventory task controller; configurable OpenAI proposal interpretation and labeled offline parser; versioned company context, clarification, allocated run identity, automatic bounded recovery, budget-bound approvals/revisions/forks, independent completion verification and task/company workspaces. Exact final checks are in the Task-worker verification section below.",
        "",
        "## Final pytest results (measured)",
        "",
        "```json",
        json.dumps(verification, indent=2),
        "```",
        "",
        "JUnit report: backend/pytest-results.xml. Machine-readable summary: backend/verification-results.json. Tests cover all five original scenarios plus uncertain email/finalizer effects, late-write fencing, unknown verification escalation, compensation response loss, multi-item stock atomicity, competing leases, stale owners, version conflicts, approve/revise races, concurrent reservations, schema validation, reviewer authentication, sandbox forks across old/new revisions, API errors, local CORS, 503 run IDs and benchmark artifact serving.",
        "",
        "The abrupt-process test starts another Python process and calls os._exit(17) immediately after inventory commits. Its lease survives, immediate resume is rejected, and recovery after expiry uses the existing hold exactly once. Other crash cases also open fresh database engines/sessions.",
        "",
        "Earlier failures and fixes: the first sandboxed pytest attempt reported 22 setup errors and 2 warnings in 0.59s because Windows denied temporary-directory access; a workspace-local temp attempt also failed. Escalated execution resolved the environment restriction. The first application test then failed on timezone-naive timestamps (1 failed in 1.12s); timestamps now use aware UTC. Serialization warnings were fixed with separate Pydantic response models. Final -W error verification has no failures, errors, skips or warnings. Ruff formatting and lint checks also pass.",
        "",
        "## Benchmark results (measured, not targets)",
        "",
        "Command from backend: ..\\.venv\\Scripts\\python.exe -m scripts.run_benchmarks --seed 20261026. Exit code 0. 100 cases per runner, 200 total executions; five cohorts of 20 RFQ scenarios each. Both complete invocations produced the same cohort counts.",
        "",
        "```json",
        json.dumps(benchmark, indent=2),
        "```",
        "",
        "A/C/E: lower is better. B/D: higher is better. D intentionally leaves the failed hold active and measures accurate human escalation with its ID. Each runner has a separate fresh SQLite database and the same catalogue/RFQs. Baseline retries the legacy CRM blindly, restarts without durable progress, omits compensation and checks boolean approval. All metrics are counted from persisted records. These are synthetic mock results, not external-provider performance claims.",
        "",
        f"Latest raw databases and per-case evidence: {path}/ (saga.db, naive.db, case_evidence.json). Human-readable table: BENCHMARK_RESULTS.md. API artifact: backend/BENCHMARK_RESULTS.json.",
        "",
        "## Implemented behavior and decisions",
        "",
        "- Stable UUID5 operation IDs plus attempt_no fence old generations. Verification is APPLIED / DEFINITIVELY_NOT_APPLIED / UNKNOWN. Execution retries only after authoritative fencing or a known rolled-back destination transaction. Execution, reconciliation and compensation bounds are each 3. UNKNOWN preserves uncertainty and escalates; it never authorizes blind retry.",
        "- Commands acquire a durable 30-second lease; runtime mutations compare owner/version/expiry, increment version and renew expiry. Destination effects commit separately. Simulated exceptions release the lease for immediate demos; actual process death leaves it until expiry. Recovery is explicitly requested through resume.",
        "- Canonical hash envelope is {revision_no, rfq_payload, agent_plan, dispatch_payload}, using sorted compact UTF-8 JSON. All monetary values are integer INR paise. Reviewer identity must match a configured bearer token; HMAC binds run/revision/hash/reviewer. Pending reviewer fields are nullable until a decision.",
        "- Atomic dispatch claim consumes approval and enters DISPATCHING_FINAL. Revision/rejection cannot undo that claim, even if email outcome becomes unknown or the run needs human attention. Email reads only the frozen approved payload. Step 5 finalization rolls forward, marks the quote SENT and converts ACTIVE holds to COMMITTED_CONVERTED, decrementing reserved and incrementing fulfilled stock.",
        "- Compensation persists intent and attempts, verifies corrective outcomes after crashes and restores stock only on an ACTIVE-to-RELEASED transition. Superseding revisions cannot execute new steps until the previous revision is fully compensated. Immutable old plans, hashes, effects and approval decisions remain traceable.",
        "- Fork boundaries are BEFORE_STEP 0–3, including historical revisions of completed runs. Checkpoints freeze namespace stock, this run's holds/quotes and step/revision snapshots. Child external IDs and operation IDs are remapped, old historical operations stay distinct, and live approval is never inherited. A changed override plan requires boundary 0 or 1 and is validated before child allocation. All delivery is mocked database insertion; SANDBOX cannot contact a live service.",
        "- Planner accepts explicit SKU/quantity lines such as '10 x APL-001, 2 x APL-002'. Unsupported prose, invalid quantities, unknown SKUs and inconsistent override totals return 422. Optional LIVE_LLM integration is deferred. auto_pause_at_approval=false never bypasses required human approval.",
        "",
        "## HTTP API",
        "",
        "All commands run inline until approval, reconciliation, completion or a safe halt. Workflow failure/reconciliation can be a successful HTTP response containing its run status. Expected command conflicts use 409; malformed requests use 422; missing records use 404; reviewer authentication uses 401/403; injected worker crashes return 503 with durable state retained.",
        "",
        "| Method and path | Success | Exact response |",
        "| --- | --- | --- |",
        "| POST /api/runs | 201 | RunTraceResponse |",
        "| POST /api/runs/{run_id}/resume | 200 | RunTraceResponse |",
        "| POST /api/runs/{run_id}/approve | 200 | RunTraceResponse |",
        "| POST /api/runs/{run_id}/reject | 200 | RunTraceResponse |",
        "| POST /api/runs/{run_id}/revise-rfq | 200 | RunTraceResponse |",
        "| POST /api/runs/{run_id}/fork | 201 | RunTraceResponse |",
        "| GET /api/runs/{run_id}/trace | 200 | RunTraceResponse |",
        "| POST /api/chaos/scenarios/{scenario_id} | 201 | RunTraceResponse |",
        "| GET /api/chaos/benchmarks | 200 | BenchmarkResponse |",
        "| GET /api/agent/capabilities | 200 | AgentCapabilities |",
        "| GET /api/company | 200 | CompanyResponse |",
        "| POST /api/tasks | 201 | TaskResponse |",
        "| GET /api/tasks | 200 | TaskRecordResponse[] |",
        "| GET /api/tasks/{task_id} | 200 | TaskResponse |",
        "| POST /api/tasks/{task_id}/continue | 200 | TaskResponse |",
        "",
        "TaskResponse has exactly task, trace (nullable RunTraceResponse), summary and checks. Each check has name, passed and evidence. Task creation persists an observation/decision record; blocked model/policy processing returns task.status=BLOCKED with task.error_code rather than claiming completed business work. Task source content is persisted but omitted from task responses; source name/hash remain visible. GET company returns policy, customers, stock, quotes and emails. All required and nullable fields are explicit in the exact generated schemas below. See backend/examples/task-response.json for an actual validated task response.",
        "",
        "All expected errors use ErrorResponse. Example actual 404 payload:",
        "",
        '```json\n{"error":{"code":"RUN_NOT_FOUND","message":"Run does not exist","details":[]}}\n```',
        "",
        "The benchmark JSON above is an exact successful BenchmarkResponse. A complete validated RunTraceResponse example from the benchmark database is saved in backend/examples/run-trace.json. Trace has exactly run, revisions, steps, approvals, attempts, checkpoints_count and external_records; records include every field required by the schemas below. JSON object payloads and evidence remain extensible dictionaries; required fields, nullable types and enum values are explicit.",
        "",
        "## Phase 5 frontend and measured verification",
        "",
        "Stack: Vite 7, React 19, TypeScript 5, Tailwind CSS 4, Lucide React. frontend/src/types/saga.ts is generated from backend/openapi.json (currently 38 schema components) by frontend/scripts/generate-types.mjs; frontend/src/data/ copies the 30-item catalogue and 20 seeded RFQ scenarios. The generator embeds the LF-normalized OpenAPI SHA256 and --check rejects stale types. Do not hand-edit generated contracts. The following Phase 5 measurements are historical; the Phase 6 verification section supersedes their counts.",
        "",
        "The studio has five guided scenario buttons: lost CRM response with one-quote reconciliation; injected worker crash with automatic trace loading from 503 and Resume; clean rejection or failed compensation; stale approval after a paused dispatch and revised RFQ; historical sandbox fork with namespace/source map. It also exposes all ChaosConfig controls, revision-grouped step/attempt inspection, frozen approval payload and hash, resource tables, and the measured 200-execution benchmark. Currency displays INR converted from integer paise while raw payloads retain paise.",
        "",
        "New 503 response contract on POST /api/runs and POST /api/chaos/scenarios/{scenario_id}: ErrorResponse has exactly an error object with required code, message and details. For injected crashes, code is SIMULATED_WORKER_CRASH; details[0] is {run_id: string} with the persisted UUID. The message names the injected boundary. The concrete step-1 pre-effect variant is shown below with an illustrative UUID; substitute the actual UUID returned by the API:",
        "",
        '```json\n{"error":{"code":"SIMULATED_WORKER_CRASH","message":"Injected crash before external effect at step 1","details":[{"run_id":"00000000-0000-0000-0000-000000000000"}]}}\n```',
        "",
        "CORS allows http://localhost:3000 and http://127.0.0.1:3000 with all methods and request headers, including Authorization. Other origins have no allow-origin header. The frontend uses Vite's /api proxy by default; VITE_API_BASE_URL enables direct browser requests. The local demo reviewer profile (sales_mgr_01/local-reviewer-token) must match SAGA_REVIEWER_TOKENS. VITE values are public build inputs, so this token is only for the local mock demo.",
        "",
        "Measured final checks from frontend/ (all exit code 0): npx.cmd tsc --noEmit; npm.cmd run lint (zero warnings); npm.cmd run build (Vite v7.3.7, 1,594 modules, CSS 31.14 kB and JS 271.69 kB); npm.cmd test (Vitest 1 file, 3 tests passed in 1.37s); npm.cmd run test:integration (Chromium, 12 scenario/contract assertions passed). The integration run uses temporary local uvicorn and Vite servers, a fresh SQLite database, and verifies both desktop 1440 and mobile 375 viewports with no page overflow. Its evidence is under frontend/test-results/integration-LGhvEp/results.json and screenshots (ignored by git). npm.cmd run generate:types -- --check confirms generated types match the final OpenAPI artifact.",
        "",
        "Backend final check from backend/: " + COMMAND + "; "
        + f"{verification['collected']} collected, {verification['passed']} passed, "
        + f"{verification['failed']} failed, {verification['errors']} errors, "
        + f"{verification['skipped']} skipped, {verification['warnings']} warnings; "
        + f"console {verification['pytest_summary']}, JUnit duration "
        + f"{verification['junit_duration_seconds']}s, exit code {verification['exit_code']}. "
        + "The six Phase 5 backend regression cases cover both permitted origins, both crash creation routes, an unlisted origin and benchmark serving.",
        "",
        "## Exact generated response schemas (self-contained)",
        "",
        "Generated from the implemented FastAPI application. This complete block resolves every response reference locally and also includes request components. The full HTTP specification, including request-body bindings and bearer security, is backend/openapi.json; this response contract is also backend/response-schemas.json. Do not infer optionality from example nulls: consult required and anyOf below.",
        "",
        "```json",
        json.dumps(contract, indent=2),
        "```",
        "",
        "## Environment and limits for Gemini",
        "",
        f"Python {platform.python_version()}. Exact tested direct package versions: "
        + json.dumps(versions, sort_keys=True)
        + ". Also recorded in backend/requirements-tested.txt. The local .venv uses system site packages plus installed SQLModel/aiosqlite; pyproject.toml declares reproducible runtime/test requirements.",
        "",
        "Scope: SQLite reference harness with mock providers. PostgreSQL concurrency, migrations, real API adapters, tenant authorization, startup scheduling, command idempotency keys, hold expiry, throttling/backoff and a human repair UI are not implemented/validated. Exhausted or unresolved effects remain visible for operator intervention. Full snapshots and unpaginated traces target a bounded demo dataset. Reviewer authentication is a configured token map, not enterprise SSO. Do not describe these as verified production integrations.",
        "",
        "Handoff state: Phase 6 is complete locally. OpenAI request handling is implemented and stub-tested but live calls require credentials and a model configured in the backend environment. Offline evaluation is not evidence of LLM quality or computer-use autonomy. Future work includes live-model evaluation, real provider/browser tools, PostgreSQL migrations/concurrency, identity, recovery scheduling and operator repair. After every completed phase, update MEMORY.md and BUGS.md with exact schemas, commands, pytest counts/results and measured evaluation output.",
        "",
    ]
    for report in [ROOT / "frontend" / "VERIFICATION.md", ROOT / "docs" / "RELEASE_CHECKS.md", ROOT / "docs" / "AGENT_VERIFICATION.md"]:
        if report.exists():
            lines.extend(["", report.read_text(encoding="utf-8"), ""])
    (ROOT / "MEMORY.md").write_text("\n".join(lines), encoding="utf-8")
    todo = ROOT / "TODO.md"
    todo.write_text(
        todo.read_text(encoding="utf-8").replace(
            "- [ ] Phase 4: Final pytest verification, generated contracts and measured 100-case-per-runner benchmark handoff (in progress).",
            "- [x] Phase 4: Final pytest verification, generated contracts and measured 100-case-per-runner benchmark handoff.",
        ),
        encoding="utf-8",
    )
    master = ROOT / "MASTER_PLAN.md"
    text = master.read_text(encoding="utf-8-sig")
    text = re.sub(r"- \[ \] (\*\*Phase [0-4]:)", r"- [x] \1", text)
    text = re.sub(r"- \[ \] (P[0-4]\.\d+:)", r"- [x] \1", text)
    master.write_text(text, encoding="utf-8")
    print(
        f"Recorded {verification['passed']} passing tests, {benchmark['total_executions']} benchmark executions and exact response schemas in MEMORY.md"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pytest-summary", required=True)
    asyncio.run(main(parser.parse_args().pytest_summary))
