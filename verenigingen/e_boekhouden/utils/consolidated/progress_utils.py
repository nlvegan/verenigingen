"""
Consolidated progress tracking utilities for E-Boekhouden integration.

This module provides canonical progress tracking with throttled commits
for migration operations. Used by enhanced migration and coordinator modules.
"""

from datetime import datetime
from typing import Any, Callable, Dict, Optional

import frappe


class MigrationProgressTracker:
    """
    Progress tracker for migration operations with throttled database commits.

    Features:
    - Percentage-based progress updates with throttled commits
    - Operation tracking with timestamps
    - Phase management for multi-step migrations
    - Elapsed time calculation
    - Error collection

    The tracker can optionally persist progress to a migration document
    for UI updates, while minimizing database churn through commit throttling.

    Example:
        >>> tracker = MigrationProgressTracker(migration_doc=my_doc)
        >>> tracker.start("accounts")
        >>> for i, item in enumerate(items):
        ...     process(item)
        ...     tracker.update_percentage("Processing accounts", (i+1)*100//len(items))
        >>> tracker.complete()
    """

    # Commit at these percentage milestones to reduce database churn
    COMMIT_MILESTONES = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}

    def __init__(
        self,
        migration_doc: Optional[Any] = None,
        total_operations: int = 0,
    ):
        """
        Initialize progress tracker.

        Args:
            migration_doc: Optional Frappe document to persist progress to.
                          Must have 'current_operation' and 'progress_percentage' fields.
            total_operations: Expected total number of operations (for completion %)
        """
        self.migration_doc = migration_doc
        self.state = {
            "phase": None,
            "current_operation": None,
            "progress_percentage": 0,
            "total_operations": total_operations,
            "completed_operations": 0,
            "start_time": None,
            "phase_start_time": None,
            "errors": [],
        }

    def start(self, phase: str, total_operations: int = 0) -> None:
        """
        Start tracking a new migration phase.

        Args:
            phase: Name of the phase (e.g., "accounts", "transactions")
            total_operations: Expected number of operations in this phase
        """
        now = datetime.now()
        if self.state["start_time"] is None:
            self.state["start_time"] = now

        self.state["phase"] = phase
        self.state["phase_start_time"] = now
        self.state["progress_percentage"] = 0
        self.state["current_operation"] = f"Starting {phase}..."

        if total_operations > 0:
            self.state["total_operations"] = total_operations
            self.state["completed_operations"] = 0

        self._persist_progress(force_commit=True)

    def update_percentage(
        self,
        operation: str,
        percentage: int,
        force_commit: bool = False,
    ) -> None:
        """
        Update progress with a percentage value.

        Commits are throttled to occur only at 10% milestones, 0%, 100%,
        or when explicitly forced. Progress is always written to the database
        but commits are batched to reduce overhead.

        Args:
            operation: Description of current operation for UI display
            percentage: Progress percentage (0-100)
            force_commit: If True, commit immediately regardless of percentage
        """
        self.state["current_operation"] = operation
        self.state["progress_percentage"] = min(max(percentage, 0), 100)

        should_commit = force_commit or percentage in self.COMMIT_MILESTONES
        self._persist_progress(force_commit=should_commit)

    def increment(self, operation: Optional[str] = None) -> None:
        """
        Increment completed operations count and update percentage.

        Use this for operation-based tracking where total_operations is known.

        Args:
            operation: Optional operation description (uses previous if not provided)
        """
        self.state["completed_operations"] += 1

        if operation:
            self.state["current_operation"] = operation

        if self.state["total_operations"] > 0:
            percentage = int(self.state["completed_operations"] / self.state["total_operations"] * 100)
            self.state["progress_percentage"] = min(percentage, 100)

        should_commit = self.state["progress_percentage"] in self.COMMIT_MILESTONES
        self._persist_progress(force_commit=should_commit)

    def complete(self, message: str = "Completed") -> None:
        """
        Mark the current phase as complete.

        Args:
            message: Completion message for UI display
        """
        self.state["current_operation"] = message
        self.state["progress_percentage"] = 100
        self._persist_progress(force_commit=True)

    def record_error(self, error: str, context: Optional[Dict] = None) -> None:
        """
        Record an error during migration.

        Args:
            error: Error message
            context: Optional context dictionary
        """
        error_record = {
            "message": error,
            "timestamp": datetime.now().isoformat(),
            "phase": self.state["phase"],
            "operation": self.state["current_operation"],
        }
        if context:
            error_record["context"] = context

        self.state["errors"].append(error_record)

    def get_progress(self) -> Dict:
        """
        Get current progress state with computed fields.

        Returns:
            Progress dictionary with percentage, elapsed time, etc.
        """
        progress = self.state.copy()

        # Compute completion percentage from operations if tracking that way
        if progress["total_operations"] > 0:
            progress["operation_percentage"] = (
                progress["completed_operations"] / progress["total_operations"] * 100
            )

        # Compute elapsed time
        if progress["start_time"]:
            progress["elapsed_seconds"] = (datetime.now() - progress["start_time"]).total_seconds()

        if progress["phase_start_time"]:
            progress["phase_elapsed_seconds"] = (
                datetime.now() - progress["phase_start_time"]
            ).total_seconds()

        return progress

    def _persist_progress(self, force_commit: bool = False) -> None:
        """
        Persist progress to migration document if available.

        Args:
            force_commit: Whether to commit the transaction
        """
        if not self.migration_doc:
            return

        try:
            # Use db_set for efficient update without loading full document
            self.migration_doc.db_set(
                {
                    "current_operation": self.state["current_operation"],
                    "progress_percentage": self.state["progress_percentage"],
                }
            )

            if force_commit:
                frappe.db.commit()

        except Exception as e:
            # Don't fail migration if progress update fails
            frappe.log_error(
                title="Migration Progress Update", message=f"Failed to persist progress: {str(e)}"
            )


def update_migration_progress(
    migration_doc: Any,
    operation: str,
    percentage: int,
    force_commit: bool = False,
) -> None:
    """
    Convenience function for one-off progress updates.

    Use MigrationProgressTracker for more complex tracking needs.

    Args:
        migration_doc: Frappe document with progress fields
        operation: Current operation description
        percentage: Progress percentage (0-100)
        force_commit: Whether to force a database commit
    """
    try:
        migration_doc.db_set(
            {
                "current_operation": operation,
                "progress_percentage": percentage,
            }
        )

        # Throttle commits to 10% milestones
        should_commit = force_commit or percentage == 0 or percentage == 100 or (percentage % 10 == 0)
        if should_commit:
            frappe.db.commit()

    except Exception as e:
        frappe.log_error(title="Migration Progress", message=f"Failed to update progress: {str(e)}")
