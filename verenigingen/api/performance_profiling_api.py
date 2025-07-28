#!/usr/bin/env python3
"""
Performance Profiling API
Phase 2 Implementation - Comprehensive Architectural Refactoring Plan v2.0

This API provides whitelisted methods to run performance profiling and establish baselines
from within the Frappe environment.
"""

import cProfile
import io
import json
import pstats
import time
from datetime import datetime
from typing import Any, Dict, List

import frappe


@frappe.whitelist()
def establish_performance_baselines():
    """Create baseline performance measurements for all critical operations"""
    frappe.only_for(["System Manager", "Verenigingen Administrator"])

    try:
        baselines = {
            "timestamp": datetime.now().isoformat(),
            "environment": get_environment_info(),
            "measurements": {},
        }

        # 1. Payment History Loading Performance
        frappe.publish_realtime(
            "performance_profiling",
            {"message": "Measuring Payment History Loading Performance...", "progress": 10},
        )
        baselines["measurements"]["payment_history_load"] = profile_payment_history_loading()

        # 2. Member Search Performance
        frappe.publish_realtime(
            "performance_profiling", {"message": "Measuring Member Search Performance...", "progress": 30}
        )
        baselines["measurements"]["member_search"] = profile_member_search()

        # 3. API Response Times
        frappe.publish_realtime(
            "performance_profiling", {"message": "Measuring API Response Times...", "progress": 50}
        )
        baselines["measurements"]["api_response_times"] = profile_api_endpoints()

        # 4. Database Query Performance
        frappe.publish_realtime(
            "performance_profiling", {"message": "Measuring Database Query Performance...", "progress": 70}
        )
        baselines["measurements"]["database_queries"] = profile_database_queries()

        # 5. Background Job Performance
        frappe.publish_realtime(
            "performance_profiling", {"message": "Measuring Background Job Performance...", "progress": 85}
        )
        baselines["measurements"]["background_jobs"] = profile_background_jobs()

        # 6. Memory Usage
        frappe.publish_realtime(
            "performance_profiling", {"message": "Measuring Memory Usage...", "progress": 95}
        )
        baselines["measurements"]["memory_usage"] = profile_memory_usage()

        # Save baselines
        save_baselines(baselines)

        # Generate summary report
        report_summary = generate_baseline_summary(baselines)

        frappe.publish_realtime(
            "performance_profiling",
            {
                "message": "Performance baseline establishment completed successfully!",
                "progress": 100,
                "completed": True,
            },
        )

        return {
            "success": True,
            "baselines": baselines,
            "summary": report_summary,
            "file_saved": "/home/frappe/frappe-bench/apps/verenigingen/performance_baselines.json",
        }

    except Exception as e:
        frappe.log_error(f"Performance baseline establishment failed: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def run_comprehensive_performance_profiling():
    """Run comprehensive performance profiling to identify bottlenecks"""
    frappe.only_for(["System Manager", "Verenigingen Administrator"])

    try:
        frappe.publish_realtime(
            "performance_profiling",
            {"message": "Starting comprehensive performance profiling...", "progress": 5},
        )

        profiling_results = {
            "timestamp": datetime.now().isoformat(),
            "operations_profiled": {},
            "bottlenecks_identified": [],
            "optimization_recommendations": [],
        }

        # Profile different payment operation scenarios
        operations = {
            "payment_batch_processing": profile_payment_batch_processing,
            "member_payment_history_generation": profile_member_payment_history_generation,
            "sepa_mandate_processing": profile_sepa_mandate_processing,
            "invoice_generation_batch": profile_invoice_generation_batch,
            "payment_reconciliation": profile_payment_reconciliation,
        }

        progress_step = 80 / len(operations)
        current_progress = 10

        for operation_name, operation_function in operations.items():
            frappe.publish_realtime(
                "performance_profiling",
                {"message": f"Profiling {operation_name.replace('_', ' ')}...", "progress": current_progress},
            )

            try:
                profiling_results["operations_profiled"][operation_name] = operation_function()
            except Exception as e:
                profiling_results["operations_profiled"][operation_name] = {"error": f"Profiling failed: {e}"}

            current_progress += progress_step

        # Analyze bottlenecks across all operations
        frappe.publish_realtime(
            "performance_profiling", {"message": "Analyzing performance bottlenecks...", "progress": 90}
        )
        profiling_results["bottlenecks_identified"] = identify_performance_bottlenecks(
            profiling_results["operations_profiled"]
        )

        # Generate optimization recommendations
        frappe.publish_realtime(
            "performance_profiling", {"message": "Generating optimization recommendations...", "progress": 95}
        )
        profiling_results["optimization_recommendations"] = generate_optimization_recommendations(
            profiling_results["bottlenecks_identified"]
        )

        # Save profiling results
        save_profiling_results(profiling_results)

        frappe.publish_realtime(
            "performance_profiling",
            {"message": "Performance profiling completed successfully!", "progress": 100, "completed": True},
        )

        return {
            "success": True,
            "results": profiling_results,
            "bottlenecks_count": len(profiling_results["bottlenecks_identified"]),
            "recommendations_count": len(profiling_results["optimization_recommendations"]),
            "file_saved": "/home/frappe/frappe-bench/apps/verenigingen/performance_profiling_results.json",
        }

    except Exception as e:
        frappe.log_error(f"Performance profiling failed: {e}")
        return {"success": False, "error": str(e)}


def get_environment_info() -> Dict[str, Any]:
    """Get current environment information"""
    return {
        "frappe_version": frappe.__version__,
        "site": frappe.local.site,
        "database": frappe.conf.db_type or "mariadb",
        "workers": frappe.conf.workers or 1,
    }


def profile_payment_history_loading() -> Dict[str, Any]:
    """Profile payment history loading performance"""
    start_time = time.time()

    results = {
        "total_members_tested": 0,
        "total_time": 0,
        "time_per_member": 0,
        "query_count": 0,
        "queries_per_member": 0,
        "profile_data": [],
    }

    try:
        # Get sample of active members with payment history
        members = frappe.get_all(
            "Member",
            filters={"status": "Active", "payment_method": ["in", ["SEPA Direct Debit", "Bank Transfer"]]},
            fields=["name"],
            limit=20,  # Reduced for faster profiling
        )

        results["total_members_tested"] = len(members)

        with cProfile.Profile() as profiler:
            for member in members:
                member_start = time.time()

                # Load member document
                member_doc = frappe.get_doc("Member", member.name)

                # Trigger payment history loading if method exists
                if hasattr(member_doc, "load_payment_history"):
                    member_doc.load_payment_history()
                elif hasattr(member_doc, "get_payment_history"):
                    member_doc.get_payment_history()
                elif hasattr(member_doc, "payment_history"):
                    # Access payment history property
                    _ = member_doc.payment_history

                member_time = time.time() - member_start
                results["profile_data"].append({"member": member.name, "time": member_time})

        # Calculate metrics
        end_time = time.time()
        results["total_time"] = end_time - start_time
        results["time_per_member"] = results["total_time"] / max(results["total_members_tested"], 1)

        # Get profiler stats
        stats = pstats.Stats(profiler)
        stats.sort_stats("tottime")

        # Extract top functions
        results["top_functions"] = extract_top_functions(stats, 10)

    except Exception as e:
        results["error"] = str(e)

    return results


def profile_member_search() -> Dict[str, Any]:
    """Profile member search performance"""
    results = {"search_queries": [], "average_time": 0, "total_queries": 0}

    search_terms = ["john", "amsterdam", "test@example.com", "active", "2025"]

    total_time = 0

    for term in search_terms:
        start_time = time.time()

        try:
            # Simulate member search
            search_results = frappe.get_all(
                "Member",
                filters=[
                    ["Member", "full_name", "like", f"%{term}%"],
                ],
                fields=["name", "full_name", "email", "member_id", "status"],
                limit=20,
            )

            end_time = time.time()
            search_time = end_time - start_time
            total_time += search_time

            results["search_queries"].append(
                {"term": term, "time": search_time, "result_count": len(search_results)}
            )

        except Exception as e:
            results["search_queries"].append({"term": term, "error": str(e)})

    results["total_queries"] = len(search_terms)
    results["average_time"] = total_time / max(len(search_terms), 1)

    return results


def profile_api_endpoints() -> Dict[str, Any]:
    """Profile critical API endpoint response times"""
    results = {"endpoints": [], "average_response_time": 0}

    # Define critical endpoints to test
    critical_endpoints = [
        {
            "name": "get_member_list",
            "module": "verenigingen.api.member_management",
            "method": "get_member_list",
            "args": {"limit": 20},
        },
        {
            "name": "get_payment_dashboard_data",
            "module": "verenigingen.api.payment_dashboard",
            "method": "get_payment_dashboard_data",
            "args": {},
        },
    ]

    total_time = 0
    successful_tests = 0

    for endpoint in critical_endpoints:
        start_time = time.time()

        try:
            # Try to call the API endpoint
            if frappe.get_attr(f"{endpoint['module']}.{endpoint['method']}"):
                frappe.call(f"{endpoint['module']}.{endpoint['method']}", **endpoint.get("args", {}))

                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # Convert to ms
                total_time += response_time
                successful_tests += 1

                results["endpoints"].append(
                    {"name": endpoint["name"], "response_time_ms": response_time, "status": "success"}
                )
            else:
                results["endpoints"].append(
                    {"name": endpoint["name"], "status": "not_found", "error": "Endpoint not found"}
                )

        except Exception as e:
            results["endpoints"].append({"name": endpoint["name"], "status": "error", "error": str(e)})

    if successful_tests > 0:
        results["average_response_time"] = total_time / successful_tests

    return results


def profile_database_queries() -> Dict[str, Any]:
    """Profile database query performance"""
    results = {"query_patterns": [], "slow_queries": []}

    # Common query patterns to test
    query_patterns = [
        {
            "name": "active_members_count",
            "query": """
                SELECT COUNT(*) as count
                FROM `tabMember`
                WHERE status = 'Active'
            """,
        },
        {
            "name": "unpaid_invoices",
            "query": """
                SELECT COUNT(*) as count
                FROM `tabSales Invoice`
                WHERE status = 'Unpaid'
                AND docstatus = 1
            """,
        },
        {
            "name": "member_with_mandates",
            "query": """
                SELECT m.name, m.full_name, sm.iban
                FROM `tabMember` m
                LEFT JOIN `tabSEPA Mandate` sm ON sm.member = m.name
                WHERE m.status = 'Active'
                AND sm.status = 'Active'
                LIMIT 10
            """,
        },
    ]

    for pattern in query_patterns:
        start_time = time.time()

        try:
            result = frappe.db.sql(pattern["query"], as_dict=True)
            end_time = time.time()

            query_time = (end_time - start_time) * 1000  # Convert to ms

            results["query_patterns"].append(
                {
                    "name": pattern["name"],
                    "time_ms": query_time,
                    "row_count": len(result) if isinstance(result, list) else 1,
                }
            )

            # Mark as slow query if > 100ms
            if query_time > 100:
                results["slow_queries"].append(pattern["name"])

        except Exception as e:
            results["query_patterns"].append({"name": pattern["name"], "error": str(e)})

    return results


def profile_background_jobs() -> Dict[str, Any]:
    """Profile background job performance"""
    results = {"job_types": [], "queue_length": 0}

    # Check current queue lengths
    try:
        from frappe.utils.background_jobs import get_jobs

        queues = ["default", "short", "long"]
        total_jobs = 0

        for queue in queues:
            jobs = len(get_jobs(queue=queue))
            total_jobs += jobs
            results[f"{queue}_queue_length"] = jobs

        results["queue_length"] = total_jobs

    except Exception as e:
        results["error"] = str(e)

    return results


def profile_memory_usage() -> Dict[str, Any]:
    """Profile current memory usage"""
    results = {}

    try:
        import psutil

        process = psutil.Process()
        memory_info = process.memory_info()

        results["rss_mb"] = memory_info.rss / 1024 / 1024  # Resident Set Size in MB
        results["vms_mb"] = memory_info.vms / 1024 / 1024  # Virtual Memory Size in MB
        results["percent"] = process.memory_percent()

        # System memory
        system_memory = psutil.virtual_memory()
        results["system_total_mb"] = system_memory.total / 1024 / 1024
        results["system_available_mb"] = system_memory.available / 1024 / 1024
        results["system_percent"] = system_memory.percent

    except Exception as e:
        results["error"] = str(e)

    return results


def extract_top_functions(stats: pstats.Stats, limit: int = 10) -> List[Dict[str, Any]]:
    """Extract top functions from profiler stats"""
    top_functions = []

    try:
        for func_name, (call_count, total_calls, total_time, cumulative_time, callers) in stats.stats.items():
            if total_time > 0.001:  # Only include functions taking more than 1ms
                top_functions.append(
                    {
                        "function": f"{func_name[0]}:{func_name[1]}({func_name[2]})",
                        "total_time_seconds": round(total_time, 4),
                        "cumulative_time_seconds": round(cumulative_time, 4),
                        "call_count": total_calls,
                        "time_per_call_ms": round((total_time / total_calls) * 1000, 2)
                        if total_calls > 0
                        else 0,
                    }
                )
    except:
        # Fallback if stats structure is different
        pass

    # Sort by total time and take top functions
    top_functions.sort(key=lambda x: x["total_time_seconds"], reverse=True)
    return top_functions[:limit]


def save_baselines(baselines: Dict[str, Any]):
    """Save baselines to JSON file"""
    filename = "/home/frappe/frappe-bench/apps/verenigingen/performance_baselines.json"

    with open(filename, "w") as f:
        json.dump(baselines, f, indent=2, default=str)


def generate_baseline_summary(baselines: Dict[str, Any]) -> Dict[str, Any]:
    """Generate baseline summary for easy consumption"""
    measurements = baselines.get("measurements", {})

    summary = {"timestamp": baselines.get("timestamp"), "key_metrics": {}}

    # Payment History Performance
    if "payment_history_load" in measurements:
        ph = measurements["payment_history_load"]
        summary["key_metrics"]["payment_history_time_per_member"] = ph.get("time_per_member", 0)
        summary["key_metrics"]["payment_history_queries_per_member"] = ph.get("queries_per_member", 0)

    # API Performance
    if "api_response_times" in measurements:
        api = measurements["api_response_times"]
        summary["key_metrics"]["api_average_response_time_ms"] = api.get("average_response_time", 0)

    # Database Performance
    if "database_queries" in measurements:
        db = measurements["database_queries"]
        summary["key_metrics"]["slow_queries_count"] = len(db.get("slow_queries", []))

    # Memory Usage
    if "memory_usage" in measurements:
        mem = measurements["memory_usage"]
        summary["key_metrics"]["memory_usage_mb"] = mem.get("rss_mb", 0)
        summary["key_metrics"]["system_memory_percent"] = mem.get("system_percent", 0)

    return summary


# Additional profiling functions for comprehensive analysis
def profile_payment_batch_processing() -> Dict[str, Any]:
    """Profile payment batch processing operations"""
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()

            # Simulate payment batch processing
            processed_count = process_payment_batch_simulation(batch_size=50)

            end_time = time.time()
            total_time = end_time - start_time

        # Analyze profiler results
        analysis = analyze_profiler_results(profiler, "payment_batch_processing")
        analysis["total_execution_time"] = round(total_time, 3)
        analysis["operations_per_second"] = round(processed_count / total_time, 2) if total_time > 0 else 0

        return analysis

    except Exception as e:
        return {"error": f"Payment batch profiling failed: {e}"}


def profile_member_payment_history_generation() -> Dict[str, Any]:
    """Profile member payment history generation"""
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()

            # Simulate payment history generation for multiple members
            generated_count = generate_member_payment_history_simulation(member_count=25)

            end_time = time.time()
            total_time = end_time - start_time

        analysis = analyze_profiler_results(profiler, "member_payment_history_generation")
        analysis["total_execution_time"] = round(total_time, 3)
        analysis["members_per_second"] = round(generated_count / total_time, 2) if total_time > 0 else 0

        return analysis

    except Exception as e:
        return {"error": f"Payment history profiling failed: {e}"}


def profile_sepa_mandate_processing() -> Dict[str, Any]:
    """Profile SEPA mandate processing operations"""
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()

            # Simulate SEPA mandate processing
            processed_count = process_sepa_mandates_simulation(mandate_count=15)

            end_time = time.time()
            total_time = end_time - start_time

        analysis = analyze_profiler_results(profiler, "sepa_mandate_processing")
        analysis["total_execution_time"] = round(total_time, 3)
        analysis["mandates_per_second"] = round(processed_count / total_time, 2) if total_time > 0 else 0

        return analysis

    except Exception as e:
        return {"error": f"SEPA mandate profiling failed: {e}"}


def profile_invoice_generation_batch() -> Dict[str, Any]:
    """Profile batch invoice generation operations"""
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()

            # Simulate batch invoice generation
            generated_count = generate_invoices_batch_simulation(invoice_count=20)

            end_time = time.time()
            total_time = end_time - start_time

        analysis = analyze_profiler_results(profiler, "invoice_generation_batch")
        analysis["total_execution_time"] = round(total_time, 3)
        analysis["invoices_per_second"] = round(generated_count / total_time, 2) if total_time > 0 else 0

        return analysis

    except Exception as e:
        return {"error": f"Invoice generation profiling failed: {e}"}


def profile_payment_reconciliation() -> Dict[str, Any]:
    """Profile payment reconciliation operations"""
    try:
        with cProfile.Profile() as profiler:
            start_time = time.time()

            # Simulate payment reconciliation
            reconciled_count = reconcile_payments_simulation(payment_count=30)

            end_time = time.time()
            total_time = end_time - start_time

        analysis = analyze_profiler_results(profiler, "payment_reconciliation")
        analysis["total_execution_time"] = round(total_time, 3)
        analysis["payments_per_second"] = round(reconciled_count / total_time, 2) if total_time > 0 else 0

        return analysis

    except Exception as e:
        return {"error": f"Payment reconciliation profiling failed: {e}"}


def process_payment_batch_simulation(batch_size: int):
    """Simulate payment batch processing"""
    # Get sample payment entries
    payments = frappe.get_all(
        "Payment Entry",
        fields=["name", "party", "paid_amount", "posting_date"],
        limit=batch_size,
        order_by="creation desc",
    )

    processed_count = 0

    for payment in payments:
        try:
            # Simulate payment processing operations
            payment_doc = frappe.get_doc("Payment Entry", payment.name)

            # Simulate related data lookups
            if payment_doc.party:
                # Look up member information
                _ = frappe.get_all(
                    "Member",
                    filters={"customer": payment_doc.party},
                    fields=["name", "full_name", "chapter"],
                    limit=1,
                )

                # Look up related invoices
                _ = frappe.get_all(
                    "Sales Invoice",
                    filters={"customer": payment_doc.party, "status": ["!=", "Cancelled"]},
                    fields=["name", "grand_total", "outstanding_amount"],
                    limit=10,
                )

                # Simulate payment entry reference processing
                _ = frappe.get_all(
                    "Payment Entry Reference",
                    filters={"parent": payment_doc.name},
                    fields=["reference_name", "allocated_amount"],
                )

            processed_count += 1

        except Exception:
            continue  # Skip problematic records

    return processed_count


def generate_member_payment_history_simulation(member_count: int):
    """Simulate member payment history generation"""
    # Get sample members
    members = frappe.get_all(
        "Member", fields=["name", "customer", "full_name"], limit=member_count, filters={"status": "Active"}
    )

    histories_generated = 0

    for member in members:
        try:
            if not member.customer:
                continue

            # Simulate payment history generation
            # 1. Get all invoices for the member
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer},
                fields=["name", "grand_total", "outstanding_amount", "posting_date", "due_date"],
                order_by="posting_date desc",
            )

            # 2. Get all payment entries
            payments = frappe.get_all(
                "Payment Entry",
                filters={"party": member.customer},
                fields=["name", "paid_amount", "posting_date"],
                order_by="posting_date desc",
            )

            # 3. Get SEPA mandates
            sepa_mandates = frappe.get_all(
                "SEPA Mandate", filters={"member": member.name}, fields=["name", "iban", "status", "creation"]
            )

            # 4. Simulate history compilation
            _ = {
                "member": member.name,
                "invoices": len(invoices),
                "payments": len(payments),
                "mandates": len(sepa_mandates),
                "total_invoiced": sum(inv.grand_total for inv in invoices if inv.grand_total),
                "total_paid": sum(pay.paid_amount for pay in payments if pay.paid_amount),
            }

            histories_generated += 1

        except Exception:
            continue

    return histories_generated


