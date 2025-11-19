"""
Performance Testing Suite for Address Matching Optimization

This module provides comprehensive performance testing to validate the 75% improvement
claim and analyze the effectiveness of the O(log N) optimization.
"""

import statistics
import time
from typing import Dict, List, Tuple

import frappe

from verenigingen.utils.address_matching.optimized_matcher import OptimizedAddressMatcher


@frappe.whitelist()
def run_comprehensive_performance_test():
    """Run comprehensive performance tests comparing old vs new implementation"""

    print("Starting comprehensive address matching performance test...")

    # Get test sample
    test_members = get_test_member_sample()
    print(f"Testing with {len(test_members)} members with addresses")

    if len(test_members) < 5:
        return {"error": "Insufficient test data - need at least 5 members with addresses"}

    results = {
        "test_summary": {
            "total_members_tested": len(test_members),
            "test_timestamp": frappe.utils.now(),
            "database_stats": get_database_stats(),
        },
        "original_performance": test_original_implementation(test_members),
        "optimized_performance": test_optimized_implementation(test_members),
        "tier_breakdown": analyze_tier_usage(test_members),
        "improvement_analysis": {},
        "recommendations": [],
    }

    # Calculate improvements
    if results["original_performance"]["avg_duration_ms"] > 0:
        improvement_percent = (
            (
                results["original_performance"]["avg_duration_ms"]
                - results["optimized_performance"]["avg_duration_ms"]
            )
            / results["original_performance"]["avg_duration_ms"]
            * 100
        )
        results["improvement_analysis"] = {
            "performance_improvement_percent": round(improvement_percent, 2),
            "speed_multiplier": round(
                results["original_performance"]["avg_duration_ms"]
                / results["optimized_performance"]["avg_duration_ms"],
                2,
            ),
            "meets_75_percent_target": improvement_percent >= 75,
            "avg_time_saved_ms": round(
                results["original_performance"]["avg_duration_ms"]
                - results["optimized_performance"]["avg_duration_ms"],
                2,
            ),
        }

    # Generate recommendations
    results["recommendations"] = generate_performance_recommendations(results)

    return results


def get_test_member_sample(limit: int = 20) -> List[Dict]:
    """Get a representative sample of members for testing"""

    return frappe.db.sql(
        """
        SELECT m.name, m.full_name, m.primary_address,
               m.address_fingerprint, m.normalized_address_line, m.normalized_city
        FROM `tabMember` m
        WHERE m.primary_address IS NOT NULL
            AND m.primary_address != ''
            AND m.status IN ('Active', 'Pending', 'Suspended')
        ORDER BY RAND()
        LIMIT %s
    """,
        (limit,),
        as_dict=True,
    )


def get_database_stats() -> Dict:
    """Get current database statistics"""

    try:
        stats = frappe.db.sql(
            """
            SELECT
                (SELECT COUNT(*) FROM `tabMember` WHERE primary_address IS NOT NULL) as members_with_address,
                (SELECT COUNT(*) FROM `tabAddress`) as total_addresses,
                (SELECT COUNT(*) FROM `tabMember` WHERE address_fingerprint IS NOT NULL) as members_with_fingerprint,
                (SELECT COUNT(DISTINCT address_fingerprint) FROM `tabMember`
                 WHERE address_fingerprint IS NOT NULL) as unique_fingerprints
        """,
            as_dict=True,
        )[0]

        if stats["members_with_address"] > 0 and stats["members_with_fingerprint"] > 0:
            stats["fingerprint_coverage_percent"] = round(
                (stats["members_with_fingerprint"] / stats["members_with_address"]) * 100, 2
            )
        else:
            stats["fingerprint_coverage_percent"] = 0

        return stats

    except Exception as e:
        return {"error": str(e)}


def test_original_implementation(test_members: List[Dict]) -> Dict:
    """Test the original O(N) implementation performance"""

    print("Testing original O(N) implementation...")
    durations = []
    results_count = []
    errors = 0

    for member_data in test_members:
        try:
            start_time = time.time()

            # Simulate original O(N) implementation
            results = simulate_original_address_matching(member_data)

            duration_ms = (time.time() - start_time) * 1000
            durations.append(duration_ms)
            results_count.append(len(results))

        except Exception as e:
            errors += 1
            print(f"Error in original implementation for {member_data['name']}: {e}")

    return {
        "total_tests": len(test_members),
        "successful_tests": len(durations),
        "errors": errors,
        "avg_duration_ms": round(statistics.mean(durations), 2) if durations else 0,
        "median_duration_ms": round(statistics.median(durations), 2) if durations else 0,
        "min_duration_ms": round(min(durations), 2) if durations else 0,
        "max_duration_ms": round(max(durations), 2) if durations else 0,
        "avg_results_count": round(statistics.mean(results_count), 2) if results_count else 0,
        "total_duration_ms": round(sum(durations), 2) if durations else 0,
    }


