import pytest
from app.api.routes_chaos import BENCHMARK_PATH

@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
async def test_frontend_cors_authorization_preflight(client, origin):
    response = await client.options(
        "/api/runs/example/approve",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize("route", ["/api/runs", "/api/chaos/scenarios/rfq_01"])
async def test_creation_crash_exposes_exact_resumable_run_id(client, route):
    payload = {"chaos_config": {"crash_worker_after_step_in_flight": 1}}
    if route == "/api/runs":
        payload.update(customer_name="Acme", customer_email="buyer@example.test", raw_request="10 x APL-001")
    response = await client.post(route, json=payload)
    assert response.status_code == 503
    run_id = response.json()["error"]["details"][0]["run_id"]
    trace = await client.get(f"/api/runs/{run_id}/trace")
    assert trace.status_code == 200
    assert trace.json()["run"]["id"] == run_id
    assert trace.json()["steps"][1]["status"] == "IN_FLIGHT"
    resumed = await client.post(f"/api/runs/{run_id}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["run"]["status"] == "AWAITING_APPROVAL"


async def test_unlisted_origin_is_not_allowed(client):
    response = await client.options(
        "/api/runs",
        headers={"Origin": "https://unlisted.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_benchmark_route_uses_the_measured_backend_artifact(client):
    assert BENCHMARK_PATH.name == "BENCHMARK_RESULTS.json"
    if BENCHMARK_PATH.exists():
        response = await client.get("/api/chaos/benchmarks")
        assert response.status_code == 200
        assert response.json()["total_executions"] == 200