def process_sepa_mandates_simulation(mandate_count: int):
    """Simulate SEPA mandate processing"""
    # Get sample SEPA mandates
    mandates = frappe.get_all(
        "SEPA Mandate",
        fields=["name", "member", "iban", "status"],
        limit=mandate_count,
        order_by="creation desc",
    )

    processed_mandates = 0

    for mandate in mandates:
        try:
            # Simulate mandate processing operations
            mandate_doc = frappe.get_doc("SEPA Mandate", mandate.name)

            # Get member information
            if mandate_doc.member:
                member_doc = frappe.get_doc("Member", mandate_doc.member)

                # Get related dues schedules
                _ = frappe.get_all(
                    "Membership Dues Schedule",
                    filters={"member": mandate_doc.member},
                    fields=["name", "dues_rate", "billing_frequency", "status"],
                )

                # Simulate validation operations
                if mandate_doc.iban:
                    # Validate IBAN format (simulation)
                    _ = len(mandate_doc.iban) >= 15

                # Check for active invoices
                if member_doc.customer:
                    _ = frappe.get_all(
                        "Sales Invoice",
                        filters={
                            "customer": member_doc.customer,
                            "status": ["!=", "Paid"],
                            "outstanding_amount": [">", 0],
                        },
                        fields=["name", "outstanding_amount"],
                    )

            processed_mandates += 1

        except Exception:
            continue

    return processed_mandates


