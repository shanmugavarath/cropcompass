"""
Task 5.5 §4.3 — Latency Benchmark
Measures P50/P95/mean end-to-end pipeline latency and asserts P95 < 15 s.

Marked @pytest.mark.slow — excluded from regular CI runs by default.
Run explicitly:
  pytest tests/test_latency.py -m slow --live   # demo-day acceptance run
  pytest tests/test_latency.py -m slow          # against mock (measures overhead only)

A Markdown report is written to docs/latency_report.md after each run.
"""

from __future__ import annotations

import datetime
import os
import statistics
import time
from typing import Any

import pytest

HINDI_QUERY   = "क्या मुझे अभी खाद डालनी चाहिए और बुवाई का सही समय क्या है?"
P95_TARGET_S  = 15.0
BENCHMARK_RUNS = 10
REPORT_PATH    = "docs/latency_report.md"


# ── Core benchmark helper ─────────────────────────────────────────────────────
async def _single_chat_latency(client, farmer_id: str, message: str = HINDI_QUERY) -> float:
    """Run one POST /api/chat and return wall-clock seconds."""
    t0 = time.perf_counter()
    resp = await client.post(
        "/api/chat",
        json={"farmer_id": farmer_id, "message": message},
    )
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200, (
        f"Latency run failed ({resp.status_code}): {resp.text[:200]}"
    )
    return elapsed


async def benchmark_pipeline(
    client,
    farmer_id: str,
    runs: int = BENCHMARK_RUNS,
    message: str = HINDI_QUERY,
) -> dict[str, Any]:
    """
    Run `runs` sequential chat requests and return latency statistics.
    Sequential (not concurrent) to simulate a single-user interaction model.
    """
    latencies: list[float] = []
    for i in range(runs):
        elapsed = await _single_chat_latency(client, farmer_id, message)
        latencies.append(elapsed)

    latencies_sorted = sorted(latencies)
    p50 = statistics.median(latencies)
    # P95 index: ceiling of 0.95 * N, clamped to last element
    p95_idx = min(int(len(latencies_sorted) * 0.95), len(latencies_sorted) - 1)
    p95 = latencies_sorted[p95_idx]
    mean = statistics.mean(latencies)

    return {
        "runs":     runs,
        "p50_s":    round(p50,  3),
        "p95_s":    round(p95,  3),
        "mean_s":   round(mean, 3),
        "min_s":    round(min(latencies), 3),
        "max_s":    round(max(latencies), 3),
        "raw_s":    latencies,
    }


# ── Report writer ─────────────────────────────────────────────────────────────
def write_report(stats: dict[str, Any], path: str = REPORT_PATH) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    passed = stats["p95_s"] < P95_TARGET_S

    lines = [
        "# CropCompass — Latency Benchmark Report",
        "",
        f"**Generated:** {now}  ",
        f"**Runs:** {stats['runs']}  ",
        f"**Query language:** Hindi (`hin_Deva`)  ",
        f"**P95 target:** {P95_TARGET_S}s  ",
        "",
        "## Results",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| P50    | {stats['p50_s']:.3f}s |",
        f"| P95    | {stats['p95_s']:.3f}s |",
        f"| Mean   | {stats['mean_s']:.3f}s |",
        f"| Min    | {stats['min_s']:.3f}s |",
        f"| Max    | {stats['max_s']:.3f}s |",
        "",
        f"**Overall:** {'✅ PASS' if passed else '❌ FAIL — P95 exceeds target'}",
        "",
        "## Raw timings (seconds)",
        "",
        ", ".join(f"{v:.3f}" for v in stats["raw_s"]),
        "",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"\nLatency report written → {path}")


# ── Tests ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.slow
async def test_latency_p95_under_15s(async_client, farmer_id):
    """
    P95 end-to-end latency over {BENCHMARK_RUNS} sequential runs must be < 15 s.
    This is the formal acceptance gate from PLAN.md §5.5.
    Writes docs/latency_report.md as an artefact.
    """
    stats = await benchmark_pipeline(async_client, farmer_id, runs=BENCHMARK_RUNS)

    print(
        f"\n── Latency ({stats['runs']} runs) ──\n"
        f"  P50:  {stats['p50_s']:.3f}s\n"
        f"  P95:  {stats['p95_s']:.3f}s  (target < {P95_TARGET_S}s)\n"
        f"  Mean: {stats['mean_s']:.3f}s\n"
        f"  Min/Max: {stats['min_s']:.3f}s / {stats['max_s']:.3f}s"
    )

    write_report(stats)

    assert stats["p95_s"] < P95_TARGET_S, (
        f"P95 latency {stats['p95_s']:.3f}s exceeds the {P95_TARGET_S}s target. "
        f"See {REPORT_PATH} for the full breakdown."
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_latency_smoke(async_client, farmer_id):
    """Single-run sanity check — faster than the full 10-run benchmark."""
    elapsed = await _single_chat_latency(async_client, farmer_id)
    assert elapsed < P95_TARGET_S, (
        f"Single request took {elapsed:.2f}s — already over the 15s budget"
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_latency_report_file_produced(async_client, farmer_id):
    """Verifies the report file is written and non-empty after a benchmark run."""
    stats = await benchmark_pipeline(async_client, farmer_id, runs=3)
    write_report(stats)
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    assert os.path.getsize(REPORT_PATH) > 0, "Report file is empty"
