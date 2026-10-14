"""
tools.browser_tool_cloud — Browser cloud configuration stubs.
"""
from __future__ import annotations

import os


def _is_headed_mode() -> bool:
    """Determine whether browser should run in headed mode."""
    return bool(os.environ.get("AGENT_BROWSER_HEADED"))
