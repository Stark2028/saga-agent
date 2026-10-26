from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.agent.company import company_snapshot
from app.agent.models import AgentTask
from app.agent.schemas import (
    AgentCapabilities,
    CompanyResponse,
    TaskContinueRequest,
    TaskCreateRequest,
    TaskRecordResponse,
    TaskResponse,
)
from app.agent.service import TaskWorker
from app.api.routes_runs import runtime
from app.api.schemas import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["task worker"], responses=ERROR_RESPONSES)


def worker(engine=Depends(runtime)):
    return TaskWorker(engine)


@router.get("/agent/capabilities", response_model=AgentCapabilities)
async def capabilities(engine=Depends(runtime)):
    configured = bool(engine.settings.openai_api_key and engine.settings.openai_model)
    return AgentCapabilities(
        offline_available=True,
        openai_configured=configured,
        model=engine.settings.openai_model or None,
        workflow="Quotation and inventory tasks in an isolated company demonstration environment",
        tools=[
            "read_document",
            "load_company_context",
            "inspect_inventory",
            "select_catalogue_items",
            "create_quote_workflow",
            "resume_and_verify",
            "ask_clarification",
            "human_approval",
        ],
    )


@router.get("/company", response_model=CompanyResponse)
async def company(engine=Depends(runtime)):
    return await company_snapshot(engine.db)


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(body: TaskCreateRequest, agent=Depends(worker)):
    return await agent.create(body)


@router.get("/tasks", response_model=list[TaskRecordResponse])
async def list_tasks(agent=Depends(worker)):
    async with agent.db.sessions() as session:
        tasks = (
            await session.scalars(
                select(AgentTask).order_by(AgentTask.created_at.desc()).limit(20)
            )
        ).all()
    return [(await agent.snapshot(task.id)).task for task in tasks]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def read_task(task_id: str, agent=Depends(worker)):
    return await agent.snapshot(task_id)


@router.post("/tasks/{task_id}/continue", response_model=TaskResponse)
async def continue_task(task_id: str, body: TaskContinueRequest, agent=Depends(worker)):
    return await agent.continue_task(
        task_id,
        body.answer,
        body.chaos_config.model_dump() if body.chaos_config is not None else None,
    )
