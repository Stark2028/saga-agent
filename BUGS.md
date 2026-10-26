# SagaAgent — Architecture Resolution and Bug Log

Updated 2026-10-26 (Asia/Calcutta). V2 resolutions are implemented and verified in the SQLite mock harness. Final pytest counts, exact commands and API schemas are in MEMORY.md and backend/verification-results.json.

Phase 5 frontend is complete. The final backend suite has 65 passing tests with warnings treated as errors; frontend checks and exact commands are in MEMORY.md.

## Visual refinement — 2026-10-26

- Increased 9–10px trace metadata to 12px, strengthened secondary text, and enlarged controls and section headings.
- Added a contextual next-action panel and focused step indicator. A committed approval-gate step remains highlighted while its separate reviewer decision is pending; approved-but-paused runs focus dispatch instead.
- Reconciled writes now use persisted `verification_evidence.status=APPLIED`, rather than `reconcile_polls`, which only counts unresolved polls and can remain zero after successful verification.
- Failed compensation in an older revision remains an actionable focus, with direct step inspection. Terminal runs have no next-step indicator.
- Mobile creation controls collapse after a trace loads; reopening preserves the entered values. The trace changes to a connected vertical timeline. All five guided scenarios remain visible in a compact grid, avoiding horizontal selection drift.
- API schemas are unchanged. See MEMORY.md and frontend/VERIFICATION.md for exact results and screenshot evidence.

## Resolved architecture gaps

| ID | Resolution | Implementation / regression evidence |
| --- | --- | --- |
| A01 | Three-valued verification, deadlines, attempt-generation fencing, bounded uncertainty escalation; no blind retry on UNKNOWN. | tools/base.py; test_reconciliation.py (dropped response, UNKNOWN, unexpired attempt, rejected late generation). |
| A02 | Durable 30-second leases and owner/version/expiry guards on runtime writes; transactional inventory changes. | engine/runtime.py; test_concurrency.py (one lease winner, stale owner, version conflict, approve/revise race, overselling). |
| A03 | Token-authenticated reviewer identity, HMAC-bound immutable payload and atomic approval consumption/dispatch lockout. | engine/approval.py, runtime.py, email_tool.py; test_stale_approval.py, test_api.py, test_finalization.py. |
| A04 | Immutable revision plans/payloads, stale approval invalidation and ordered old-revision compensation before new execution. | run_revisions table; test_stale_approval.py (failed rollback blocks replacement steps). |
| A05 | Write-ahead compensation attempts, stable corrective IDs, verify_compensation and conditional stock release. | engine/compensator.py, inventory_tool.py; test_compensation.py (crash after either corrective write, lost response, exact failed hold ID). |
| A06 | Mock effects commit independently from runtime state; inventory reservations/releases are atomic and conditional. Legacy CRM remains deliberately duplicate-capable. | db/session.py, tools/; test_contracts_and_validation.py, test_concurrency.py, benchmark A. |
| A07 | Orthogonal idempotency/compensatability attributes; email verification; irreversible claim; separate forward finalizer converting holds and stock. | email_tool.py, finalizer_tool.py; test_finalization.py covers uncertain effects, crashes, known-aborted finalizer repair and no resend. |
| A08 | BEFORE_STEP checkpoints preserve external/revision/prefix history; fork IDs and operations are remapped; fresh sandbox approvals. | engine/fork_sandbox.py; test_sandbox_fork.py includes boundaries 0–3, revised runs and replay of superseded revisions. |
| A09 | Explicit run/step transition maps, nine typed routes, generated OpenAPI/response schemas, standard error envelopes and explicit resume recovery. | state_machine.py, api/; test_api.py; test_crash_recovery.py includes a real process exit and surviving lease. |
| A10 | Persisted fault consumption, retry bounds, isolated benchmark databases, fixed seed, five explicit denominators and measured evidence. | chaos_middleware.py, run_benchmarks.py; test_benchmarks.py; BENCHMARK_RESULTS.md. |

## Defects found and fixed during implementation

- SQLModel 0.0.48 rejects naive datetime values. All timestamps now use aware UTC datetimes.
- Using SQLModel table classes directly as response DTOs bypassed expected enum/datetime coercion and produced serializer warnings. Dedicated Pydantic read DTOs validate output and require every emitted field. Final tests run with warnings treated as errors.
- A fork override could leave a partially allocated child on invalid input. Overrides are validated against checkpoint prices before the atomic child/revision allocation.
- A changed plan at step 1 could leave inherited planner output inconsistent. The cloned step 0 output now matches the child's validated plan.
- Forking a revised run could assign the same new operation ID to both historical and current holds. Historical operations and corrective IDs are remapped distinctly; all four fork boundaries have regression coverage.
- A known-aborted finalizer originally had no forward retry path. The destination closes the aborted generation; resume retries finalization within the execution bound without resending email.
- Frontend direct-origin requests needed CORS from localhost and 127.0.0.1 port 3000. Both origins now support all methods and headers, including Authorization; an unlisted origin receives no CORS allow-origin header.
- Injected create/scenario crashes returned 503 without a discoverable durable run ID. Both now include `error.details[0].run_id`, allowing the studio to load the trace and offer Resume.
- The benchmark API used the wrong parent directory for its generated JSON artifact. Its route now reads `backend/BENCHMARK_RESULTS.json`, and a regression test validates the served artifact.

## Remaining deployment limits (outside the accepted V2 mock scope)

- PostgreSQL is an optional declared driver; its concurrency behavior is untested. Schema initialization uses create_all, with migrations deferred.
- External ledger/fencing, delivery and corrective actions are simulated provider behavior. Real CRM, inventory and email adapters require provider-specific enforcement and reconciliation. Cross-table finalization is atomic only in the mock database.
- Recovery is driven by explicit resume. There is no startup recovery scheduler, automatic lease heartbeat during remote calls, or guided repair action for exhausted effects. The studio shows traces and resource IDs for human intervention. An expired worker cannot commit progress.
- Reviewer tokens are a configured local identity map. Per-tenant authorization, SSO and idempotency keys for API command submission are deferred.
- Full checkpoint snapshots and unpaginated traces are bounded demo mechanisms. Hold expiry, throttling/backoff and richer natural-language/LLM planning are deferred. auto_pause_at_approval=false cannot bypass approval.
- Simulated crash exceptions release their invocation lease to keep demos immediate; actual process termination retains it until expiry, as tested.

## GitHub publication preparation

- Generated TypeScript's OpenAPI fingerprint previously depended on CRLF/LF bytes. The generator now normalizes the input to LF, matching Git checkout behavior across platforms.
- Browser integration previously hard-coded the Windows Python path. It now selects the platform-appropriate repository virtual environment and accepts `SAGA_TEST_PYTHON`.
- Personal interview files and local assistant memory remain outside the public repository. Database, secret, cache and test-output exclusions were verified before staging.
- Exact publication verification results are in docs/RELEASE_CHECKS.md and copied into local MEMORY.md by the handoff generator.

## Environment note

Windows sandbox restrictions denied pytest temporary-directory access, including a workspace-local temp directory. The suite was run through the execution tool's approved escalation, with temporary databases inside backend/.test-tmp-verified. This was an execution-environment restriction, not an application defect.
