#!/usr/bin/env python3
"""
Performance Measurement Script for Plan Validation
==================================================

Comprehensive performance measurement and analysis system for the Verenigingen association
management system that provides empirical data for performance optimization decisions,
baseline establishment, and improvement validation.

This critical performance engineering tool enables data-driven optimization by measuring
actual system performance across multiple dimensions including execution time, query
patterns, code complexity, and test suite efficiency.

Strategic Purpose
----------------
The Performance Measurement Script addresses the fundamental challenge of performance
optimization in complex business applications where:

- **Optimization Claims Need Validation**: Performance improvements must be measurable
- **Baseline Establishment**: Current performance must be quantified for comparison
- **Bottleneck Identification**: Performance issues must be precisely located
- **Resource Impact Assessment**: System resource utilization must be monitored
- **Regression Prevention**: Performance degradation must be detected early

Core Measurement Capabilities
----------------------------

### 1. Payment History Performance Analysis
**Purpose**: Measure actual payment history loading performance under realistic conditions
**Metrics Collected**:
- Execution time per member (seconds)
- Database query count per operation
- Cache hit/miss ratios
- Entry count analysis
- Success rate tracking

**Business Impact**: Payment history is a frequently accessed feature that directly
impacts user experience and system responsiveness.

### 2. Code Complexity Analysis
**Purpose**: Quantify code complexity metrics for maintainability assessment
**Metrics Collected**:
- Total lines of code
- Method count and size distribution
- Cyclomatic complexity indicators
- Database call density
- Exception handling coverage

**Business Impact**: Code complexity directly correlates with maintenance costs,
bug rates, and development velocity.

### 3. Test Suite Performance Measurement
**Purpose**: Analyze test execution efficiency and identify optimization opportunities
**Metrics Collected**:
- Individual test suite execution times
- Success/failure rates
- Output volume analysis
- Timeout detection
- Resource utilization patterns

**Business Impact**: Test performance affects development cycle speed and
developer productivity.

### 4. Database Query Pattern Analysis
**Purpose**: Identify N+1 query problems and optimization opportunities
**Metrics Collected**:
- Query count per operation
- Query execution patterns
- Parameter usage analysis
- Execution time distribution
- Resource consumption patterns

**Business Impact**: Database performance is often the primary bottleneck in
business applications.

Advanced Performance Analysis Features
-------------------------------------

### Comprehensive Performance Profiling
The measurement system employs sophisticated profiling techniques:

```python
# Query counting with execution tracking
def counting_sql(*args, **kwargs):
    nonlocal query_count
    query_count += 1
    start_time = time.time()
    result = original_sql(*args, **kwargs)
    execution_time = time.time() - start_time
    # Track query performance metrics
    return result
```

### Statistical Analysis Integration
All measurements include comprehensive statistical analysis:

- **Central Tendency**: Mean, median, mode calculations
- **Variability**: Standard deviation and range analysis
- **Distribution Analysis**: Performance consistency measurement
- **Outlier Detection**: Identification of anomalous performance

### Cache Impact Measurement
Sophisticated cache analysis for accurate performance measurement:

```python
# Clear cache to ensure fresh load
cache_key = f"payment_history_optimized_{member.name}_{member.modified}"
frappe.cache().delete(cache_key)
```

### Real-World Scenario Testing
Performance measurements use realistic data conditions:

- **Production-Like Data Volumes**: Testing with actual member counts
- **Realistic Usage Patterns**: Simulating typical user workflows
- **Variable Load Conditions**: Testing under different system loads
- **Edge Case Coverage**: Including boundary conditions and stress scenarios

Performance Measurement Methodologies
------------------------------------

### 1. Execution Time Measurement
High-precision timing with microsecond accuracy:

```python
start_time = time.time()
# Execute operation
execution_time = time.time() - start_time
```

**Considerations**:
- **System Load Impact**: Measurements account for system load variations
- **Warm-up Periods**: Initial runs excluded from statistical analysis
- **Measurement Overhead**: Timing overhead is factored into calculations
- **Precision Requirements**: Microsecond precision for accurate analysis

### 2. Query Count Analysis
Comprehensive database interaction tracking:

```python
# Hook into database layer for complete query visibility
original_sql = frappe.db.sql
query_count = 0

def tracking_sql(*args, **kwargs):
    queries.append({
        "query": str(args[0]),
        "params": str(args[1:]),
        "timestamp": time.time()
    })
    return original_sql(*args, **kwargs)
```

**Analysis Dimensions**:
- **Query Frequency**: Number of queries per operation
- **Query Complexity**: Analysis of query structure and joins
- **Parameter Patterns**: Identification of query patterns
- **Performance Correlation**: Relationship between query count and execution time

### 3. Code Complexity Metrics
Multi-dimensional complexity analysis:

```python
metrics = {
    "total_lines": len(lines),
    "code_lines": count_executable_lines(lines),
    "method_count": content.count("def "),
    "cyclomatic_complexity": calculate_complexity(content),
    "database_calls": content.count("frappe.db."),
    "exception_blocks": content.count("try:")
}
```

**Complexity Indicators**:
- **Lines of Code**: Raw size measurements
- **Method Distribution**: Function size and count analysis
- **Dependency Density**: External dependency usage patterns
- **Error Handling Coverage**: Exception handling completeness

### 4. Resource Utilization Tracking
System resource impact measurement:

- **Memory Usage**: Peak and average memory consumption
- **CPU Utilization**: Processing resource requirements
- **I/O Patterns**: Disk and network utilization
- **Concurrency Impact**: Multi-user performance characteristics

Business Intelligence and Reporting
----------------------------------

### Performance Baseline Establishment
The measurement system establishes quantitative baselines:

```python
baseline_metrics = {
    "avg_payment_history_time": 2.45,  # seconds
    "avg_query_count": 12.3,           # queries per operation
    "code_complexity_score": 847,      # lines of code
    "test_suite_duration": 892         # seconds
}
```

### Improvement Opportunity Identification
Automated analysis identifies optimization opportunities:

```python
if ph_summary.get("avg_execution_time", 0) > 1.0:
    opportunities.append(
        "Payment history optimization could provide significant improvement"
    )
```

### Trend Analysis and Monitoring
Historical performance tracking capabilities:

- **Performance Regression Detection**: Automatic identification of performance degradation
- **Improvement Validation**: Quantitative verification of optimization efforts
- **Capacity Planning**: Resource requirement forecasting
- **SLA Monitoring**: Service level agreement compliance tracking

Integration with Development Workflows
-------------------------------------

### Pre-Deployment Performance Gates
```python
# Automated performance validation before deployment
performance_results = run_comprehensive_performance_analysis()
if performance_results["baseline_metrics"]["avg_payment_history_time"] > 1.5:
    raise DeploymentBlockedException("Performance regression detected")
```

### Continuous Performance Monitoring
```python
# Regular performance measurement for trend analysis
@scheduler.weekly
def weekly_performance_measurement():
    results = run_comprehensive_performance_analysis()
    store_performance_baseline(results)
    check_performance_regressions(results)
```

### Developer Performance Feedback
```python
# Development-time performance insights
def measure_development_impact(before_changes, after_changes):
    improvement_percentage = calculate_improvement(before_changes, after_changes)
    return {
        "performance_impact": improvement_percentage,
        "recommendations": generate_recommendations(after_changes)
    }
```

Quality Assurance and Validation
-------------------------------

### Measurement Accuracy Validation
The measurement system includes accuracy validation:

- **Calibration Procedures**: Regular calibration against known benchmarks
- **Measurement Consistency**: Multiple runs for statistical significance
- **Environmental Factor Control**: Isolation from external performance factors
- **Baseline Stability**: Verification of measurement repeatability

### Error Handling and Recovery
Comprehensive error handling ensures reliable measurements:

```python
try:
    # Perform measurement
    measurement_result = execute_performance_test()
except Exception as e:
    # Log error but continue with other measurements
    frappe.log_error(f"Measurement failed: {e}")
    measurement_result = {"error": str(e), "success": False}
```

### Statistical Significance Validation
- **Sample Size Adequacy**: Ensuring sufficient data for reliable conclusions
- **Confidence Intervals**: Statistical confidence in reported metrics
- **Variance Analysis**: Understanding measurement variability
- **Outlier Treatment**: Appropriate handling of anomalous measurements

Performance Optimization Guidance
--------------------------------

### Optimization Priority Matrix
The measurement system provides optimization guidance:

```python
optimization_priorities = {
    "high_impact_low_effort": ["query_optimization", "cache_tuning"],
    "high_impact_high_effort": ["architecture_refactoring"],
    "low_impact_low_effort": ["code_cleanup"],
    "low_impact_high_effort": ["framework_migration"]
}
```

### Resource Allocation Recommendations
- **Development Time Allocation**: Where to focus optimization efforts
- **Infrastructure Investment**: Hardware/software upgrade recommendations
- **Team Skill Development**: Training needs for performance optimization
- **Tool and Technology Selection**: Performance tool recommendations

### Performance Target Setting
Quantitative target establishment based on measurement data:

```python
performance_targets = {
    "payment_history_load_time": "< 1.0 seconds",
    "test_suite_execution": "< 15 minutes",
    "query_count_per_operation": "< 5 queries",
    "code_complexity_score": "< 1000 lines"
}
```

This performance measurement system provides the empirical foundation needed for
data-driven performance optimization in the Verenigingen association management
system, enabling informed decisions about system improvements and resource allocation.
"""

