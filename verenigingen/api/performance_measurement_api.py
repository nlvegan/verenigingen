"""
Performance Measurement API
Phase 1 Implementation - Evidence-Based Performance Improvement Plan

API endpoints for accessing query measurement tools and performance analysis.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.performance.bottleneck_analyzer import PaymentOperationAnalyzer, PerformanceComparison
from verenigingen.utils.performance.performance_reporter import (
    PerformanceReporter,
    create_performance_baseline,
    generate_performance_report,
    get_recent_reports,
)
from verenigingen.utils.performance.query_measurement import (
    PerformanceBaselineCollector,
    QueryMeasurementStore,
    measure_member_payment_history,
    measure_sepa_mandate_operations,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def measure_member_performance(member_name: str) -> Dict[str, Any]:
    """
    Measure performance for a specific member's payment operations

    Args:
        member_name: Name of the member to analyze

    Returns:
        Dict containing performance measurements and analysis
    """
    try:
        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} not found"}

        # Run comprehensive analysis
        analyzer = PaymentOperationAnalyzer()
        analysis = analyzer.analyze_member_payment_performance(member_name)

        return {
            "success": True,
            "data": analysis,
            "message": f"Performance analysis completed for member {member_name}",
        }

    except Exception as e:
        frappe.log_error(f"Failed to measure member performance for {member_name}: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def measure_payment_history_performance(member_name: str) -> Dict[str, Any]:
    """
    Quick measurement of payment history loading performance

    Args:
        member_name: Name of the member

    Returns:
        Dict containing payment history performance metrics
    """
    try:
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} not found"}

        results = measure_member_payment_history(member_name)

        return {
            "success": True,
            "data": results,
            "message": f"Payment history performance measured for {member_name}",
        }

    except Exception as e:
        frappe.log_error(f"Failed to measure payment history performance: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def measure_sepa_mandate_performance(member_name: str) -> Dict[str, Any]:
    """
    Measure SEPA mandate operation performance

    Args:
        member_name: Name of the member

    Returns:
        Dict containing SEPA mandate performance metrics
    """
    try:
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} not found"}

        results = measure_sepa_mandate_operations(member_name)

        return {
            "success": True,
            "data": results,
            "message": f"SEPA mandate performance measured for {member_name}",
        }

    except Exception as e:
        frappe.log_error(f"Failed to measure SEPA mandate performance: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def generate_comprehensive_performance_report(sample_size: int = 10) -> Dict[str, Any]:
    """
    Generate comprehensive system performance report

    Args:
        sample_size: Number of members to analyze (default: 10)

    Returns:
        Dict containing comprehensive performance report
    """
    try:
        # Validate sample size
        sample_size = max(1, min(int(sample_size), 50))  # Limit to reasonable range

        report = generate_performance_report(sample_size=sample_size)

        return {
            "success": True,
            "data": report,
            "message": f"Comprehensive performance report generated (sample size: {sample_size})",
        }

    except Exception as e:
        frappe.log_error(f"Failed to generate performance report: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def collect_performance_baselines(sample_size: int = 15) -> Dict[str, Any]:
    """
    Collect current performance baselines

    Args:
        sample_size: Number of members to sample for baselines

    Returns:
        Dict containing baseline measurements
    """
    try:
        sample_size = max(1, min(int(sample_size), 30))

        collector = PerformanceBaselineCollector()
        baseline_report = collector.generate_baseline_report()

        return {
            "success": True,
            "data": baseline_report,
            "message": f"Performance baselines collected (sample size: {sample_size})",
        }

    except Exception as e:
        frappe.log_error(f"Failed to collect performance baselines: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_performance_measurement_history(operation_name: str = None, limit: int = 20) -> Dict[str, Any]:
    """
    Get historical performance measurements

    Args:
        operation_name: Filter by specific operation name (optional)
        limit: Maximum number of results to return

    Returns:
        Dict containing historical measurements
    """
    try:
        limit = max(1, min(int(limit), 100))

        measurements = QueryMeasurementStore.get_results(operation_name, limit)
        aggregated_stats = QueryMeasurementStore.get_aggregated_stats()

        return {
            "success": True,
            "data": {
                "measurements": measurements,
                "aggregated_stats": aggregated_stats,
                "filter_applied": operation_name is not None,
                "operation_name": operation_name,
            },
            "message": f"Retrieved {len(measurements)} performance measurements",
        }

    except Exception as e:
        frappe.log_error(f"Failed to get performance measurement history: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def create_performance_baseline_snapshot(operation_name: str = "member_payment_operations") -> Dict[str, Any]:
    """
    Create performance baseline snapshot for comparison

    Args:
        operation_name: Name for the baseline snapshot

    Returns:
        Dict containing baseline snapshot data
    """
    try:
        baseline = create_performance_baseline(operation_name)

        return {
            "success": True,
            "data": baseline,
            "message": f"Performance baseline snapshot created: {operation_name}",
        }

    except Exception as e:
        frappe.log_error(f"Failed to create performance baseline: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_recent_performance_reports(limit: int = 10) -> Dict[str, Any]:
    """
    Get list of recent performance reports

    Args:
        limit: Maximum number of reports to return

    Returns:
        Dict containing list of recent reports
    """
    try:
        reports = get_recent_reports()

        # Limit results
        if limit:
            limit = max(1, min(int(limit), 20))
            reports = reports[-limit:]

        return {
            "success": True,
            "data": {"reports": reports, "count": len(reports)},
            "message": f"Retrieved {len(reports)} recent performance reports",
        }

    except Exception as e:
        frappe.log_error(f"Failed to get recent performance reports: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def analyze_system_bottlenecks() -> Dict[str, Any]:
    """
    Analyze system-wide performance bottlenecks

    Returns:
        Dict containing bottleneck analysis
    """
    try:
        # Get sample of members for analysis
        members = frappe.get_all("Member", filters={"customer": ("!=", "")}, fields=["name"], limit=15)

        if not members:
            return {"success": False, "error": "No members with customers found for analysis"}

        analyzer = PaymentOperationAnalyzer()
        bottleneck_results = []

        for member in members[:10]:  # Limit to 10 for performance
            try:
                analysis = analyzer.analyze_member_payment_performance(member.name)
                bottleneck_results.append(
                    {
                        "member_name": member.name,
                        "bottlenecks": analysis.get("bottlenecks", []),
                        "n1_patterns": analysis.get("n1_patterns", {}),
                        "optimization_priority": analysis.get("optimization_priority", "low"),
                    }
                )
            except Exception as e:
                frappe.log_error(f"Failed to analyze member {member.name}: {e}")
                continue

        # Aggregate bottleneck analysis
        all_bottlenecks = []
        all_patterns = []
        priorities = []

        for result in bottleneck_results:
            all_bottlenecks.extend(result["bottlenecks"])
            all_patterns.extend(result["n1_patterns"].get("patterns", []))
            priorities.append(result["optimization_priority"])

        # Summarize findings
        bottleneck_types = {}
        for bottleneck in all_bottlenecks:
            btype = bottleneck.get("type", "unknown")
            if btype not in bottleneck_types:
                bottleneck_types[btype] = 0
            bottleneck_types[btype] += 1

        pattern_types = {}
        for pattern in all_patterns:
            ptype = pattern.get("pattern_type", "unknown")
            if ptype not in pattern_types:
                pattern_types[ptype] = 0
            pattern_types[ptype] += 1

        priority_counts = {p: priorities.count(p) for p in ["critical", "high", "medium", "low"]}

        return {
            "success": True,
            "data": {
                "members_analyzed": len(bottleneck_results),
                "total_bottlenecks": len(all_bottlenecks),
                "total_n1_patterns": len(all_patterns),
                "bottleneck_types": bottleneck_types,
                "pattern_types": pattern_types,
                "priority_distribution": priority_counts,
                "detailed_results": bottleneck_results,
                "recommendations": _generate_system_recommendations(
                    bottleneck_types, pattern_types, priority_counts
                ),
            },
            "message": f"System bottleneck analysis completed for {len(bottleneck_results)} members",
        }

    except Exception as e:
        frappe.log_error(f"Failed to analyze system bottlenecks: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_performance_summary() -> Dict[str, Any]:
    """
    Get summary of recent performance measurements

    Returns:
        Dict containing performance summary
    """
    try:
        summary = get_performance_summary()

        return {"success": True, "data": summary, "message": "Performance summary retrieved successfully"}

    except Exception as e:
        frappe.log_error(f"Failed to get performance summary: {e}")
        return {"success": False, "error": str(e)}


def _generate_system_recommendations(
    bottleneck_types: Dict, pattern_types: Dict, priority_counts: Dict
) -> List[Dict[str, Any]]:
    """Generate system-level optimization recommendations"""
    recommendations = []

    # N+1 pattern recommendations
    if pattern_types.get("payment_reference_lookup", 0) > 5:
        recommendations.append(
            {
                "priority": "high",
                "category": "query_optimization",
                "title": "Optimize Payment Reference Lookups",
                "description": f"Found {pattern_types['payment_reference_lookup']} instances of N+1 payment reference lookups",
                "action": "Implement batch loading for payment references using IN queries",
                "expected_impact": "60-80% query reduction for payment operations",
            }
        )

    if pattern_types.get("invoice_lookup", 0) > 3:
        recommendations.append(
            {
                "priority": "high",
                "category": "query_optimization",
                "title": "Optimize Invoice Data Loading",
                "description": f"Found {pattern_types['invoice_lookup']} instances of repetitive invoice queries",
                "action": "Use comprehensive field lists in invoice queries to reduce roundtrips",
                "expected_impact": "40-60% query reduction for invoice processing",
            }
        )

    # High query count bottlenecks
    if bottleneck_types.get("high_query_count", 0) > 3:
        recommendations.append(
            {
                "priority": "critical",
                "category": "architecture",
                "title": "Implement Query Batching",
                "description": "Multiple members showing high query counts",
                "action": "Enable optimized payment history loading with batch queries",
                "expected_impact": "50-70% overall query reduction",
            }
        )

    # Performance priorities
    critical_count = priority_counts.get("critical", 0)
    high_count = priority_counts.get("high", 0)

    if critical_count > 0:
        recommendations.append(
            {
                "priority": "critical",
                "category": "immediate_action",
                "title": "Address Critical Performance Issues",
                "description": f"{critical_count} members have critical performance issues",
                "action": "Immediately implement caching and batch loading optimizations",
                "expected_impact": "Prevent system timeouts and improve user experience",
            }
        )

    elif high_count > 5:
        recommendations.append(
            {
                "priority": "high",
                "category": "performance_tuning",
                "title": "Performance Optimization Sprint",
                "description": f"{high_count} members need performance optimization",
                "action": "Schedule dedicated sprint for performance improvements",
                "expected_impact": "Significant improvement in system responsiveness",
            }
        )

    return recommendations


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def benchmark_current_performance() -> Dict[str, Any]:
    """
    Benchmark current system performance for Phase 1 baseline

    Returns:
        Dict containing comprehensive benchmark results
    """
    try:
        frappe.logger().info("Starting Phase 1 performance benchmark...")

        # Get baseline measurements
        baseline_collector = PerformanceBaselineCollector()
        baseline_report = baseline_collector.generate_baseline_report()

        # Analyze system bottlenecks
        bottleneck_analysis = analyze_system_bottlenecks()

        # Generate comprehensive report
        performance_report = generate_performance_report(sample_size=15)

        # Create benchmark summary
        benchmark_results = {
            "benchmark_timestamp": frappe.utils.now(),
            "phase": "Phase 1 - Baseline Measurement",
            "baseline_metrics": baseline_report.get("data", baseline_report),
            "bottleneck_analysis": bottleneck_analysis.get("data", bottleneck_analysis),
            "comprehensive_report": performance_report.get("data", performance_report),
            "key_findings": _extract_key_findings(baseline_report, bottleneck_analysis, performance_report),
            "optimization_targets": _identify_optimization_targets(baseline_report, bottleneck_analysis),
        }

        # Store benchmark for historical reference
        frappe.cache().set(
            "phase1_performance_benchmark", benchmark_results, expires_in_sec=86400 * 30
        )  # 30 days

        frappe.logger().info("Phase 1 performance benchmark completed successfully")

        return {
            "success": True,
            "data": benchmark_results,
            "message": "Phase 1 performance benchmark completed successfully",
        }

    except Exception as e:
        frappe.log_error(f"Failed to benchmark current performance: {e}")
        return {"success": False, "error": str(e)}


def _extract_key_findings(
    baseline_report: Dict, bottleneck_analysis: Dict, performance_report: Dict
) -> List[str]:
    """Extract key findings from benchmark results"""
    findings = []

    # Extract from baseline
    baseline_data = baseline_report.get("data", baseline_report)
    if "payment_history_baseline" in baseline_data:
        avg_queries = baseline_data["payment_history_baseline"].get("avg_query_count", 0)
        if avg_queries > 50:
            findings.append(
                f"Payment history loading averages {avg_queries:.1f} queries per member (target: <20)"
            )

    # Extract from bottleneck analysis
    bottleneck_data = bottleneck_analysis.get("data", bottleneck_analysis)
    if bottleneck_data and bottleneck_analysis.get("success", True) is not False:
        total_bottlenecks = bottleneck_data.get("total_bottlenecks", 0)
        if total_bottlenecks > 20:
            findings.append(f"Detected {total_bottlenecks} performance bottlenecks across sample members")

        n1_patterns = bottleneck_data.get("total_n1_patterns", 0)
        if n1_patterns > 10:
            findings.append(f"Found {n1_patterns} N+1 query patterns requiring optimization")

    # Extract from performance report
    perf_data = performance_report.get("data", performance_report)
    if "bottleneck_summary" in perf_data:
        health_score = (
            perf_data["bottleneck_summary"].get("system_health_score", {}).get("health_percentage", 100)
        )
        if health_score < 75:
            findings.append(f"System health score: {health_score:.1f}% - requires optimization")

    if not findings:
        findings.append("System performance appears to be within acceptable ranges")

    return findings


def _identify_optimization_targets(baseline_report: Dict, bottleneck_analysis: Dict) -> List[Dict[str, Any]]:
    """Identify specific optimization targets based on benchmark"""
    targets = []

    # Query count targets
    baseline_data = baseline_report.get("data", baseline_report)
    if "payment_history_baseline" in baseline_data:
        current_avg = baseline_data["payment_history_baseline"].get("avg_query_count", 0)
        if current_avg > 20:
            targets.append(
                {
                    "metric": "Average Query Count per Payment History Load",
                    "current_value": current_avg,
                    "target_value": 15,
                    "improvement_needed": f"{((current_avg - 15) / current_avg * 100):.1f}% reduction",
                    "priority": "high",
                }
            )

        current_time = baseline_data["payment_history_baseline"].get("avg_execution_time", 0)
        if current_time > 1.0:
            targets.append(
                {
                    "metric": "Average Execution Time per Payment History Load",
                    "current_value": f"{current_time:.2f}s",
                    "target_value": "0.5s",
                    "improvement_needed": f"{((current_time - 0.5) / current_time * 100):.1f}% reduction",
                    "priority": "medium",
                }
            )

    # N+1 pattern targets
    bottleneck_data = bottleneck_analysis.get("data", bottleneck_analysis)
    if bottleneck_data and bottleneck_analysis.get("success", True) is not False:
        n1_patterns = bottleneck_data.get("total_n1_patterns", 0)
        if n1_patterns > 5:
            targets.append(
                {
                    "metric": "N+1 Query Patterns",
                    "current_value": n1_patterns,
                    "target_value": 0,
                    "improvement_needed": "100% elimination",
                    "priority": "critical",
                }
            )

    return targets


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_measurement_infrastructure() -> Dict[str, Any]:
    """
    Test the measurement infrastructure to ensure it's working correctly

    Returns:
        Dict containing test results
    """
    try:
        # Get a test member
        members = frappe.get_all(
            "Member", filters={"customer": ("!=", "")}, fields=["name", "full_name"], limit=1
        )

        if not members:
            return {"success": False, "error": "No members with customers found for testing"}

        test_member = members[0]

        # Run basic measurement test
        result = measure_member_performance(test_member.name)

        if result.get("success"):
            data = result["data"]
            qp = data.get("query_performance", {})

            return {
                "success": True,
                "test_results": {
                    "test_member": test_member.full_name,
                    "query_count": qp.get("total_queries", 0),
                    "execution_time": qp.get("total_execution_time", 0),
                    "bottlenecks_found": len(data.get("bottlenecks", [])),
                    "optimization_priority": data.get("optimization_priority", "unknown"),
                    "infrastructure_status": "working",
                },
                "message": "Performance measurement infrastructure is working correctly",
            }
        else:
            return {"success": False, "error": f"Measurement failed: {result.get('error', 'Unknown error')}"}

    except Exception as e:
        frappe.log_error(f"Failed to test measurement infrastructure: {e}")
        return {"success": False, "error": str(e)}
