"""CropCompass evaluation harness.

Measures agent output quality (retrieval, grounding, answer quality, behavior,
safety) against a hand-authored golden dataset. See EVAL_HARNESS_SPEC.md.

Phase 1 ships the data layer only: schema.py + datasets/. Later phases add
targets/, trace.py, metrics/, judge.py, runner.py, report.py, cli.py — at which
point `run_suite` is re-exported here for programmatic use.
"""

from __future__ import annotations

__version__ = "0.1.0"
