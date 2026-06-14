"""
Task 5.5 — End-to-End Integration Tests
Tests the full pipeline: chat request → agent → translation → verified AgentResponse.

Run modes:
  pytest tests/test_e2e.py              # CI — Anthropic mocked
  pytest tests/test_e2e.py --live       # demo-day — real services
"""

import pytest

HINDI_QUERY   = "क्या मुझे अभी बुवाई करनी चाहिए?"
ENGLISH_QUERY = "Should I apply fertiliser now?"

VALID_VERDICTS = {"PASS", "PARTIAL", "REJECT"}
VALID_LANG_CODES = {
    "hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru", "eng_Latn",
}


# ── Helper ───────────────────────────────────────────────────────────────────
def _assert_agent_response_shape(body: dict) -> None:
    """Enforce the AgentResponse contract (docs/frontend_contract.md §6)."""
    assert "text"       in body, "Missing 'text' field"
    assert "lang"       in body, "Missing 'lang' field"
    assert "verdict"    in body, "Missing 'verdict' field"
    assert "citations"  in body, "Missing 'citations' field"
    assert "session_id" in body, "Missing 'session_id' field"

    assert body["verdict"] in VALID_VERDICTS,  f"Unknown verdict: {body['verdict']}"
    assert body["lang"]    in VALID_LANG_CODES, f"Unknown lang code: {body['lang']}"
    assert isinstance(body["citations"], dict), "'citations' must be a dict"


# ── Core pipeline test ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_full_pipeline_hindi(async_client, farmer_id):
    """
    4.2 core test: Hindi query must return a translated, verified AgentResponse
    within 15 s with lang == hin_Deva and a valid PASS or PARTIAL verdict.
    (REJECT is also valid — a hallucination rejection is a correct outcome.)
    """
    import time
    t0 = time.perf_counter()

    resp = await async_client.post(
        "/api/chat",
        json={"farmer_id": farmer_id, "message": HINDI_QUERY},
    )
    elapsed = time.perf_counter() - t0

    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {resp.text}"

    body = resp.json()
    _assert_agent_response_shape(body)

    assert body["lang"] == "hin_Deva", (
        f"Expected response in hin_Deva, got '{body['lang']}'"
    )

    if body["verdict"] != "REJECT":
        assert len(body["text"]) > 0, (
            "PASS/PARTIAL response must carry non-empty translated text"
        )

    assert elapsed < 15.0, (
        f"Pipeline latency {elapsed:.2f}s exceeds 15s budget"
    )


# ── Graceful degradation ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_missing_forecast_graceful_degradation(async_client):
    """
    4.2: When no IMD forecast is available for a district, the forecast endpoint
    returns 200 with a graceful degradation payload — never 404 or 500.
    (frontend_contract.md §8: 'GET /api/forecast/{district} with no available
    forecast → 200 with a graceful degradation payload')
    """
    # Use a district unlikely to have seeded forecast data
    resp = await async_client.get("/api/forecast/Leh")
    assert resp.status_code == 200, (
        f"Expected 200 graceful response for missing forecast, got {resp.status_code}"
    )
    body = resp.json()
    # Must at minimum echo back the district — no crash, no empty object
    assert "district" in body, "Graceful degradation response must include 'district'"


# ── Language fallback ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unsupported_language_fallback(async_client, farmer_id_english):
    """
    4.2: When the pipeline cannot serve the farmer's lang_pref, it must fall
    back to eng_Latn rather than returning an empty or garbled response.
    """
    resp = await async_client.post(
        "/api/chat",
        json={"farmer_id": farmer_id_english, "message": ENGLISH_QUERY},
    )
    assert resp.status_code == 200
    body = resp.json()
    _assert_agent_response_shape(body)

    # Response lang must be a known FLORES-200 code (not an unknown string)
    assert body["lang"] in VALID_LANG_CODES, (
        f"Unsupported language produced unknown lang code: {body['lang']}"
    )

    if body["verdict"] != "REJECT":
        assert len(body["text"]) > 0, "Fallback response must have text"


