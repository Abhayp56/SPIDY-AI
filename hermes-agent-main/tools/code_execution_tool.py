"""
tools/code_execution_tool.py — Code Execution Tool Schema & Helpers
"""

from typing import Any, Dict

SANDBOX_ALLOWED_TOOLS = set()


def _get_execution_mode() -> str:
    return "local"


def build_execute_code_schema(*args, **kwargs) -> Dict[str, Any]:
    return {
        "name": "execute_code",
        "description": "Executes Python code snippet in local Python runtime.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "code": {"type": "STRING", "description": "Python code to execute."}
            },
            "required": ["code"],
        },
    }
