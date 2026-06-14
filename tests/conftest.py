"""
Shared fixtures for CropCompass E2E and latency tests.

Two modes (select at runtime):
  default  — in-process ASGI test client; Anthropic API is monkey-patched with a
             deterministic stub.  No API keys required.  Safe for CI.
  --live   — real httpx client pointing at a running server on TEST_BASE_URL.
             Real Anthropic API key must be in env.  Use on demo day.

Usage:
  pytest                         # CI / default mode
  pytest --live                  # demo-day acceptance run
  TEST_BASE_URL=http://prod pytest --live
"""

import os
import pytest
import pytest_asyncio
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


# ── CLI flag ─────────────────────────────────────────────────────────────────
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Hit real Anthropic API and a running backend (demo-day mode).",
    )


@pytest.fixture(scope="session")
def live(request: pytest.FixtureRequest) -> bool:
    return request.config.getoption("--live")


@pytest.fixture(scope="session")
def base_url(live: bool) -> str:
    return os.environ.get("TEST_BASE_URL", "http://localhost:8000")


# ── Backend app import (optional — backend may not exist yet) ─────────────────
def _try_import_app():
    """Try to import the FastAPI app.  Returns None if backend not yet written."""
    try:
        from api.main import app  # noqa: PLC0415  — expected path once backend lands
        return app
    except ImportError:
        return None


_APP = _try_import_app()


# ── HTTP client fixture ───────────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def async_client(live: bool, base_url: str):
    """
    Session-scoped async HTTP client.

    - live=False + backend available  → in-process ASGI client (fast, isolated)
    - live=False + no backend yet     → pytest.skip with a clear message
    - live=True                       → real HTTP client at base_url
    """
    if live:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            yield client
        return

    if _APP is None:
        pytest.skip(
            "Backend (api.main) not implemented yet. "
            "Run 'pytest --live' to test against an external server."
        )
        return

    async with httpx.AsyncClient(
        app=_APP, base_url="http://test", timeout=30.0
    ) as client:
        yield client


# ── Anthropic mock (auto-applied unless --live) ───────────────────────────────
_MOCK_PASS_RESPONSE = {
    "text": "अभी बुवाई करें और खाद की मात्रा बढ़ाएं। IMD के अनुसार अच्छी वर्षा की संभावना है।",
    "lang": "hin_Deva",
    "verdict": "PASS",
    "citations": {
        "बुवाई का सही समय": "icar_chunk_001",
        "खाद की मात्रा":     "icar_chunk_042",
    },
    "session_id": "test-session-pass",
}

_MOCK_REJECT_RESPONSE = {
    "text": "",
    "lang": "hin_Deva",
    "verdict": "REJECT",
    "citations": {},
    "session_id": "test-session-reject",
}


@pytest.fixture(autouse=True)
def mock_anthropic(live: bool):
    """
    Auto-applied fixture: patches anthropic.AsyncAnthropic for every test unless
    --live is passed.  The patch target ('api.agent.anthropic.AsyncAnthropic')
    should be adjusted to match the actual import path once the backend is written.
    """
    if live:
        yield
        return

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=str(_MOCK_PASS_RESPONSE))]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    targets = [
        "anthropic.AsyncAnthropic",           # fallback — patches at import site
        "api.agent.client",                   # likely actual path once backend lands
    ]

    try:
        with patch(targets[0], return_value=mock_client):
            yield
    except (ImportError, AttributeError):
        yield  # anthropic not installed or path wrong — tests will surface this clearly


# ── Seed farmer fixtures ──────────────────────────────────────────────────────
_FARMER_HINDI = {
    "district":     "Pune",
    "soil_type":    "clay_loam",
    "crop_variety": "Soybean JS-335",
    "growth_stage": "sowing",
    "lang_pref":    "hin_Deva",
}

_FARMER_TAMIL = {
    "district":     "Chennai",
    "soil_type":    "loam",
    "crop_variety": "Rice (IR-36)",
    "growth_stage": "vegetative",
    "lang_pref":    "tam_Taml",
}

_FARMER_ENGLISH = {
    "district":     "Bangalore",
    "soil_type":    "sandy",
    "crop_variety": "Maize HQPM-1",
    "growth_stage": "flowering",
    "lang_pref":    "eng_Latn",
}


async def _create_farmer(client: httpx.AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/profile", json=payload)
    assert resp.status_code == 200, (
        f"Seed farmer creation failed ({resp.status_code}): {resp.text}"
    )
    return resp.json()["farmer_id"]


@pytest_asyncio.fixture(scope="session")
async def farmer_id(async_client: httpx.AsyncClient) -> str:
    """Hindi (hin_Deva) farmer — used by most E2E tests."""
    return await _create_farmer(async_client, _FARMER_HINDI)


@pytest_asyncio.fixture(scope="session")
async def farmer_id_tamil(async_client: httpx.AsyncClient) -> str:
    return await _create_farmer(async_client, _FARMER_TAMIL)


@pytest_asyncio.fixture(scope="session")
async def farmer_id_english(async_client: httpx.AsyncClient) -> str:
    return await _create_farmer(async_client, _FARMER_ENGLISH)
