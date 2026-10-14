"""
tools/terminal_tool_lifecycle.py — Terminal Tool Lifecycle & Environment Management
"""
import os
from typing import Any, Dict


def cleanup_vm(*args, **kwargs) -> None:
    """Cleanup virtual environment / container resources if needed."""
    pass


def get_active_env(*args, **kwargs) -> Dict[str, str]:
    """Get active environment dictionary."""
    return dict(os.environ)


def is_persistent_env(*args, **kwargs) -> bool:
    """Check if the active terminal environment is persistent."""
    return True
