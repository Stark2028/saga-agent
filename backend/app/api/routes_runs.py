import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.schemas import (
    ApproveRunRequest,
    CreateRunRequest,
    ERROR_RESPONSES,
    ForkRunRequest,
    RejectRunRequest,
    ResumeRunRequest,
    ReviseRfqRequest,
    RunTraceResponse,
)
from app.engine.contracts import SagaError

router = APIRouter(prefix="/api/runs", tags=["runs"], responses=ERROR_RESPONSES)
bearer = HTTPBearer(auto_error=False)


def runtime(request: Request):
    return request.app.state.runtime


def actor(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    if credentials is None:
        raise SagaError(
            "AUTHENTICATION_REQUIRED",
            "A configured reviewer bearer token is required",
            401,
        )
    for (
        token,
        reviewer_id,
    ) in request.app.state.runtime.settings.reviewer_tokens.items():
        if secrets.compare_digest(token, credentials.credentials):
            return reviewer_id
    raise SagaError("INVALID_CREDENTIALS", "Invalid reviewer bearer token", 401)


def require_actor(reviewer_id, authenticated):
    if reviewer_id != authenticated:
        raise SagaError(
            "REVIEWER_MISMATCH",
            "Reviewer ID does not match the authenticated identity",
            403,
        )


@router.post("", response_model=RunTraceResponse, status_code=201)
async def create(body: CreateRunRequest, worker=Depends(runtime)):
    return await worker.create(**body.model_dump())


@router.get("/{run_id}/trace", response_model=RunTraceResponse)
async def trace(run_id: str, worker=Depends(runtime)):
    return await worker.trace(run_id)


@router.post("/{run_id}/resume", response_model=RunTraceResponse)
async def resume(run_id: str, body: ResumeRunRequest, worker=Depends(runtime)):
    return await worker.resume(run_id, **body.model_dump())


@router.post("/{run_id}/approve", response_model=RunTraceResponse)
async def approve(
    run_id: str,
    body: ApproveRunRequest,
    worker=Depends(runtime),
    authenticated=Depends(actor),
):
    require_actor(body.reviewer_id, authenticated)
    return await worker.approve(run_id, **body.model_dump())


@router.post("/{run_id}/reject", response_model=RunTraceResponse)
async def reject(
    run_id: str,
    body: RejectRunRequest,
    worker=Depends(runtime),
    authenticated=Depends(actor),
):
    require_actor(body.reviewer_id, authenticated)
    return await worker.reject(run_id, **body.model_dump())


@router.post("/{run_id}/revise-rfq", response_model=RunTraceResponse)
async def revise(run_id: str, body: ReviseRfqRequest, worker=Depends(runtime)):
    return await worker.revise(run_id, **body.model_dump())


@router.post("/{run_id}/fork", response_model=RunTraceResponse, status_code=201)
async def fork(run_id: str, body: ForkRunRequest, worker=Depends(runtime)):
    return await worker.fork(run_id, **body.model_dump())
