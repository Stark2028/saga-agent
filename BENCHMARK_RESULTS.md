# SagaAgent Benchmark Results

Seed: 20261026. 100 cases per runner; 200 total executions. Counts are runs exhibiting the metric, with 20 cases per cohort.

| Cohort | Metric | SagaAgent | NaiveRetryRunner |
| --- | --- | ---: | ---: |
| A | duplicate_crm_quotes_created | 0/20 | 20/20 |
| B | clean_recovery_without_duplicate_holds | 20/20 | 0/20 |
| C | orphaned_active_inventory_holds | 0/20 | 20/20 |
| D | accurately_halted_in_failed_needs_human_with_uncompensated_id | 20/20 | 0/20 |
| E | stale_emails_dispatched | 0/20 | 20/20 |

A/C/E: lower is better. B/D: higher is better. Cohort D intentionally retains the failed hold and measures whether its ID is surfaced, rather than counting it as a clean rollback.

Both runners use isolated SQLite databases seeded with the same catalogue and RFQs. The baseline intentionally lacks durable progress, compensation and payload-bound approvals. Results describe this deterministic mock harness, not real-provider performance.

Raw databases and per-case evidence: `backend/.benchmark-runs/b17f52e1-10f8-41ce-98cd-281a2144cadb`.