def generate_invoices_batch_simulation(invoice_count: int):
    """Simulate batch invoice generation"""
    # Get sample membership dues schedules
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        fields=["name", "member", "dues_rate", "billing_frequency"],
        limit=invoice_count,
        filters={"status": "Active"},
    )

    invoices_generated = 0

    for schedule in schedules:
        try:
            # Simulate invoice generation process
            schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)

            # Get member information
            if schedule_doc.member:
                member_doc = frappe.get_doc("Member", schedule_doc.member)

                # Check if member has customer
                if not member_doc.customer:
                    continue

                # Simulate invoice creation data preparation
                invoice_data = {
                    "customer": member_doc.customer,
                    "posting_date": frappe.utils.today(),
                    "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
                    "items": [
                        {
                            "item_code": "Membership Fee",  # Assuming this item exists
                            "rate": schedule_doc.dues_rate or 0,
                            "qty": 1,
                        }
                    ],
                }

                # Simulate validation checks
                if invoice_data["items"][0]["rate"] > 0:
                    # Check for existing unpaid invoices
                    _ = frappe.get_all(
                        "Sales Invoice",
                        filters={"customer": invoice_data["customer"], "status": ["!=", "Paid"]},
                        fields=["name"],
                    )

                    invoices_generated += 1

        except Exception:
            continue

    return invoices_generated


