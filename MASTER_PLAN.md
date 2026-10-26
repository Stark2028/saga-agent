# MASTER_PLAN.md — SagaAgent: Durable Execution Runtime for AI Workers

## 0. Purpose & Co-Op Protocol (Gemini + VS Code Codex)

This document is the single source of truth for building **SagaAgent**, a production-grade durable execution runtime for tool-calling AI workers, demonstrated via an **Aplus B2B RFQ-to-Quote Workflow** with an integrated **Fault-Injection & Replay Harness**.

### 0.1 Why This Architecture Exists (CentrAlign AI Alignment)
- **Problem:** Enterprise AI workers fail silently when external APIs drop responses after writes, when processes crash mid-workflow, when compensations fail mid-rollback, or when customers mutate requests after human approval is granted.
- **What SagaAgent Proves:**
  1. **Durable Execution:** Persist every planning output and step attempt to relational storage before and after execution; recover deterministically from process crashes.
  2. **Explicit Uncertainty Resolution (`OUTCOME_UNKNOWN`):** Never blindly retry a write when a network response is lost. Transition to `OUTCOME_UNKNOWN` and invoke `tool.verify(operation_id)` against the external system before deciding whether to commit or re-execute.
  3. **Realistic Saga Compensation (Without False ACID Claims):** Sagas lack isolation and cannot erase history. Compensation executes semantic forward corrective actions (e.g., voiding a draft quote, releasing an inventory hold) in reverse order, and explicitly halts in `FAILED_NEEDS_HUMAN` if a compensating action itself fails.
  4. **Cryptographically Bound Approvals:** Human approvals sign a canonical SHA-256 hash of `(revision_id + rfq_payload + proposed_plan + action_payload)`. If the underlying state changes before terminal execution, the runtime invalidates the stale approval.
  5. **Bounded Time-Travel Forking:** Historical runs can be forked from any step into an isolated `SANDBOX` namespace without mutating live service records.

### 0.2 Division of Labor Between VS Code Codex & Browser Gemini
To prevent overlapping edits, we coordinate via four files in the repository root (`MASTER_PLAN.md`, `TODO.md`, `MEMORY.md`, `BUGS.md`):

| Zone | Owner | Files / Directories Owned |
| :--- | :--- | :--- |
| **Core Runtime, DB & Contracts** | **VS Code Codex** | `backend/app/db/`, `backend/app/engine/`, `backend/app/tools/`, `backend/app/api/`, `backend/tests/` |
| **Seed Data, AI Planner & Eval** | **Shared (Spec in Plan, Impl by Codex/Gemini)** | `backend/scripts/seed_data.py`, `backend/app/agent/`, `backend/scripts/run_benchmarks.py` |
| **Frontend Trace & Chaos Studio** | **Codex (Phase 5 implemented)** | `frontend/` (Vite + React + TypeScript, revision trace and chaos controls) |

**Sync Rule:** After completing any phase or task, **Codex updates `MEMORY.md` and `BUGS.md`**. The user pastes `MEMORY.md` to Gemini when architectural review or frontend generation is needed.

---

## 1. Repository Structure

```text
saga-agent/
├── MASTER_PLAN.md           # This master architecture & coordination document
├── TODO.md                  # Phased implementation checklist
├── MEMORY.md                # Shared state handoff log between Codex and Gemini
├── BUGS.md                  # Edge-case and bug log (used for engineering validation)
├── backend/
│   ├── pyproject.toml       # Python 3.11+, FastAPI, SQLModel, SQLAlchemy, aiosqlite, pydantic, pytest, pytest-asyncio, httpx
│   ├── app/
│   │   ├── main.py                  # FastAPI entrypoint + lifespan DB init
│   │   ├── config.py                # Settings (DB URL, LLM mode: DETERMINISTIC_MOCK vs LIVE_LLM)
│   │   ├── db/
│   │   │   ├── session.py           # AsyncEngine & AsyncSession (sqlite+aiosqlite default, postgres ready)
│   │   │   ├── models.py            # SQLModel tables: Runs, Steps, Approvals, MockExternalTables
│   │   │   └── seed/
│   │   │       ├── catalogue.json   # 30 Aplus B2B items
│   │   │       └── rfq_scenarios.json # 20 synthetic RFQ + mutation scenarios
│   │   ├── engine/
│   │   │   ├── state_machine.py     # Enums & strict legal state transition guards
│   │   │   ├── contracts.py         # BaseToolContract, ToolResult, VerifyResult, CompensateResult, ChaosContext
│   │   │   ├── approval.py          # Canonical JSON SHA-256 hashing & stale approval guard
│   │   │   ├── compensator.py       # Reverse-order Saga rollback & compensation failure handling
│   │   │   ├── runtime.py           # Durable runner, write-ahead IN_FLIGHT logging, OUTCOME_UNKNOWN reconciliation
│   │   │   └── fork_sandbox.py      # Clones run state at Step K into isolated SANDBOX namespace
│   │   ├── agent/
│   │   │   └── planner.py           # RFQ parser, catalogue matcher, compatibility verifier, exception detector
│   │   ├── tools/
│   │   │   ├── chaos_middleware.py  # Fault injection hooks (drop response after write, crash, timeout, fail compensation)
│   │   │   ├── inventory_tool.py    # Reserve stock / verify hold / release hold
│   │   │   ├── crm_tool.py          # Create draft quote / verify quote / mark quote VOIDED
│   │   │   └── email_tool.py        # Dispatch final quote (NON_COMPENSATABLE terminal tool)
│   │   └── api/
│   │       ├── routes_runs.py       # Create, resume, approve, reject, revise-rfq, fork, get trace
│   │       └── routes_chaos.py      # Trigger scenarios & fetch benchmark metrics
│   ├── scripts/
│   │   ├── seed_data.py             # Generates catalogue.json & rfq_scenarios.json and seeds DB
│   │   └── run_benchmarks.py        # Runs 100 fault-injected trials: NaiveRetryAgent vs SagaAgentRuntime
│   └── tests/
│       ├── conftest.py              # Async SQLite fixture + seeded catalogue
│       ├── test_reconciliation.py   # Scenario 1: CRM write succeeds -> response drops -> verify() resolves
│       ├── test_crash_recovery.py   # Scenario 2: Worker crashes mid-run -> resumes cleanly from persisted progress
│       ├── test_compensation.py     # Scenario 3: Rejection triggers reverse compensation; failed compensation halts safely
│       ├── test_stale_approval.py   # Scenario 4: Customer mutates RFQ post-approval -> stale approval rejected
│       └── test_sandbox_fork.py     # Scenario 5: Fork failed/completed run at Step K into isolated sandbox
└── frontend/                        # Phase 5 Vite + React + TypeScript Trace & Chaos Studio
```

