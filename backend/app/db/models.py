from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, JSON, CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.engine.state_machine import (
    ApprovalStatus,
    CompensationStatus,
    ExecutionMode,
    RunStatus,
    StepStatus,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


def json_field(default_factory=dict):
    return Field(
        default_factory=default_factory, sa_column=Column(JSON, nullable=False)
    )


class Run(SQLModel, table=True):
    __tablename__ = "workflow_runs"
    id: str = Field(default_factory=uid, primary_key=True)
    parent_run_id: str | None = Field(default=None, foreign_key="workflow_runs.id")
    forked_from_step_index: int | None = None
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    sandbox_namespace: str = "live"
    status: RunStatus = RunStatus.RUNNING
    active_revision_no: int = 1
    rfq_payload: dict = json_field()
    agent_plan: dict = json_field()
    state_hash: str = ""
    source_record_map: dict = json_field()
    chaos_config: dict = json_field()
    version: int = 1
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Revision(SQLModel, table=True):
    __tablename__ = "run_revisions"
    run_id: str = Field(primary_key=True, foreign_key="workflow_runs.id")
    revision_no: int = Field(primary_key=True)
    rfq_payload: dict = json_field()
    agent_plan: dict = json_field()
    state_hash: str = ""
    status: str = "ACTIVE"
    created_at: datetime = Field(default_factory=now)


class Step(SQLModel, table=True):
    __tablename__ = "step_executions"
    __table_args__ = (UniqueConstraint("run_id", "revision_no", "step_index"),)
    id: str = Field(default_factory=uid, primary_key=True)
    run_id: str = Field(foreign_key="workflow_runs.id", index=True)
    revision_no: int
    step_index: int
    step_name: str
    tool_name: str
    operation_id: str = Field(unique=True, index=True)
    status: StepStatus = StepStatus.PENDING
    attempt_count: int = 0
    reconcile_polls: int = 0
    input_payload: dict = json_field()
    output_payload: dict = json_field()
    external_record_id: str | None = None
    verification_evidence: dict = json_field()
    compensation_evidence: dict = json_field()
    compensation_operation_id: str
    compensation_status: CompensationStatus = CompensationStatus.NOT_NEEDED
    compensation_attempt_count: int = 0
    error_detail: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Approval(SQLModel, table=True):
    __tablename__ = "approval_records"
    __table_args__ = (UniqueConstraint("run_id", "revision_no"),)
    id: str = Field(default_factory=uid, primary_key=True)
    run_id: str = Field(foreign_key="workflow_runs.id", index=True)
    revision_no: int
    bound_state_hash: str
    frozen_dispatch_payload: dict = json_field()
    reviewer_id: str | None = (
        None  # Required on approval/rejection, absent while PENDING.
    )
    reviewer_signature: str | None = None
    reviewer_note: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=now)
    decided_at: datetime | None = None


class Stock(SQLModel, table=True):
    __tablename__ = "mock_inventory_stock"
    __table_args__ = (
        CheckConstraint(
            "available_qty >= 0 AND reserved_qty >= 0 AND fulfilled_qty >= 0"
        ),
    )
    namespace: str = Field(primary_key=True)
    sku: str = Field(primary_key=True)
    name: str
    category: str
    unit_price: int  # Integer paise, INR.
    available_qty: int
    reserved_qty: int = 0
    fulfilled_qty: int = 0
    specs: dict = json_field()


class Hold(SQLModel, table=True):
    __tablename__ = "mock_inventory_holds"
    __table_args__ = (UniqueConstraint("namespace", "operation_id"),)
    hold_id: str = Field(default_factory=uid, primary_key=True)
    namespace: str = Field(index=True)
    operation_id: str = Field(index=True)
    run_id: str = Field(index=True)
    items: list[dict] = json_field(list)
    status: str = "ACTIVE"
    released_by_op_id: str | None = None
    created_at: datetime = Field(default_factory=now)
    released_at: datetime | None = None


class Quote(SQLModel, table=True):
    __tablename__ = "mock_crm_quotes"
    # Deliberately no unique operation_id: legacy endpoint used by the naive baseline.
    quote_id: str = Field(default_factory=uid, primary_key=True)
    namespace: str = Field(index=True)
    operation_id: str = Field(index=True)
    run_id: str = Field(index=True)
    customer_email: str
    total_amount: int
    line_items: list[dict] = json_field(list)
    status: str = "DRAFT"
    voided_by_op_id: str | None = None
    created_at: datetime = Field(default_factory=now)
    voided_at: datetime | None = None


class Email(SQLModel, table=True):
    __tablename__ = "mock_dispatched_emails"
    __table_args__ = (UniqueConstraint("namespace", "operation_id"),)
    email_id: str = Field(default_factory=uid, primary_key=True)
    namespace: str = Field(index=True)
    operation_id: str = Field(index=True)
    run_id: str = Field(index=True)
    recipient: str
    quote_id: str
    bound_state_hash: str
    body_summary: str
    sent_at: datetime = Field(default_factory=now)


class OperationLedger(SQLModel, table=True):
    __tablename__ = "mock_operation_ledger"
    namespace: str = Field(primary_key=True)
    tool_name: str = Field(primary_key=True)
    operation_id: str = Field(primary_key=True)
    attempt_no: int = 1
    status: str = "IN_FLIGHT_EXTERNAL"
    external_record_id: str | None = None
    output_payload: dict = json_field()
    deadline_at: datetime
    updated_at: datetime = Field(default_factory=now)


class Checkpoint(SQLModel, table=True):
    __tablename__ = "step_state_checkpoints"
    run_id: str = Field(primary_key=True, foreign_key="workflow_runs.id")
    revision_no: int = Field(primary_key=True)
    step_index: int = Field(primary_key=True)
    phase: str = Field(primary_key=True)
    inventory_snapshot: dict = json_field()  # {stock: [...], holds: [...]}
    crm_quotes_snapshot: list[dict] = json_field(list)
    revision_snapshot: dict = json_field()
    created_at: datetime = Field(default_factory=now)


class Attempt(SQLModel, table=True):
    __tablename__ = "execution_attempts"
    id: str = Field(default_factory=uid, primary_key=True)
    run_id: str = Field(foreign_key="workflow_runs.id", index=True)
    step_id: str = Field(foreign_key="step_executions.id", index=True)
    kind: str
    attempt_no: int
    event: str
    evidence: dict = json_field()
    created_at: datetime = Field(default_factory=now)


class ChaosEvent(SQLModel, table=True):
    __tablename__ = "chaos_events"
    run_id: str = Field(primary_key=True, foreign_key="workflow_runs.id")
    revision_no: int = Field(primary_key=True)
    fault: str = Field(primary_key=True)
    step_index: int = Field(primary_key=True)
    created_at: datetime = Field(default_factory=now)
