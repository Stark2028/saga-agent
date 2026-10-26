import pytest


async def make(client, **kwargs):
    return await client.post(
        "/api/runs",
        json={
            "customer_name": "Acme",
            "customer_email": "buyer@example.test",
            "raw_request": "10 x APL-001",
            **kwargs,
        },
    )


async def test_create_trace_approve_and_terminal_conflict(client):
    response = await make(client)
    assert response.status_code == 201, response.text
    trace = response.json()
    run = trace["run"]
    assert set(trace) == {
        "run",
        "steps",
        "revisions",
        "approvals",
        "attempts",
        "checkpoints_count",
        "external_records",
    }
    response = await client.get(f"/api/runs/{run['id']}/trace")
    assert response.status_code == 200
    approval = {
        "reviewer_id": "manager",
        "bound_revision_no": 1,
        "bound_state_hash": run["state_hash"],
    }
    response = await client.post(
        f"/api/runs/{run['id']}/approve",
        json=approval,
        headers={"Authorization": "Bearer test-reviewer-token"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "COMPLETED"
    response = await client.post(
        f"/api/runs/{run['id']}/revise-rfq", json={"raw_request": "14 x APL-001"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DISPATCH_ALREADY_CLAIMED"


@pytest.mark.parametrize(
    "headers,reviewer,status",
    [
        ({}, "manager", 401),
        ({"Authorization": "Bearer wrong"}, "manager", 401),
        ({"Authorization": "Bearer test-reviewer-token"}, "someone-else", 403),
    ],
)
async def test_approval_requires_matching_authenticated_identity(
    client, headers, reviewer, status
):
    trace = (await make(client)).json()
    response = await client.post(
        f"/api/runs/{trace['run']['id']}/approve",
        json={
            "reviewer_id": reviewer,
            "bound_revision_no": 1,
            "bound_state_hash": trace["run"]["state_hash"],
        },
        headers=headers,
    )
    assert response.status_code == status


async def test_validation_and_not_found_have_error_envelope(client):
    response = await make(client, customer_email="invalid")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    response = await client.get("/api/runs/missing/trace")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "RUN_NOT_FOUND",
            "message": "Run does not exist",
            "details": [],
        }
    }


async def test_crash_is_http_503_with_durable_run(client, db):
    from sqlalchemy import select
    from app.db.models import Run

    response = await make(client, chaos_config={"crash_worker_after_step_in_flight": 1})
    assert response.status_code == 503
    async with db.sessions() as session:
        run_id = (await session.scalar(select(Run))).id
    response = await client.post(f"/api/runs/{run_id}/resume", json={})
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "AWAITING_APPROVAL"


async def test_chaos_trigger_and_fork_route(client):
    response = await client.post(
        "/api/chaos/scenarios/rfq_01",
        json={"chaos_config": {"drop_response_after_write_on_step": 2}},
    )
    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    response = await client.post(f"/api/runs/{run_id}/resume", json={})
    assert response.json()["run"]["status"] == "AWAITING_APPROVAL"
    response = await client.post(
        f"/api/runs/{run_id}/fork", json={"from_step_index": 1}
    )
    assert response.status_code == 201, response.text
    assert response.json()["run"]["execution_mode"] == "SANDBOX"


async def test_api_reject_and_revise_routes(client):
    trace = (await make(client)).json()
    run_id = trace["run"]["id"]
    response = await client.post(
        f"/api/runs/{run_id}/revise-rfq", json={"raw_request": "14 x APL-001"}
    )
    assert response.status_code == 200
    assert response.json()["run"]["active_revision_no"] == 2
    response = await client.post(
        f"/api/runs/{run_id}/reject",
        json={"reviewer_id": "manager", "reviewer_note": "No"},
        headers={"Authorization": "Bearer test-reviewer-token"},
    )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "COMPENSATED_HALTED"


async def test_invalid_fork_override_returns_422_without_partial_child(client, db):
    from sqlalchemy import select
    from app.db.models import Run

    trace = (await make(client)).json()
    response = await client.post(
        f"/api/runs/{trace['run']['id']}/fork",
        json={"from_step_index": 1, "override_plan": {"line_items": []}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_OVERRIDE"
    async with db.sessions() as session:
        assert len((await session.scalars(select(Run))).all()) == 1


async def test_benchmark_endpoint_reports_saved_measurements(
    client, tmp_path, monkeypatch
):
    import json
    from app.api import routes_chaos

    path = tmp_path / "metrics.json"
    monkeypatch.setattr(routes_chaos, "BENCHMARK_PATH", path)
    response = await client.get("/api/chaos/benchmarks")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BENCHMARK_NOT_RUN"
    result = {
        "seed": 20261026,
        "cases_per_runner": 100,
        "total_executions": 200,
        "metrics": [
            {
                "cohort": "A",
                "metric": "duplicate_crm_quotes_created",
                "denominator": 20,
                "saga": 0,
                "naive": 20,
            }
        ],
    }
    path.write_text(json.dumps(result), encoding="utf-8")
    response = await client.get("/api/chaos/benchmarks")
    assert response.status_code == 200
    assert response.json() == result
