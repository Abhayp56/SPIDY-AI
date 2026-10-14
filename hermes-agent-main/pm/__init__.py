"""
pm — Package manager stubs for Hermes Agent runtime compatibility.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class InstalledPackage:
    name: str
    binary: Optional[Path] = None


def installed_package(package_name: str) -> Optional[InstalledPackage]:
    """Look up an installed package binary; returns None if not provisioned."""
    return None


def env_for(name: str, base_env: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Return environment variables for a package."""
    return dict(base_env or os.environ)
