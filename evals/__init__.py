"""CropCompass evaluation harness.

Measures agent output quality (retrieval, grounding, answer quality, behavior,
safety) against a hand-authored golden dataset. See EVAL_HARNESS_SPEC.md.

Programmatic entry points are re-exported here; the CLI lives in evals.cli.
"""

from __future__ import annotations

from .runner import load_dataset, run_suite

__version__ = "0.1.0"

__all__ = ["load_dataset", "run_suite", "__version__"]