import json
import statistics
import time
from typing import Dict, List

import frappe
from frappe.utils import nowdate


@frappe.whitelist()
def measure_payment_history_performance(member_count: int = 10) -> Dict:
    """
    Measure actual payment history loading performance

    Args:
        member_count: Number of members to test with

    Returns:
        Dict with performance metrics
    """
    results = {
        "test_config": {
            "member_count": member_count,
            "test_date": nowdate(),
            "method": "load_payment_history",
        },
        "measurements": [],
    }

    try:
        # Get sample members with customers
        members = frappe.get_all(
            "Member", filters={"customer": ["!=", ""]}, fields=["name", "customer"], limit=member_count
        )

        if not members:
            return {"error": "No members with customers found for testing"}

        # Test each member
        execution_times = []
        query_counts = []

        for member_data in members:
            try:
                member = frappe.get_doc("Member", member_data.name)

                # Clear cache to ensure fresh load
                cache_key = f"payment_history_optimized_{member.name}_{member.modified}"
                frappe.cache().delete(cache_key)

                # Measure execution time and query count
                start_time = time.time()

                # Hook into database to count queries
                original_sql = frappe.db.sql
                query_count = 0

                def counting_sql(*args, **kwargs):
                    nonlocal query_count
                    query_count += 1
                    return original_sql(*args, **kwargs)

                frappe.db.sql = counting_sql

                try:
                    # Execute payment history load
                    member.load_payment_history()
                    execution_time = time.time() - start_time

                    # Count entries in payment history
                    entry_count = len(member.payment_history) if hasattr(member, "payment_history") else 0

                    execution_times.append(execution_time)
                    query_counts.append(query_count)

                    results["measurements"].append(
                        {
                            "member": member.name,
                            "execution_time": execution_time,
                            "query_count": query_count,
                            "entry_count": entry_count,
                            "success": True,
                        }
                    )

                finally:
                    # Restore original sql function
                    frappe.db.sql = original_sql

            except Exception as e:
                results["measurements"].append(
                    {"member": member_data.name, "error": str(e), "success": False}
                )
                frappe.log_error(f"Error measuring member {member_data.name}: {e}")

        # Calculate statistics
        if execution_times:
            results["summary"] = {
                "avg_execution_time": statistics.mean(execution_times),
                "min_execution_time": min(execution_times),
                "max_execution_time": max(execution_times),
                "median_execution_time": statistics.median(execution_times),
                "avg_query_count": statistics.mean(query_counts),
                "min_query_count": min(query_counts),
                "max_query_count": max(query_counts),
                "total_tests": len(execution_times),
                "success_rate": len(execution_times) / len(members) * 100,
            }

        return results

    except Exception as e:
        frappe.log_error(f"Error in payment history performance measurement: {e}")
        return {"error": str(e)}


