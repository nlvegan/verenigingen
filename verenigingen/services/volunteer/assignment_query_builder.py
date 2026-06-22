"""
Volunteer Assignment Query Builder

Provides a unified abstraction layer for querying volunteer assignment data.
Encapsulates the complexity of choosing between raw SQL (fast) and Query Builder (type-safe).

Architecture:
    This abstraction solves several key problems:

    1. N+1 Query Prevention:
       - Without optimization: O(n) queries where n = number of assignment sources
       - With UNION queries: O(1) query regardless of assignment count
       - Example: 3 sources (Board, Teams, Activities) = 1 query instead of 3+

    2. Query Strategy Selection:
       - UNION queries: Best for aggregating multiple sources with different schemas
       - Query Builder: Best for simple queries with type safety
       - Trade-off: UNION is faster but harder to maintain; QB is slower but safer

    3. Consistent Interface:
       - Callers don't need to know which strategy is used
       - Easy to switch strategies without changing business logic
       - Centralized query optimization logic

Performance Characteristics:
    - get_all_assignments: O(1) query, returns all assignments at once
    - check_has_active: O(1) query with early termination, stops at first match
    - get_complete_history: O(1) query, includes archived records from child table

Author: Verenigingen Development Team
License: MIT
"""

from typing import Dict, List

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import getdate


