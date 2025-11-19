#!/usr/bin/env python3
"""
Integration test for Coverage Analysis with real data
Run with: bench --site dev.veganisme.net execute verenigingen.test_coverage_integration.run_integration_test
"""

import json

import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def run_integration_test():
    """Test the report with existing data"""

    results = {"status": "success", "tests": [], "data_summary": {}, "errors": []}

    try:
        # Check available test data
        member_count = frappe.db.count("Member", {"status": "Active"})
        membership_count = frappe.db.count("Membership", {"docstatus": 1})
        invoice_count = frappe.db.count(
            "Sales Invoice", {"docstatus": 1, "custom_coverage_start_date": ["is", "set"]}
        )

        results["data_summary"] = {
            "active_members": member_count,
            "memberships": membership_count,
            "coverage_invoices": invoice_count,
        }

        # Test 1: Basic report execution with current data
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            execute,
        )

        try:
            filters = {"from_date": add_days(today(), -365), "to_date": today()}
            columns, data = execute(filters)

            results["tests"].append(
                {
                    "name": "Basic Report Execution",
                    "status": "success",
                    "data_rows": len(data),
                    "columns": len(columns),
                }
            )

        except Exception as e:
            results["tests"].append({"name": "Basic Report Execution", "status": "failed", "error": str(e)})
            results["errors"].append(f"Report execution failed: {str(e)}")

        # Test 2: Member with coverage data
        if invoice_count > 0:
            # Find a member with coverage data
            member_with_coverage = frappe.db.sql(
                """
                SELECT DISTINCT m.name as member_name
                FROM `tabMember` m
                JOIN `tabSales Invoice` si ON si.customer = m.customer
                WHERE si.custom_coverage_start_date IS NOT NULL
                AND m.status = 'Active'
                LIMIT 1
            """,
                as_dict=True,
            )

            if member_with_coverage:
                try:
                    from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                        calculate_coverage_timeline,
                    )

                    member_name = member_with_coverage[0]["member_name"]
                    coverage_analysis = calculate_coverage_timeline(member_name)

                    results["tests"].append(
                        {
                            "name": "Coverage Timeline Calculation",
                            "status": "success",
                            "member": member_name,
                            "timeline_events": len(coverage_analysis.get("timeline", [])),
                            "gaps_found": len(coverage_analysis.get("gaps", [])),
                            "stats": coverage_analysis.get("stats", {}),
                        }
                    )

                except Exception as e:
                    results["tests"].append(
                        {"name": "Coverage Timeline Calculation", "status": "failed", "error": str(e)}
                    )
                    results["errors"].append(f"Coverage timeline failed: {str(e)}")

        # Test 3: Filter functionality
        try:
            # Test with specific filters
            filters_test = {"from_date": add_days(today(), -90), "to_date": today(), "show_only_gaps": True}
            columns, data = execute(filters_test)

            results["tests"].append(
                {
                    "name": "Filter Functionality",
                    "status": "success",
                    "filtered_rows": len(data),
                    "filter_applied": "show_only_gaps",
                }
            )

        except Exception as e:
            results["tests"].append({"name": "Filter Functionality", "status": "failed", "error": str(e)})

        # Summary
        success_tests = len([t for t in results["tests"] if t["status"] == "success"])
        total_tests = len(results["tests"])

        if success_tests == total_tests and not results["errors"]:
            results["status"] = "success"
        elif success_tests > 0:
            results["status"] = "partial"
        else:
            results["status"] = "failed"

        results["summary"] = f"{success_tests}/{total_tests} tests passed"

        return results

    except Exception as e:
        return {"status": "error", "message": str(e), "tests": results.get("tests", [])}


@frappe.whitelist()
def check_data_quality():
    """Check data quality for report accuracy"""

    try:
        # Check for members without customers
        members_no_customer = frappe.db.count("Member", {"status": "Active", "customer": ["in", ["", None]]})

        # Check for invoices without coverage dates
        invoices_no_coverage = frappe.db.count(
            "Sales Invoice", {"docstatus": 1, "custom_coverage_start_date": ["in", ["", None]]}
        )

        # Check for active memberships
        active_memberships = frappe.db.count("Membership", {"status": "Active", "docstatus": 1})

        # Check for dues schedules
        active_schedules = frappe.db.count("Membership Dues Schedule", {"status": "Active"})

        return {
            "status": "success",
            "data_quality": {
                "members_without_customer": members_no_customer,
                "invoices_without_coverage": invoices_no_coverage,
                "active_memberships": active_memberships,
                "active_dues_schedules": active_schedules,
            },
            "recommendations": {
                "fix_customer_links": members_no_customer > 0,
                "add_coverage_dates": invoices_no_coverage > 0,
                "create_dues_schedules": active_schedules == 0,
            },
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}