def reconcile_payments_simulation(payment_count: int):
    """Simulate payment reconciliation operations"""
    # Get sample payment entries
    payments = frappe.get_all(
        "Payment Entry",
        fields=["name", "party", "paid_amount", "unallocated_amount"],
        limit=payment_count,
        filters={"docstatus": 1},
    )

    reconciled_payments = 0

    for payment in payments:
        try:
            # Simulate reconciliation process
            payment_doc = frappe.get_doc("Payment Entry", payment.name)

            if payment_doc.party:
                # Get outstanding invoices for this party
                outstanding_invoices = frappe.get_all(
                    "Sales Invoice",
                    filters={
                        "customer": payment_doc.party,
                        "outstanding_amount": [">", 0],
                        "status": ["!=", "Cancelled"],
                    },
                    fields=["name", "outstanding_amount", "posting_date"],
                    order_by="posting_date asc",
                )

                # Get existing payment entry references
                existing_refs = frappe.get_all(
                    "Payment Entry Reference",
                    filters={"parent": payment_doc.name},
                    fields=["reference_name", "allocated_amount"],
                )

                # Simulate allocation logic
                total_allocated = sum(ref.allocated_amount for ref in existing_refs if ref.allocated_amount)
                remaining_amount = payment_doc.paid_amount - total_allocated

                # Simulate matching logic
                if remaining_amount > 0 and outstanding_invoices:
                    for invoice in outstanding_invoices:
                        if remaining_amount <= 0:
                            break

                        allocation_amount = min(remaining_amount, invoice.outstanding_amount)
                        remaining_amount -= allocation_amount

                reconciled_payments += 1

        except Exception:
            continue

    return reconciled_payments


