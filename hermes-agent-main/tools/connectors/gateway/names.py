"""Connector naming stubs."""
from typing import Optional, Tuple

def parse_connector_name(name: str) -> Optional[Tuple[str, str]]:
    if not isinstance(name, str) or not name.startswith("connectors__"):
        return None
    parts = name.split("__", 2)
    if len(parts) == 3:
        return (parts[1], parts[2])
    return None
