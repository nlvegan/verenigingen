"""
Member Utility Services - Reusable member-related utilities.

Contains member-specific utility functions:
- Age calculation and validation
- Membership duration calculation
- Member data processing utilities
"""

from verenigingen.services.member.utils.member_duration_service import (
    get_member_duration_service,
)

__all__ = [
    "get_member_duration_service",
]