---

## 2. Database Schema & State Machines (`backend/app/db/models.py`)

### 2.1 Enumerations (`backend/app/engine/state_machine.py`)

```python
from enum import Enum

class ExecutionMode(str, Enum):
    LIVE = "LIVE"
    SANDBOX = "SANDBOX"

class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RECONCILING = "RECONCILING"
    COMPENSATING = "COMPENSATING"
    COMPLETED = "COMPLETED"
    COMPENSATED_HALTED = "COMPENSATED_HALTED"
    FAILED_NEEDS_HUMAN = "FAILED_NEEDS_HUMAN"

class StepStatus(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    COMMITTED = "COMMITTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"

class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVALIDATED_STALE = "INVALIDATED_STALE"

class IdempotencyCapability(str, Enum):
    NATIVE_IDEMPOTENT = "NATIVE_IDEMPOTENT"
    VERIFY_BEFORE_RETRY = "VERIFY_BEFORE_RETRY"
    NON_COMPENSATABLE = "NON_COMPENSATABLE"
```

### 2.2 Core Runtime Tables

1. **`workflow_runs`**
   - `id`: `str` (UUID4 PK)
   - `parent_run_id`: `Optional[str]` (FK to `workflow_runs.id` when forked)
   - `forked_from_step_index`: `Optional[int]`
   - `execution_mode`: `ExecutionMode` (`LIVE` or `SANDBOX`)
   - `sandbox_namespace`: `str` (default `"live"`, or `"sandbox_<run_id>"` for forked runs)
   - `status`: `RunStatus`
   - `current_revision_id`: `int` (default `1`; increments when customer revises RFQ)
   - `rfq_payload`: `dict` (JSON column storing customer name, email, raw request text, and revision history)
   - `agent_plan`: `dict` (JSON column storing extracted line items, matched SKUs, total amount, exceptions, and proposed action payload)
   - `state_hash`: `str` (SHA-256 hex digest of canonical JSON of `current_revision_id + rfq_payload + agent_plan`)
   - `error_summary`: `Optional[str]`
   - `created_at`, `updated_at`: `datetime`

2. **`step_executions`**
   - `id`: `str` (UUID4 PK)
   - `run_id`: `str` (Indexed FK to `workflow_runs.id`)
   - `revision_id`: `int` (Matches `workflow_runs.current_revision_id` when step was created)
   - `step_index`: `int`
     - `0`: `parse_and_match_rfq` (AI Planner step)
     - `1`: `reserve_inventory` (`inventory_tool`)
     - `2`: `create_crm_draft` (`crm_tool`)
     - `3`: `await_human_approval` (Approval gate)
     - `4`: `dispatch_quote_email` (`email_tool` — terminal action)
   - `step_name`: `str`
   - `tool_name`: `str`
   - `operation_id`: `str` (Deterministic UUID5: `uuid5(NAMESPACE_OID, f"{run_id}:{revision_id}:{step_index}")`, Indexed)
   - `status`: `StepStatus`
   - `attempt_count`: `int` (default `0`)
   - `input_payload`: `dict` (JSON)
   - `output_payload`: `Optional[dict]` (JSON)
   - `external_record_id`: `Optional[str]` (e.g., `hold_id`, `quote_id`, `email_id`)
   - `verification_evidence`: `Optional[dict]` (JSON proof from `execute()` or `verify()`)
   - `compensation_evidence`: `Optional[dict]` (JSON proof from `compensate()`)
   - `error_detail`: `Optional[str]`
   - `started_at`, `completed_at`: `Optional[datetime]`

3. **`approval_records`**
   - `id`: `str` (UUID4 PK)
   - `run_id`: `str` (Indexed FK to `workflow_runs.id`)
   - `bound_revision_id`: `int`
   - `bound_state_hash`: `str` (SHA-256 hash at the moment approval was requested/granted)
   - `status`: `ApprovalStatus`
   - `reviewer_id`: `Optional[str]`
   - `reviewer_note`: `Optional[str]`
   - `created_at`, `decided_at`: `Optional[datetime]`

