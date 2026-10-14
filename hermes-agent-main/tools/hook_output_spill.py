"""
tools/hook_output_spill.py — Hook Output Spill Management
"""

from typing import Any, Dict, Tuple


def get_spill_config() -> Dict[str, Any]:
    return {"max_chars": 8000}


def spill_if_oversized(text: str, *args, **kwargs) -> Tuple[str, bool]:
    if len(text) > 16000:
        return text[:16000] + "... (truncated)", True
    return text, False
