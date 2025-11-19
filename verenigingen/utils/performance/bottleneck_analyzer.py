"""
Performance Bottleneck Analyzer
Phase 1 Implementation - Evidence-Based Performance Improvement Plan

This module analyzes query patterns and identifies specific bottlenecks
in the payment operations, particularly N+1 query patterns.
"""

import re
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

import frappe
from frappe.utils import now

from .query_measurement import PaymentHistoryProfiler, QueryProfiler


class N1QueryDetector:
    """Detects N+1 query patterns in payment operations"""

    def __init__(self):
        self.query_patterns = defaultdict(list)
        self.suspicious_patterns = []

    def analyze_payment_history_n1_patterns(self, member_name: str) -> Dict[str, Any]:
        """Analyze a member's payment history loading for N+1 patterns"""

        # Use custom profiler that captures more detail
        with QueryProfiler(f"N1_Analysis_{member_name}") as profiler:
            member = frappe.get_doc("Member", member_name)

            # Trigger payment history loading
            if hasattr(member, "_load_payment_history_without_save"):
                member._load_payment_history_without_save()

        results = profiler.get_results()
        queries = profiler.queries

        # Analyze for N+1 patterns
        n1_analysis = self._detect_n1_patterns(queries)

        # Add to results
        results["n1_analysis"] = n1_analysis
        results["critical_n1_patterns"] = [p for p in n1_analysis["patterns"] if p["severity"] == "high"]

        return results

    def _detect_n1_patterns(self, queries: List[Dict]) -> Dict[str, Any]:
        """Detect N+1 patterns in query list"""

        # Group similar queries
        query_groups = defaultdict(list)

        for query in queries:
            # Normalize query by removing specific values
            normalized = self._normalize_query(query["query"])
            query_groups[normalized].append(query)

        # Analyze each group for N+1 patterns
        patterns = []
        for normalized_query, query_list in query_groups.items():
            if len(query_list) > 3:  # More than 3 similar queries is suspicious
                pattern = self._analyze_query_group(normalized_query, query_list)
                if pattern:
                    patterns.append(pattern)

        # Sort by severity
        patterns.sort(key=lambda x: x["occurrence_count"], reverse=True)

        return {
            "patterns": patterns,
            "total_pattern_count": len(patterns),
            "high_severity_count": len([p for p in patterns if p["severity"] == "high"]),
            "analysis_timestamp": now(),
        }

    def _normalize_query(self, query: str) -> str:
        """Normalize query by removing specific values"""
        # Remove quoted strings and numbers to find patterns
        normalized = re.sub(r"'[^']*'", "'?'", query)
        normalized = re.sub(r'"[^"]*"', '"?"', normalized)
        normalized = re.sub(r"\b\d+\b", "?", normalized)

        # Remove extra whitespace
        normalized = " ".join(normalized.split())

        return normalized

    def _analyze_query_group(self, normalized_query: str, query_list: List[Dict]) -> Dict[str, Any]:
        """Analyze a group of similar queries for N+1 pattern"""

        occurrence_count = len(query_list)
        total_time = sum(q["execution_time"] for q in query_list)
        avg_time = total_time / occurrence_count

        # Determine severity
        if occurrence_count > 20:
            severity = "critical"
        elif occurrence_count > 10:
            severity = "high"
        elif occurrence_count > 5:
            severity = "medium"
        else:
            severity = "low"

        # Identify the type of N+1 pattern
        pattern_type = self._identify_pattern_type(normalized_query)

        # Extract table names
        tables = self._extract_tables_from_query(normalized_query)

        return {
            "normalized_query": normalized_query[:200],  # Truncate for readability
            "occurrence_count": occurrence_count,
            "total_execution_time": total_time,
            "avg_execution_time": avg_time,
            "severity": severity,
            "pattern_type": pattern_type,
            "affected_tables": tables,
            "sample_queries": [q["query"][:150] for q in query_list[:3]],  # First 3 examples
            "optimization_suggestions": self._get_optimization_suggestions(
                pattern_type, tables, occurrence_count
            ),
        }

    def _identify_pattern_type(self, query: str) -> str:
        """Identify the type of query pattern"""
        query_upper = query.upper()

        if "PAYMENT ENTRY REFERENCE" in query_upper:
            return "payment_reference_lookup"
        elif "SALES INVOICE" in query_upper:
            return "invoice_lookup"
        elif "SEPA MANDATE" in query_upper:
            return "sepa_mandate_lookup"
        elif "MEMBERSHIP" in query_upper:
            return "membership_lookup"
        elif "PAYMENT ENTRY" in query_upper and "WHERE NAME" in query_upper:
            return "payment_entry_detail_lookup"
        elif "DONATION" in query_upper:
            return "donation_lookup"
        else:
            return "unknown_pattern"

    def _extract_tables_from_query(self, query: str) -> List[str]:
        """Extract table names from query"""
        tables = set()

        # Find FROM and JOIN clauses
        from_matches = re.findall(r"FROM\s+`?(\w+)`?", query, re.IGNORECASE)
        join_matches = re.findall(r"JOIN\s+`?(\w+)`?", query, re.IGNORECASE)

        tables.update(from_matches)
        tables.update(join_matches)

        return list(tables)

    def _get_optimization_suggestions(self, pattern_type: str, tables: List[str], count: int) -> List[str]:
        """Get optimization suggestions based on pattern type"""
        suggestions = []

        if pattern_type == "payment_reference_lookup" and count > 10:
            suggestions.append("Consider batch loading payment references for all invoices at once")
            suggestions.append("Implement JOIN query instead of individual lookups")

        elif pattern_type == "invoice_lookup" and count > 5:
            suggestions.append("Batch load invoice details with single query")
            suggestions.append("Use frappe.get_all() with comprehensive field list")

        elif pattern_type == "sepa_mandate_lookup":
            suggestions.append("Cache SEPA mandate status per member")
            suggestions.append("Load all member mandates in single query")

        elif pattern_type == "payment_entry_detail_lookup":
            suggestions.append("Join payment entry details with references query")
            suggestions.append("Use payment entry batch loading")

        elif pattern_type == "membership_lookup":
            suggestions.append("Pre-load membership data with invoice query")
            suggestions.append("Cache membership details per member")

        else:
            suggestions.append(f"Investigate {count} repetitive queries on tables: {', '.join(tables)}")
            suggestions.append("Consider batch loading or caching strategy")

        return suggestions


