"""
pm.environments — Virtual environment helpers for Hermes Agent runtime compatibility.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def venv_bin_dir(venv_dir: Path | str, *, windows: Optional[bool] = None) -> Path:
    """Return the scripts/bin directory for a virtual environment."""
    v = Path(venv_dir)
    is_win = sys.platform == "win32" if windows is None else windows
    return v / ("Scripts" if is_win else "bin")


def site_packages(venv: Path | str) -> Path:
    """Return site-packages directory for a virtual environment."""
    v = Path(venv)
    is_win = sys.platform == "win32"
    if is_win:
        return v / "Lib" / "site-packages"
    return v / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"


def venv_python(venv_dir: Path | str, *, windows: Optional[bool] = None) -> Path:
    """Return python binary path for a virtual environment."""
    b = venv_bin_dir(venv_dir, windows=windows)
    is_win = sys.platform == "win32" if windows is None else windows
    return b / ("python.exe" if is_win else "python")


def activate_dependencies() -> None:
    """No-op stub for runtime dependency activation."""
    pass