def test_optimized_implementation(test_members: List[Dict]) -> Dict:
    """Test the optimized O(log N) implementation performance"""

    print("Testing optimized O(log N) implementation...")
    durations = []
    results_count = []
    errors = 0
    tier_usage = {"fingerprint": 0, "normalized": 0, "join": 0, "error": 0}

    for member_data in test_members:
        try:
            # Create a temporary member document for testing
            member_doc = frappe.new_doc("Member")
            member_doc.name = member_data["name"]
            member_doc.full_name = member_data["full_name"]
            member_doc.primary_address = member_data["primary_address"]
            member_doc.address_fingerprint = member_data.get("address_fingerprint")
            member_doc.normalized_address_line = member_data.get("normalized_address_line")
            member_doc.normalized_city = member_data.get("normalized_city")

            start_time = time.time()

            # Test optimized implementation
            from verenigingen.utils.address_matching.simple_optimized_matcher import (
                SimpleOptimizedAddressMatcher,
            )

            results = SimpleOptimizedAddressMatcher.get_other_members_at_address_simple(member_doc)

            duration_ms = (time.time() - start_time) * 1000
            durations.append(duration_ms)
            results_count.append(len(results))

            # Track which tier was used (simplified detection)
            if member_data.get("address_fingerprint") and results:
                tier_usage["fingerprint"] += 1
            elif member_data.get("normalized_address_line") and results:
                tier_usage["normalized"] += 1
            elif results:
                tier_usage["join"] += 1

        except Exception as e:
            errors += 1
            tier_usage["error"] += 1
            print(f"Error in optimized implementation for {member_data['name']}: {e}")

    return {
        "total_tests": len(test_members),
        "successful_tests": len(durations),
        "errors": errors,
        "avg_duration_ms": round(statistics.mean(durations), 2) if durations else 0,
        "median_duration_ms": round(statistics.median(durations), 2) if durations else 0,
        "min_duration_ms": round(min(durations), 2) if durations else 0,
        "max_duration_ms": round(max(durations), 2) if durations else 0,
        "avg_results_count": round(statistics.mean(results_count), 2) if results_count else 0,
        "total_duration_ms": round(sum(durations), 2) if durations else 0,
        "tier_usage": tier_usage,
    }


def simulate_original_address_matching(member_data: Dict) -> List[Dict]:
    """Simulate the original O(N) address matching implementation for comparison"""

    if not member_data.get("primary_address"):
        return []

    try:
        # Get address details
        address = frappe.get_doc("Address", member_data["primary_address"])

        # Normalize using simple method (original approach)
        normalized_address_line = address.address_line1.lower().strip() if address.address_line1 else ""
        normalized_city = address.city.lower().strip() if address.city else ""

        # Original O(N) approach: Get ALL addresses and filter
        all_addresses = frappe.get_all(
            "Address",
            filters=[
                ["address_line1", "!=", ""],
                ["address_line1", "is", "set"],
            ],
            fields=["name", "address_line1", "city", "pincode"],
        )

        # O(N) loop through all addresses
        matching_addresses = []
        for addr in all_addresses:
            addr_line_normalized = addr.address_line1.lower().strip() if addr.address_line1 else ""
            addr_city_normalized = addr.city.lower().strip() if addr.city else ""

            if (
                addr_line_normalized == normalized_address_line
                and addr_city_normalized == normalized_city
                and addr.name != member_data["primary_address"]
            ):
                matching_addresses.append(addr.name)

        if not matching_addresses:
            return []

        # Find members at matching addresses
        other_members = frappe.get_all(
            "Member",
            filters={
                "primary_address": ["in", matching_addresses],
                "name": ["!=", member_data["name"]],
                "status": ["in", ["Active", "Pending", "Suspended"]],
            },
            fields=["name", "full_name", "email", "status", "member_since"],
            order_by="full_name asc",
        )

        return other_members

    except Exception as e:
        print(f"Error in simulated original matching: {e}")
        return []