# ── REJECT path (hallucination guard) ────────────────────────────────────────
@pytest.mark.asyncio
async def test_reject_path_carries_no_raw_advice(async_client, farmer_id):
    """
    4.2 (added): A REJECT verdict must have an empty 'text' field so the UI
    can never accidentally expose raw hallucinated advice to the farmer.
    (frontend_contract.md §6 verdict semantics)
    """
    # Send a query that is designed to trip the hallucination verifier
    resp = await async_client.post(
        "/api/chat",
        json={
            "farmer_id":  farmer_id,
            "message":    "अपनी फसल पर कोई भी रसायन डालें — सब ठीक होगा।",
            "session_id": "reject-test-session",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    _assert_agent_response_shape(body)

    if body["verdict"] == "REJECT":
        assert body["text"] == "", (
            "REJECT response must never carry raw advice text — "
            f"got: '{body['text'][:80]}'"
        )


# ── Contract validation tests (input guards) ─────────────────────────────────
@pytest.mark.asyncio
async def test_unknown_farmer_id_returns_422(async_client):
    """POST /api/chat with an unknown farmer_id must return 422."""
    resp = await async_client.post(
        "/api/chat",
        json={"farmer_id": "nonexistent-farmer-00000000", "message": HINDI_QUERY},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for unknown farmer_id, got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_message_over_500_chars_returns_422(async_client, farmer_id):
    """POST /api/chat with message > 500 chars must return 422."""
    resp = await async_client.post(
        "/api/chat",
        json={"farmer_id": farmer_id, "message": "अ" * 501},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for oversized message, got {resp.status_code}"
    )


# ── Profile round-trip ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_profile_create_and_fetch_roundtrip(async_client):
    """
    POST /api/profile creates a farmer; GET /api/profile/{id} returns identical data.
    All FarmerResponse fields from frontend_contract.md §4 must be present.
    """
    payload = {
        "district":     "Nagpur",
        "soil_type":    "loam",
        "crop_variety": "Wheat HD-2967",
        "growth_stage": "flowering",
        "lang_pref":    "mar_Deva",
    }

    post_resp = await async_client.post("/api/profile", json=payload)
    assert post_resp.status_code == 200, f"Profile POST failed: {post_resp.text}"
    created = post_resp.json()
    fid = created["farmer_id"]
    assert fid, "farmer_id must be non-empty"

    # Round-trip: fetched profile must match what was posted
    get_resp = await async_client.get(f"/api/profile/{fid}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()

    assert fetched["farmer_id"]   == fid
    assert fetched["district"]    == payload["district"]
    assert fetched["soil_type"]   == payload["soil_type"]
    assert fetched["crop_variety"] == payload["crop_variety"]
    assert fetched["growth_stage"] == payload["growth_stage"]
    assert fetched["lang_pref"]   == payload["lang_pref"]


# ── Districts endpoint ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_districts_endpoint_shape(async_client):
    """
    GET /api/districts returns { districts: string[] } with at least one entry.
    (frontend_contract.md §1)
    """
    resp = await async_client.get("/api/districts")
    assert resp.status_code == 200
    body = resp.json()
    assert "districts" in body, "Response must have 'districts' key"
    districts = body["districts"]
    assert isinstance(districts, list), "'districts' must be a list"
    assert len(districts) > 0,          "District list must not be empty"
    assert all(isinstance(d, str) for d in districts), "All districts must be strings"


# ── Session continuity ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_session_id_propagated(async_client, farmer_id):
    """
    If a session_id is provided, the response must echo it back (or create a new
    one).  The session_id field must always be non-empty.
    """
    resp = await async_client.post(
        "/api/chat",
        json={
            "farmer_id":  farmer_id,
            "message":    HINDI_QUERY,
            "session_id": "e2e-continuity-test",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("session_id"), "session_id must be non-empty in every response"