def analyze_profiler_results(profiler: cProfile.Profile, operation_name: str) -> Dict[str, Any]:
    """Analyze cProfile results and extract key metrics"""

    # Capture profiler output
    stats_stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stats_stream)
    stats.sort_stats("tottime")

    # Get top time-consuming functions
    top_functions = []
    for func_name, (call_count, total_calls, total_time, cumulative_time, callers) in stats.stats.items():
        if total_time > 0.001:  # Only include functions taking more than 1ms
            top_functions.append(
                {
                    "function": f"{func_name[0]}:{func_name[1]}({func_name[2]})",
                    "total_time_seconds": round(total_time, 4),
                    "cumulative_time_seconds": round(cumulative_time, 4),
                    "call_count": total_calls,
                    "time_per_call_ms": round((total_time / total_calls) * 1000, 2) if total_calls > 0 else 0,
                }
            )

    # Sort by total time and take top 20
    top_functions.sort(key=lambda x: x["total_time_seconds"], reverse=True)
    top_functions = top_functions[:20]

    # Calculate summary statistics
    total_function_time = sum(func["total_time_seconds"] for func in top_functions)
    database_time = sum(
        func["total_time_seconds"]
        for func in top_functions
        if "sql" in func["function"].lower() or "db" in func["function"].lower()
    )

    analysis = {
        "operation_name": operation_name,
        "total_functions_analyzed": len(stats.stats),
        "top_time_consuming_functions": top_functions,
        "total_function_time_seconds": round(total_function_time, 3),
        "database_time_seconds": round(database_time, 3),
        "database_time_percentage": round((database_time / total_function_time) * 100, 1)
        if total_function_time > 0
        else 0,
        "hotspots_identified": identify_function_hotspots(top_functions),
    }

    return analysis


