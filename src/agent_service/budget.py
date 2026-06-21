from dataclasses import dataclass

CONTEXT_BUDGET: dict[str, int] = {
    "system_prompt": 800,
    "farmer_profile": 200,
    "imd_forecast": 300,
    "icar_chunks": 1200,
    "user_query": 200,
    "conversation_history": 500,
}

# tiktoken's get_encoding() downloads the BPE file on first use. In an offline
# container (no DNS) that raises at import time and crashes the whole agent. Load
# it lazily and fall back to a ~4-chars/token approximation if it's unavailable —
# token counts here only bound context size and report rough sizes, so an estimate
# is fine. Bake the cache into the image (TIKTOKEN_CACHE_DIR) for exact counts.
_APPROX_CHARS_PER_TOKEN = 4
_encoder = None
_encoder_loaded = False


def _get_encoder():
    global _encoder, _encoder_loaded
    if _encoder_loaded:
        return _encoder
    _encoder_loaded = True
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _encoder = None  # offline / no cache -> approximate
    return _encoder


def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


def truncate_to_budget(text: str, budget: int) -> str:
    if budget <= 0 or not text:
        return ""
    enc = _get_encoder()
    if enc is not None:
        tokens = enc.encode(text)
        if len(tokens) <= budget:
            return text
        return enc.decode(tokens[:budget])
    # Approximate: keep ~budget tokens' worth of characters.
    max_chars = budget * _APPROX_CHARS_PER_TOKEN
    return text if len(text) <= max_chars else text[:max_chars]


@dataclass
class BudgetReport:
    used: dict[str, int]
    total: int
    limit: int

    @property
    def within_budget(self) -> bool:
        return self.total <= self.limit


def measure(components: dict[str, str]) -> BudgetReport:
    used = {name: count_tokens(text) for name, text in components.items()}
    limit = sum(CONTEXT_BUDGET.get(name, 0) for name in components)
    return BudgetReport(used=used, total=sum(used.values()), limit=limit)
