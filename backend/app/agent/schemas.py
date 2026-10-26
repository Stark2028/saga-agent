from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import (
    QuoteResponse,
    RunTraceResponse,
    StockResponse,
    EmailResponse,
)
from app.tools.chaos_middleware import ChaosConfig


class RequestedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str | None
    category: Literal["laptop", "monitor", "keyboard", "dock", "headset"] | None
    quantity: int | None


class TaskIntent(BaseModel):
    """Model output is a proposal, never an executable tool invocation."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["quote", "inventory", "clarify"]
    customer_name: str | None
    customer_email: str | None
    items: list[RequestedItem]
    budget_paise: int | None
    questions: list[str]
    decision_summary: str


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=5, max_length=4000)
    source_document: str = Field(default="", max_length=12000)
    source_name: str = Field(default="", max_length=200)
    planner_mode: Literal["offline", "openai"] = "offline"
    customer_name: str | None = Field(default=None, max_length=200)
    customer_email: str | None = Field(default=None, max_length=320)
    chaos_config: ChaosConfig | None = None


class TaskContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(default="", max_length=4000)
    chaos_config: ChaosConfig | None = None


class TaskObservation(BaseModel):
    sequence: int
    action: str
    summary: str
    evidence: dict
    created_at: str


class TaskRecordResponse(BaseModel):
    id: str
    goal: str
    source_name: str
    source_sha256: str
    planner_mode: str
    status: str
    questions: list[str]
    intent: TaskIntent | None
    policy_snapshot: dict
    observations: list[TaskObservation]
    run_id: str | None
    version: int
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class CompletionCheck(BaseModel):
    name: str
    passed: bool
    evidence: dict


class TaskResponse(BaseModel):
    task: TaskRecordResponse
    trace: RunTraceResponse | None
    summary: str
    checks: list[CompletionCheck]


class AgentCapabilities(BaseModel):
    offline_available: bool
    openai_configured: bool
    model: str | None
    workflow: str
    tools: list[str]


class CompanyResponse(BaseModel):
    policy: dict
    customers: list[dict]
    stock: list[StockResponse]
    quotes: list[QuoteResponse]
    emails: list[EmailResponse]
