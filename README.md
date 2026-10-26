# SagaAgent

**Durable execution, verified recovery, and human approval for tool-driven workflows.**

[![CI](https://github.com/Stark2028/saga-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Stark2028/saga-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/License-All_rights_reserved-lightgrey)

SagaAgent is a reference runtime for workflows that must survive uncertain API outcomes, worker crashes, rejected approvals, and changing customer requests. It persists execution intent, reconciles external effects, compensates reversible actions, and binds approval to the exact payload that will be dispatched.

The included **Trace & Chaos Studio** makes these behaviors inspectable through a B2B request-for-quotation workflow: parse an RFQ, reserve stock, draft a quote, obtain approval, dispatch an email, and finalize the order.

> **Implementation scope:** a deterministic planner, SQLite persistence, and database-backed mock inventory, CRM, and email providers. All delivery is simulated, including `LIVE` mode. No LLM API key is required. This repository demonstrates reliability mechanisms; production provider integrations and PostgreSQL concurrency validation are future work.

![SagaAgent Trace & Chaos Studio showing a reconciled CRM write and pending human approval](docs/images/studio-desktop.png)

[Quick start](#quick-start) · [Architecture](#architecture) · [Guided demos](#guided-demos) · [Verification](#verification) · [API](#api) · [Limitations](#limitations-and-roadmap)

## The problem

A timeout does not tell you whether a remote write happened. Retrying can create a duplicate quote or reserve inventory twice. A process can die after an external commit but before recording success. An approval can become stale when the customer changes the order.

SagaAgent makes those boundaries explicit:

| Failure | Runtime behavior |
| --- | --- |
| CRM write succeeds but its response is lost | Persist uncertainty, verify the existing operation, then commit its known outcome. |
| Worker exits with a step in flight | Recover from persisted state after the prior lease expires. |
| Reviewer rejects a draft | Void the quote and release inventory in reverse order. |
| Compensation fails | Halt with the uncompensated resource ID visible for operator attention. |
| RFQ changes after approval | Invalidate the old approval, compensate the previous revision, and require a new decision. |
| Operator replays a historical checkpoint | Fork into an isolated sandbox with remapped operation IDs and fresh approval. |

## Features

- **Durable intent and attempts:** database records precede tool execution; external effects commit separately from runtime bookkeeping.
- **Three-valued verification:** `APPLIED`, `DEFINITIVELY_NOT_APPLIED`, and `UNKNOWN`. An unknown outcome never authorizes a blind retry.
- **Concurrency controls:** persisted leases, optimistic versions, and attempt-generation fencing guard execution and stale writes.
- **Payload-bound approval:** canonical SHA-256 state hashes and HMAC signatures bind reviewer decisions to the exact revision and dispatch payload.
- **Recoverable compensation:** corrective operations have stable IDs, persisted attempts, and verification of their own outcomes.
- **Historical sandbox replay:** immutable `BEFORE_STEP` checkpoints at boundaries 0–3 isolate child records from the parent.
- **Operator studio:** guided faults, connected step traces, evidence inspection, approval/revision controls, external-state tables, and benchmark results.
- **Typed contracts:** nine FastAPI routes and 28 generated schema components shared with the TypeScript client.

## Architecture

```mermaid
flowchart TD
    UI[React Trace & Chaos Studio] --> API[FastAPI commands and trace API]
    API --> RT[Durable runtime]
    RT --> DB[(SQLite: runs, revisions, steps,
    attempts, approvals and checkpoints)]
    RT --> TOOLS[Inventory / CRM / Email / Finalizer]
    TOOLS --> EXT[(Mock provider records
    and operation ledgers)]
    RT --> VERIFY[Verify uncertain effects]
    VERIFY --> EXT
    RT --> COMP[Compensate reversible effects]
    COMP --> EXT
    RT --> GATE[Human approval gate]
    GATE --> RT
```

The mock provider records and runtime state share the SQLite database but use **separate commits**. This preserves the failure window between a completed effect and recorded runtime success. A provider ledger fences superseded attempt generations.

Commands execute inline until they reach approval, reconciliation, completion, or a safe halt. Recovery is explicitly requested through **Resume**. A simulated crash releases its lease for immediate demos; an actual process exit leaves the lease until expiry. The test suite includes a subprocess that exits immediately after an external commit.

Approval does not authorize arbitrary future work. Dispatch consumes the approval atomically and prevents subsequent revision. Email is irreversible; finalization rolls forward and converts reserved inventory into fulfilled stock.

### Stack

| Layer | Technology |
| --- | --- |
| API | Python, FastAPI, Pydantic |
| Persistence | SQLModel, SQLAlchemy async sessions, SQLite, aiosqlite |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, Lucide |
| Tests | pytest, pytest-asyncio, HTTPX, Vitest, Testing Library, Playwright Chromium |
| Automation | GitHub Actions; backend checks on Windows and Linux |

## Quick start

**Prerequisites:** Git, Python 3.11+ (3.12 used for verification), and Node.js 22 with npm. Reserve ports **8000** for the API and **3000** for the studio.

```bash
git clone https://github.com/Stark2028/saga-agent.git
cd saga-agent
```

<details open>
<summary><strong>Windows · PowerShell</strong></summary>

Install dependencies from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-tested.txt -e './backend[test]'
npm.cmd --prefix frontend ci
```

Start the API in terminal 1:

```powershell
$env:SAGA_HMAC_SECRET = [guid]::NewGuid().ToString() + [guid]::NewGuid().ToString()
$env:SAGA_REVIEWER_TOKENS = '{"local-reviewer-token":"sales_mgr_01"}'
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the studio in terminal 2, from the repository root:

```powershell
Set-Location frontend
npm.cmd run dev
```

</details>

<details>
<summary><strong>macOS / Linux · Bash</strong></summary>

Install dependencies from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-tested.txt -e './backend[test]'
npm --prefix frontend ci
```

Start the API in terminal 1:

```bash
export SAGA_HMAC_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
export SAGA_REVIEWER_TOKENS='{"local-reviewer-token":"sales_mgr_01"}'
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the studio in terminal 2, from the repository root:

```bash
cd frontend
npm run dev
```

</details>

Open **[the studio](http://127.0.0.1:3000)** or **[interactive API docs](http://127.0.0.1:8000/docs)**. Startup creates the schema and seeds the 30-item catalogue automatically. Twenty RFQ presets are included.

Keep the same HMAC secret when restarting against an existing database so recorded approvals remain valid. The default database is `backend/saga.db` when the server starts from `backend/`. Local database files are ignored by Git.

### Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `SAGA_HMAC_SECRET` | Approval-signing secret, at least 32 characters | Required |
| `SAGA_REVIEWER_TOKENS` | JSON mapping of bearer token to reviewer identity | `{}` |
| `SAGA_DATABASE_URL` | Async SQLAlchemy database URL | `sqlite+aiosqlite:///./saga.db` |
| `VITE_API_BASE_URL` | Direct API address; empty uses Vite's `/api` proxy | Empty |
| `VITE_REVIEWER_ID` | Local demo reviewer identity | `sales_mgr_01` |
| `VITE_REVIEWER_TOKEN` | Local demo bearer token | `local-reviewer-token` |
| `SAGA_TEST_PYTHON` | Optional Python executable for browser integration tests | Repository `.venv` |

The commands above match the studio's demo reviewer profile. Reviewer credentials are checked on approval and rejection. Frontend `VITE_*` values are public build inputs; the demo token is for this local mock harness. See [frontend/.env.example](frontend/.env.example).

The API allows browser requests from `http://localhost:3000` and `http://127.0.0.1:3000`. The Vite development proxy targets `http://127.0.0.1:8000`. A production frontend build needs an API base URL or a reverse proxy serving `/api`.

## Guided demos

Use the five numbered controls at the top of the studio. Step selection opens persisted inputs, outputs, verification evidence, compensation evidence, and attempt history.

| Demo | What to do | What to inspect |
| --- | --- | --- |
| **1 · Lost CRM response** | Launch, then **Resume / Reconcile** | Step 2 becomes reconciled; exactly one CRM quote exists. |
| **2 · Worker crash** | Launch; the UI loads the run from its `503` response; **Resume run** | Persisted in-flight intent and recovery evidence. |
| **3 · Rejection & rollback** | **Reject & roll back**; try a new run with **Fail inventory compensation** enabled | Clean rollback versus `FAILED_NEEDS_HUMAN` with its hold ID. |
| **4 · Stale approval** | **Approve & pause**, then **Revise RFQ** | Invalidated old approval, compensated prior revision, and a fresh approval hash. |
| **5 · Sandbox fork** | Select a revision and boundary, then **Fork to sandbox** | Parent provenance, source record map, isolated inventory/quotes, and fresh approval. |

Custom RFQs use explicit SKU lines such as `10 x APL-001, 2 x APL-002`. Unsupported prose and unknown SKUs return validation errors. All monetary values in API payloads are **integer INR paise**; the studio formats them as rupees.

<details>
<summary><strong>Mobile execution trace</strong></summary>

The studio uses a connected vertical timeline on narrow screens, keeps the five demos visible, and collapses the creation form after a run loads.

<img src="docs/images/studio-mobile-trace.png" alt="Mobile vertical trace with the approval gate highlighted" width="343" />

</details>

## Verification

Recorded local verification:

| Check | Result |
| --- | --- |
| Backend | **65 tests passed**, with warnings treated as errors |
| Frontend component and API-client tests | **8 tests passed** |
| Chromium integration | **16 scenario, interaction, and responsive checks passed** |
| TypeScript, ESLint, production build | Passed |
| Generated contracts | **28 schema components verified** |
| Responsive coverage | 320, 375, 768, 1024, and 1440px widths |

The [CI workflow](.github/workflows/ci.yml) reruns backend tests on Windows and Linux and frontend/browser checks on Linux. Published counts describe recorded verification; the CI badge shows the current repository status.

From `backend/` on Windows:

```powershell
..\.venv\Scripts\python.exe -m pytest -q -W error --junitxml=pytest-results.xml
```

On macOS/Linux, use `../.venv/bin/python` in place of the Windows Python path.

From `frontend/`:

```bash
npm run generate:types -- --check
npx tsc --noEmit
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:integration
```

Use `npm.cmd` and `npx.cmd` if PowerShell's execution policy blocks their `.ps1` launchers. Browser integration starts its own temporary backend and frontend, uses a fresh database, and closes both afterward. Stop a running studio on port 3000 before starting it. Linux environments may need `npx playwright install --with-deps chromium`.

See [frontend/VERIFICATION.md](frontend/VERIFICATION.md) for measured frontend results. Backend tests cover subprocess termination, competing leases, stale owners, uncertain effects, failed compensation, approval/revision races, stock contention, and historical forks.

## Benchmark

The benchmark compares SagaAgent with an intentionally naive retry runner on the same seeded RFQs in isolated databases: **100 cases per runner, 200 executions total**, with 20 cases in each cohort.

| Outcome | Direction | SagaAgent | Naive retry |
| --- | --- | ---: | ---: |
| Duplicate CRM quotes | Lower is better | **0/20** | 20/20 |
| Clean recovery without duplicate holds | Higher is better | **20/20** | 0/20 |
| Orphaned inventory holds | Lower is better | **0/20** | 20/20 |
| Failed compensation surfaced with resource ID | Higher is better | **20/20** | 0/20 |
| Stale emails dispatched | Lower is better | **0/20** | 20/20 |

These are deterministic mock results against a deliberately weak baseline, not a comparison with production workflow platforms. The failed-compensation cohort intentionally retains the affected hold and measures accurate escalation.

Reproduce from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m scripts.run_benchmarks --seed 20261026
```

The command writes [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md), the [API artifact](backend/BENCHMARK_RESULTS.json), and fresh raw evidence under `backend/.benchmark-runs/<uuid>/`. Raw databases are generated locally and excluded from Git.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs` | Create and execute an RFQ run |
| `GET` | `/api/runs/{run_id}/trace` | Read the complete trace and external state |
| `POST` | `/api/runs/{run_id}/resume` | Recover or continue execution |
| `POST` | `/api/runs/{run_id}/approve` | Approve the bound revision/hash; bearer authentication required |
| `POST` | `/api/runs/{run_id}/reject` | Reject and compensate; bearer authentication required |
| `POST` | `/api/runs/{run_id}/revise-rfq` | Create a new immutable RFQ revision |
| `POST` | `/api/runs/{run_id}/fork` | Replay a historical checkpoint in a sandbox |
| `POST` | `/api/chaos/scenarios/{scenario_id}` | Launch a seeded scenario (`rfq_01`–`rfq_20`) |
| `GET` | `/api/chaos/benchmarks` | Read persisted benchmark measurements |

Successful run commands return `RunTraceResponse`. Expected errors use `{"error":{"code":"...","message":"...","details":[]}}`. Injected worker crashes return `503` with `details[0].run_id`, allowing the client to load the durable trace immediately.

The exact contracts are in [OpenAPI](backend/openapi.json), [response schemas](backend/response-schemas.json), and [generated TypeScript](frontend/src/types/saga.ts). A complete [trace example](backend/examples/run-trace.json) is included. After API schema changes, export contracts from `backend/` with `python -m scripts.export_contracts`, then run `npm run generate:types` from `frontend/`.

## Repository layout

```text
backend/
  app/
    agent/          Deterministic RFQ planning
    api/            Routes, authentication and response schemas
    db/             Models, async sessions and catalogue seeds
    engine/         Runtime, leases, approvals, compensation and forks
    tools/          Mock provider adapters and fault injection
  scripts/          Seed generation, benchmarks and contract export
  tests/            API, concurrency, recovery and workflow tests
frontend/
  src/
    app/            Operator studio
    components/     Trace, approval, sandbox and resource views
    lib/            Typed client, formatting and execution focus
    types/          Generated OpenAPI TypeScript contracts
    test/           Component and API-client tests
  scripts/          Type generation and browser integration
docs/images/        Studio screenshots
.github/workflows/  Continuous integration
```

See [architecture resolutions](ARCHITECTURE_V2_RESOLUTIONS.md), [design notes](DESIGN.md), and the [bug/limitations log](BUGS.md) for deeper implementation decisions.

## Limitations and roadmap

- **Providers and planning:** mock CRM/inventory/email; explicit SKU parsing; no live LLM or provider adapters.
- **Recovery:** explicit resume; no automatic recovery scheduler or lease heartbeat during long remote calls.
- **Persistence:** SQLite verified locally; PostgreSQL driver support is declared but concurrency behavior is unverified; schema migrations are not implemented.
- **Access control:** configured reviewer token map; no tenant isolation or SSO. Trace, mutation, and chaos routes require additional authorization before public deployment.
- **Operations:** no API command idempotency keys, hold expiry, or guided repair workflow for exhausted effects.
- **Scale:** full checkpoints and unpaginated traces target a bounded demonstration dataset. Real adapters need provider-specific reconciliation and finalization.

The next engineering milestones are background workers and recovery scheduling, API idempotency, PostgreSQL migrations/concurrency tests, and a real provider adapter.

## Author and licensing

Built by **[Sameer Prasad](https://github.com/Stark2028)**.

**All rights reserved.** This repository does not grant an open-source license. See [LICENSE](LICENSE); third-party dependencies retain their own licenses.
