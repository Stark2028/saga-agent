from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.db.models import (
    Approval,
    Attempt,
    Email,
    Hold,
    Quote,
    Revision,
    Run,
    Step,
    Stock,
)
from app.tools.chaos_middleware import ChaosConfig


def read_model(table):
    # Table models skip ordinary Pydantic construction validation. Separate DTOs
    # validate JSON trace dictionaries and make every emitted field required.
    return create_model(
        table.__name__ + "Response",
        __config__=ConfigDict(from_attributes=True),
        **{name: (field.annotation, ...) for name, field in table.model_fields.items()},
    )


RunResponse = read_model(Run)
RevisionResponse = read_model(Revision)
StepResponse = read_model(Step)
ApprovalResponse = read_model(Approval)
AttemptResponse = read_model(Attempt)
StockResponse = read_model(Stock)
HoldResponse = read_model(Hold)
QuoteResponse = read_model(Quote)
EmailResponse = read_model(Email)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRunRequest(RequestModel):
    scenario_id: str | None = None
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    raw_request: str = Field(min_length=1, max_length=20000)
    chaos_config: ChaosConfig | None = None
    auto_pause_at_approval: bool = True


class ResumeRunRequest(RequestModel):
    chaos_config: ChaosConfig | None = None


class ApproveRunRequest(RequestModel):
    reviewer_id: str = Field(min_length=1, max_length=200)
    bound_revision_no: int = Field(ge=1)
    bound_state_hash: str = Field(pattern="^[0-9a-f]{64}$")
    reviewer_note: str | None = Field(default=None, max_length=2000)
    auto_execute_dispatch: bool = True
    chaos_config: ChaosConfig | None = None


class RejectRunRequest(RequestModel):
    reviewer_id: str = Field(min_length=1, max_length=200)
    reviewer_note: str = Field(min_length=1, max_length=2000)
    chaos_config: ChaosConfig | None = None


class ReviseRfqRequest(RequestModel):
    raw_request: str = Field(min_length=1, max_length=20000)
    chaos_config: ChaosConfig | None = None


class ForkRunRequest(RequestModel):
    from_step_index: Annotated[int, Field(ge=0, le=3)]
    revision_no: int | None = Field(default=None, ge=1)
    override_plan: dict | None = None


class ExternalRecords(BaseModel):
    stock: list[StockResponse]
    holds: list[HoldResponse]
    quotes: list[QuoteResponse]
    emails: list[EmailResponse]


class RunTraceResponse(BaseModel):
    run: RunResponse
    revisions: list[RevisionResponse]
    steps: list[StepResponse]
    approvals: list[ApprovalResponse]
    attempts: list[AttemptResponse]
    checkpoints_count: int
    external_records: ExternalRecords


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ChaosScenarioRequest(RequestModel):
    chaos_config: ChaosConfig = Field(default_factory=ChaosConfig)


class BenchmarkMetric(BaseModel):
    cohort: str
    metric: str
    denominator: int
    saga: int
    naive: int


class BenchmarkResponse(BaseModel):
    seed: int
    cases_per_runner: int
    total_executions: int
    metrics: list[BenchmarkMetric]


ERROR_RESPONSES = {
    status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 503)
}
