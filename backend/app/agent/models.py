from datetime import datetime

from sqlmodel import Field, SQLModel

from app.db.models import json_field, now, uid


class AgentTask(SQLModel, table=True):
    __tablename__ = "agent_tasks"
    id: str = Field(default_factory=uid, primary_key=True)
    goal: str
    source_document: str = ""
    source_name: str = ""
    source_sha256: str = ""
    planner_mode: str = "offline"
    status: str = "PLANNING"
    customer_name: str | None = None
    customer_email: str | None = None
    intent: dict = json_field()
    policy_snapshot: dict = json_field()
    conversation: list[dict] = json_field(list)
    observations: list[dict] = json_field(list)
    questions: list[str] = json_field(list)
    run_id: str | None = Field(default=None, unique=True)
    raw_request: str | None = None
    selected_plan: dict = json_field()
    chaos_config: dict = json_field()
    version: int = 1
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class CompanyMemory(SQLModel, table=True):
    __tablename__ = "company_memory"
    key: str = Field(primary_key=True)
    version: int = Field(primary_key=True)
    content: dict = json_field()
    created_at: datetime = Field(default_factory=now)
