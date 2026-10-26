# SagaAgent

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated by PHASE_5_FRONTEND_SPEC.md.txt: Vite + React + TypeScript + Tailwind CSS with Lucide icons. Existing FastAPI/SQLite runtime stays authoritative.

## Users and purpose

Operators and engineers inspect durable RFQ executions, trigger controlled faults, recover interrupted work, review exact approval payloads and fork historical steps into isolated sandboxes. Success means all five guided scenarios are inspectable and operable against the actual backend.

The task workspace at `/` accepts a bounded business goal and optional text RFQ, shows the selected planner mode, persists observations, asks clarifications, and verifies resulting company records. `/company` exposes company policy, customers, catalogue and business effects independently. `/studio` retains the original chaos and trace workbench. OpenAI mode is explicit and configurable; offline mode is transparently a limited parser. See docs/AGENT_WORKER.md.

## Constraints

Use the generated API contracts; monetary values are integer INR paise. Preserve approval, revision and dispatch safety rules. Reviewer credentials come from explicit local configuration and are held in browser memory. Display mock-provider scope and measured benchmark results honestly. The user requested local repository implementation and side-by-side startup, with no hosting requested.

## Evidence

PHASE_5_FRONTEND_SPEC.md.txt, MASTER_PLAN.md, backend/openapi.json, catalogue/scenario seeds, backend/examples/run-trace.json and the measured BENCHMARK_RESULTS.md. No existing frontend or brand assets.
