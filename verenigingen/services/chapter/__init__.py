# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Chapter Services Package

This package contains service layer implementations for Chapter business logic:
- DepartmentSyncService: ERPNext department synchronization
- ChapterFinanceService: Cost center management and company validation
- ChapterValidationService: Access validation and field auto-fixing
- ChapterBoardService: Board member data operations
- ChapterQueryService: Optimized query operations and permissions
- ChapterEventService: Change detection and event emission
- ChapterPermissionService: Permission checking and access control
- ChapterAssignmentService: Member assignment and reassignment operations
- ChapterMatchingService: Chapter matching and suggestion algorithms

Import from the submodule that defines what you need, not from this package:

    from verenigingen.services.chapter.chapter_board_service import ChapterBoardService

This __init__ deliberately imports nothing. It used to re-export nine
submodules, which made `import verenigingen.services.chapter.<anything>` run
all nine first. CPython takes the submodule lock before the package lock
(importlib._bootstrap._find_and_load acquires the lock for the full dotted
name, then _find_and_load_unlocked re-enters the import of a parent whose spec
is still _initializing), so under a threaded web worker one thread could hold
the package lock inside this file while a second held a submodule lock and
waited for the package -- a cycle CPython reports as _DeadlockError. See
verenigingen/services/billing/__init__.py, where this shape first surfaced in
production, and issue #396, which covers this and other barrel packages.

Note this is 3.13+ behaviour: python 3.12's _find_and_load_unlocked re-imports
the parent only when it is absent from sys.modules, so the cycle never closed.

verenigingen/tests/utils/test_barrel_init_no_self_import.py keeps this file
honest, alongside every other barrel package in the app.
"""
