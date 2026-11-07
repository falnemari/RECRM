import os
import sys
import pytest

# 1. Force the database environment variable to the dedicated test database 'redb'
os.environ["DB_NAME"] = "redb"

# 2. Ensure backend is in python path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 3. Configure settings to guarantee target is 'redb'
from app.config import settings
settings.DB_NAME = "redb"


@pytest.fixture(autouse=True, scope="session")
def enforce_test_database_isolation():
    """
    Safety Guardrail:
    Strictly asserts that tests NEVER connect to the user database 're_db'.
    All automated test execution must run against 'redb'.
    """
    assert settings.DB_NAME == "redb", (
        f"CRITICAL SAFETY VIOLATION: Automated tests must run exclusively on 'redb'. "
        f"Detected DB_NAME='{settings.DB_NAME}'. Execution aborted to protect 're_db'."
    )
    assert "redb" in settings.asyncpg_dsn, (
        f"CRITICAL SAFETY VIOLATION: asyncpg_dsn must target 'redb', found: {settings.asyncpg_dsn}"
    )
    assert "redb" in settings.database_url, (
        f"CRITICAL SAFETY VIOLATION: database_url must target 'redb', found: {settings.database_url}"
    )

