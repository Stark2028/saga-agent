import json
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "SAGA_DATABASE_URL", "sqlite+aiosqlite:///./saga.db"
        )
    )
    hmac_secret: str = field(default_factory=lambda: os.getenv("SAGA_HMAC_SECRET", ""))
    reviewer_tokens: dict[str, str] = field(
        default_factory=lambda: json.loads(os.getenv("SAGA_REVIEWER_TOKENS", "{}"))
    )
    planner_mode: str = "DETERMINISTIC_MOCK"
    lease_seconds: int = 30
    operation_timeout_seconds: int = 30
    max_execute_attempts: int = 3
    max_reconcile_polls: int = 3
    max_compensation_attempts: int = 3

    def validate(self):
        if len(self.hmac_secret) < 32:
            raise ValueError("SAGA_HMAC_SECRET must contain at least 32 characters")
        if self.planner_mode != "DETERMINISTIC_MOCK":
            raise ValueError("Only the deterministic planner is implemented")
