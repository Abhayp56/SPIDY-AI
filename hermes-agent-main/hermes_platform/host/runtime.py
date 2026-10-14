"""
hermes_platform.host.runtime — Platform detection stubs.
"""
from __future__ import annotations


def is_termux() -> bool:
    return False


def is_wsl() -> bool:
    return False


def is_container() -> bool:
    return False


def _detect_container() -> bool:
    return False
