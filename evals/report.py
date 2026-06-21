"""Render a RunReport to JSON + Markdown + console, and evaluate gates."""

from __future__ import annotations

from pathlib import Path

from .schema import RunReport

_VERDICTS = ["PASS", "PARTIAL", "REJECT", "NONE"]


def write_json(report: RunReport, out_dir: Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "results.json"
    p.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return p


def write_markdown(report: RunReport, out_dir: Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        f"# Eval report — {report.dataset}",
        "",
        f"- cases: {report.n_cases}",
        f"- started: {report.started_at}",
        f"- finished: {report.finished_at}",
        "",
        "## Aggregates",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    for k in sorted(report.aggregates):
        lines.append(f"| {k} | {report.aggregates[k]:.3f} |")

    lines += ["", "## Verdict confusion (expected → predicted)", ""]
    lines.append("| expected \\ predicted | " + " | ".join(_VERDICTS) + " |")
    lines.append("|" + "---|" * (len(_VERDICTS) + 1))
    for e in _VERDICTS:
        if e not in report.confusion:
            continue
        row = report.confusion[e]
        lines.append(f"| {e} | " + " | ".join(str(row.get(p, 0)) for p in _VERDICTS) + " |")

    lines += ["", "## Per-case", "", "| id | passed | verdict | tags |", "|---|---|---|---|"]
    for r in report.per_case:
        mark = "✅" if r.passed else "❌"
        verdict = r.trace.final_verdict or "-"
        lines.append(f"| {r.case.id} | {mark} | {verdict} | {','.join(r.case.tags)} |")

    if report.gate_failures:
        lines += ["", "## Gate failures", ""] + [f"- {g}" for g in report.gate_failures]

    p = out / "report.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def print_summary(report: RunReport) -> None:
    print(f"\n=== Eval: {report.dataset} ({report.n_cases} cases) ===")
    for k in sorted(report.aggregates):
        print(f"  {k:26s} {report.aggregates[k]:.3f}")
    if report.gate_failures:
        print("GATE FAILURES:")
        for g in report.gate_failures:
            print("  -", g)


def evaluate_gates(report: RunReport, thresholds: dict[str, float]) -> list[str]:
    """Return the metrics below their threshold. Thresholds referencing metrics
    that weren't computed (e.g. judge_* without --judge) are skipped, not failed."""
    failures: list[str] = []
    for key, minv in thresholds.items():
        if key not in report.aggregates:
            continue
        if report.aggregates[key] < minv:
            failures.append(f"{key} {report.aggregates[key]:.3f} < {minv}")
    return failures
