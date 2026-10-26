import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chaos import router as chaos_router
from app.api.routes_runs import router as runs_router
from app.api.routes_tasks import router as tasks_router
from app.agent.company import seed_company
from app.config import Settings
from app.db.session import Database
from app.engine.contracts import SagaError, SimulatedWorkerCrashError
from app.engine.runtime import Runtime
from scripts.seed_data import seed


def create_app(settings=None, database=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.validate()
        db = database or Database(settings.database_url)
        await db.init()
        await seed(db)
        await seed_company(db)
        app.state.runtime = Runtime(db, settings)
        try:
            yield
        finally:
            if database is None:
                await db.close()

    app = FastAPI(title="SagaAgent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(runs_router)
    app.include_router(chaos_router)
    app.include_router(tasks_router)

    @app.exception_handler(SagaError)
    async def saga_error(request: Request, error: SagaError):
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {"code": error.code, "message": error.message, "details": []}
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = json.loads(json.dumps(error.errors(), default=str))
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    @app.exception_handler(SimulatedWorkerCrashError)
    async def simulated_crash(request: Request, error: SimulatedWorkerCrashError):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SIMULATED_WORKER_CRASH",
                    "message": str(error),
                    "details": [{"run_id": error.run_id}] if error.run_id else [],
                }
            },
        )

    return app


app = create_app()