def identify_function_hotspots(top_functions: List[Dict]) -> List[Dict]:
    """Identify performance hotspots from function analysis"""

    hotspots = []

    for func in top_functions[:10]:  # Focus on top 10 functions
        hotspot_type = "UNKNOWN"

        func_name = func["function"].lower()

        if any(keyword in func_name for keyword in ["sql", "db", "query", "execute"]):
            hotspot_type = "DATABASE"
        elif any(keyword in func_name for keyword in ["get_doc", "get_all", "get_value"]):
            hotspot_type = "FRAPPE_ORM"
        elif any(keyword in func_name for keyword in ["load", "fetch", "retrieve"]):
            hotspot_type = "DATA_LOADING"
        elif any(keyword in func_name for keyword in ["validate", "check", "verify"]):
            hotspot_type = "VALIDATION"
        elif any(keyword in func_name for keyword in ["loop", "iterate", "process"]):
            hotspot_type = "ITERATION"

        hotspots.append(
            {
                "function": func["function"],
                "hotspot_type": hotspot_type,
                "time_seconds": func["total_time_seconds"],
                "call_count": func["call_count"],
                "severity": "HIGH"
                if func["total_time_seconds"] > 0.1
                else "MEDIUM"
                if func["total_time_seconds"] > 0.05
                else "LOW",
            }
        )

    return hotspots