def analyze_tier_usage(test_members: List[Dict]) -> Dict:
    """Analyze which optimization tier is being used most effectively"""

    tier_analysis = {
        "members_with_fingerprint": 0,
        "members_with_normalized_fields": 0,
        "members_needing_join": 0,
        "fingerprint_coverage_percent": 0,
        "normalization_coverage_percent": 0,
    }

    for member in test_members:
        if member.get("address_fingerprint"):
            tier_analysis["members_with_fingerprint"] += 1

        if member.get("normalized_address_line") and member.get("normalized_city"):
            tier_analysis["members_with_normalized_fields"] += 1

        if not member.get("address_fingerprint") and not member.get("normalized_address_line"):
            tier_analysis["members_needing_join"] += 1

    total_members = len(test_members)
    if total_members > 0:
        tier_analysis["fingerprint_coverage_percent"] = round(
            (tier_analysis["members_with_fingerprint"] / total_members) * 100, 2
        )
        tier_analysis["normalization_coverage_percent"] = round(
            (tier_analysis["members_with_normalized_fields"] / total_members) * 100, 2
        )

    return tier_analysis


def generate_performance_recommendations(results: Dict) -> List[str]:
    """Generate performance optimization recommendations based on test results"""

    recommendations = []

    # Check if performance target was met
    if results.get("improvement_analysis", {}).get("meets_75_percent_target", False):
        recommendations.append("✅ Performance target of 75% improvement achieved!")
    else:
        improvement = results.get("improvement_analysis", {}).get("performance_improvement_percent", 0)
        recommendations.append(f"⚠️ Performance improvement ({improvement}%) below 75% target")

    # Check tier usage effectiveness
    tier_breakdown = results.get("tier_breakdown", {})
    fingerprint_coverage = tier_breakdown.get("fingerprint_coverage_percent", 0)

    if fingerprint_coverage < 90:
        recommendations.append(
            f"🔧 Only {fingerprint_coverage}% of members have computed fingerprints - run full normalization"
        )

    # Check error rates
    optimized_errors = results.get("optimized_performance", {}).get("errors", 0)
    total_tests = results.get("optimized_performance", {}).get("total_tests", 1)
    error_rate = (optimized_errors / total_tests) * 100

    if error_rate > 5:
        recommendations.append(f"🚨 High error rate ({error_rate}%) in optimized implementation")

    # Check for slow queries
    avg_duration = results.get("optimized_performance", {}).get("avg_duration_ms", 0)
    if avg_duration > 50:
        recommendations.append(f"⚡ Average query time ({avg_duration}ms) could be optimized further")

    if not recommendations:
        recommendations.append("🎉 Optimization is performing excellently!")

    return recommendations


@frappe.whitelist()
def quick_performance_comparison():
    """Quick performance comparison for immediate feedback"""

    # Get one test member
    test_member = frappe.db.sql(
        """
        SELECT name, primary_address, address_fingerprint
        FROM `tabMember`
        WHERE primary_address IS NOT NULL
        LIMIT 1
    """,
        as_dict=True,
    )

    if not test_member:
        return {"error": "No members with addresses found for testing"}

    member_data = test_member[0]

    # Test original approach
    start_time = time.time()
    original_results = simulate_original_address_matching(member_data)
    original_duration = (time.time() - start_time) * 1000

    # Test optimized approach
    from verenigingen.utils.address_matching.simple_optimized_matcher import SimpleOptimizedAddressMatcher

    member_doc = frappe.get_doc("Member", member_data["name"])
    start_time = time.time()
    optimized_results = SimpleOptimizedAddressMatcher.get_other_members_at_address_simple(member_doc)
    optimized_duration = (time.time() - start_time) * 1000

    improvement = 0
    if original_duration > 0:
        improvement = ((original_duration - optimized_duration) / original_duration) * 100

    return {
        "test_member": member_data["name"],
        "original_duration_ms": round(original_duration, 2),
        "optimized_duration_ms": round(optimized_duration, 2),
        "improvement_percent": round(improvement, 2),
        "original_result_count": len(original_results),
        "optimized_result_count": len(optimized_results),
        "results_match": len(original_results) == len(optimized_results),
        "meets_target": improvement >= 75,
    }
