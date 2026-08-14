"""Fixtures that spawn real backend and vpn-agent processes for the cross-service E2E
suite. See tests/README.md for what this proves and why it's separate from each service's
own (mocked) test suite.
"""

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
VPN_AGENT_DIR = REPO_ROOT / "vpn"

BACKEND_PORT = 8100
VPN_AGENT_PORT = 8801

INTERNAL_TOKEN = "e2e-internal-token"
PAYMENT_WEBHOOK_SECRET = "e2e-payment-webhook-secret"
ADMIN_SECRET = "e2e-admin-bootstrap-secret"
VPN_AGENT_SHARED_SECRET = "e2e-vpn-agent-secret"

BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
VPN_AGENT_URL = f"http://localhost:{VPN_AGENT_PORT}"


def _venv_python(service_dir: Path) -> str:
    candidate = service_dir / ".venv" / "bin" / "python"
    if not candidate.exists():
        pytest.skip(
            f"{service_dir.name}/.venv not found — run `pip install -e '.[dev]'` in "
            f"{service_dir.name}/ before running the cross-service E2E suite."
        )
    return str(candidate)


def _wait_until_healthy(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{url}/health", timeout=1.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.3)
    raise RuntimeError(f"{url} never became healthy") from last_error


@pytest.fixture(scope="session")
def e2e_db_path() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="e2e_")
    os.close(fd)
    os.remove(path)  # alembic/sqlite creates it fresh
    db_url = f"sqlite+aiosqlite:///{path}"

    subprocess.run(
        [_venv_python(BACKEND_DIR), "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": db_url},
        check=True,
        capture_output=True,
    )
    yield db_url
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture(scope="session")
def vpn_agent_process() -> Iterator[str]:
    env = {
        **os.environ,
        "STATE_DB_PATH": ":memory:",
        "APPLY_TO_LIVE_INTERFACE": "false",
        "VPN_AGENT_SHARED_SECRET": VPN_AGENT_SHARED_SECRET,
    }
    proc = subprocess.Popen(
        [
            _venv_python(VPN_AGENT_DIR),
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(VPN_AGENT_PORT),
            "--log-level",
            "warning",
        ],
        cwd=VPN_AGENT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until_healthy(VPN_AGENT_URL)
        yield VPN_AGENT_URL
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def backend_process(e2e_db_path: str, vpn_agent_process: str) -> Iterator[str]:
    env = {
        **os.environ,
        "DATABASE_URL": e2e_db_path,
        "INTERNAL_SERVICE_TOKEN": INTERNAL_TOKEN,
        "PAYMENT_WEBHOOK_SECRET": PAYMENT_WEBHOOK_SECRET,
        "ADMIN_SECRET": ADMIN_SECRET,
        "VPN_AGENT_SHARED_SECRET": VPN_AGENT_SHARED_SECRET,
        "PAYMENT_PROVIDER": "mock",
    }
    proc = subprocess.Popen(
        [
            _venv_python(BACKEND_DIR),
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(BACKEND_PORT),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until_healthy(BACKEND_URL)
        yield BACKEND_URL
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def bot_client_module() -> Any:
    """Imports the bot's real BackendClient without requiring the bot's own venv — its
    only third-party dependencies (httpx, pydantic-settings, structlog) are already present
    in the backend venv this suite runs under."""
    bot_dir = str(REPO_ROOT / "bot")
    if bot_dir not in sys.path:
        sys.path.insert(0, bot_dir)
    from app.services.backend_client import BackendClient

    return BackendClient
