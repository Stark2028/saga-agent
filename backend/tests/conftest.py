import pytest
import httpx

from app.config import Settings
from app.db.session import Database
from app.engine.runtime import Runtime
from app.main import create_app
from scripts.seed_data import seed


@pytest.fixture
def settings():
    return Settings(
        hmac_secret="test-secret-for-approvals-at-least-32-chars",
        reviewer_tokens={"test-reviewer-token": "manager"},
    )


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.init()
    await seed(database)
    yield database
    await database.close()


@pytest.fixture
def runtime(db, settings):
    return Runtime(db, settings)


@pytest.fixture
async def client(db, settings):
    app = create_app(settings, db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield http


async def create_run(runtime, chaos=None, raw="10 x APL-001"):
    return await runtime.create("Acme", "buyer@example.test", raw, chaos_config=chaos)


async def approve(runtime, trace, **kwargs):
    return await runtime.approve(
        trace["run"]["id"],
        "manager",
        trace["run"]["active_revision_no"],
        trace["run"]["state_hash"],
        **kwargs,
    )
