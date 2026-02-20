"""Shared utilities for MijnRood sync services."""

import json
from typing import Optional, Union


def safe_int(value) -> Optional[int]:
    """Safely convert a value to int, returning None on failure."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def safe_json_load(json_str: Optional[str], default: Union[dict, list, None] = None) -> Union[dict, list]:
    """Parse JSON string with guard for None/empty, returning *default* on falsy input."""
    if default is None:
        default = {}
    if not json_str:
        return default
    return json.loads(json_str)