def identify_performance_bottlenecks(operations_profiled: Dict[str, Any]) -> List[Dict]:
    """Identify performance bottlenecks across all profiled operations"""

    bottlenecks = []

    for operation_name, operation_data in operations_profiled.items():
        if "error" in operation_data:
            continue

        # Check for slow operations
        execution_time = operation_data.get("total_execution_time", 0)
        if execution_time > 2:  # Operations taking more than 2 seconds
            bottlenecks.append(
                {
                    "operation": operation_name,
                    "bottleneck_type": "SLOW_EXECUTION",
                    "severity": "HIGH",
                    "time_seconds": execution_time,
                    "description": f"Operation takes {execution_time}s to complete",
                }
            )

        # Check for low throughput
        throughput_metrics = [
            ("operations_per_second", 1),
            ("members_per_second", 2),
            ("mandates_per_second", 1),
            ("invoices_per_second", 2),
            ("payments_per_second", 3),
        ]

        for metric_name, threshold in throughput_metrics:
            if metric_name in operation_data:
                throughput = operation_data[metric_name]
                if throughput < threshold:
                    bottlenecks.append(
                        {
                            "operation": operation_name,
                            "bottleneck_type": "LOW_THROUGHPUT",
                            "severity": "MEDIUM",
                            "throughput": throughput,
                            "threshold": threshold,
                            "description": f"Low throughput: {throughput} {metric_name.replace('_', ' ')}",
                        }
                    )

        # Check for database-heavy operations
        db_time_percentage = operation_data.get("database_time_percentage", 0)
        if db_time_percentage > 70:  # More than 70% time spent in database operations
            bottlenecks.append(
                {
                    "operation": operation_name,
                    "bottleneck_type": "DATABASE_HEAVY",
                    "severity": "MEDIUM",
                    "db_time_percentage": db_time_percentage,
                    "description": f"Database operations consume {db_time_percentage}% of execution time",
                }
            )

        # Check for function hotspots
        hotspots = operation_data.get("hotspots_identified", [])
        high_severity_hotspots = [h for h in hotspots if h.get("severity") == "HIGH"]

        if high_severity_hotspots:
            bottlenecks.append(
                {
                    "operation": operation_name,
                    "bottleneck_type": "FUNCTION_HOTSPOTS",
                    "severity": "HIGH",
                    "hotspot_count": len(high_severity_hotspots),
                    "top_hotspot": high_severity_hotspots[0]["function"],
                    "description": f"{len(high_severity_hotspots)} high-severity function hotspots identified",
                }
            )

    # Sort bottlenecks by severity
    severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    bottlenecks.sort(key=lambda x: severity_order.get(x["severity"], 0), reverse=True)

    return bottlenecks