### 2.3 Mock External Service Tables (Partitioned by `namespace`)

All mock external services live in the database and partition state by `namespace` (`"live"` vs `"sandbox_<run_id>"`) so sandbox forks can copy state and execute against realistic tables without touching live records:

1. **`mock_inventory_stock`**
   - Composite PK: `(namespace, sku)`
   - Fields: `name`, `category`, `unit_price` (int/float), `available_qty` (int), `reserved_qty` (int), `specs` (JSON)
2. **`mock_inventory_holds`**
   - PK: `hold_id` (`str`)
   - Fields: `namespace` (Indexed), `operation_id` (Indexed), `run_id`, `items` (JSON list of `{sku, qty}`), `status` (`ACTIVE`, `RELEASED`), `created_at`, `released_at`
3. **`mock_crm_quotes`**
   - PK: `quote_id` (`str`)
   - Fields: `namespace` (Indexed), `operation_id` (Indexed), `run_id`, `customer_email`, `total_amount`, `line_items` (JSON), `status` (`DRAFT`, `VOIDED`, `SENT`), `created_at`, `voided_at`
4. **`mock_dispatched_emails`**
   - PK: `email_id` (`str`)
   - Fields: `namespace` (Indexed), `operation_id` (Indexed), `run_id`, `recipient`, `quote_id`, `bound_state_hash`, `body_summary`, `sent_at`

---

## 3. Tool Contracts & Fault Injection Specification

### 3.1 `ChaosContext` (`backend/app/tools/chaos_middleware.py`)
Passed into runtime execution to deterministically trigger failures in unit tests, benchmarks, and the UI demo:

```python
class ChaosConfig(BaseModel):
    drop_response_after_write_on_step: Optional[int] = None   # Scenario 1: Write commits to mock DB, then raises NetworkDropAfterWriteError
    crash_worker_after_step_in_flight: Optional[int] = None   # Scenario 2: Raises WorkerCrashError while step is IN_FLIGHT or right after
    fail_compensation_on_step: Optional[int] = None           # Scenario 3: Raises CompensationFailureError inside tool.compensate()
    transient_timeout_before_write_on_step: Optional[int] = None # Fails before external write occurs
```

### 3.2 Concrete Tool Specifications

| Tool Name | `idempotency_capability` | `supports_compensation` | `execute()` Behavior | `verify(operation_id)` Behavior | `compensate(external_record_id)` Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `inventory_tool` | `VERIFY_BEFORE_RETRY` | `True` | Checks stock in `mock_inventory_stock`, decrements `available_qty`, increments `reserved_qty`, inserts `ACTIVE` row in `mock_inventory_holds` with `operation_id`. | Queries `mock_inventory_holds` by `(namespace, operation_id)`. If found, returns `exists=True, external_record_id=hold_id`. | Marks `mock_inventory_holds.status = RELEASED` and restores `available_qty` / decrements `reserved_qty` (idempotent if already `RELEASED`). |
| `crm_tool` | `VERIFY_BEFORE_RETRY` | `True` | Inserts `DRAFT` quote into `mock_crm_quotes` with `operation_id` (simulating a non-idempotent legacy CRM endpoint that creates duplicates if `execute` is called twice without checking). | Queries `mock_crm_quotes` by `(namespace, operation_id)`. Returns `exists=True, external_record_id=quote_id` if present. | Updates `mock_crm_quotes.status = VOIDED` and sets `voided_at` (preserves audit trail rather than deleting row). |
| `email_tool` | `NON_COMPENSATABLE` | `False` | Verifies active approval hash one final time, updates CRM quote status to `SENT`, inserts row into `mock_dispatched_emails`. | Queries `mock_dispatched_emails` by `(namespace, operation_id)`. | Raises `NonCompensatableActionError` (cannot unsend an email). |

---

## 4. Detailed Specification of the 5 Core Scenarios

### Scenario 1: CRM Accepts Write, Response Disappears (`test_reconciliation.py`)
1. Run starts with `ChaosConfig(drop_response_after_write_on_step=2)`.
2. Step 0 (`parse_and_match_rfq`) and Step 1 (`reserve_inventory`) -> `COMMITTED`.
3. Step 2 (`create_crm_draft`) writes `status = IN_FLIGHT` to `step_executions` and commits.
4. `crm_tool.execute()` inserts a `DRAFT` row in `mock_crm_quotes`, then `ChaosConfig` raises `SimulatedNetworkDropAfterWriteError`.
5. Runtime catches the error, marks Step 2 as `OUTCOME_UNKNOWN` and Run as `RECONCILING`.
6. When `resume_run(run_id)` (or automatic reconciliation) runs:
   - Runtime sees Step 2 is `OUTCOME_UNKNOWN` with capability `VERIFY_BEFORE_RETRY`.
   - Calls `crm_tool.verify(operation_id)`.
   - `verify()` finds the created quote in `mock_crm_quotes` and returns `VerifyResult(exists=True, external_record_id=quote_id, evidence={...})`.
   - Runtime transitions Step 2 to `COMMITTED` and proceeds to Step 3 (`AWAITING_APPROVAL`).
   - **Assertion:** `SELECT count(*) FROM mock_crm_quotes WHERE run_id = :run_id` equals **1** (zero duplicate CRM quotes created).

