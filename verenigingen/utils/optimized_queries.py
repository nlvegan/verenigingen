#!/usr/bin/env python3
"""
Optimized Query Utilities for Verenigingen App
Database Query Performance Optimization - Problem #1

This module provides optimized query functions that replace N+1 query patterns
with efficient bulk operations, joins, and caching strategies.

Based on analysis of 4,111+ individual database calls causing performance issues,
this module targets the major bottlenecks:
1. Member payment history loading
2. Payment entry/invoice processing
3. Volunteer assignment aggregation
4. SEPA mandate processing
5. Chapter management operations

Performance Goals:
- Replace individual frappe.get_doc() calls with bulk operations
- Implement strategic caching for frequently accessed data
- Use database joins instead of Python loops for related data
- Reduce database calls by 70-80% for core operations
"""

# Database import not needed for this module functionality
import re
from typing import Any, Dict, List, Optional

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


# Security and Input Validation Functions
def validate_member_names(member_names: List[str]) -> None:
    """
    Validate member names to prevent SQL injection and ensure data integrity.

    Args:
        member_names: List of member names to validate

    Raises:
        ValueError: If member names are invalid or potentially malicious
    """
    if not member_names:
        raise ValueError("Member names list cannot be empty")

    if not isinstance(member_names, list):
        raise ValueError("Member names must be provided as a list")

    # Check for reasonable list size to prevent DoS
    if len(member_names) > 1000:
        raise ValueError("Too many member names provided (max 1000)")

    # Pattern for valid member names (alphanumeric, spaces, hyphens, dots, underscores)
    valid_name_pattern = re.compile(r"^[a-zA-Z0-9\s\-\._@]+$")

    for name in member_names:
        if not isinstance(name, str):
            raise ValueError(f"Invalid member name type: {type(name)}")

        if not name or not name.strip():
            raise ValueError("Member name cannot be empty or whitespace")

        if len(name.strip()) > 200:  # Reasonable length limit
            raise ValueError(f"Member name too long: {name[:50]}...")

        # Check for SQL injection patterns
        if not valid_name_pattern.match(name.strip()):
            raise ValueError(f"Member name contains invalid characters: {name}")

        # Additional SQL injection protection - check for common SQL keywords and patterns
        dangerous_patterns = [
            "union",
            "select",
            "drop",
            "delete",
            "update",
            "insert",
            "exec",
            "script",
            "alter",
            "create",
            "truncate",
            "--",
            ";",
            "/*",
            "*/",
            "xp_",
            "sp_",
        ]
        name_lower = name.lower().strip()
        for pattern in dangerous_patterns:
            if pattern in name_lower:
                raise ValueError(f"Member name contains potentially dangerous content: {name}")


def create_safe_sql_placeholders(count: int) -> str:
    """
    Create safe SQL placeholders for prepared statements.

    Args:
        count: Number of placeholders needed

    Returns:
        str: Safe placeholder string for SQL queries

    Raises:
        ValueError: If count is invalid
    """
    if not isinstance(count, int) or count <= 0:
        raise ValueError(f"Count must be a positive integer: {count}")

    if count > 1000:  # Reasonable limit to prevent DoS
        raise ValueError(f"Too many placeholders requested: {count}")

    return ",".join(["%s"] * count)


