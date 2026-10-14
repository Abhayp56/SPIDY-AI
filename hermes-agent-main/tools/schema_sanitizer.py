"""
tools/schema_sanitizer.py — Tool Schema Sanitizer Helpers
"""
from typing import Any, Dict, List


def _normalize_type_array(type_val: Any) -> Any:
    if isinstance(type_val, list) and type_val:
        return type_val[0]
    return type_val


def sanitize_schema(schema: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
    return schema


def sanitize_tool_schemas(schemas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return schemas