### Scenario 2: Worker Crashes During Execution or Recovery (`test_crash_recovery.py`)
1. Run starts with `ChaosConfig(crash_worker_after_step_in_flight=1)`.
2. Step 1 (`reserve_inventory`) persists `IN_FLIGHT`, executes or partially executes, and raises `SimulatedWorkerCrashError`, terminating the invocation.
3. Calling `resume_run(run_id)` loads persisted progress from DB:
   - Step 0 (`COMMITTED`) is not re-executed.
   - Step 1 (`IN_FLIGHT` / `OUTCOME_UNKNOWN`) is reconciled via `inventory_tool.verify(operation_id)` and completed if needed.
   - Execution continues to Step 2 and Step 3 (`AWAITING_APPROVAL`).

### Scenario 3: Rejection & Compensation Failure (`test_compensation.py`)
1. **Part A (Clean Compensation):**
   - Run reaches Step 3 (`AWAITING_APPROVAL`) after committing Step 1 (Inventory hold) and Step 2 (CRM draft).
   - Reviewer calls `reject_run(run_id, note="Margin too low")`.
   - Runtime transitions Run to `COMPENSATING` and runs compensation in reverse order: Step 2 (`crm_tool.compensate` -> marks quote `VOIDED`), then Step 1 (`inventory_tool.compensate` -> marks hold `RELEASED` and restores stock).
   - Run finishes in `COMPENSATED_HALTED`.
2. **Part B (Compensation Attempt Fails):**
   - Same setup, but with `ChaosConfig(fail_compensation_on_step=1)`.
   - Step 2 compensates cleanly (`COMPENSATED`).
   - Step 1 compensation raises `SimulatedCompensationFailureError`.
   - Step 1 transitions to `COMPENSATION_FAILED`.
   - Run transitions to `FAILED_NEEDS_HUMAN` and records the exact uncompensated `hold_id` in `error_summary`.

### Scenario 4: Customer Mutates Request After Approval (`test_stale_approval.py`)
1. Run reaches Step 3 (`AWAITING_APPROVAL`) with quantity = 10 and `state_hash = H1`.
2. Reviewer calls `approve_run(run_id)` -> creates `ApprovalRecord(status=APPROVED, bound_state_hash=H1)` (with auto-dispatch paused so we can test the race window before Step 4 runs, or customer mutation arriving before `resume_after_approval`).
3. Customer revision arrives via `revise_rfq(run_id, new_rfq_payload)` changing quantity from 10 to 14:
   - `current_revision_id` increments to `2`.
   - `state_hash` recomputes to `H2` (`H2 != H1`).
   - Existing `ApprovalRecord` with `bound_state_hash = H1` is immediately marked `INVALIDATED_STALE`.
   - If the caller attempts to execute Step 4 (`dispatch_quote_email`) using the old approval, the pre-dispatch guard rejects execution (`StaleApprovalError`), compensates Revision 1's hold/draft (`VOIDED` / `RELEASED`), re-runs steps for Revision 2, and waits for a fresh approval bound to `H2`.
   - **Assertion:** Zero emails are dispatched with the stale quantity of 10.

### Scenario 5: Time-Travel Sandbox Forking (`test_sandbox_fork.py`)
1. A live run (`execution_mode=LIVE`, `sandbox_namespace="live"`) completes or fails at Step 2.
2. Engineer calls `fork_run(run_id, from_step_index=1, override_plan={...})`:
   - Creates `child_run` with `parent_run_id=run_id`, `execution_mode=SANDBOX`, `sandbox_namespace=f"sandbox_{child_run.id}"`.
   - Copies `"live"` catalogue stock and any prior step records into `sandbox_<child_run.id>`.
   - Copies Step 0 as `COMMITTED` and executes Step 1, Step 2, etc. inside the sandbox namespace.
   - **Assertion:** All records in `namespace="live"` remain completely unchanged by the forked run.

---

## 5. Benchmark Experiment Specification (`backend/scripts/run_benchmarks.py`)

To back resume claims with reproducible experimental evidence, `run_benchmarks.py` runs **100 automated trials** (20 RFQ scenarios × 5 fault profiles):
- **Baseline (`NaiveRetryRunner`):** Standard agent loop that retries on timeout/lost-response without `OUTCOME_UNKNOWN` verification, lacks reverse compensation on rejection, and checks a boolean `is_approved=True` flag instead of payload hashes.
- **System Under Test (`SagaAgentRuntime`):** Full durable runtime with `verify()`, Saga compensation, and SHA-256 payload-bound approvals.

**Metrics Measured & Output as Markdown Table:**
1. Duplicate CRM records created under dropped write responses.
2. Stale quote emails sent after mid-flight customer mutations.
3. Orphaned inventory holds left active after workflow rejection/failure.
4. Successful recovery rate after mid-flight process crashes.
5. Uncompensated resource visibility when compensation itself fails (`100% surfaced`).

---

## 6. Phased Execution Checklist (`TODO.md`)

- [x] **Phase 0: Project Setup & Seed Data**
  - [x] P0.1: Create `backend/pyproject.toml` and initialize directory structure.
  - [x] P0.2: Implement `backend/scripts/seed_data.py` and generate `catalogue.json` & `rfq_scenarios.json`.