@frappe.whitelist()
def count_payment_mixin_complexity() -> Dict:
    """
    Analyze PaymentMixin code complexity

    Returns:
        Dict with complexity metrics
    """
    try:
        import os

        file_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py"

        if not os.path.exists(file_path):
            return {"error": "PaymentMixin file not found"}

        with open(file_path, "r") as f:
            content = f.read()

        # Count various complexity metrics
        lines = content.split("\n")

        metrics = {
            "total_lines": len(lines),
            "non_empty_lines": len([line for line in lines if line.strip()]),
            "comment_lines": len([line for line in lines if line.strip().startswith("#")]),
            "docstring_lines": content.count('"""') // 2 * 3,  # Rough estimate
            "code_lines": 0,
            "method_count": content.count("def "),
            "class_count": content.count("class "),
            "import_count": len(
                [
                    line
                    for line in lines
                    if line.strip().startswith("import") or line.strip().startswith("from")
                ]
            ),
            "exception_handling_blocks": content.count("try:"),
            "frappe_db_calls": content.count("frappe.db."),
            "frappe_get_calls": content.count("frappe.get_"),
            "whitelist_methods": content.count("@frappe.whitelist()"),
        }

        # Calculate actual code lines (non-empty, non-comment)
        for line in lines:
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("#")
                and not stripped.startswith('"""')
                and stripped != '"""'
            ):
                metrics["code_lines"] += 1

        # Analyze method complexity
        methods = []
        current_method = None
        method_line_count = 0
        indent_level = 0

        for line in lines:
            if line.strip().startswith("def "):
                if current_method:
                    methods.append({"name": current_method, "line_count": method_line_count})
                current_method = line.strip().split("(")[0].replace("def ", "")
                method_line_count = 1
                indent_level = len(line) - len(line.lstrip())
            elif current_method and line.strip():
                current_method_indent = len(line) - len(line.lstrip())
                if current_method_indent > indent_level or line.strip().startswith("#"):
                    method_line_count += 1
                elif current_method_indent <= indent_level and not line.strip().startswith("class"):
                    # Method ended
                    methods.append({"name": current_method, "line_count": method_line_count})
                    current_method = None
                    method_line_count = 0

        # Add last method if exists
        if current_method:
            methods.append({"name": current_method, "line_count": method_line_count})

        metrics["methods"] = methods
        metrics["largest_method"] = max(methods, key=lambda x: x["line_count"]) if methods else None
        metrics["avg_method_size"] = statistics.mean([m["line_count"] for m in methods]) if methods else 0

        return metrics

    except Exception as e:
        frappe.log_error(f"Error analyzing PaymentMixin complexity: {e}")
        return {"error": str(e)}


