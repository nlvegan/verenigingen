"""
Display services for Member operations.

This module contains services responsible for HTML templating and
presentation logic for member-related displays.
"""

from verenigingen.services.member.display.member_onload_service import (
    get_member_onload_service,
)

__all__ = [
    "get_member_onload_service",
]
