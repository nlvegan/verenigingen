#!/usr/bin/env python3
"""
Performance Measurement Script for Plan Validation
Measures actual current system performance to validate improvement claims
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
