# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Chapter Services Package

This package contains service layer implementations for Chapter business logic.

Services:
- DepartmentSyncService: ERPNext department synchronization
- ChapterFinanceService: Cost center management and company validation
- ChapterValidationService: Access validation and field auto-fixing
- ChapterBoardService: Board member data operations
- ChapterQueryService: Optimized query operations and permissions
- ChapterEventService: Change detection and event emission
- ChapterPermissionService: Permission checking and access control
- ChapterAssignmentService: Member assignment and reassignment operations
- ChapterMatchingService: Chapter matching and suggestion algorithms
"""

from verenigingen.services.chapter.chapter_assignment_service import ChapterAssignmentService
from verenigingen.services.chapter.chapter_board_service import ChapterBoardService, get_chapter_board_service
from verenigingen.services.chapter.chapter_event_service import ChapterEventService, get_chapter_event_service
from verenigingen.services.chapter.chapter_finance_service import (
    ChapterFinanceService,
    get_chapter_finance_service,
)
from verenigingen.services.chapter.chapter_matching_service import ChapterMatchingService
from verenigingen.services.chapter.chapter_permission_service import ChapterPermissionService
from verenigingen.services.chapter.chapter_query_service import ChapterQueryService, get_chapter_query_service
from verenigingen.services.chapter.chapter_validation_service import (
    ChapterValidationService,
    get_chapter_validation_service,
)
from verenigingen.services.chapter.department_sync_service import (
    DepartmentSyncService,
    get_department_sync_service,
)

__all__ = [
    "DepartmentSyncService",
    "get_department_sync_service",
    "ChapterFinanceService",
    "get_chapter_finance_service",
    "ChapterValidationService",
    "get_chapter_validation_service",
    "ChapterBoardService",
    "get_chapter_board_service",
    "ChapterQueryService",
    "get_chapter_query_service",
    "ChapterEventService",
    "get_chapter_event_service",
    "ChapterPermissionService",
    "ChapterAssignmentService",
    "ChapterMatchingService",
]
