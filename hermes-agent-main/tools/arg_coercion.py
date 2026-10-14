"""
tools/arg_coercion.py — Argument Coercion for Tool Calls
"""

from typing import Any, Dict


def coerce_tool_args(tool_name: str, args: Any) -> Dict[str, Any]:
    """Ensure tool call arguments are a clean dictionary."""
    if isinstance(args, str):
        import json
        try:
            args = json.loads(args)
        except Exception:
            args = {"input": args}
    if not isinstance(args, dict):
        args = {}
    return args