- [x] **Phase 1: Database Models, Contracts & Mock Tools**
  - [x] P1.1: Implement `backend/app/engine/state_machine.py` and `backend/app/db/models.py` + `session.py`.
  - [x] P1.2: Implement `backend/app/engine/contracts.py` and `backend/app/tools/chaos_middleware.py`.
  - [x] P1.3: Implement `inventory_tool.py`, `crm_tool.py`, and `email_tool.py` with `execute`, `verify`, and `compensate`.
- [x] **Phase 2: Durable Runtime, Reconciliation, Approvals & Sandbox Forking**
  - [x] P2.1: Implement `backend/app/agent/planner.py` (deterministic RFQ-to-SKU matcher + optional LLM enhancement).
  - [x] P2.2: Implement `backend/app/engine/approval.py` (canonical SHA-256 state hash & stale approval invalidation).
  - [x] P2.3: Implement `backend/app/engine/compensator.py` (reverse order compensation & `FAILED_NEEDS_HUMAN` halt).
  - [x] P2.4: Implement `backend/app/engine/runtime.py` (durable step runner, `OUTCOME_UNKNOWN` reconciliation, revision handling).
  - [x] P2.5: Implement `backend/app/engine/fork_sandbox.py` (isolated namespace cloning).
- [x] **Phase 3: FastAPI Endpoints**
  - [x] P3.1: Implement `routes_runs.py`, `routes_chaos.py`, and `main.py`.
- [x] **Phase 4: Pytest Verification Suite & 100-Trial Benchmark**
  - [x] P4.1: Pass `tests/test_reconciliation.py` (Scenario 1).
  - [x] P4.2: Pass `tests/test_crash_recovery.py` (Scenario 2).
  - [x] P4.3: Pass `tests/test_compensation.py` (Scenario 3A & 3B).
  - [x] P4.4: Pass `tests/test_stale_approval.py` (Scenario 4).
  - [x] P4.5: Pass `tests/test_sandbox_fork.py` (Scenario 5).
  - [x] P4.6: Run `scripts/run_benchmarks.py` and write output table to `BENCHMARK_RESULTS.md`.
- [x] **Phase 5: Frontend Trace & Chaos Studio (Vite + React + TypeScript)**
  - [x] P5.1: Build revision-grouped step trace, approval hash inspector, chaos controls, sandbox fork provenance and external-state views.
  - [x] P5.2: Add five guided scenarios, generated OpenAPI TypeScript contracts, local reviewer actions and benchmark scorecard.
  - [x] P5.3: Verify TypeScript, lint, production build, component tests, browser integration and backend pytest with warnings as errors.
  - [x] P5.4: Refine typography, contextual action guidance, connected trace states and mobile layout; verify eight component/API tests and 16 browser checks. See frontend/VERIFICATION.md for the latest frontend record.

## V2 precedence and implementation clarifications

ARCHITECTURE_V2_RESOLUTIONS.md supersedes conflicting V1 definitions. Phases 0 through 5 are implemented. Phase 5 follows PHASE_5_FRONTEND_SPEC.md.txt and uses its allowed Vite + React stack. Retries use a stable operation_id plus a monotonically increasing external attempt_no: fencing rejects the aborted generation, while an authorized higher generation can execute. Reviewer IDs must match a configured bearer-token identity. Demo commands execute inline under a durable 30-second lease; crash recovery is explicitly driven by resume. API schemas and verification results are recorded in MEMORY.md.



---

# ARCHITECTURE_V2_RESOLUTIONS.md — Formal Resolution of All 8 Architectural Gaps

All 8 architectural gaps logged in `MEMORY.md` and `BUGS.md` are formally resolved below. Incorporate these exact specifications into the implementation and proceed with Phase 0 through Phase 4.

---

## 1. Three-Valued Verification & Late-Write Fencing (Resolves Gap 1)

“Record not found” during a timeout does not prove a write failed if the request may still be in flight.

### 1.1 `VerificationStatus` Enum
```python
class VerificationStatus(str, Enum):
    APPLIED = "APPLIED"                               # Side effect is durably committed externally
    DEFINITIVELY_NOT_APPLIED = "DEFINITIVELY_NOT_APPLIED" # Proven not applied and fenced against late arrival
    UNKNOWN = "UNKNOWN"                               # Ambiguous; cannot safely re-execute yet
```

### 1.2 Fencing & Operation Ledger Mechanism
Add table `mock_operation_ledger`:
- Composite PK: `(namespace, tool_name, operation_id)`
- Columns: `attempt_no` (`int`), `status` (`IN_FLIGHT_EXTERNAL`, `COMMITTED`, `FENCED_ABORTED`), `external_record_id` (`Optional[str]`), `deadline_at` (`datetime`), `updated_at` (`datetime`)

**Verification & Retry Rules:**
1. When a tool write is attempted, if `ChaosConfig` injects a timeout *before* the external write commits, or if `verify(operation_id)` inspects `mock_operation_ledger`:
   - If the external write committed (`status == COMMITTED`), `verify()` returns `VerifyResult(status=APPLIED, external_record_id=...)`. Runtime transitions step from `OUTCOME_UNKNOWN` -> `COMMITTED`.
   - If the external record does not exist AND the runtime calls `verify(operation_id, fence_if_missing=True)` after `deadline_at` has expired, the mock service atomically inserts/updates `(namespace, tool_name, operation_id)` to `FENCED_ABORTED` (ensuring any late arriving write with that `operation_id` is rejected by the destination) and returns `DEFINITIVELY_NOT_APPLIED`. Only on `DEFINITIVELY_NOT_APPLIED` may the runtime retry `execute()` (up to `max_execute_attempts = 3`).
   - If `ChaosConfig.keep_verification_unknown = True` (or the destination cannot fence late writes and `deadline_at` has not expired), `verify()` returns `UNKNOWN`. After `max_reconcile_polls = 3` consecutive `UNKNOWN` results, the step remains `OUTCOME_UNKNOWN` and the run halts in `FAILED_NEEDS_HUMAN` with reason `"UNRESOLVED_UNCERTAIN_SIDE_EFFECT"`. It **never** blindly re-executes on `UNKNOWN`.

