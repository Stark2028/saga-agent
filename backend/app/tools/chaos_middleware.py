from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ChaosEvent


class ChaosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drop_response_after_write_on_step: int | None = Field(default=None, ge=1, le=5)
    crash_worker_after_step_in_flight: int | None = Field(default=None, ge=1, le=5)
    crash_after_external_commit_on_step: int | None = Field(default=None, ge=1, le=5)
    transient_timeout_before_write_on_step: int | None = Field(default=None, ge=1, le=5)
    fail_compensation_on_step: int | None = Field(default=None, ge=1, le=2)
    crash_after_compensation_write_on_step: int | None = Field(default=None, ge=1, le=2)
    drop_compensation_response_on_step: int | None = Field(default=None, ge=1, le=2)
    crash_after_dispatch_claim: bool = False
    keep_verification_unknown: bool = False
    fail_finalization_once: bool = False


async def consume_fault(
    db, run_id: str, revision_no: int, fault: str, step_index: int
) -> bool:
    async with db.transaction() as session:
        key = (run_id, revision_no, fault, step_index)
        if await session.get(ChaosEvent, key):
            return False
        session.add(
            ChaosEvent(
                run_id=run_id,
                revision_no=revision_no,
                fault=fault,
                step_index=step_index,
            )
        )
        return True