class PaymentOperationAnalyzer:
    """Analyzes payment operations for performance bottlenecks"""

    def __init__(self):
        self.n1_detector = N1QueryDetector()

    def analyze_member_payment_performance(self, member_name: str) -> Dict[str, Any]:
        """Comprehensive analysis of member payment performance"""

        analysis_start = time.time()

        # Run N+1 analysis
        n1_analysis = self.n1_detector.analyze_payment_history_n1_patterns(member_name)

        # Additional performance metrics
        member = frappe.get_doc("Member", member_name)
        payment_count = len(getattr(member, "payment_history", []))

        # Analyze specific bottlenecks
        bottlenecks = self._identify_specific_bottlenecks(n1_analysis, payment_count)

        analysis_time = time.time() - analysis_start

        return {
            "member_name": member_name,
            "analysis_timestamp": now(),
            "analysis_duration": analysis_time,
            "payment_entries_count": payment_count,
            "query_performance": {
                "total_queries": n1_analysis["query_count"],
                "total_execution_time": n1_analysis["execution_time"],
                "queries_per_payment": n1_analysis["query_count"] / payment_count if payment_count > 0 else 0,
                "avg_query_time": n1_analysis["avg_query_time"],
            },
            "n1_patterns": n1_analysis["n1_analysis"],
            "bottlenecks": bottlenecks,
            "optimization_priority": self._calculate_optimization_priority(bottlenecks),
            "recommendations": self._generate_recommendations(bottlenecks, n1_analysis),
        }

    def _identify_specific_bottlenecks(self, n1_analysis: Dict, payment_count: int) -> List[Dict[str, Any]]:
        """Identify specific performance bottlenecks"""
        bottlenecks = []

        # High query count bottleneck
        if n1_analysis["query_count"] > 50:
            bottlenecks.append(
                {
                    "type": "high_query_count",
                    "severity": "high" if n1_analysis["query_count"] > 100 else "medium",
                    "description": f"Excessive query count: {n1_analysis['query_count']} queries",
                    "impact": "Database connection exhaustion, slow response times",
                    "metric_value": n1_analysis["query_count"],
                }
            )

        # Slow execution bottleneck
        if n1_analysis["execution_time"] > 2.0:
            bottlenecks.append(
                {
                    "type": "slow_execution",
                    "severity": "high" if n1_analysis["execution_time"] > 5.0 else "medium",
                    "description": f"Slow execution time: {n1_analysis['execution_time']:.2f}s",
                    "impact": "Poor user experience, timeout risks",
                    "metric_value": n1_analysis["execution_time"],
                }
            )

        # N+1 pattern bottlenecks
        for pattern in n1_analysis["n1_analysis"]["patterns"]:
            if pattern["severity"] in ["high", "critical"]:
                bottlenecks.append(
                    {
                        "type": "n1_pattern",
                        "severity": pattern["severity"],
                        "description": f"N+1 pattern: {pattern['pattern_type']} ({pattern['occurrence_count']} queries)",
                        "impact": f"Repetitive database access, {pattern['total_execution_time']:.2f}s wasted",
                        "metric_value": pattern["occurrence_count"],
                        "pattern_details": pattern,
                    }
                )

        # Inefficient query patterns
        if n1_analysis.get("slow_query_count", 0) > 0:
            bottlenecks.append(
                {
                    "type": "slow_queries",
                    "severity": "medium",
                    "description": f"{n1_analysis['slow_query_count']} slow queries (>100ms)",
                    "impact": "Individual query performance issues",
                    "metric_value": n1_analysis["slow_query_count"],
                }
            )

        return bottlenecks

    def _calculate_optimization_priority(self, bottlenecks: List[Dict]) -> str:
        """Calculate optimization priority based on bottlenecks"""
        critical_count = len([b for b in bottlenecks if b["severity"] == "critical"])
        high_count = len([b for b in bottlenecks if b["severity"] == "high"])

        if critical_count > 0:
            return "critical"
        elif high_count > 2:
            return "high"
        elif high_count > 0 or len(bottlenecks) > 3:
            return "medium"
        else:
            return "low"

    def _generate_recommendations(self, bottlenecks: List[Dict], n1_analysis: Dict) -> List[Dict[str, Any]]:
        """Generate specific optimization recommendations"""
        recommendations = []

        # Recommendations based on bottleneck types
        bottleneck_types = [b["type"] for b in bottlenecks]

        if "n1_pattern" in bottleneck_types:
            recommendations.append(
                {
                    "priority": "high",
                    "category": "batch_loading",
                    "title": "Implement Batch Query Loading",
                    "description": "Replace N+1 query patterns with batch loading using frappe.get_all() with IN filters",
                    "implementation": "Use background_jobs.py optimized loading functions",
                    "expected_improvement": "60-80% query reduction",
                }
            )

        if "high_query_count" in bottleneck_types:
            recommendations.append(
                {
                    "priority": "high",
                    "category": "query_optimization",
                    "title": "Reduce Total Query Count",
                    "description": "Implement comprehensive data preloading and caching",
                    "implementation": "Enable payment history caching and limit entry count",
                    "expected_improvement": "50-70% query reduction",
                }
            )

        if "slow_execution" in bottleneck_types:
            recommendations.append(
                {
                    "priority": "medium",
                    "category": "performance_tuning",
                    "title": "Optimize Slow Queries",
                    "description": "Add database indexes and optimize query structure",
                    "implementation": "Review and optimize individual slow queries",
                    "expected_improvement": "30-50% execution time reduction",
                }
            )

        # Always recommend caching
        recommendations.append(
            {
                "priority": "medium",
                "category": "caching",
                "title": "Implement Smart Caching",
                "description": "Cache payment history data with invalidation on updates",
                "implementation": "Use frappe.cache() with member-specific keys",
                "expected_improvement": "80-90% improvement for repeated access",
            }
        )

        return recommendations