---

## 2. Concurrency Control, Durable Leases & Optimistic Locking (Resolves Gap 2)

### 2.1 Optimistic Concurrency Control (`version`) & Worker Leases
Add to `workflow_runs`:
- `version`: `int` (default `1`, incremented atomically on every state transition)
- `lease_owner`: `Optional[str]` (UUID of active worker invocation)
- `lease_expires_at`: `Optional[datetime]`

### 2.2 Concurrency Rules
1. **Lease Acquisition:** Before executing, resuming, reconciling, or compensating a run, the worker must atomically acquire the lease:
   ```sql
   UPDATE workflow_runs
   SET lease_owner = :worker_id, lease_expires_at = :now_plus_30s, version = version + 1
   WHERE id = :run_id AND (lease_owner IS NULL OR lease_expires_at < :now OR lease_owner = :worker_id)
   ```
   If `rowcount == 0`, raise `409 RunLockedByActiveWorkerError`.
2. **State Mutation Guard:** Every step commit or run transition checks `WHERE id = :run_id AND version = :expected_version` and increments `version`.

---

## 3. Atomic Approval Claim & Dispatch Lock (Resolves Gap 3)

Closes the race window between approval validation, customer RFQ revision, and email dispatch, and separates content binding from reviewer attribution.

### 3.1 `approval_records` Schema Updates
- `id`: `str` (PK)
- `run_id`: `str` (FK)
- `revision_no`: `int`
- `bound_state_hash`: `str` (SHA-256 of canonical `{revision_no, rfq_payload, agent_plan, dispatch_payload}`)
- `frozen_dispatch_payload`: `dict` (Immutable JSON snapshot of exact recipient, quote_id, line items, and total approved)
- `reviewer_id`: `str` (Required authenticated actor ID, e.g., `"sales_mgr_01"`)
- `reviewer_signature`: `str` (HMAC-SHA256 over `f"{run_id}:{revision_no}:{bound_state_hash}:{reviewer_id}"` using server secret)
- `status`: `PENDING` | `APPROVED` | `CONSUMED_FOR_DISPATCH` | `REJECTED` | `INVALIDATED_STALE`

### 3.2 Atomic Dispatch Claim & Revision Lockout
Add `DISPATCHING_FINAL` to `RunStatus`.
1. Before invoking `email_tool.execute()`, the runtime executes a single database transaction that:
   - Verifies `workflow_runs.active_revision_no == approval.revision_no` and `workflow_runs.state_hash == approval.bound_state_hash` and `verify_hmac(approval.reviewer_signature)`.
   - Transitions `approval_records.status` from `APPROVED` -> `CONSUMED_FOR_DISPATCH`.
   - Transitions `workflow_runs.status` from `AWAITING_APPROVAL` / `RUNNING` -> `DISPATCHING_FINAL` and increments `version`.
2. **Revision Lockout Rule:** If `POST /api/runs/{id}/revise-rfq` is called while `workflow_runs.status in (DISPATCHING_FINAL, COMPLETED)`, the API immediately rejects the request with `409 Conflict ("Cannot revise RFQ after terminal dispatch has been claimed")`.
3. `email_tool.execute()` reads **only** from `approval_records.frozen_dispatch_payload`.

---

## 4. Durable, Reconcilable Compensation (Resolves Gap 4)

Prevents a crash during compensation from restoring inventory stock twice.

### 4.1 Compensation Tracking Columns on `step_executions`
- `compensation_operation_id`: `str` (Deterministic UUID5: `uuid5(NAMESPACE_OID, f"comp:{run_id}:{revision_no}:{step_index}")`)
- `compensation_status`: `enum` (`NOT_NEEDED`, `PENDING`, `IN_FLIGHT`, `OUTCOME_UNKNOWN`, `COMPENSATED`, `COMPENSATION_FAILED`)
- `compensation_attempt_count`: `int` (default `0`)

### 4.2 Idempotent Compensation Contract
Add `verify_compensation(compensation_operation_id, external_record_id, namespace) -> VerifyResult` to `BaseToolContract`.
- Before calling `tool.compensate(...)`, the runtime persists `compensation_status = IN_FLIGHT`.
- In `inventory_tool.compensate()`, releasing a hold updates `mock_inventory_holds` with:
  ```sql
  UPDATE mock_inventory_holds
  SET status = 'RELEASED', released_by_op_id = :comp_op_id, released_at = :now
  WHERE hold_id = :hold_id AND namespace = :ns AND status = 'ACTIVE'
  ```
  Stock (`available_qty += qty`, `reserved_qty -= qty`) is restored **only inside the transaction where `status` transitions from `ACTIVE` to `RELEASED`**.
