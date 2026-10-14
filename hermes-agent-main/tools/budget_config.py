"""
tools/budget_config.py — Budget configuration stubs.
"""
from typing import Any

DEFAULT_BUDGET = 50000


class BudgetConfig:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.budget = DEFAULT_BUDGET


def budget_for_context_window(*args: Any, **kwargs: Any) -> int:
    return DEFAULT_BUDGET
