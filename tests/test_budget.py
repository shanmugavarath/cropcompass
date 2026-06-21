from agent_service.budget import CONTEXT_BUDGET, count_tokens, measure, truncate_to_budget


def test_count_tokens_handles_empty():
    assert count_tokens("") == 0
    assert count_tokens("hello world") > 0


def test_truncate_respects_budget():
    text = "word " * 1000
    out = truncate_to_budget(text, 50)
    assert count_tokens(out) <= 50


def test_truncate_noop_when_under():
    assert truncate_to_budget("short text", 100) == "short text"


def test_measure_within_total_budget():
    components = {
        "system_prompt": "a" * 100,
        "farmer_profile": "b" * 50,
        "imd_forecast": "c" * 50,
        "icar_chunks": "d" * 200,
        "user_query": "e" * 20,
    }
    report = measure(components)
    assert report.within_budget
    assert report.total > 0
    assert sum(CONTEXT_BUDGET[k] for k in components) == report.limit
