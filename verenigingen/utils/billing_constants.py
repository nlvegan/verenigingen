# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Billing Constants - Shared constants for billing operations

This module provides shared constants used across billing services:
- Error message length limits for database storage
- Database deadlock error pattern matching
- Compiled regex patterns for performance
- Recovery action enumerations for type safety

These constants are extracted from membership_dues_schedule.py and
invoice_error_handler_service.py to eliminate duplication and ensure
consistency across the billing system.
"""

import re
from enum import Enum

# Error message length limits
MAX_USER_ERROR_LENGTH = 200  # For user-facing error messages
MAX_DB_ERROR_LENGTH = 255  # For database field storage
MAX_LOG_ERROR_LENGTH = 100  # For abbreviated log messages

# Database deadlock error patterns (MySQL/MariaDB)
# These patterns are used to detect transient database locking issues
# that should be retried without counting as permanent failures
DEADLOCK_PATTERNS = [
    "deadlock",  # Generic deadlock message
    "1213",  # Deadlock found when trying to get lock; try restarting transaction
    "1205",  # Lock wait timeout exceeded; try restarting transaction
    "3058",  # InnoDB deadlock (newer MariaDB/MySQL versions)
]

# Compiled regex pattern for error message deduplication (performance optimization)
# Matches one or more occurrences of "Invoice gen(eration)? failed:" prefix
ERROR_DEDUP_PATTERN = re.compile(r"(Invoice gen(?:eration)? failed:\s*)+", re.IGNORECASE)


class RecoveryAction(str, Enum):
    """
    Enumeration of possible recovery actions for invoice generation failures.

    Inherits from str to maintain JSON serialization compatibility while
    providing type safety and IDE autocomplete support.
    """

    RETRY_TRACKED = "retry_tracked"  # Error logged, will retry in next batch
    DATE_ADVANCED = "date_advanced"  # Schedule dates advanced to prevent infinite loop
    SKIPPED = "skipped"  # Flagged for manual review


# Explicit public API declaration
__all__ = [
    "MAX_USER_ERROR_LENGTH",
    "MAX_DB_ERROR_LENGTH",
    "MAX_LOG_ERROR_LENGTH",
    "DEADLOCK_PATTERNS",
    "ERROR_DEDUP_PATTERN",
    "RecoveryAction",
]