def generate_optimization_recommendations(bottlenecks: List[Dict]) -> List[Dict]:
    """Generate specific optimization recommendations based on identified bottlenecks"""

    recommendations = []

    # Group bottlenecks by type
    bottleneck_types = {}
    for bottleneck in bottlenecks:
        btype = bottleneck["bottleneck_type"]
        if btype not in bottleneck_types:
            bottleneck_types[btype] = []
        bottleneck_types[btype].append(bottleneck)

    # Generate recommendations for each bottleneck type
    if "SLOW_EXECUTION" in bottleneck_types:
        slow_operations = bottleneck_types["SLOW_EXECUTION"]
        recommendations.append(
            {
                "priority": "HIGH",
                "category": "Slow Operations",
                "affected_operations": [op["operation"] for op in slow_operations],
                "recommendation": "Convert slow synchronous operations to background jobs",
                "implementation": "Use frappe.enqueue() for operations taking >2 seconds",
                "expected_improvement": "90% reduction in user-perceived response time",
            }
        )

    if "DATABASE_HEAVY" in bottleneck_types:
        db_heavy_operations = bottleneck_types["DATABASE_HEAVY"]
        recommendations.append(
            {
                "priority": "HIGH",
                "category": "Database Optimization",
                "affected_operations": [op["operation"] for op in db_heavy_operations],
                "recommendation": "Optimize database queries and add strategic indexes",
                "implementation": "Add compound indexes on frequently queried fields, batch database operations",
                "expected_improvement": "50-70% reduction in database query time",
            }
        )

    if "LOW_THROUGHPUT" in bottleneck_types:
        low_throughput_operations = bottleneck_types["LOW_THROUGHPUT"]
        recommendations.append(
            {
                "priority": "MEDIUM",
                "category": "Throughput Optimization",
                "affected_operations": [op["operation"] for op in low_throughput_operations],
                "recommendation": "Implement batch processing and caching strategies",
                "implementation": "Process records in batches, cache frequently accessed data",
                "expected_improvement": "200-300% increase in processing throughput",
            }
        )

    if "FUNCTION_HOTSPOTS" in bottleneck_types:
        hotspot_operations = bottleneck_types["FUNCTION_HOTSPOTS"]
        recommendations.append(
            {
                "priority": "MEDIUM",
                "category": "Code Optimization",
                "affected_operations": [op["operation"] for op in hotspot_operations],
                "recommendation": "Optimize high-time-consumption functions",
                "implementation": "Refactor algorithms, reduce function call overhead, eliminate N+1 queries",
                "expected_improvement": "30-50% reduction in function execution time",
            }
        )

    return recommendations


def save_profiling_results(results: Dict[str, Any]) -> str:
    """Save profiling results to file"""

    results_file = "/home/frappe/frappe-bench/apps/verenigingen/performance_profiling_results.json"

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return results_file