class AssignmentQueryBuilder:
    """Unified query interface for volunteer assignment data

    This class encapsulates two query strategies:
    1. Raw SQL with UNION: Fast aggregation across multiple sources
    2. Frappe Query Builder: Type-safe individual queries

    The choice of strategy is transparent to callers.

    Caching:
    - Request-level caching prevents duplicate queries within same request
    - Results are cached per volunteer_name
    - Cache is automatically cleared at end of request
    """

    # Request-level cache attribute name
    _CACHE_ATTR = "_volunteer_assignment_cache"

    def __init__(self, volunteer_name: str):
        """Initialize query builder for specific volunteer

        Args:
            volunteer_name: Volunteer record name to query assignments for
        """
        self.volunteer_name = volunteer_name

    @classmethod
    def clear_request_cache(cls):
        """Drop the request-level assignment cache.

        The cache lives on ``frappe.local`` and is scoped to a single request in
        production (each HTTP request gets a fresh ``frappe.local``). The test
        runner, however, shares one ``frappe.local`` across many tests, and
        volunteer names repeat across rolled-back tests (the ``Volunteer``
        autoname is a sequential counter that rolls back with the transaction).
        A cached entry from an earlier test can therefore mask a later test's
        freshly-created assignments. Tests should call this in ``setUp`` to
        simulate a fresh request and avoid that cross-test leakage.
        """
        if hasattr(frappe.local, cls._CACHE_ATTR):
            delattr(frappe.local, cls._CACHE_ATTR)

    def _get_cache(self) -> dict:
        """Get or create request-level cache."""
        if not hasattr(frappe.local, self._CACHE_ATTR):
            setattr(frappe.local, self._CACHE_ATTR, {})
        return getattr(frappe.local, self._CACHE_ATTR)

    def _cache_key(self, method_name: str) -> str:
        """Generate cache key for a method."""
        return f"{self.volunteer_name}:{method_name}"

    def get_all_active_assignments(self) -> List[Dict]:
        """Get all active assignments from all sources

        Uses optimized UNION query to prevent N+1 problems.
        Results are cached per-request to avoid duplicate queries.

        Returns:
            List[Dict]: Active assignments with metadata:
                - source_type: Type of assignment (Board Position, Team, Activity)
                - source_doctype: Actual DocType name
                - source_name: Record name
                - role: Volunteer's role in this assignment
                - start_date: Assignment start date
                - end_date: Assignment end date (if applicable)
                - is_active: Boolean active status
                - editable: Whether user can edit this assignment type
                - source_link: UI link to the source document
                - reference_display: Human-readable reference (if applicable)
                - reference_link: Link to referenced document (if applicable)

        Performance:
            - O(1) query complexity regardless of number of assignments
            - Single database round-trip
            - Results sorted by start_date DESC
            - Request-level caching prevents duplicate queries
        """
        # Check request-level cache first
        cache = self._get_cache()
        cache_key = self._cache_key("active_assignments")
        if cache_key in cache:
            return cache[cache_key]

        assignments_data = frappe.db.sql(
            """
            SELECT
                'Board Position' as source_type,
                'Chapter Board Member' as source_doctype,
                cbm.parent as source_name,
                'Chapter' as source_doctype_display,
                c.name as source_name_display,
                cbm.chapter_role as role,
                cbm.from_date as start_date,
                cbm.to_date as end_date,
                cbm.is_active,
                0 as editable,
                CONCAT('/app/chapter/', cbm.parent) as source_link,
                '' as reference_display,
                '' as reference_link
            FROM `tabChapter Board Member` cbm
            LEFT JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE cbm.volunteer = %s AND cbm.is_active = 1

            UNION ALL

            SELECT
                'Team' as source_type,
                'Team Member' as source_doctype,
                tm.parent as source_name,
                COALESCE(t.team_type, 'Team') as source_doctype_display,
                t.team_name as source_name_display,
                tm.team_role as role,
                tm.from_date as start_date,
                tm.to_date as end_date,
                CASE WHEN tm.status = 'Active' THEN 1 ELSE 0 END as is_active,
                0 as editable,
                CONCAT('/app/team/', tm.parent) as source_link,
                '' as reference_display,
                '' as reference_link
            FROM `tabTeam Member` tm
            LEFT JOIN `tabTeam` t ON tm.parent = t.name
            WHERE tm.volunteer = %s AND tm.status = 'Active'

            UNION ALL

            SELECT
                'Activity' as source_type,
                'Volunteer Activity' as source_doctype,
                va.name as source_name,
                va.activity_type as source_doctype_display,
                COALESCE(va.description, va.role) as source_name_display,
                va.role,
                va.start_date,
                va.end_date,
                CASE WHEN va.status = 'Active' THEN 1 ELSE 0 END as is_active,
                1 as editable,
                CONCAT('/app/volunteer-activity/', va.name) as source_link,
                CASE
                    WHEN va.reference_doctype IS NOT NULL AND va.reference_name IS NOT NULL
                    THEN CONCAT(va.reference_doctype, ': ', va.reference_name)
                    ELSE ''
                END as reference_display,
                CASE
                    WHEN va.reference_doctype IS NOT NULL AND va.reference_name IS NOT NULL
                    THEN CONCAT('/app/', LOWER(REPLACE(va.reference_doctype, ' ', '-')), '/', va.reference_name)
                    ELSE ''
                END as reference_link
            FROM `tabVolunteer Activity` va
            WHERE va.volunteer = %s AND va.status = 'Active'

            ORDER BY start_date DESC
        """,
            (self.volunteer_name, self.volunteer_name, self.volunteer_name),
            as_dict=True,
        )

        # Convert to consistent format and cache
        result = self._format_assignments(assignments_data)
        cache[cache_key] = result
        return result

    def get_complete_history(self) -> List[Dict]:
        """Get complete assignment history including archived records

        Uses optimized UNION query for active/completed assignments,
        then augments with archived records from child table.
        Results are cached per-request.

        Returns:
            List[Dict]: Complete history with all assignments:
                - assignment_type: Type of assignment
                - role: Volunteer's role
                - reference: Reference to source document or description
                - start_date: Assignment start date
                - end_date: Assignment end date (if applicable)
                - is_active: Boolean active status
                - status: Status text (Active, Completed, etc.)

        Performance:
            - O(1) query for main data
            - O(n) iteration for child table where n = archived records
            - Results sorted by start_date DESC
            - Request-level caching prevents duplicate queries
        """
        # Check request-level cache first
        cache = self._get_cache()
        cache_key = self._cache_key("complete_history")
        if cache_key in cache:
            return cache[cache_key]

        history_data = frappe.db.sql(
            """
            SELECT
                'Board Position' as assignment_type,
                cbm.chapter_role as role,
                cbm.parent as reference,
                cbm.from_date as start_date,
                cbm.to_date as end_date,
                cbm.is_active,
                CASE WHEN cbm.is_active = 1 THEN 'Active' ELSE 'Completed' END as status
            FROM `tabChapter Board Member` cbm
            WHERE cbm.volunteer = %s

            UNION ALL

            SELECT
                'Team' as assignment_type,
                tm.team_role as role,
                tm.parent as reference,
                tm.from_date as start_date,
                tm.to_date as end_date,
                CASE WHEN tm.status = 'Active' THEN 1 ELSE 0 END as is_active,
                tm.status
            FROM `tabTeam Member` tm
            WHERE tm.volunteer = %s

            UNION ALL

            SELECT
                va.activity_type as assignment_type,
                va.role,
                COALESCE(va.description, va.name) as reference,
                va.start_date,
                va.end_date,
                CASE WHEN va.status = 'Active' THEN 1 ELSE 0 END as is_active,
                va.status
            FROM `tabVolunteer Activity` va
            WHERE va.volunteer = %s

            ORDER BY start_date DESC
        """,
            (self.volunteer_name, self.volunteer_name, self.volunteer_name),
            as_dict=True,
        )

        # Convert to consistent format
        history = self._format_history(history_data)

        # Add archived records from assignment_history child table
        # Note: This requires loading the volunteer document, but it's unavoidable
        # for accessing child table data
        volunteer_doc = frappe.get_doc("Volunteer", self.volunteer_name)
        for item in volunteer_doc.assignment_history:
            history.append(
                {
                    "assignment_type": item.assignment_type,
                    "role": item.role,
                    "reference": (
                        f"{item.reference_doctype}: {item.reference_name}" if item.reference_doctype else ""
                    ),
                    "start_date": item.start_date,
                    "end_date": item.end_date,
                    "is_active": False,
                    "status": item.status,
                }
            )

        # Re-sort to include archived records
        history.sort(
            key=lambda x: getdate(x.get("start_date")) if x.get("start_date") else getdate("1900-01-01"),
            reverse=True,
        )

        # Cache and return
        cache[cache_key] = history
        return history

    def check_has_active_assignments(self) -> bool:
        """Check if volunteer has any active assignments with early termination

        Uses Query Builder for type safety with optimized short-circuit logic.
        Returns True as soon as any active assignment is found.
        Result is cached per-request.

        Query Strategy Choice:
            - Query Builder instead of UNION for this use case because:
              1. Simple boolean check doesn't need complex aggregation
              2. Early termination (LIMIT 1) works better with separate queries
              3. Type safety is more valuable than minor performance difference

        Returns:
            bool: True if volunteer has any active assignments

        Performance:
            - O(1) with early termination
            - Each query uses LIMIT 1 to stop at first match
            - Maximum 3 queries but usually stops at first source
            - Request-level caching prevents duplicate checks
        """
        # Check request-level cache first
        cache = self._get_cache()
        cache_key = self._cache_key("has_active")
        if cache_key in cache:
            return cache[cache_key]

        # Check board positions
        CBM = DocType("Chapter Board Member")
        board_result = (
            frappe.qb.from_(CBM)
            .select(CBM.name)
            .where((CBM.volunteer == self.volunteer_name) & (CBM.is_active == 1))
            .limit(1)
            .run()
        )
        if board_result:
            cache[cache_key] = True
            return True

        # Check team memberships
        TM = DocType("Team Member")
        team_result = (
            frappe.qb.from_(TM)
            .select(TM.name)
            .where((TM.volunteer == self.volunteer_name) & (TM.status == "Active"))
            .limit(1)
            .run()
        )
        if team_result:
            cache[cache_key] = True
            return True

        # Check volunteer activities
        VA = DocType("Volunteer Activity")
        activity_result = (
            frappe.qb.from_(VA)
            .select(VA.name)
            .where((VA.volunteer == self.volunteer_name) & (VA.status == "Active"))
            .limit(1)
            .run()
        )
        if activity_result:
            cache[cache_key] = True
            return True

        cache[cache_key] = False
        return False

    def _format_assignments(self, raw_data: List[Dict]) -> List[Dict]:
        """Convert raw SQL results to consistent assignment format

        Args:
            raw_data: Raw SQL query results

        Returns:
            List[Dict]: Formatted assignments with proper types
        """
        assignments = []
        for data in raw_data:
            assignments.append(
                {
                    "source_type": data.source_type,
                    "source_doctype": data.source_doctype,
                    "source_name": data.source_name,
                    "source_doctype_display": data.source_doctype_display,
                    "source_name_display": data.source_name_display,
                    "role": data.role,
                    "start_date": data.start_date,
                    "end_date": data.end_date,
                    "is_active": bool(data.is_active),
                    "editable": bool(data.editable),
                    "source_link": data.source_link,
                    "reference_display": data.reference_display,
                    "reference_link": data.reference_link,
                }
            )
        return assignments

    def _format_history(self, raw_data: List[Dict]) -> List[Dict]:
        """Convert raw SQL results to consistent history format

        Args:
            raw_data: Raw SQL query results

        Returns:
            List[Dict]: Formatted history with proper types
        """
        history = []
        for data in raw_data:
            history.append(
                {
                    "assignment_type": data.assignment_type,
                    "role": data.role,
                    "reference": data.reference,
                    "start_date": data.start_date,
                    "end_date": data.end_date,
                    "is_active": bool(data.is_active),
                    "status": data.status,
                }
            )
        return history


def invalidate_volunteer_assignment_cache(volunteer_name: str = None) -> None:
    """
    Invalidate volunteer assignment cache.

    Call this when assignment data changes (board member, team member,
    or volunteer activity updates).

    Args:
        volunteer_name: Specific volunteer to invalidate, or None for all
    """
    cache_attr = AssignmentQueryBuilder._CACHE_ATTR

    if not hasattr(frappe.local, cache_attr):
        return

    cache = getattr(frappe.local, cache_attr)

    if volunteer_name:
        # Invalidate specific volunteer's cache entries
        keys_to_remove = [k for k in cache.keys() if k.startswith(f"{volunteer_name}:")]
        for key in keys_to_remove:
            del cache[key]
    else:
        # Clear entire cache
        cache.clear()