class PerformanceComparison:
    """Compare performance before and after optimizations"""

    @staticmethod
    def create_baseline_snapshot(operation_name: str, sample_size: int = 5) -> Dict[str, Any]:
        """Create performance baseline snapshot"""

        # Get sample members
        members = frappe.get_all(
            "Member", filters={"customer": ("!=", "")}, fields=["name"], limit=sample_size
        )

        measurements = []
        analyzer = PaymentOperationAnalyzer()

        for member in members:
            try:
                analysis = analyzer.analyze_member_payment_performance(member.name)
                measurements.append(analysis)
                time.sleep(0.1)  # Prevent overload
            except Exception as e:
                frappe.log_error(f"Failed to measure member {member.name}: {e}")
                continue

        # Calculate baseline metrics
        if measurements:
            query_counts = [m["query_performance"]["total_queries"] for m in measurements]
            exec_times = [m["query_performance"]["total_execution_time"] for m in measurements]

            baseline = {
                "operation_name": operation_name,
                "timestamp": now(),
                "sample_size": len(measurements),
                "avg_query_count": sum(query_counts) / len(query_counts),
                "max_query_count": max(query_counts),
                "min_query_count": min(query_counts),
                "avg_execution_time": sum(exec_times) / len(exec_times),
                "max_execution_time": max(exec_times),
                "min_execution_time": min(exec_times),
                "individual_measurements": measurements,
                "bottleneck_summary": PerformanceComparison._summarize_bottlenecks(measurements),
            }

            # Store baseline
            frappe.cache().set(f"performance_baseline_{operation_name}", baseline, expires_in_sec=7200)
            return baseline
        else:
            return {"error": "No measurements collected"}

    @staticmethod
    def _summarize_bottlenecks(measurements: List[Dict]) -> Dict[str, Any]:
        """Summarize bottlenecks across measurements"""
        all_bottlenecks = []
        for measurement in measurements:
            all_bottlenecks.extend(measurement.get("bottlenecks", []))

        bottleneck_types = Counter(b["type"] for b in all_bottlenecks)
        severity_counts = Counter(b["severity"] for b in all_bottlenecks)

        return {
            "total_bottlenecks": len(all_bottlenecks),
            "bottleneck_types": dict(bottleneck_types),
            "severity_distribution": dict(severity_counts),
            "most_common_type": bottleneck_types.most_common(1)[0] if bottleneck_types else None,
        }

    @staticmethod
    def compare_with_baseline(operation_name: str, current_measurements: List[Dict]) -> Dict[str, Any]:
        """Compare current measurements with baseline"""

        baseline = frappe.cache().get(f"performance_baseline_{operation_name}")
        if not baseline:
            return {"error": "No baseline found for comparison"}

        # Calculate current metrics
        current_query_counts = [m["query_performance"]["total_queries"] for m in current_measurements]
        current_exec_times = [m["query_performance"]["total_execution_time"] for m in current_measurements]

        current_avg_queries = sum(current_query_counts) / len(current_query_counts)
        current_avg_exec_time = sum(current_exec_times) / len(current_exec_times)

        # Calculate improvements
        query_improvement = (
            (baseline["avg_query_count"] - current_avg_queries) / baseline["avg_query_count"]
        ) * 100
        time_improvement = (
            (baseline["avg_execution_time"] - current_avg_exec_time) / baseline["avg_execution_time"]
        ) * 100

        return {
            "comparison_timestamp": now(),
            "baseline_timestamp": baseline["timestamp"],
            "baseline_metrics": {
                "avg_query_count": baseline["avg_query_count"],
                "avg_execution_time": baseline["avg_execution_time"],
            },
            "current_metrics": {
                "avg_query_count": current_avg_queries,
                "avg_execution_time": current_avg_exec_time,
            },
            "improvements": {
                "query_count_improvement_percent": query_improvement,
                "execution_time_improvement_percent": time_improvement,
                "overall_assessment": PerformanceComparison._assess_improvement(
                    query_improvement, time_improvement
                ),
            },
            "bottleneck_comparison": PerformanceComparison._compare_bottlenecks(
                baseline.get("bottleneck_summary", {}),
                PerformanceComparison._summarize_bottlenecks(current_measurements),
            ),
        }

    @staticmethod
    def _assess_improvement(query_improvement: float, time_improvement: float) -> str:
        """Assess overall improvement"""
        avg_improvement = (query_improvement + time_improvement) / 2

        if avg_improvement > 50:
            return "excellent"
        elif avg_improvement > 25:
            return "good"
        elif avg_improvement > 10:
            return "moderate"
        elif avg_improvement > 0:
            return "slight"
        else:
            return "regression"

    @staticmethod
    def _compare_bottlenecks(baseline_summary: Dict, current_summary: Dict) -> Dict[str, Any]:
        """Compare bottleneck summaries"""
        return {
            "baseline_bottlenecks": baseline_summary.get("total_bottlenecks", 0),
            "current_bottlenecks": current_summary.get("total_bottlenecks", 0),
            "bottleneck_reduction": baseline_summary.get("total_bottlenecks", 0)
            - current_summary.get("total_bottlenecks", 0),
            "baseline_types": baseline_summary.get("bottleneck_types", {}),
            "current_types": current_summary.get("bottleneck_types", {}),
        }
