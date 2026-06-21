from .anthropic_client import AnthropicLLM
from .base import LLMClient, LLMStreamEvent
from .lm_studio_client import LMStudioLLM


def get_default_llm() -> LLMClient:
    """Auto-pick the LLM client.

    Resolution order:
      1. Explicit LLM_BACKEND env var wins (anthropic | lm_studio).
      2. If ANTHROPIC_API_KEY is set, use Anthropic.
      3. Fall back to LM Studio (local, no key needed).
    """
    from ..config import get_settings

    s = get_settings()
    backend = s.llm_backend
    if backend == "anthropic" and not s.anthropic_api_key:
        backend = "lm_studio"
    if backend == "lm_studio":
        return LMStudioLLM()
    return AnthropicLLM()


__all__ = ["AnthropicLLM", "LMStudioLLM", "LLMClient", "LLMStreamEvent", "get_default_llm"]
