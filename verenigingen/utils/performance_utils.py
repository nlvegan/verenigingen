"""
Performance optimization utilities for Verenigingen app

This module provides utilities to optimize database queries, implement caching,
and monitor performance bottlenecks in the association management system.
"""

import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

import frappe
from frappe import _


class QueryOptimizer:
    """Utility class for optimizing database queries"""

    @staticmethod
    def bulk_get_linked_docs(
        doctype: str,
        parent_field: str,
        parent_names: List[str],
        fields: List[str] = None,
        filters: Dict[str, Any] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Efficiently get linked documents for multiple parent records

        Solves N+1 query problems by fetching all linked docs in a single query

        Args:
            doctype: The child doctype to query
            parent_field: Field name that links to parent
            parent_names: List of parent document names
            fields: Fields to fetch (default: all)
            filters: Additional filters to apply

        Returns:
            Dictionary mapping parent names to lists of child documents
        """
        if not parent_names:
            return {}

        # Build filters
        query_filters = {parent_field: ["in", parent_names]}
        if filters:
            query_filters.update(filters)

        # Execute single query for all children
        children = frappe.get_all(doctype, filters=query_filters, fields=fields or ["*"])

        # Group children by parent
        result = {name: [] for name in parent_names}
        for child in children:
            parent_name = child.get(parent_field)
            if parent_name in result:
                result[parent_name].append(child)

        return result

    @staticmethod
    def batch_get_values(doctype: str, names: List[str], fieldname: Union[str, List[str]]) -> Dict[str, Any]:
        """
        Get field values for multiple documents in a single query

        Args:
            doctype: Document type
            names: List of document names
            fieldname: Field name(s) to retrieve

        Returns:
            Dictionary mapping document names to field values
        """
        if not names:
            return {}

        if isinstance(fieldname, str):
            fields = ["name", fieldname]
            single_field = True
        else:
            fields = ["name"] + list(fieldname)
            single_field = False

        # Execute single query
        results = frappe.get_all(doctype, filters={"name": ["in", names]}, fields=fields)

        # Build result dictionary
        if single_field:
            return {row["name"]: row.get(fieldname) for row in results}
        else:
            return {row["name"]: {f: row.get(f) for f in fieldname} for row in results}


class PermissionOptimizer:
    """Optimized permission checking to avoid N+1 queries"""

    @staticmethod
    def get_user_teams_bulk(user_emails: List[str]) -> Dict[str, List[Dict]]:
        """
        Get team memberships for multiple users efficiently

        Args:
            user_emails: List of user email addresses

        Returns:
            Dictionary mapping user emails to their team memberships
        """
        if not user_emails:
            return {}

        # Single query to get all team memberships
        team_members = frappe.db.sql(
            """
            SELECT tm.volunteer, tm.parent as team, tm.role_type, tm.role,
                   v.member, m.email as email_id
            FROM `tabTeam Member` tm
            JOIN `tabVolunteer` v ON tm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.email IN %s AND tm.is_active = 1
        """,
            [user_emails],
            as_dict=True,
        )

        # Group by user email
        result = {email: [] for email in user_emails}
        for tm in team_members:
            if tm.email_id in result:
                result[tm.email_id].append(tm)

        return result

    @staticmethod
    def get_chapter_permissions_bulk(user_emails: List[str]) -> Dict[str, List[str]]:
        """
        Get chapter permissions for multiple users efficiently

        Args:
            user_emails: List of user email addresses

        Returns:
            Dictionary mapping user emails to list of chapters they can access
        """
        if not user_emails:
            return {}

        # Single query for all chapter memberships
        chapter_members = frappe.db.sql(
            """
            SELECT cm.parent as chapter, m.email as email_id
            FROM `tabChapter Member` cm
            JOIN `tabMember` m ON cm.member = m.name
            WHERE m.email IN %s AND cm.status = 'Active' AND cm.enabled = 1

            UNION

            SELECT cbm.parent as chapter, m.email as email_id
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.email IN %s AND cbm.is_active = 1
        """,
            [user_emails, user_emails],
            as_dict=True,
        )

        # Group by user email
        result = {email: [] for email in user_emails}
        for cm in chapter_members:
            if cm.email_id in result:
                result[cm.email_id].append(cm.chapter)

        return result


class CacheManager:
    """Simple caching utility for frequently accessed data"""

    _cache = {}
    _cache_ttl = {}

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get value from cache"""
        if key in cls._cache:
            # Check TTL
            if key in cls._cache_ttl and time.time() > cls._cache_ttl[key]:
                cls.delete(key)
                return default
            return cls._cache[key]
        return default

    @classmethod
    def set(cls, key: str, value: Any, ttl: int = 300) -> None:
        """Set value in cache with TTL (default 5 minutes)"""
        cls._cache[key] = value
        cls._cache_ttl[key] = time.time() + ttl

    @classmethod
    def delete(cls, key: str) -> None:
        """Delete value from cache"""
        cls._cache.pop(key, None)
        cls._cache_ttl.pop(key, None)

    @classmethod
    def clear(cls) -> None:
        """Clear all cache"""
        cls._cache.clear()
        cls._cache_ttl.clear()


def cached(ttl: int = 300, key_func: Callable = None):
    """
    Decorator to cache function results

    Args:
        ttl: Time to live in seconds
        key_func: Function to generate cache key (default: use function name and args)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__module__}.{func.__name__}:{hash(str(args) + str(kwargs))}"

            # Try to get from cache
            result = CacheManager.get(cache_key)
            if result is not None:
                return result

            # Execute function and cache result
            result = func(*args, **kwargs)
            CacheManager.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


def performance_monitor(threshold_ms: float = 1000):
    """
    Decorator to monitor function performance and log slow operations

    Args:
        threshold_ms: Log warning if function takes longer than this (milliseconds)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                execution_time = (time.time() - start_time) * 1000  # Convert to ms

                if execution_time > threshold_ms:
                    logger = frappe.logger("verenigingen.performance")
                    logger.warning(
                        "Slow operation: {func.__module__}.{func.__name__} took {execution_time:.2f}ms",
                        extra={
                            "function": func.__name__,
                            "module": func.__module__,
                            "execution_time_ms": execution_time,
                            "args_length": len(args),
                            "user": frappe.session.user if frappe.session else "System",
                        },
                    )

        return wrapper

    return decorator


# Optimized permission checking functions


@cached(ttl=60)  # Cache for 1 minute
def get_user_volunteer_record_optimized(user_email: str) -> Optional[Dict[str, Any]]:
    """
    Optimized version of get_user_volunteer_record that includes all required fields

    Args:
        user_email: User's email address

    Returns:
        Volunteer record with member information, or None if not found
    """
    try:
        # Single query with JOIN to get all required data
        volunteer_data = frappe.db.sql(
            """
            SELECT v.name, v.volunteer_name, v.member, v.skills, v.availability,
                   m.name as member_name, m.email, m.first_name, m.last_name
            FROM `tabVolunteer` v
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.email = %s
            LIMIT 1
        """,
            [user_email],
            as_dict=True,
        )

        if volunteer_data:
            return volunteer_data[0]

        return None

    except Exception as e:
        frappe.logger("verenigingen.performance").error(
            f"Error in get_user_volunteer_record_optimized: {str(e)}"
        )
        return None


@cached(ttl=300)  # Cache for 5 minutes
def get_user_chapter_memberships_optimized(user_email: str) -> List[Dict[str, Any]]:
    """
    Optimized version to get user's chapter memberships

    Args:
        user_email: User's email address

    Returns:
        List of chapter memberships
    """
    try:
        # Single query to get all chapter relationships
        chapter_data = frappe.db.sql(
            """
            SELECT DISTINCT c.name as chapter_name, c.region as display_name,
                   'member' as relationship_type
            FROM `tabChapter Member` cm
            JOIN `tabMember` m ON cm.member = m.name
            JOIN `tabChapter` c ON cm.parent = c.name
            WHERE m.email = %s AND cm.status = 'Active' AND cm.enabled = 1

            UNION

            SELECT DISTINCT c.name as chapter_name, c.region as display_name,
                   'board_member' as relationship_type
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            JOIN `tabChapter` c ON cbm.parent = c.name
            WHERE m.email = %s AND cbm.is_active = 1
        """,
            [user_email, user_email],
            as_dict=True,
        )

        return chapter_data

    except Exception as e:
        frappe.logger("verenigingen.performance").error(
            f"Error in get_user_chapter_memberships_optimized: {str(e)}"
        )
        return []


# Database index recommendations
DATABASE_INDEX_RECOMMENDATIONS = [
    {
        "table": "tabMember",
        "index": "idx_member_email_status",
        "columns": ["email", "status"],
        "reason": "Frequent lookups by email and filtering by status",
    },
    {
        "table": "tabVolunteer",
        "index": "idx_volunteer_member",
        "columns": ["member"],
        "reason": "JOIN operations with Member table",
    },
    {
        "table": "tabChapter Member",
        "index": "idx_chapter_member_active",
        "columns": ["member", "enabled"],
        "reason": "Permission checking queries",
    },
    {
        "table": "tabChapter Board Member",
        "index": "idx_chapter_board_volunteer_active",
        "columns": ["volunteer", "is_active"],
        "reason": "Board member permission checks",
    },
    {
        "table": "tabTeam Member",
        "index": "idx_team_member_volunteer_active",
        "columns": ["volunteer", "is_active"],
        "reason": "Team membership queries",
    },
    {
        "table": "tabSEPA Direct Debit Mandate",
        "index": "idx_sepa_mandate_member_status",
        "columns": ["member", "status"],
        "reason": "Payment processing queries",
    },
]


def create_recommended_indexes():
    """
    Create recommended database indexes for better performance
    Should be run during maintenance windows
    """
    for index_info in DATABASE_INDEX_RECOMMENDATIONS:
        try:
            # Check if index already exists
            existing_indexes = frappe.db.sql(
                f"""
                SHOW INDEX FROM `{index_info['table']}`
                WHERE Key_name = '{index_info['index']}'
            """
            )

            if not existing_indexes:
                # Create the index
                columns_str = ", ".join(f"`{col}`" for col in index_info["columns"])
                frappe.db.sql(
                    f"""
                    CREATE INDEX `{index_info['index']}`
                    ON `{index_info['table']}` ({columns_str})
                """
                )

                frappe.logger("verenigingen.performance").info(
                    f"Created index {index_info['index']} on {index_info['table']}"
                )

        except Exception as e:
            frappe.logger("verenigingen.performance").error(
                f"Failed to create index {index_info['index']}: {str(e)}"
            )


def analyze_query_performance():
    """
    Analyze performance of common queries and suggest optimizations
    """
    # Common slow queries to analyze
    test_queries = [
        {
            "name": "member_lookup_by_email",
            "query": "SELECT name FROM `tabMember` WHERE email_id = %s",
            "params": ["test@example.com"],
        },
        {
            "name": "volunteer_team_memberships",
            "query": """
                SELECT tm.parent, tm.role
                FROM `tabTeam Member` tm
                JOIN `tabVolunteer` v ON tm.volunteer = v.name
                WHERE v.member = %s AND tm.is_active = 1
            """,
            "params": ["MEMBER001"],
        },
    ]

    results = []
    for query_info in test_queries:
        try:
            start_time = time.time()
            frappe.db.sql(query_info["query"], query_info["params"])
            execution_time = (time.time() - start_time) * 1000

            results.append(
                {
                    "query": query_info["name"],
                    "execution_time_ms": execution_time,
                    "status": "slow" if execution_time > 100 else "ok",
                }
            )

        except Exception as e:
            results.append({"query": query_info["name"], "error": str(e), "status": "error"})

    return results


# Performance monitoring utilities
class PerformanceCollector:
    """Collect performance metrics for monitoring"""

    @staticmethod
    def record_api_call(endpoint: str, execution_time: float, success: bool):
        """Record API call performance metrics"""
        # This would integrate with monitoring systems
        pass

    @staticmethod
    def record_database_query(query_type: str, execution_time: float, row_count: int):
        """Record database query performance metrics"""
        # This would integrate with monitoring systems
        pass