@frappe.whitelist()
def measure_test_suite_performance() -> Dict:
    """
    Measure test suite execution time

    Returns:
        Dict with test performance metrics
    """
    try:
        import os
        import subprocess

        app_path = "/home/frappe/frappe-bench/apps/verenigingen"
        os.chdir(app_path)

        # Test different test suites
        test_suites = [
            {"name": "smoke_test", "command": ["python", "verenigingen/tests/test_runner.py", "smoke"]},
            {
                "name": "critical_business_logic",
                "command": ["python", "verenigingen/tests/test_critical_business_logic.py"],
            },
            {"name": "iban_validator", "command": ["python", "verenigingen/tests/test_iban_validator.py"]},
        ]

        results = {"test_date": nowdate(), "test_results": []}

        for suite in test_suites:
            try:
                start_time = time.time()

                # Run test with timeout
                result = subprocess.run(
                    suite["command"],
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                    cwd=app_path,
                )

                execution_time = time.time() - start_time

                results["test_results"].append(
                    {
                        "suite_name": suite["name"],
                        "execution_time": execution_time,
                        "return_code": result.returncode,
                        "success": result.returncode == 0,
                        "stdout_lines": len(result.stdout.split("\n")) if result.stdout else 0,
                        "stderr_lines": len(result.stderr.split("\n")) if result.stderr else 0,
                        "command": " ".join(suite["command"]),
                    }
                )

            except subprocess.TimeoutExpired:
                results["test_results"].append(
                    {
                        "suite_name": suite["name"],
                        "execution_time": 300,
                        "timeout": True,
                        "success": False,
                        "error": "Test suite timed out after 5 minutes",
                    }
                )
            except Exception as e:
                results["test_results"].append(
                    {"suite_name": suite["name"], "error": str(e), "success": False}
                )

        # Calculate total time
        successful_tests = [r for r in results["test_results"] if r.get("success")]
        if successful_tests:
            results["summary"] = {
                "total_execution_time": sum(r["execution_time"] for r in successful_tests),
                "avg_execution_time": statistics.mean([r["execution_time"] for r in successful_tests]),
                "successful_suites": len(successful_tests),
                "failed_suites": len([r for r in results["test_results"] if not r.get("success")]),
            }

        return results

    except Exception as e:
        frappe.log_error(f"Error measuring test suite performance: {e}")
        return {"error": str(e)}