- If `hold.status` is already `'RELEASED'` with `released_by_op_id == comp_op_id`, both `compensate()` and `verify_compensation()` return `APPLIED` without modifying `mock_inventory_stock` a second time.
- If a crash occurs mid-compensation, `resume_run()` reconciles any step with `compensation_status in (IN_FLIGHT, OUTCOME_UNKNOWN)` via `verify_compensation()` before continuing reverse rollback.

---

## 5. Historical Checkpoints for Sandbox Forking (Resolves Gap 5)

Forking at Step $K$ must reconstruct external state as it existed at Step $K$, not copy current live state.

### 5.1 `step_state_checkpoints` Table
- Composite PK: `(run_id, revision_no, step_index, phase)` where `phase` is `BEFORE_STEP` or `AFTER_STEP`.
- Columns:
  - `inventory_snapshot`: `list[dict]` (Full state of relevant SKUs and holds in the run's namespace at that boundary)
  - `crm_quotes_snapshot`: `list[dict]` (Full state of quotes for this run at that boundary)
  - `revision_snapshot`: `dict` (Frozen `rfq_payload` and `agent_plan` at that boundary)
  - `created_at`: `datetime`

### 5.2 Deterministic Fork Mechanics
- **Allowed Fork Boundaries:** `step_index in (0, 1, 2, 3)` (cannot fork at or after terminal dispatch if already completed, unless forking from `BEFORE_STEP` of a prior step).
- When `fork_run(run_id, from_step_index=K, revision_no=R)` runs:
  1. Loads `(run_id, R, K, 'BEFORE_STEP')` from `step_state_checkpoints`.
  2. Creates `child_run` with `execution_mode = SANDBOX` and `sandbox_namespace = f"sandbox_{child_run.id}"`.
  3. Hydrates `mock_inventory_stock`, `mock_inventory_holds`, and `mock_crm_quotes` inside `sandbox_<child_run.id>` strictly from the checkpoint snapshot, remapping `run_id` on cloned records to `child_run.id` and recording `source_record_map` in `child_run`.
  4. Copies steps `< K` as `COMMITTED` (pointing to the remapped sandbox record IDs) and executes steps $\ge K$ exclusively against `sandbox_<child_run.id>`.

---

## 6. Separation of Idempotency vs. Compensatability & Post-Dispatch Finalization (Resolves Gap 6)

### 6.1 Orthogonal Tool Attributes
Replace the single `IdempotencyCapability` enum with two distinct enums on `BaseToolContract`:
```python
class IdempotencyMode(str, Enum):
    DEDUP_KEY_SUPPORTED = "DEDUP_KEY_SUPPORTED"   # Destination deduplicates by operation_id natively
    VERIFY_THEN_FENCE = "VERIFY_THEN_FENCE"       # Requires verify() + fence before retry

class Compensatability(str, Enum):
    COMPENSATABLE = "COMPENSATABLE"               # Has semantic undo via compensate()
    IRREVERSIBLE_TERMINAL = "IRREVERSIBLE_TERMINAL" # Cannot be undone once APPLIED (e.g., external email)
```

### 6.2 Email Send vs. CRM/Inventory Finalization (Steps 4 and 5)
Separate external email transmission from internal/CRM finalization:
- **Step 4 (`dispatch_quote_email` — `email_tool`):**
  - `idempotency_mode = DEDUP_KEY_SUPPORTED`, `compensatability = IRREVERSIBLE_TERMINAL`.
  - Sends the email and records row in `mock_dispatched_emails` keyed by `operation_id`.
  - If Step 4 enters `OUTCOME_UNKNOWN`, recovery calls `email_tool.verify(operation_id)`. If `APPLIED`, Step 4 becomes `COMMITTED` and the run is **permanently non-compensatable** (must roll forward).
- **Step 5 (`finalize_quote_and_inventory` — `finalizer_tool`):**
  - `idempotency_mode = DEDUP_KEY_SUPPORTED`, `compensatability = IRREVERSIBLE_TERMINAL`.
  - Marks `mock_crm_quotes.status = 'SENT'` and transitions `mock_inventory_holds.status` from `'ACTIVE'` -> `'COMMITTED_CONVERTED'` (decrementing `reserved_qty` and recording `fulfilled_qty` so holds are never left dangling as `'ACTIVE'`).
  - If Step 4 succeeded (`COMMITTED`) and a crash/error occurs in Step 5, `resume_run()` retries Step 5 forward until `COMMITTED`, then marks the run `COMPLETED`.

---

## 7. Immutable Revision Snapshots & Ordered Superseding (Resolves Gap 7)

### 7.1 `run_revisions` Table
- Composite PK: `(run_id, revision_no)`
- Columns: `rfq_payload` (`dict`), `agent_plan` (`dict`), `state_hash` (`str`), `status` (`ACTIVE`, `SUPERSEDING_COMPENSATING`, `SUPERSEDED_COMPENSATED`, `COMPLETED`), `created_at` (`datetime`)

### 7.2 Strict Superseding Sequence
When `POST /api/runs/{id}/revise-rfq` is called on a run in `AWAITING_APPROVAL` (or `RUNNING` prior to `DISPATCHING_FINAL`):
1. Any `PENDING` or `APPROVED` (unconsumed) approval records for `revision_no = R` transition to `INVALIDATED_STALE`.
2. Revision `R` transitions to `SUPERSEDING_COMPENSATING`, and new Revision `R+1` is inserted in `run_revisions` as `ACTIVE`.
3. The runtime **must first compensate all `COMMITTED` steps belonging to `revision_no == R`** in reverse order and confirm they reach `compensation_status == COMPENSATED`.
4. Only after Revision `R` is `SUPERSEDED_COMPENSATED` does the runtime execute Step 0 (`parse_and_match_rfq`), Step 1, Step 2, and Step 3 for `revision_no = R+1`.
5. If compensation of Revision `R` fails, the run halts in `FAILED_NEEDS_HUMAN` and **never** starts Revision `R+1` on top of uncompensated Revision `R` holds/quotes.

---

## 8. Exact API Schemas, Retry Bounds & Benchmark Denominators (Resolves Gap 8)

### 8.1 Retry & Reconciliation Bounds
- `MAX_EXECUTE_ATTEMPTS = 3` (Only retried when prior attempt resulted in `DEFINITIVELY_NOT_APPLIED` or pre-write validation error).
- `MAX_RECONCILE_POLLS = 3` (If still `UNKNOWN` after 3 verification polls, halt in `FAILED_NEEDS_HUMAN`).
- `MAX_COMPENSATION_ATTEMPTS = 3` (Reconciled via `verify_compensation` between attempts; if exhausted, halt in `FAILED_NEEDS_HUMAN`).

### 8.2 REST API Contract (`backend/app/api/`)
- `POST /api/runs` -> Request: `CreateRunRequest(scenario_id: Optional[str], customer_name: str, customer_email: str, raw_request: str, chaos_config: Optional[ChaosConfig] = None, auto_pause_at_approval: bool = True)` -> Response: `RunTraceResponse`
- `POST /api/runs/{run_id}/resume` -> Request: `ResumeRunRequest(chaos_config: Optional[ChaosConfig] = None)` -> Response: `RunTraceResponse`
- `POST /api/runs/{run_id}/approve` -> Request: `ApproveRunRequest(reviewer_id: str, bound_revision_no: int, bound_state_hash: str, reviewer_note: Optional[str] = None, auto_execute_dispatch: bool = True, chaos_config: Optional[ChaosConfig] = None)` -> Response: `RunTraceResponse`
- `POST /api/runs/{run_id}/reject` -> Request: `RejectRunRequest(reviewer_id: str, reviewer_note: str, chaos_config: Optional[ChaosConfig] = None)` -> Response: `RunTraceResponse`
- `POST /api/runs/{run_id}/revise-rfq` -> Request: `ReviseRfqRequest(raw_request: str, chaos_config: Optional[ChaosConfig] = None)` -> Response: `RunTraceResponse`
- `POST /api/runs/{run_id}/fork` -> Request: `ForkRunRequest(from_step_index: int, revision_no: Optional[int] = None, override_plan: Optional[dict] = None)` -> Response: `RunTraceResponse`
- `GET /api/runs/{run_id}/trace` -> Response: `RunTraceResponse` (Includes `run`, `revisions`, `steps`, `approvals`, `checkpoints_count`, and current `external_records` in the run's namespace)

### 8.3 Benchmark Denominators (`backend/scripts/run_benchmarks.py`)
Run **100 deterministic trials** partitioned into 5 explicit cohorts of 20 runs each (1 per RFQ scenario):
1. **Cohort A (20 runs — Dropped CRM Write Response):** Denominator = 20 runs. Measure `duplicate_crm_quotes_created` (`0/20` on SagaAgent vs `20/20` on NaiveRetryRunner).
2. **Cohort B (20 runs — Worker Crash Mid-Step 1/2 + Resume):** Denominator = 20 runs. Measure `clean_recovery_without_duplicate_holds` (`20/20` on SagaAgent).
3. **Cohort C (20 runs — Reviewer Rejection at Step 3):** Denominator = 20 runs. Measure `orphaned_active_inventory_holds` (`0/20` on SagaAgent vs `20/20` on NaiveRetryRunner).
4. **Cohort D (20 runs — Injected Compensation Failure on Step 1):** Denominator = 20 runs. Measure `accurately_halted_in_failed_needs_human_with_uncompensated_id` (`20/20` on SagaAgent).
5. **Cohort E (20 runs — Post-Approval Customer RFQ Mutation Before Dispatch):** Denominator = 20 runs. Measure `stale_emails_dispatched` (`0/20` on SagaAgent vs `20/20` on Naive boolean-approval runner).

## Implemented V2 boundary details

- Integer money uses INR paise. Only explicit SKU/quantity RFQs are accepted by the deterministic planner; optional live LLM integration is deferred.
- PENDING approvals have nullable reviewer fields. Decisions require a configured token matching reviewer_id; approval signatures are HMAC-SHA256.
- Checkpoint inventory_snapshot is stored as {stock: list, holds: list}; namespace stock and this run's holds/quotes are frozen together. Prefix step snapshots are included to preserve history after later compensation. Historical operation IDs are remapped distinctly when a checkpoint includes multiple revisions.
- Invalid overrides are validated before child allocation; changed payloads require a fork at step 0 or 1. The child and immutable revision are inserted in one transaction.
- All nine routes have generated OpenAPI schemas in backend/openapi.json; response schemas are copied into MEMORY.md.
- Commands run inline; abandoned runs recover via explicit resume after lease expiry. PostgreSQL and real external providers are not validated in this scope.
