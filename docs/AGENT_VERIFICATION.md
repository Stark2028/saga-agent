## Task-worker verification — 2026-10-27

This is the latest verification record and supersedes the earlier Phase 5/publication counts. The extension preserves the legacy runtime/chaos API contracts and adds six task/company routes: **15 routes and 38 OpenAPI schema components** in total. All new response fields, nullability and nested references are embedded in the generated response-schema block in local MEMORY.md and in backend/openapi.json and backend/response-schemas.json. TypeScript is generated from that same specification.

| Working directory | Command | Measured result |
| --- | --- | --- |
| backend | `..\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-tmp-verified --junitxml=pytest-results.xml` | **89 passed in 130.98s (0:02:10)**, exit 0. JUnit: 89 tests, 0 failures, 0 errors, 0 skipped, duration 130.971s. Warnings are errors; none reported. |
| backend | `..\.venv\Scripts\python.exe -m scripts.run_agent_evals` | **12/12 offline cases passed**, exit 0; `backend/AGENT_EVAL_RESULTS.json`. No model calls. |
| backend | `..\.venv\Scripts\python.exe -m ruff check app tests scripts` | Passed, exit 0. |
| frontend | `npx.cmd tsc --noEmit` | Passed without diagnostics, exit 0. |
| frontend | `npm.cmd run lint` | Passed with zero warnings, exit 0. |
| frontend | `npm.cmd test` | Vitest v3.2.7: **8 passed**, 1 file; test execution 114ms, total 1.85s, exit 0. |
| frontend | `npm.cmd run build` | Vite v7.3.7: **1,598 modules**, built in 3.35s; CSS 41.21 kB (gzip 9.25 kB), JS 293.42 kB (gzip 88.86 kB), exit 0. |
| frontend | `npm.cmd run test:integration` | **24 scenario and interaction checks passed**, exit 0. |
| frontend | `npm.cmd run generate:types -- --check` | 38 generated API types match the final OpenAPI specification. |

The 24 task-worker backend cases cover interpreted quotation and verified dispatch; clarification without effects; three crash/response-loss modes; stable run reuse after continuation/reconstruction; budgets on creation, revision and sandbox override; stock-based adaptation; explicit SKU substitution only after clarification; inventory-only goals; document provenance; missing model configuration; invalid payloads; task leases; approval-bypass attempts; failed completion verification; INR paise; negative/fractional quantities and unsupported budget/currency formats; paused approved dispatch; and OpenAI structured-response/refusal handling with stubbed HTTP responses. The original 65 durability/API/benchmark tests also pass.

The 24 Chromium checks retain all 16 existing trace/chaos/responsive checks and add eight task-worker checks: explicit planner-mode labeling, goal execution with reconciliation, authenticated approval and verified completion, company-record readback, ambiguity with no allocated run, clarification continuation, text-file intake/provenance, and mobile containment. No uncaught page errors were observed.

Final browser evidence: `frontend/test-results/integration-IGAaSX/results.json`. Screenshots include task-worker-viewport.png, task-worker.png, company-workspace.png, task-worker-mobile.png and the original studio/mobile/uncertainty captures. Reviewed desktop task/company screens and the mobile task screenshot. Evidence databases and raw screenshots stay ignored by Git; selected screenshots are copied to docs/images for the README.

**Live-model limit:** no OpenAI API key/model was configured during verification. The actual Responses API path is implemented, and its request schema, strict JSON handling and refusal behavior were tested with an HTTP stub. The 12/12 evaluation is explicitly offline and does not establish live model quality or accuracy. Configure both OPENAI_API_KEY and SAGA_OPENAI_MODEL before running a separate live evaluation. Failures do not silently switch planners.

**Architecture boundary:** the model interprets the goal; the bounded controller selects permitted quotation/inventory actions based on policy and observations. Business tools mutate local mock records. This does not implement a general-purpose computer-use agent or background scheduling. Task policy is versioned persisted context; all runtime dispatch gates remain authoritative.