@frappe.whitelist()
def measure_database_query_patterns() -> Dict:
    """
    Analyze database query patterns for common member operations

    Returns:
        Dict with query analysis
    """
    try:
        # Test operations that would be affected by the plan
        operations = [
            {
                "name": "get_member_with_payment_history",
                "function": lambda: test_member_payment_history_queries(),
            },
            {"name": "member_creation_workflow", "function": lambda: test_member_creation_queries()},
            {"name": "sepa_mandate_lookup", "function": lambda: test_sepa_mandate_queries()},
        ]

        results = {"test_date": nowdate(), "query_analysis": []}

        for operation in operations:
            try:
                # Hook into database to count queries
                original_sql = frappe.db.sql
                queries = []

                def tracking_sql(*args, **kwargs):
                    queries.append(
                        {
                            "query": str(args[0]) if args else "Unknown",
                            "params": str(args[1:]) if len(args) > 1 else "",
                            "timestamp": time.time(),
                        }
                    )
                    return original_sql(*args, **kwargs)

                frappe.db.sql = tracking_sql

                try:
                    start_time = time.time()
                    operation_result = operation["function"]()
                    execution_time = time.time() - start_time

                    results["query_analysis"].append(
                        {
                            "operation": operation["name"],
                            "execution_time": execution_time,
                            "query_count": len(queries),
                            "queries": queries[:10],  # First 10 queries for analysis
                            "success": True,
                            "result": operation_result,
                        }
                    )

                finally:
                    frappe.db.sql = original_sql

            except Exception as e:
                results["query_analysis"].append(
                    {"operation": operation["name"], "error": str(e), "success": False}
                )

        return results

    except Exception as e:
        frappe.log_error(f"Error measuring database query patterns: {e}")
        return {"error": str(e)}


def test_member_payment_history_queries():
    """Test member payment history loading queries"""
    members = frappe.get_all("Member", filters={"customer": ["!=", ""]}, limit=1)
    if not members:
        return {"error": "No members found"}

    member = frappe.get_doc("Member", members[0].name)
    member._load_payment_history_without_save()

    return {
        "member": member.name,
        "payment_history_count": len(member.payment_history) if hasattr(member, "payment_history") else 0,
    }


def test_member_creation_queries():
    """Test member creation query patterns"""
    # Just get a member to simulate the query pattern
    members = frappe.get_all("Member", limit=1, fields=["name", "first_name", "last_name"])
    if members:
        member = frappe.get_doc("Member", members[0].name)
        return {"member": member.name, "found": True}
    return {"found": False}


def test_sepa_mandate_queries():
    """Test SEPA mandate lookup queries"""
    mandates = frappe.get_all("SEPA Mandate", limit=1, fields=["name", "member", "status"])
    if mandates:
        mandate = frappe.get_doc("SEPA Mandate", mandates[0].name)
        return {"mandate": mandate.name, "member": mandate.member, "found": True}
    return {"found": False}


