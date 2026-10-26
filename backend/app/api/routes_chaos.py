import json
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.routes_runs import runtime
from app.api.schemas import (
    BenchmarkResponse,
    ChaosScenarioRequest,
    ERROR_RESPONSES,
    RunTraceResponse,
)
from app.engine.contracts import SagaError
from scripts.seed_data import scenarios

router = APIRouter(prefix="/api/chaos", tags=["chaos"], responses=ERROR_RESPONSES)
BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "BENCHMARK_RESULTS.json"


@router.post(
    "/scenarios/{scenario_id}", response_model=RunTraceResponse, status_code=201
)
async def trigger(
    scenario_id: str, body: ChaosScenarioRequest, worker=Depends(runtime)
):
    scenario = next((s for s in scenarios() if s["scenario_id"] == scenario_id), None)
    if scenario is None:
        raise SagaError("SCENARIO_NOT_FOUND", "Unknown scenario ID", 404)
    return await worker.create(
        **{
            key: value
            for key, value in scenario.items()
            if key != "revised_raw_request"
        },
        chaos_config=body.chaos_config.model_dump(),
    )


@router.get("/benchmarks", response_model=BenchmarkResponse)
async def benchmarks():
    if not BENCHMARK_PATH.exists():
        raise SagaError(
            "BENCHMARK_NOT_RUN", "Run python -m scripts.run_benchmarks first", 404
        )
    return BenchmarkResponse.model_validate(
        json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    )
