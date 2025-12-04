"""
Volunteer Assignment Service

Handles volunteer assignment aggregation from multiple sources including board positions,
team memberships, and volunteer activities.

Business Logic:
    - Aggregates assignments from three sources: Board, Teams, Activities
    - Provides historical view of all volunteer engagements
    - Checks for active assignments across all sources

Architecture:
    This service is a thin facade over AssignmentQueryBuilder that:
    - Provides a clean public API for volunteer assignment operations
    - Delegates complex query logic to specialized query builder
    - Handles errors gracefully with fail-fast behavior
    - Maintains backward compatibility with existing code

    Design Pattern: Facade + Delegation
    - Public methods provide simple interface (get_aggregated_assignments, etc.)
    - Private methods handle implementation details (_optimized, _fallback)
    - Query complexity encapsulated in AssignmentQueryBuilder
    - Service layer focuses on business logic and error handling

Query Strategy (see AssignmentQueryBuilder for details):
    - UNION queries: Fast aggregation across multiple sources (prevents N+1)
    - Query Builder: Type-safe queries for simple operations
    - Fail-fast: Alert users to critical failures rather than hiding data

Author: Verenigingen Development Team
License: MIT
"""

from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.volunteer.assignment_query_builder import AssignmentQueryBuilder


class VolunteerAssignmentService(StatelessService):
    """Service for managing volunteer assignment aggregation"""

    def __init__(self, volunteer_name: str):
        """Initialize service for specific volunteer

        Args:
            volunteer_name: Volunteer record name
        """
        super().__init__(service_name="VolunteerAssignmentService")
        self.volunteer_name = volunteer_name
        self.volunteer_doc = None  # Lazy loaded

    def get_aggregated_assignments(self) -> List[Dict]:
        """Get aggregated assignments from all sources

        Public API method that delegates to query builder for implementation.

        Returns:
            List[Dict]: List of assignments from all sources with metadata:
                - source_type: Type of assignment (Board Position, Team, Activity)
                - source_doctype: Actual DocType name
                - role: Volunteer's role in this assignment
                - start_date, end_date: Assignment time period
                - is_active: Boolean active status
                - editable: Whether user can edit this assignment
                - source_link: UI link to source document
                - reference_display, reference_link: Reference info if applicable

        Raises:
            frappe.ValidationError: If query fails critically
        """
        try:
            # Delegate to optimized query builder
            return self._get_aggregated_assignments_optimized()
        except Exception as e:
            self.logger.error(f"Error in optimized assignments query: {str(e)}")
            # Fail-fast: show user-visible error
            return self._fail_fast_on_query_error("volunteer assignments")

    def _get_aggregated_assignments_optimized(self) -> List[Dict]:
        """Private implementation using query builder

        Delegates to AssignmentQueryBuilder for optimized UNION query.

        Returns:
            List[Dict]: Formatted assignments with metadata
        """
        query_builder = AssignmentQueryBuilder(self.volunteer_name)
        return query_builder.get_all_active_assignments()

    def _fail_fast_on_query_error(self, operation: str) -> List[Dict]:
        """
        Escalate critical query failure to user with fail-fast approach.

        This method implements the fail-fast philosophy: when optimized queries fail,
        we alert the user immediately rather than silently hiding data or attempting
        degraded functionality. The optimized queries should always work - if they
        don't, it indicates a system error requiring investigation.

        Args:
            operation: Name of the operation that failed (e.g., "volunteer assignments")

        Raises:
            frappe.ValidationError: Always throws to alert user of system error
        """
        error_message = (
            f"Critical: Optimized {operation} query failed for {self.volunteer_name}. "
            "This indicates a system error that requires investigation."
        )

        self.logger.error(f"Volunteer Query Failure: {error_message}")

        # Fail-fast: Show user-visible error instead of silently hiding data
        frappe.throw(
            frappe._(
                f"Unable to load {operation} due to a system error. "
                "Please contact your administrator. The error has been logged for investigation."
            ),
            title=frappe._("System Error"),
        )

        return []  # Unreachable, but keeps type checker happy

    def get_volunteer_history(self) -> List[Dict]:
        """Get complete volunteer history in chronological order

        Public API method that delegates to query builder for implementation.

        Returns:
            List[Dict]: Complete history from all sources, sorted by start date (newest first)
                - assignment_type: Type of assignment
                - role: Volunteer's role
                - reference: Reference to source document
                - start_date, end_date: Assignment time period
                - is_active: Boolean active status
                - status: Status text (Active, Completed, etc.)

        Raises:
            frappe.ValidationError: If query fails critically
        """
        try:
            # Delegate to optimized query builder
            return self._get_volunteer_history_optimized()
        except Exception as e:
            self.logger.error(f"Error in optimized history query: {str(e)}")
            # Fail-fast: show user-visible error (consistent with get_aggregated_assignments)
            return self._fail_fast_on_query_error("volunteer history")

    def _get_volunteer_history_optimized(self) -> List[Dict]:
        """Private implementation using query builder

        Delegates to AssignmentQueryBuilder for optimized UNION query
        plus child table integration.

        Returns:
            List[Dict]: Complete history sorted by start date
        """
        query_builder = AssignmentQueryBuilder(self.volunteer_name)
        return query_builder.get_complete_history()

    def has_active_assignments(self) -> bool:
        """Check if volunteer has any active assignments

        Public API method that delegates to query builder for implementation.
        Uses efficient short-circuit logic with early termination.

        Returns:
            bool: True if volunteer has any active assignments across all sources
        """
        query_builder = AssignmentQueryBuilder(self.volunteer_name)
        return query_builder.check_has_active_assignments()

    def _load_volunteer(self):
        """Lazy load volunteer document"""
        if not self.volunteer_doc:
            self.volunteer_doc = frappe.get_doc("Volunteer", self.volunteer_name)
        return self.volunteer_doc


def get_volunteer_assignment_service(volunteer_name: str = None) -> VolunteerAssignmentService:
    """Get instance of VolunteerAssignmentService."""
    return VolunteerAssignmentService(volunteer_name=volunteer_name)