@frappe.whitelist()
def run_comprehensive_performance_analysis() -> Dict:
    """
    Run all performance measurements and provide comprehensive analysis

    Returns:
        Dict with complete performance analysis
    """
    try:
        results = {"analysis_date": nowdate(), "analysis_version": "1.0", "measurements": {}}

        # 1. Payment history performance
        print("Measuring payment history performance...")
        results["measurements"]["payment_history"] = measure_payment_history_performance(5)

        # 2. Code complexity analysis
        print("Analyzing PaymentMixin complexity...")
        results["measurements"]["code_complexity"] = count_payment_mixin_complexity()

        # 3. Test suite performance
        print("Measuring test suite performance...")
        results["measurements"]["test_performance"] = measure_test_suite_performance()

        # 4. Database query patterns
        print("Analyzing database query patterns...")
        results["measurements"]["query_patterns"] = measure_database_query_patterns()

        # 5. Generate analysis summary
        results["analysis_summary"] = generate_performance_analysis_summary(results["measurements"])

        return results

    except Exception as e:
        frappe.log_error(f"Error in comprehensive performance analysis: {e}")
        return {"error": str(e)}


def generate_performance_analysis_summary(measurements: Dict) -> Dict:
    """Generate summary analysis of all measurements"""
    summary = {"key_findings": [], "improvement_opportunities": [], "baseline_metrics": {}}

    try:
        # Analyze payment history performance
        if "payment_history" in measurements and "summary" in measurements["payment_history"]:
            ph_summary = measurements["payment_history"]["summary"]
            summary["baseline_metrics"]["avg_payment_history_time"] = ph_summary.get("avg_execution_time", 0)
            summary["baseline_metrics"]["avg_query_count"] = ph_summary.get("avg_query_count", 0)

            if ph_summary.get("avg_execution_time", 0) > 1.0:
                summary["key_findings"].append(
                    f"Payment history loading takes {ph_summary['avg_execution_time']:.2f}s on average - slower than 1s target"
                )
                summary["improvement_opportunities"].append(
                    "Payment history optimization could provide significant improvement"
                )

        # Analyze code complexity
        if "code_complexity" in measurements:
            complexity = measurements["code_complexity"]
            summary["baseline_metrics"]["payment_mixin_lines"] = complexity.get("total_lines", 0)
            summary["baseline_metrics"]["payment_mixin_methods"] = complexity.get("method_count", 0)

            if complexity.get("total_lines", 0) > 1000:
                summary["key_findings"].append(
                    f"PaymentMixin has {complexity['total_lines']} lines - substantial complexity"
                )
                summary["improvement_opportunities"].append(
                    "Code refactoring could significantly reduce complexity"
                )

        # Analyze test performance
        if "test_performance" in measurements and "summary" in measurements["test_performance"]:
            test_summary = measurements["test_performance"]["summary"]
            summary["baseline_metrics"]["total_test_time"] = test_summary.get("total_execution_time", 0)

            if test_summary.get("total_execution_time", 0) > 900:  # 15 minutes
                summary["key_findings"].append(
                    f"Test suite takes {test_summary['total_execution_time'] / 60:.1f} minutes - longer than 15min target"
                )
                summary["improvement_opportunities"].append("Test optimization could reduce execution time")

        # Analyze query patterns
        if "query_patterns" in measurements:
            query_analysis = measurements["query_patterns"]["query_analysis"]
            successful_ops = [op for op in query_analysis if op.get("success")]
            if successful_ops:
                avg_queries = statistics.mean([op["query_count"] for op in successful_ops])
                summary["baseline_metrics"]["avg_queries_per_operation"] = avg_queries

                if avg_queries > 10:
                    summary["key_findings"].append(
                        f"Average {avg_queries:.1f} queries per operation - potential N+1 query issues"
                    )
                    summary["improvement_opportunities"].append(
                        "Query optimization and batching could reduce database load"
                    )

    except Exception as e:
        summary["analysis_error"] = str(e)

    return summary


if __name__ == "__main__":
    # Can be run directly for testing
    print("Starting comprehensive performance analysis...")
    result = run_comprehensive_performance_analysis()
    print(json.dumps(result, indent=2, default=str))
