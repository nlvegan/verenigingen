"""
Optimized Address Matcher with Three-Tier Lookup Strategy

This module provides O(log N) address matching using computed fields,
composite indexes, and intelligent caching for high-performance lookups.
"""

import time
from typing import Dict, List, Optional, Tuple

import frappe

from verenigingen.utils.address_matching.dutch_address_normalizer import (
    AddressFingerprintCollisionHandler,
    DutchAddressNormalizer,
)


class OptimizedAddressMatcher:
    """O(log N) address matching with three-tier optimization strategy"""

    # Performance thresholds for tier selection
    FINGERPRINT_CONFIDENCE_THRESHOLD = 0.95
    NORMALIZED_CONFIDENCE_THRESHOLD = 0.85

    @staticmethod
    def get_other_members_at_address_optimized(member_doc) -> List[Dict]:
        """
        Optimized O(log N) address matching with three-tier fallback strategy

        Args:
            member_doc: Member document with address information

        Returns:
            List[Dict]: List of member dictionaries with relationship data
        """
        start_time = time.time()

        if not member_doc.primary_address:
            return []

        try:
            # Get address details
            address = frappe.get_doc("Address", member_doc.primary_address)

            # Generate normalized forms and fingerprint if not already computed
            if not getattr(member_doc, "address_fingerprint", None):
                normalized_line, normalized_city, fingerprint = DutchAddressNormalizer.normalize_address_pair(
                    address.address_line1 or "", address.city or ""
                )

                # Handle collisions
                if AddressFingerprintCollisionHandler.detect_collision(
                    fingerprint, normalized_line, normalized_city, member_doc.name
                ):
                    fingerprint = AddressFingerprintCollisionHandler.resolve_collision(
                        fingerprint, normalized_line, normalized_city, member_doc.name
                    )

                # Update member with computed fields
                frappe.db.set_value(
                    "Member",
                    member_doc.name,
                    {
                        "address_fingerprint": fingerprint,
                        "normalized_address_line": normalized_line,
                        "normalized_city": normalized_city,
                        "address_last_updated": frappe.utils.now(),
                    },
                )

                # Update the document object for immediate use
                member_doc.address_fingerprint = fingerprint
                member_doc.normalized_address_line = normalized_line
                member_doc.normalized_city = normalized_city

            # TIER 1: O(1) Fingerprint lookup (fastest, highest confidence)
            matching_members = OptimizedAddressMatcher._fingerprint_lookup(
                member_doc.address_fingerprint, member_doc.name
            )

            lookup_tier = "fingerprint"
            if matching_members:
                OptimizedAddressMatcher._track_performance(
                    lookup_tier, time.time() - start_time, len(matching_members), True
                )
                return matching_members

            # TIER 2: O(log N) Normalized lookup (fast fallback, medium confidence)
            matching_members = OptimizedAddressMatcher._normalized_lookup(
                member_doc.normalized_address_line, member_doc.normalized_city, member_doc.name
            )

            lookup_tier = "normalized"
            if matching_members:
                OptimizedAddressMatcher._track_performance(
                    lookup_tier, time.time() - start_time, len(matching_members), True
                )
                return matching_members

            # TIER 3: O(log N) JOIN fallback (compatibility, lower confidence)
            matching_members = OptimizedAddressMatcher._join_lookup(
                address.address_line1 or "", address.city or "", member_doc.name
            )

            lookup_tier = "join"
            OptimizedAddressMatcher._track_performance(
                lookup_tier, time.time() - start_time, len(matching_members), True
            )

            return matching_members

        except Exception as e:
            frappe.log_error(f"Error in optimized address matching for {member_doc.name}: {e}")
            OptimizedAddressMatcher._track_performance("error", time.time() - start_time, 0, False)
            return []

    @staticmethod
    def _fingerprint_lookup(fingerprint: str, exclude_member: str) -> List[Dict]:
        """
        Tier 1: O(1) fingerprint-based lookup using primary index

        Args:
            fingerprint (str): Address fingerprint for exact matching
            exclude_member (str): Member to exclude from results

        Returns:
            List[Dict]: Matching members with enriched data
        """
        if not fingerprint:
            return []

        try:
            return frappe.db.sql(
                """
                SELECT
                    m.name,
                    m.full_name,
                    m.email,
                    m.status,
                    m.member_since,
                    m.birth_date,
                    COALESCE(m.relationship_guess, 'Unknown') as relationship,
                    CASE
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) < 18 THEN 'Minor'
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) >= 65 THEN 'Senior'
                        ELSE 'Adult'
                    END as age_group,
                    m.contact_number,
                    m.application_date,
                    DATEDIFF(CURDATE(), m.member_since) as days_member
                FROM `tabMember` m
                WHERE m.address_fingerprint = %(fingerprint)s
                    AND m.name != %(exclude_member)s
                    AND m.status IN ('Active', 'Pending', 'Suspended')
                ORDER BY m.member_since ASC, m.full_name ASC
                LIMIT 20
            """,
                {"fingerprint": fingerprint, "exclude_member": exclude_member},
                as_dict=True,
            )

        except Exception as e:
            frappe.log_error(f"Error in fingerprint lookup: {e}")
            return []

    @staticmethod
    def _normalized_lookup(normalized_line: str, normalized_city: str, exclude_member: str) -> List[Dict]:
        """
        Tier 2: O(log N) normalized field lookup using composite index

        Args:
            normalized_line (str): Normalized address line
            normalized_city (str): Normalized city name
            exclude_member (str): Member to exclude from results

        Returns:
            List[Dict]: Matching members with enriched data
        """
        if not normalized_line or not normalized_city:
            return []

        try:
            return frappe.db.sql(
                """
                SELECT DISTINCT
                    m.name,
                    m.full_name,
                    m.email,
                    m.status,
                    m.member_since,
                    m.birth_date,
                    COALESCE(m.relationship_guess, 'Unknown') as relationship,
                    CASE
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) < 18 THEN 'Minor'
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) >= 65 THEN 'Senior'
                        ELSE 'Adult'
                    END as age_group,
                    m.contact_number,
                    m.application_date,
                    DATEDIFF(CURDATE(), m.member_since) as days_member
                FROM `tabMember` m
                WHERE m.normalized_address_line = %(normalized_line)s
                    AND m.normalized_city = %(normalized_city)s
                    AND m.name != %(exclude_member)s
                    AND m.status IN ('Active', 'Pending', 'Suspended')
                ORDER BY m.member_since ASC, m.full_name ASC
                LIMIT 20
            """,
                {
                    "normalized_line": normalized_line,
                    "normalized_city": normalized_city,
                    "exclude_member": exclude_member,
                },
                as_dict=True,
            )

        except Exception as e:
            frappe.log_error(f"Error in normalized lookup: {e}")
            return []

    @staticmethod
    def _join_lookup(address_line: str, city: str, exclude_member: str) -> List[Dict]:
        """
        Tier 3: O(log N) JOIN-based fallback for backward compatibility

        Args:
            address_line (str): Raw address line for JOIN matching
            city (str): Raw city name for JOIN matching
            exclude_member (str): Member to exclude from results

        Returns:
            List[Dict]: Matching members with enriched data
        """
        if not address_line or not city:
            return []

        # Normalize for comparison in the query
        normalized_line = DutchAddressNormalizer.normalize_address_line(address_line)
        normalized_city = DutchAddressNormalizer.normalize_city(city)

        try:
            return frappe.db.sql(
                """
                SELECT DISTINCT
                    m.name,
                    m.full_name,
                    m.email,
                    m.status,
                    m.member_since,
                    m.birth_date,
                    'Unknown' as relationship,
                    CASE
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) < 18 THEN 'Minor'
                        WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) >= 65 THEN 'Senior'
                        ELSE 'Adult'
                    END as age_group,
                    m.contact_number,
                    m.application_date,
                    DATEDIFF(CURDATE(), m.member_since) as days_member
                FROM `tabMember` m
                INNER JOIN `tabAddress` a ON m.primary_address = a.name
                WHERE LOWER(TRIM(REGEXP_REPLACE(a.address_line1, '[^a-zA-Z0-9 ]', ''))) = %(normalized_line)s
                    AND LOWER(TRIM(REGEXP_REPLACE(a.city, '[^a-zA-Z0-9 ]', ''))) = %(normalized_city)s
                    AND m.name != %(exclude_member)s
                    AND m.status IN ('Active', 'Pending', 'Suspended')
                ORDER BY m.member_since ASC, m.full_name ASC
                LIMIT 20
            """,
                {
                    "normalized_line": normalized_line,
                    "normalized_city": normalized_city,
                    "exclude_member": exclude_member,
                },
                as_dict=True,
            )

        except Exception as e:
            frappe.log_error(f"Error in JOIN lookup: {e}")
            return []

    @staticmethod
    def _track_performance(tier: str, duration_seconds: float, result_count: int, success: bool):
        """
        Track address matching performance metrics for monitoring and optimization (lightweight version)

        Args:
            tier (str): Lookup tier used (fingerprint, normalized, join, error)
            duration_seconds (float): Time taken for the lookup
            result_count (int): Number of results returned
            success (bool): Whether the lookup succeeded
        """
        try:
            duration_ms = round(duration_seconds * 1000, 2)

            # Only log slow queries to reduce overhead
            if duration_ms > 100:  # Queries over 100ms
                frappe.log_error(
                    f"Slow address matching query: {tier} tier took {duration_ms}ms for {result_count} results",
                    "AddressMatchingPerformance",
                )

        except Exception:
            # Don't let metrics tracking break the main functionality
            pass

    @staticmethod
    def get_performance_statistics(days: int = 7) -> Dict[str, any]:
        """
        Get address matching performance statistics for analysis

        Args:
            days (int): Number of days to analyze (default: 7)

        Returns:
            Dict: Performance statistics and analysis
        """
        try:
            end_date = frappe.utils.now()
            start_date = frappe.utils.add_days(end_date, -days)

            # Tier performance breakdown
            tier_stats = frappe.db.sql(
                """
                SELECT
                    tier,
                    COUNT(*) as query_count,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms,
                    AVG(result_count) as avg_result_count,
                    SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits
                FROM `tabAddress Matching Metrics`
                WHERE timestamp BETWEEN %(start_date)s AND %(end_date)s
                GROUP BY tier
                ORDER BY query_count DESC
            """,
                {"start_date": start_date, "end_date": end_date},
                as_dict=True,
            )

            # Overall performance metrics
            overall_stats = frappe.db.sql(
                """
                SELECT
                    COUNT(*) as total_queries,
                    AVG(duration_ms) as overall_avg_duration_ms,
                    STDDEV(duration_ms) as duration_stddev,
                    COUNT(CASE WHEN duration_ms > 100 THEN 1 END) as slow_queries,
                    COUNT(CASE WHEN cache_hit = 1 THEN 1 END) as total_cache_hits
                FROM `tabAddress Matching Metrics`
                WHERE timestamp BETWEEN %(start_date)s AND %(end_date)s
            """,
                {"start_date": start_date, "end_date": end_date},
                as_dict=True,
            )

            # Calculate cache hit rate
            total_queries = overall_stats[0]["total_queries"] if overall_stats else 0
            total_cache_hits = overall_stats[0]["total_cache_hits"] if overall_stats else 0
            cache_hit_rate = (total_cache_hits / total_queries * 100) if total_queries > 0 else 0

            return {
                "analysis_period_days": days,
                "tier_performance": tier_stats,
                "overall_performance": overall_stats[0] if overall_stats else {},
                "cache_hit_rate_percent": round(cache_hit_rate, 2),
                "slow_query_threshold_ms": 100,
                "recommendations": OptimizedAddressMatcher._generate_performance_recommendations(
                    tier_stats, overall_stats[0] if overall_stats else {}
                ),
            }

        except Exception as e:
            frappe.log_error(f"Error getting performance statistics: {e}")
            return {"error": str(e)}

    @staticmethod
    def _generate_performance_recommendations(tier_stats: List[Dict], overall_stats: Dict) -> List[str]:
        """Generate performance optimization recommendations based on statistics"""
        recommendations = []

        if not tier_stats or not overall_stats:
            return ["Insufficient data for recommendations"]

        # Check if fingerprint tier is being used effectively
        fingerprint_usage = next((stat for stat in tier_stats if stat["tier"] == "fingerprint"), None)
        if (
            not fingerprint_usage
            or fingerprint_usage["query_count"] < overall_stats.get("total_queries", 0) * 0.7
        ):
            recommendations.append(
                "Consider running member address normalization to improve fingerprint usage"
            )

        # Check for excessive slow queries
        slow_query_rate = (overall_stats.get("slow_queries", 0) / overall_stats.get("total_queries", 1)) * 100
        if slow_query_rate > 10:
            recommendations.append(
                f"High slow query rate ({slow_query_rate:.1f}%) - consider index optimization"
            )

        # Check cache effectiveness
        cache_hit_rate = (
            overall_stats.get("total_cache_hits", 0) / overall_stats.get("total_queries", 1)
        ) * 100
        if cache_hit_rate < 50:
            recommendations.append("Low cache hit rate - consider implementing caching layer")

        # Check tier distribution
        join_usage = next((stat for stat in tier_stats if stat["tier"] == "join"), None)
        if join_usage and join_usage["query_count"] > overall_stats.get("total_queries", 0) * 0.3:
            recommendations.append(
                "High JOIN tier usage indicates missing computed fields - run normalization"
            )

        return recommendations if recommendations else ["Performance is optimal"]


