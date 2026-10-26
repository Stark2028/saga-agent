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