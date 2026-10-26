# Development guide

The repository is public for review and demonstration. All rights are reserved; see [LICENSE](LICENSE) before reusing or distributing the source. Questions and defect reports can be submitted through GitHub issues.

## Set up

Follow the [README quick start](README.md#quick-start). Keep the Python virtual environment at the repository root as `.venv`, or set `SAGA_TEST_PYTHON` when running browser tests.

## Verify a change

From `backend/`, run `python -m pytest -q -W error` using the repository virtual environment. From `frontend/`, run:

```bash
npm run generate:types -- --check
npx tsc --noEmit
npm run lint
npm test
npm run build
npm run test:integration
```

Install Playwright Chromium before running browser tests, and keep port 3000 free. Browser evidence and temporary databases are written under `frontend/test-results/` and ignored by Git.

## Contracts and runtime invariants

- Update backend response DTOs first; export OpenAPI with `python -m scripts.export_contracts`, then regenerate TypeScript with `npm run generate:types`. Do not hand-edit generated interfaces.
- Preserve integer INR paise in payloads and calculation paths.
- Keep `UNKNOWN` outcomes uncertain until verification provides a definitive result.
- Approval must remain bound to the exact revision/hash and frozen payload.
- Compensation and dispatch recovery must preserve their durable operation IDs and attempt fencing.
- Record actual verification results; distinguish mock harness measurements from provider guarantees.

## Reporting a defect

Include the affected action, expected and observed behavior, a minimal RFQ/chaos configuration, and relevant sanitized trace fields. Do not attach real bearer tokens, HMAC secrets, customer data, or database files.
