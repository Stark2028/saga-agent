from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

from app.engine.state_machine import (
    Compensatability,
    IdempotencyMode,
    VerificationStatus,
)


class SagaError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code, self.message, self.status_code = code, message, status_code
        super().__init__(message)


class SimulatedWorkerCrashError(Exception):
    def __init__(self, message: str, run_id: str | None = None):
        self.run_id = run_id
        super().__init__(message)


class UncertainWriteError(Exception):
    pass


class ToolResult(BaseModel):
    external_record_id: str
    output_payload: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class VerifyResult(BaseModel):
    status: VerificationStatus
    external_record_id: str | None = None
    output_payload: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class CompensateResult(VerifyResult):
    pass


class BaseToolContract(ABC):
    idempotency_mode: IdempotencyMode
    compensatability: Compensatability

    @abstractmethod
    async def execute(
        self, namespace, operation_id, attempt_no, run_id, payload, **kwargs
    ) -> ToolResult: ...

    @abstractmethod
    async def verify(self, namespace, operation_id, **kwargs) -> VerifyResult: ...

    @abstractmethod
    async def compensate(
        self, namespace, compensation_operation_id, external_record_id, **kwargs
    ) -> CompensateResult: ...

    @abstractmethod
    async def verify_compensation(
        self, compensation_operation_id, external_record_id, namespace
    ) -> VerifyResult: ...
