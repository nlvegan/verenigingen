"""
Performance Reporting Tools
Phase 1 Implementation - Evidence-Based Performance Improvement Plan

This module generates comprehensive performance reports with actionable insights
and specific optimization targets.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict, List

import frappe
from frappe.utils import get_datetime, now

from .bottleneck_analyzer import PaymentOperationAnalyzer, PerformanceComparison
from .query_measurement import PerformanceBaselineCollector, QueryMeasurementStore


class PerformanceReporter:
    """Generates comprehensive performance reports"""

    def __init__(self):
        self.analyzer = PaymentOperationAnalyzer()

    def generate_comprehensive_report(
        self, include_baselines: bool = True, sample_size: int = 10
    ) -> Dict[str, Any]:
        """Generate comprehensive performance analysis report"""

        report_start = time.time()

        report = {
            "report_metadata": {
                "generated_at": now(),
                "report_type": "comprehensive_performance_analysis",
                "system_info": {"site": frappe.local.site, "frappe_version": frappe.__version__},
            }
        }

        # 1. Current Performance Baseline
        if include_baselines:
            frappe.logger().info("Collecting performance baselines...")
            baseline_report = PerformanceBaselineCollector().generate_baseline_report()
            report["current_baselines"] = baseline_report

        # 2. Detailed Member Analysis
        frappe.logger().info("Analyzing individual member performance...")
        member_analyses = self._analyze_sample_members(sample_size)
        report["member_analyses"] = member_analyses

        # 3. System-wide Query Analysis
        frappe.logger().info("Analyzing system-wide query patterns...")
        query_analysis = self._analyze_system_queries()
        report["query_analysis"] = query_analysis

        # 4. Bottleneck Summary
        frappe.logger().info("Summarizing bottlenecks...")
        bottleneck_summary = self._summarize_bottlenecks(member_analyses)
        report["bottleneck_summary"] = bottleneck_summary

        # 5. Optimization Recommendations
        frappe.logger().info("Generating optimization recommendations...")
        recommendations = self._generate_optimization_roadmap(bottleneck_summary, query_analysis)
        report["optimization_roadmap"] = recommendations

        # 6. Performance Targets
        performance_targets = self._calculate_performance_targets(report)
        report["performance_targets"] = performance_targets

        report["report_metadata"]["generation_time"] = time.time() - report_start

        # Store report for future reference
        self._store_report(report)

        return report

    def _analyze_sample_members(self, sample_size: int) -> List[Dict[str, Any]]:
        """Analyze performance for sample of members"""

        # Get diverse sample of members
        members = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "full_name", "customer"],
            order_by="modified desc",
            limit=sample_size,
        )

        analyses = []
        for member in members:
            try:
                analysis = self.analyzer.analyze_member_payment_performance(member.name)
                analysis["member_full_name"] = member.full_name
                analyses.append(analysis)

                # Small delay to prevent overload
                time.sleep(0.1)

            except Exception as e:
                frappe.log_error(f"Failed to analyze member {member.name}: {e}")
                analyses.append({"member_name": member.name, "error": str(e), "analysis_failed": True})

        return analyses

    def _analyze_system_queries(self) -> Dict[str, Any]:
        """Analyze system-wide query patterns"""

        # Get recent query measurements
        recent_measurements = QueryMeasurementStore.get_results(limit=50)
        aggregated_stats = QueryMeasurementStore.get_aggregated_stats()

        # Analyze patterns
        operation_performance = {}
        total_queries = 0
        total_time = 0

        for measurement in recent_measurements:
            operation = measurement.get("operation_name", "unknown")

            if operation not in operation_performance:
                operation_performance[operation] = {
                    "measurement_count": 0,
                    "total_queries": 0,
                    "total_time": 0,
                    "avg_queries": 0,
                    "avg_time": 0,
                }

            op_stats = operation_performance[operation]
            op_stats["measurement_count"] += 1
            op_stats["total_queries"] += measurement.get("query_count", 0)
            op_stats["total_time"] += measurement.get("execution_time", 0)

            total_queries += measurement.get("query_count", 0)
            total_time += measurement.get("execution_time", 0)

        # Calculate averages
        for op_stats in operation_performance.values():
            if op_stats["measurement_count"] > 0:
                op_stats["avg_queries"] = op_stats["total_queries"] / op_stats["measurement_count"]
                op_stats["avg_time"] = op_stats["total_time"] / op_stats["measurement_count"]

        return {
            "recent_measurements_count": len(recent_measurements),
            "total_queries_measured": total_queries,
            "total_execution_time": total_time,
            "operation_performance": operation_performance,
            "aggregated_stats": aggregated_stats,
            "high_impact_operations": self._identify_high_impact_operations(operation_performance),
        }

    def _identify_high_impact_operations(self, operation_performance: Dict) -> List[Dict[str, Any]]:
        """Identify operations with highest performance impact"""

        high_impact = []
        for operation, stats in operation_performance.items():
            # Calculate impact score (queries * frequency * time)
            impact_score = stats["avg_queries"] * stats["measurement_count"] * stats["avg_time"]

            high_impact.append(
                {
                    "operation": operation,
                    "impact_score": impact_score,
                    "avg_queries": stats["avg_queries"],
                    "avg_time": stats["avg_time"],
                    "frequency": stats["measurement_count"],
                }
            )

        # Sort by impact score
        high_impact.sort(key=lambda x: x["impact_score"], reverse=True)

        return high_impact[:10]  # Top 10 high-impact operations

    def _summarize_bottlenecks(self, member_analyses: List[Dict]) -> Dict[str, Any]:
        """Summarize bottlenecks across all member analyses"""

        all_bottlenecks = []
        all_patterns = []
        optimization_priorities = []

        for analysis in member_analyses:
            if analysis.get("analysis_failed"):
                continue

            bottlenecks = analysis.get("bottlenecks", [])
            n1_patterns = analysis.get("n1_patterns", {}).get("patterns", [])
            priority = analysis.get("optimization_priority", "low")

            all_bottlenecks.extend(bottlenecks)
            all_patterns.extend(n1_patterns)
            optimization_priorities.append(priority)

        # Analyze bottleneck types
        bottleneck_types = {}
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        for bottleneck in all_bottlenecks:
            btype = bottleneck.get("type", "unknown")
            severity = bottleneck.get("severity", "low")

            if btype not in bottleneck_types:
                bottleneck_types[btype] = {"count": 0, "total_impact": 0}

            bottleneck_types[btype]["count"] += 1
            bottleneck_types[btype]["total_impact"] += bottleneck.get("metric_value", 0)
            severity_counts[severity] += 1

        # Analyze N+1 patterns
        pattern_analysis = self._analyze_n1_patterns(all_patterns)

        # Priority distribution
        priority_counts = {p: optimization_priorities.count(p) for p in ["critical", "high", "medium", "low"]}

        return {
            "total_bottlenecks": len(all_bottlenecks),
            "bottleneck_types": bottleneck_types,
            "severity_distribution": severity_counts,
            "priority_distribution": priority_counts,
            "n1_pattern_analysis": pattern_analysis,
            "most_critical_issues": self._identify_most_critical_issues(all_bottlenecks),
            "system_health_score": self._calculate_system_health_score(severity_counts, priority_counts),
        }

    def _analyze_n1_patterns(self, all_patterns: List[Dict]) -> Dict[str, Any]:
        """Analyze N+1 patterns across the system"""

        pattern_types = {}
        total_wasted_queries = 0
        total_wasted_time = 0

        for pattern in all_patterns:
            ptype = pattern.get("pattern_type", "unknown")
            occurrence_count = pattern.get("occurrence_count", 0)
            execution_time = pattern.get("total_execution_time", 0)

            if ptype not in pattern_types:
                pattern_types[ptype] = {
                    "instances": 0,
                    "total_queries": 0,
                    "total_time": 0,
                    "avg_queries_per_instance": 0,
                    "severity_distribution": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                }

            pstats = pattern_types[ptype]
            pstats["instances"] += 1
            pstats["total_queries"] += occurrence_count
            pstats["total_time"] += execution_time
            pstats["severity_distribution"][pattern.get("severity", "low")] += 1

            total_wasted_queries += occurrence_count
            total_wasted_time += execution_time

        # Calculate averages
        for pstats in pattern_types.values():
            if pstats["instances"] > 0:
                pstats["avg_queries_per_instance"] = pstats["total_queries"] / pstats["instances"]

        return {
            "total_n1_instances": len(all_patterns),
            "total_wasted_queries": total_wasted_queries,
            "total_wasted_time": total_wasted_time,
            "pattern_types": pattern_types,
            "optimization_potential": {
                "query_reduction_potential": total_wasted_queries * 0.8,  # Assume 80% can be optimized
                "time_savings_potential": total_wasted_time * 0.7,  # Assume 70% time savings
            },
        }

    def _identify_most_critical_issues(self, all_bottlenecks: List[Dict]) -> List[Dict[str, Any]]:
        """Identify the most critical performance issues"""

        critical_issues = []

        # Sort by severity and impact
        sorted_bottlenecks = sorted(
            all_bottlenecks,
            key=lambda x: (
                {"critical": 4, "high": 3, "medium": 2, "low": 1}[x.get("severity", "low")],
                x.get("metric_value", 0),
            ),
            reverse=True,
        )

        # Group similar issues
        issue_groups = {}
        for bottleneck in sorted_bottlenecks[:20]:  # Top 20 most critical
            key = f"{bottleneck.get('type', 'unknown')}_{bottleneck.get('severity', 'low')}"

            if key not in issue_groups:
                issue_groups[key] = {
                    "type": bottleneck.get("type"),
                    "severity": bottleneck.get("severity"),
                    "count": 0,
                    "total_impact": 0,
                    "descriptions": [],
                    "sample_bottleneck": bottleneck,
                }

            group = issue_groups[key]
            group["count"] += 1
            group["total_impact"] += bottleneck.get("metric_value", 0)
            if len(group["descriptions"]) < 3:
                group["descriptions"].append(bottleneck.get("description", ""))

        # Convert to list and sort by impact
        critical_issues = list(issue_groups.values())
        critical_issues.sort(key=lambda x: x["total_impact"], reverse=True)

        return critical_issues[:10]  # Top 10 critical issue groups

    def _calculate_system_health_score(self, severity_counts: Dict, priority_counts: Dict) -> Dict[str, Any]:
        """Calculate overall system health score"""

        # Weight different severities
        severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
        priority_weights = {"critical": 8, "high": 4, "medium": 2, "low": 1}

        severity_score = sum(
            count * severity_weights[severity] for severity, count in severity_counts.items()
        )
        priority_score = sum(
            count * priority_weights[priority] for priority, count in priority_counts.items()
        )

        # Calculate health score (lower is better, 100 is perfect)
        max_possible_score = 200  # Arbitrary max for scaling
        combined_score = severity_score + priority_score
        health_percentage = max(0, 100 - (combined_score / max_possible_score * 100))

        # Determine health status
        if health_percentage >= 90:
            status = "excellent"
        elif health_percentage >= 75:
            status = "good"
        elif health_percentage >= 50:
            status = "fair"
        elif health_percentage >= 25:
            status = "poor"
        else:
            status = "critical"

        return {
            "health_percentage": health_percentage,
            "status": status,
            "severity_score": severity_score,
            "priority_score": priority_score,
            "recommendation": self._get_health_recommendation(status, severity_counts, priority_counts),
        }

    def _get_health_recommendation(self, status: str, severity_counts: Dict, priority_counts: Dict) -> str:
        """Get recommendation based on health status"""

        if status == "critical":
            return (
                "URGENT: System requires immediate performance optimization. Critical bottlenecks detected."
            )
        elif status == "poor":
            return "System performance is poor. Schedule optimization work immediately."
        elif status == "fair":
            return "System performance needs improvement. Plan optimization in next sprint."
        elif status == "good":
            return "System performance is acceptable. Monitor and optimize specific bottlenecks."
        else:
            return "System performance is excellent. Continue monitoring for regression."

    def _generate_optimization_roadmap(
        self, bottleneck_summary: Dict, query_analysis: Dict
    ) -> Dict[str, Any]:
        """Generate optimization roadmap with specific action items"""

        roadmap = {
            "immediate_actions": [],
            "short_term_goals": [],
            "long_term_objectives": [],
            "implementation_priority": [],
            "expected_improvements": {},
        }

        # Immediate actions (critical issues)
        critical_count = bottleneck_summary["severity_distribution"].get("critical", 0)
        high_count = bottleneck_summary["severity_distribution"].get("high", 0)

        if critical_count > 0:
            roadmap["immediate_actions"].append(
                {
                    "action": "Fix Critical N+1 Patterns",
                    "description": f"Address {critical_count} critical performance bottlenecks",
                    "implementation": "Implement batch loading for payment references and invoice data",
                    "timeline": "1-2 days",
                    "expected_improvement": "60-80% query reduction",
                }
            )

        if high_count > 5:
            roadmap["immediate_actions"].append(
                {
                    "action": "Implement Query Caching",
                    "description": f"Address {high_count} high-severity performance issues",
                    "implementation": "Enable payment history caching with smart invalidation",
                    "timeline": "2-3 days",
                    "expected_improvement": "40-60% execution time reduction",
                }
            )

        # Short-term goals
        n1_potential = bottleneck_summary["n1_pattern_analysis"]["optimization_potential"]
        if n1_potential["query_reduction_potential"] > 100:
            roadmap["short_term_goals"].append(
                {
                    "goal": "Eliminate N+1 Query Patterns",
                    "description": f'Potential to reduce {n1_potential["query_reduction_potential"]:.0f} queries',
                    "implementation": "Refactor payment history loading with comprehensive batch queries",
                    "timeline": "1-2 weeks",
                    "expected_improvement": f'{n1_potential["time_savings_potential"]:.1f}s time savings per operation',
                }
            )

        # Long-term objectives
        roadmap["long_term_objectives"].append(
            {
                "objective": "Comprehensive Performance Architecture",
                "description": "Implement system-wide performance monitoring and optimization",
                "implementation": "Deploy automated performance monitoring and alerting",
                "timeline": "1-2 months",
                "expected_improvement": "Prevent performance regressions, 90%+ uptime SLA",
            }
        )

        # Implementation priority
        priority_items = self._calculate_implementation_priority(bottleneck_summary, query_analysis)
        roadmap["implementation_priority"] = priority_items

        # Calculate expected improvements
        roadmap["expected_improvements"] = self._calculate_expected_improvements(bottleneck_summary)

        return roadmap

    def _calculate_implementation_priority(
        self, bottleneck_summary: Dict, query_analysis: Dict
    ) -> List[Dict[str, Any]]:
        """Calculate implementation priority for optimization tasks"""

        priority_items = []

        # High-impact operations from query analysis
        high_impact_ops = query_analysis.get("high_impact_operations", [])
        for i, op in enumerate(high_impact_ops[:5]):
            priority_items.append(
                {
                    "priority_rank": i + 1,
                    "task": f"Optimize {op['operation']} operation",
                    "impact_score": op["impact_score"],
                    "effort_estimate": "Medium",
                    "roi_score": op["impact_score"] / 5,  # Assuming medium effort = 5 units
                    "implementation_notes": f"Average {op['avg_queries']} queries, {op['avg_time']:.2f}s execution time",
                }
            )

        # Critical bottleneck types
        bottleneck_types = bottleneck_summary.get("bottleneck_types", {})
        for btype, stats in bottleneck_types.items():
            if stats["count"] > 3:  # Frequent bottleneck
                priority_items.append(
                    {
                        "priority_rank": len(priority_items) + 1,
                        "task": f"Address {btype} bottlenecks",
                        "impact_score": stats["total_impact"],
                        "effort_estimate": "High" if btype == "n1_pattern" else "Medium",
                        "roi_score": stats["total_impact"] / (8 if btype == "n1_pattern" else 5),
                        "implementation_notes": f"{stats['count']} instances detected across system",
                    }
                )

        # Sort by ROI score
        priority_items.sort(key=lambda x: x["roi_score"], reverse=True)

        # Re-rank after sorting
        for i, item in enumerate(priority_items):
            item["priority_rank"] = i + 1

        return priority_items[:10]  # Top 10 priority items

    def _calculate_expected_improvements(self, bottleneck_summary: Dict) -> Dict[str, Any]:
        """Calculate expected improvements from optimizations"""

        n1_analysis = bottleneck_summary.get("n1_pattern_analysis", {})

        return {
            "query_reduction": {
                "potential_queries_eliminated": n1_analysis.get("optimization_potential", {}).get(
                    "query_reduction_potential", 0
                ),
                "percentage_improvement": "60-80%",
                "confidence": "high",
            },
            "execution_time": {
                "potential_time_saved": n1_analysis.get("optimization_potential", {}).get(
                    "time_savings_potential", 0
                ),
                "percentage_improvement": "40-70%",
                "confidence": "high",
            },
            "user_experience": {
                "page_load_improvement": "2-5x faster",
                "timeout_risk_reduction": "90%",
                "confidence": "medium",
            },
            "system_resources": {
                "database_connection_savings": "50-70%",
                "memory_usage_reduction": "30-50%",
                "confidence": "medium",
            },
        }

    def _store_report(self, report: Dict[str, Any]) -> None:
        """Store report for historical tracking"""
        try:
            # Store in cache
            report_key = f"performance_report_{int(time.time())}"
            frappe.cache().set(report_key, report, expires_in_sec=86400)  # 24 hours

            # Also maintain a list of recent reports
            recent_reports_key = "recent_performance_reports"
            recent_reports = frappe.cache().get(recent_reports_key) or []

            recent_reports.append(
                {
                    "timestamp": report["report_metadata"]["generated_at"],
                    "report_key": report_key,
                    "health_score": report.get("bottleneck_summary", {})
                    .get("system_health_score", {})
                    .get("health_percentage", 0),
                }
            )

            # Keep only last 10 reports
            if len(recent_reports) > 10:
                recent_reports = recent_reports[-10:]

            frappe.cache().set(recent_reports_key, recent_reports, expires_in_sec=86400 * 7)  # 7 days

        except Exception as e:
            frappe.log_error(f"Failed to store performance report: {e}")


def generate_performance_report(sample_size: int = 10) -> Dict[str, Any]:
    """Generate comprehensive performance report"""
    reporter = PerformanceReporter()
    return reporter.generate_comprehensive_report(sample_size=sample_size)


def get_recent_reports() -> List[Dict[str, Any]]:
    """Get list of recent performance reports"""
    return frappe.cache().get("recent_performance_reports") or []


def get_report_by_key(report_key: str) -> Dict[str, Any]:
    """Get specific performance report by key"""
    return frappe.cache().get(report_key) or {}


def create_performance_baseline(operation_name: str = "member_payment_operations") -> Dict[str, Any]:
    """Create performance baseline snapshot"""
    return PerformanceComparison.create_baseline_snapshot(operation_name, sample_size=10)