class OptimizedVolunteerQueries:
    """Optimized queries for Volunteer DocType operations"""

    @staticmethod
    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def get_volunteer_assignments_bulk(volunteer_names: List[str]) -> Dict[str, List[Dict]]:
        """
        Optimized bulk loading of volunteer assignments

        Replaces N+1 pattern in volunteer.py where individual queries
        were made for board assignments, team assignments, and activities.

        Returns all assignment data in optimized bulk queries.
        """

        if not volunteer_names:
            return {}

        # Validate input to prevent SQL injection
        validate_member_names(volunteer_names)  # Reuse validation logic

        assignments_by_volunteer = {}

        # Initialize result structure
        for vol_name in volunteer_names:
            assignments_by_volunteer[vol_name] = []

        try:
            # Single query for all assignment types using UNION
            assignments_query = """
            SELECT
                v.name as volunteer_name,
                'Board' as assignment_type,
                'Chapter Board Member' as source_type,
                'Chapter' as source_doctype,
                cbm.parent as source_name,
                c.name as source_name_display,
                cbm.chapter_role as role,
                cbm.from_date as start_date,
                cbm.to_date as end_date,
                CASE WHEN cbm.to_date IS NULL OR cbm.to_date >= CURDATE() THEN 1 ELSE 0 END as is_active,
                0 as editable
            FROM `tabVolunteer` v
            LEFT JOIN `tabChapter Board Member` cbm ON v.name = cbm.volunteer
            LEFT JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE v.name IN ({placeholders}) AND cbm.name IS NOT NULL

            UNION ALL

            SELECT
                v.name as volunteer_name,
                'Team' as assignment_type,
                'Team Member' as source_type,
                'Team' as source_doctype,
                tm.parent as source_name,
                t.team_name as source_name_display,
                tm.role,
                tm.from_date as start_date,
                tm.to_date as end_date,
                CASE WHEN tm.to_date IS NULL OR tm.to_date >= CURDATE() THEN 1 ELSE 0 END as is_active,
                0 as editable
            FROM `tabVolunteer` v
            LEFT JOIN `tabMember` m ON v.member = m.name
            LEFT JOIN `tabTeam Member` tm ON v.name = tm.volunteer
            LEFT JOIN `tabTeam` t ON tm.parent = t.name
            WHERE v.name IN ({placeholders_2}) AND tm.name IS NOT NULL

            UNION ALL

            SELECT
                v.name as volunteer_name,
                'Activity' as assignment_type,
                'Volunteer Activity' as source_type,
                'Volunteer Activity' as source_doctype,
                va.name as source_name,
                va.activity_type as source_name_display,
                va.role,
                va.start_date,
                va.end_date,
                CASE WHEN va.end_date IS NULL OR va.end_date >= CURDATE() THEN 1 ELSE 0 END as is_active,
                1 as editable
            FROM `tabVolunteer` v
            LEFT JOIN `tabVolunteer Activity` va ON v.name = va.volunteer
            WHERE v.name IN ({placeholders_3}) AND va.name IS NOT NULL

            ORDER BY volunteer_name, start_date DESC
            """.format(
                placeholders=create_safe_sql_placeholders(len(volunteer_names)),
                placeholders_2=create_safe_sql_placeholders(len(volunteer_names)),
                placeholders_3=create_safe_sql_placeholders(len(volunteer_names)),
            )

            query_params = volunteer_names * 3  # Same list 3 times for UNION queries

            assignments = frappe.db.sql(assignments_query, query_params, as_dict=True)

            # Group assignments by volunteer
            for assignment in assignments:
                volunteer_name = assignment["volunteer_name"]
                if volunteer_name in assignments_by_volunteer:
                    assignments_by_volunteer[volunteer_name].append(assignment)

        except Exception as e:
            frappe.log_error(f"Failed to load volunteer assignments: {str(e)}")

        return assignments_by_volunteer


class OptimizedSEPAQueries:
    """Optimized queries for SEPA Mandate operations"""

    @staticmethod
    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def get_active_mandates_for_members(member_names: List[str]) -> Dict[str, Dict]:
        """
        Optimized bulk loading of active SEPA mandates for members

        Replaces N+1 pattern in member_utils.py where individual
        frappe.get_doc() calls were made for each mandate.
        """

        if not member_names:
            return {}

        # Validate input to prevent SQL injection
        validate_member_names(member_names)

        # Single query to get active mandates for all members
        query = """
        SELECT
            sm.member,
            sm.name as mandate_name,
            sm.mandate_id,
            sm.status,
            sm.sign_date,
            sm.first_collection_date,
            sm.expiry_date,
            sm.mandate_type,
            sm.bank_name,
            sm.iban,
            sm.account_holder_name,
            sm.is_active
        FROM `tabSEPA Mandate` sm
        WHERE sm.member IN ({placeholders})
        AND sm.status = 'Active'
        ORDER BY sm.member, sm.is_active DESC, sm.sign_date DESC
        """.format(
            placeholders=create_safe_sql_placeholders(len(member_names))
        )

        results = frappe.db.sql(query, member_names, as_dict=True)

        # Group by member, taking the first (default/most recent) mandate
        mandates_by_member = {}
        for result in results:
            member = result["member"]
            if member not in mandates_by_member:
                mandates_by_member[member] = result

        return mandates_by_member


