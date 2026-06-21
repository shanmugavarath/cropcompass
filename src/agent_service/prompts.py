from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def load(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


PLANNER_SYSTEM = load("planner_system")
VERIFIER_SYSTEM = load("verifier_system")

SAFE_FALLBACK_MESSAGE = (
    "Please consult your local Krishi Vigyan Kendra (KVK) for current, "
    "verified advice for your crop and region."
)

PARTIAL_DISCLAIMER = (
    "\n\n Some parts of this advice could not be verified against official "
    "sources and have been removed. Please confirm with your local KVK."
)