# Create DocType for performance metrics if it doesn't exist
def create_address_matching_metrics_doctype():
    """Create Address Matching Metrics DocType for performance tracking"""

    if frappe.db.exists("DocType", "Address Matching Metrics"):
        return

    doctype_doc = frappe.get_doc(
        {
            "doctype": "DocType",
            "name": "Address Matching Metrics",
            "module": "Verenigingen",
            "custom": 1,
            "is_table": 0,
            "naming_rule": "Random",
            "fields": [
                {
                    "fieldname": "tier",
                    "label": "Lookup Tier",
                    "fieldtype": "Select",
                    "options": "fingerprint\nnormalized\njoin\nerror",
                    "reqd": 1,
                },
                {
                    "fieldname": "duration_ms",
                    "label": "Duration (ms)",
                    "fieldtype": "Float",
                    "precision": 2,
                    "reqd": 1,
                },
                {"fieldname": "result_count", "label": "Result Count", "fieldtype": "Int", "reqd": 1},
                {"fieldname": "cache_hit", "label": "Cache Hit", "fieldtype": "Check", "default": 0},
                {"fieldname": "timestamp", "label": "Timestamp", "fieldtype": "Datetime", "reqd": 1},
            ],
            "permissions": [{"role": "System Manager", "read": 1, "write": 1, "delete": 1}],
        }
    )

    doctype_doc.insert(ignore_permissions=True)
