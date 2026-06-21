from dataclasses import dataclass

import tiktoken

CONTEXT_BUDGET: dict[str, int] = {
    "system_prompt": 800,
    "farmer_profile": 200,
    "imd_forecast": 300,
    "icar_chunks": 1200,
    "user_query": 200,
    "conversation_history": 500,
}

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENCODER.encode(text))


def truncate_to_budget(text: str, budget: int) -> str:
    if budget <= 0 or not text:
        return ""
    tokens = _ENCODER.encode(text)
    if len(tokens) <= budget:
        return text
    return _ENCODER.decode(tokens[:budget])


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
