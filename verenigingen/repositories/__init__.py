"""
Verenigingen Repositories

Data access layer implementing the Repository Pattern for centralized
database query management. Eliminates query duplication and provides
type-safe data access.

Available Repositories:
- DuesScheduleRepository: Membership Dues Schedule queries (eliminates 840+ duplicate lines)
- SEPAMandateRepository: SEPA Mandate operations (extracts from member.py:3279-3343)
"""

from verenigingen.repositories.dues_schedule_repository import (
    CancellationResult,
    DuesScheduleRepository,
    ScheduleInfo,
    ScheduleStatus,
)
from verenigingen.repositories.sepa_mandate_repository import (
    MandateInfo,
    MandateOperationResult,
    SEPAMandateRepository,
)

__all__ = [
    "DuesScheduleRepository",
    "ScheduleStatus",
    "ScheduleInfo",
    "CancellationResult",
    "SEPAMandateRepository",
    "MandateInfo",
    "MandateOperationResult",
]