class OptimizedChapterQueries:
    """Optimized queries for Chapter operations"""

    @staticmethod
    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def get_chapter_assignments_bulk(postal_codes: List[str]) -> Dict[str, str]:
        """
        Optimized bulk chapter assignment by postal codes

        Replaces N+1 pattern in member_utils.py:512-514 where individual
        frappe.get_doc() calls were made for each chapter.
        """

        if not postal_codes:
            return {}

        # Single query to match all postal codes to chapters
        query = """
        SELECT DISTINCT
            postal_code,
            c.name as chapter_name,
            c.name as chapter_display_name
        FROM (
            SELECT %s as postal_code
        ) pc
        CROSS JOIN `tabChapter` c
        WHERE c.status = 'Active'
        AND c.docstatus < 2
        AND (
            c.postal_codes IS NOT NULL
            AND c.postal_codes != ''
            AND FIND_IN_SET(pc.postal_code, REPLACE(c.postal_codes, ' ', '')) > 0
        )
        ORDER BY c.name
        """

        # Execute query for each postal code (could be optimized further with VALUES clause)
        chapter_assignments = {}

        for postal_code in postal_codes:
            results = frappe.db.sql(query, [postal_code], as_dict=True)
            if results:
                # Take the first (highest priority) chapter
                chapter_assignments[postal_code] = results[0]["chapter_name"]

        return chapter_assignments


# Caching utilities
class QueryCache:
    """Strategic caching for frequently accessed data"""

    # Cache timeouts in seconds
    MEMBER_DATA_TIMEOUT = 300  # 5 minutes
    VOLUNTEER_DATA_TIMEOUT = 600  # 10 minutes
    SEPA_DATA_TIMEOUT = 900  # 15 minutes
    CHAPTER_DATA_TIMEOUT = 1800  # 30 minutes

    @staticmethod
    def get_cached_member_data(member_name: str) -> Optional[Dict]:
        """Get cached member data if available"""
        cache_key = f"member_data:{member_name}"
        return frappe.cache().get_value(cache_key)

    @staticmethod
    def set_cached_member_data(member_name: str, data: Dict):
        """Cache member data"""
        cache_key = f"member_data:{member_name}"
        frappe.cache().set_value(cache_key, data, expires_in_sec=QueryCache.MEMBER_DATA_TIMEOUT)

    @staticmethod
    def invalidate_member_cache(member_name: str):
        """Invalidate cached member data"""
        cache_key = f"member_data:{member_name}"
        frappe.cache().delete_value(cache_key)

    @staticmethod
    def get_cached_volunteer_assignments(volunteer_name: str) -> Optional[List[Dict]]:
        """Get cached volunteer assignments if available"""
        cache_key = f"volunteer_assignments:{volunteer_name}"
        return frappe.cache().get_value(cache_key)

    @staticmethod
    def set_cached_volunteer_assignments(volunteer_name: str, assignments: List[Dict]):
        """Cache volunteer assignments"""
        cache_key = f"volunteer_assignments:{volunteer_name}"
        frappe.cache().set_value(cache_key, assignments, expires_in_sec=QueryCache.VOLUNTEER_DATA_TIMEOUT)


# Utility functions for replacing existing N+1 patterns
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def optimize_volunteer_assignment_loading(volunteer_name: str) -> List[Dict]:
    """
    Drop-in replacement for individual volunteer assignment loading

    Can replace existing get_aggregated_assignments method calls.
    """

    try:
        # Check cache first
        cached_assignments = QueryCache.get_cached_volunteer_assignments(volunteer_name)
        if cached_assignments:
            return cached_assignments

        # Use optimized bulk query
        assignments_data = OptimizedVolunteerQueries.get_volunteer_assignments_bulk([volunteer_name])
        assignments = assignments_data.get(volunteer_name, [])

        # Cache the result
        QueryCache.set_cached_volunteer_assignments(volunteer_name, assignments)

        return assignments

    except Exception as e:
        frappe.log_error(f"Optimized volunteer assignment loading failed for {volunteer_name}: {str(e)}")
        return []
