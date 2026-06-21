"""Execution targets — how a case is run against the agent.

Metrics never depend on *how* a case executed; they only consume the resulting
`Trace`. That indirection lives here as the `EvalTarget` protocol. Phase 2 ships
the in-process target; an HTTP target could be added later behind the same shape.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schema import EvalCase, Trace


@runtime_checkable
class EvalTarget(Protocol):
    async def run(self, case: EvalCase) -> Trace: ...
    async def aclose(self) -> None: ...


__all__ = ["EvalTarget"]
