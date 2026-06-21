from agent_service.agent.verifier import apply_verdict, strip_unsupported


def test_pass_returns_text_as_is():
    text = "Sow now. Use 75 kg seed per hectare."
    out, verdict, citations = apply_verdict(
        text,
        {
            "verdict": "PASS",
            "unsupported_claims": [],
            "supporting_citations": {"Sow now.": "c1"},
        },
    )
    assert out == text
    assert verdict == "PASS"
    assert citations == {"Sow now.": "c1"}


def test_partial_strips_unsupported_and_appends_disclaimer():
    text = "Sow now. Add 200 kg urea per hectare."
    out, verdict, _ = apply_verdict(
        text,
        {
            "verdict": "PARTIAL",
            "unsupported_claims": ["Add 200 kg urea per hectare."],
            "supporting_citations": {"Sow now.": "c1"},
        },
    )
    assert "Sow now." in out
    assert "urea" not in out
    assert "could not be verified" in out
    assert verdict == "PARTIAL"


def test_partial_collapses_to_reject_when_empty():
    text = "Add 200 kg urea per hectare."
    out, verdict, citations = apply_verdict(
        text,
        {
            "verdict": "PARTIAL",
            "unsupported_claims": ["Add 200 kg urea per hectare."],
            "supporting_citations": {},
        },
    )
    assert "Krishi Vigyan Kendra" in out
    assert verdict == "REJECT"
    assert citations == {}


def test_reject_returns_safe_fallback():
    out, verdict, citations = apply_verdict(
        "anything", {"verdict": "REJECT", "unsupported_claims": [], "supporting_citations": {}}
    )
    assert "Krishi Vigyan Kendra" in out
    assert verdict == "REJECT"
    assert citations == {}


def test_strip_unsupported_case_insensitive():
    text = "Plant deep. Spray pesticide X."
    out = strip_unsupported(text, ["spray pesticide x."])
    assert "Plant deep." in out
    assert "Spray" not in out
