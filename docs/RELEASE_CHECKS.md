# GitHub publication checks

Prepared 2026-10-26 for `Stark2028/saga-agent`, public, with all rights reserved as requested by the owner.

## Local verification

- Backend: `python -m pytest -q -W error --basetemp=.test-tmp-verified --junitxml=pytest-results.xml` from `backend/`: **65 passed in 43.38s**, exit 0, no warnings, errors, failures, or skips.
- Frontend: `npx tsc --noEmit`, `npm run lint`, and `npm run generate:types -- --check` passed. All 28 API schema components verified.
- Frontend: `npm test`: **8 tests passed**, 1 file, duration 1.81s; test execution 202ms, exit 0.
- The latest complete visual build and 16-check Chromium walkthrough are recorded in [frontend verification](../frontend/VERIFICATION.md). The publication preparation changes the integration launcher's Python-path selection, not the UI.
- Reviewed README links and checked staged source for common GitHub/AWS token formats and private-key headers: no findings.
- Personal interview documents, résumé, raw workspace audit, local assistant memory, database files, environment secrets, dependencies and temporary test output are excluded through `.gitignore`.

## Publication preparation

- Added the README, architecture diagram, desktop/mobile screenshots, contribution/development guide and rights-reserved LICENSE.
- Added LF normalization and normalized the OpenAPI fingerprint so generated types remain valid after checkout on Windows and Linux.
- Made the browser integration launcher select `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` elsewhere, with optional `SAGA_TEST_PYTHON` override.
- Added GitHub Actions for backend verification on Windows and Linux and frontend typecheck/lint/tests/build/browser checks on Linux. Actions are pinned to verified release commit SHAs; the workflow has read-only contents permissions.
- Git author uses the owner's GitHub noreply address rather than a personal email address.

API response contracts are unchanged: nine routes, 28 schema components. GitHub Actions results are reported separately from local measurements in the repository's Actions tab.
