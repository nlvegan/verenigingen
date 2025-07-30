#!/usr/bin/env python3
"""
Debug Payment History Event Handler
"""

import frappe
from frappe.utils import nowdate, today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
def fix_report_config():
    """Fix the Membership Dues Coverage Analysis report configuration"""
    try:
        # First create the missing role if it doesn't exist
        if not frappe.db.exists("Role", "Verenigingen Financial Manager"):
            role = frappe.new_doc("Role")
            role.role_name = "Verenigingen Financial Manager"
            role.insert()
            frappe.db.commit()

        # Now fix the report
        report = frappe.get_doc("Report", "Membership Dues Coverage Analysis")
        current_type = report.report_type
        current_query = report.query

        report.report_type = "Script Report"
        report.query = ""
        report.save()
        frappe.db.commit()

        return {
            "success": True,
            "message": f"Report fixed: {current_type} -> Script Report",
            "previous_query": current_query,
        }
    except Exception as e:
        frappe.log_error(f"Error fixing report config: {str(e)}", "Report Fix")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_coverage_report_display():
    """Debug the actual coverage report display issue"""
    from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
        calculate_coverage_timeline,
        execute,
        get_data,
    )

    try:
        # Test with the specific date range mentioned: July 30, 2024 to today
        filters = {"from_date": "2024-07-30", "to_date": frappe.utils.today()}

        result = {
            "debug_info": {
                "from_date": filters["from_date"],
                "to_date": filters["to_date"],
                "today": frappe.utils.today(),
            }
        }

        # Test the main execute function
        columns, data = execute(filters)

        result["report_execution"] = {
            "total_columns": len(columns),
            "total_rows": len(data),
            "first_5_rows": [],
        }

        # Examine first 5 rows in detail
        for i, row in enumerate(data[:5]):
            detailed_row = {
                "member": row.get("member"),
                "member_name": row.get("member_name"),
                "total_active_days": row.get("total_active_days"),
                "covered_days": row.get("covered_days"),
                "gap_days": row.get("gap_days"),
                "coverage_percentage": row.get("coverage_percentage"),
                "current_gaps": row.get("current_gaps"),
            }
            result["report_execution"]["first_5_rows"].append(detailed_row)

        # Test coverage calculation for specific members
        test_members = ["Assoc-Member-2025-07-0024", "Assoc-Member-2025-07-0025", "Assoc-Member-2025-07-0028"]
        result["individual_tests"] = {}

        for member in test_members:
            if frappe.db.exists("Member", member):
                try:
                    coverage = calculate_coverage_timeline(member, filters["from_date"], filters["to_date"])
                    result["individual_tests"][member] = {
                        "stats": coverage["stats"],
                        "gap_count": len(coverage["gaps"]),
                        "timeline_count": len(coverage["timeline"]),
                    }
                except Exception as e:
                    result["individual_tests"][member] = {"error": str(e)}
            else:
                result["individual_tests"][member] = {"error": "Member not found"}

        # Test filters
        gap_filter = {**filters, "show_only_gaps": True}
        try:
            _, gap_data = execute(gap_filter)
            result["gap_filter_test"] = {
                "total_with_gaps": len(gap_data),
                "sample_gaps": [
                    {"member": row.get("member"), "gap_days": row.get("gap_days")} for row in gap_data[:3]
                ],
            }
        except Exception as e:
            result["gap_filter_test"] = {"error": str(e)}

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging coverage report: {str(e)}", "Coverage Report Debug")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_membership_periods():
    """Debug why membership periods are returning 0 active days"""
    from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
        get_membership_periods,
    )

    try:
        # Test with specific members
        test_members = ["Assoc-Member-2025-07-0024", "Assoc-Member-2025-07-0025", "Assoc-Member-2025-07-0028"]
        from_date = "2024-07-30"
        to_date = "2025-07-30"

        result = {"date_range": {"from": from_date, "to": to_date}, "membership_analysis": {}}

        for member in test_members:
            if frappe.db.exists("Member", member):
                # Check raw membership data
                memberships_raw = frappe.db.sql(
                    """
                    SELECT mb.name, mb.start_date, mb.cancellation_date as end_date, mb.status, mb.docstatus
                    FROM `tabMembership` mb
                    WHERE mb.member = %s
                    ORDER BY mb.start_date
                """,
                    [member],
                    as_dict=True,
                )

                # Test the get_membership_periods function
                periods = get_membership_periods(member, from_date, to_date)

                result["membership_analysis"][member] = {
                    "raw_memberships": memberships_raw,
                    "calculated_periods": periods,
                    "period_count": len(periods),
                }
            else:
                result["membership_analysis"][member] = {"error": "Member not found"}

        # Also check the raw query from the main report
        main_query_result = frappe.db.sql(
            """
            SELECT
                m.name as member,
                CONCAT(m.first_name, ' ', COALESCE(m.last_name, '')) as member_name,
                m.status as membership_status,
                m.customer,
                mb.start_date as membership_start,
                mb.cancellation_date as membership_end,
                mb.status as membership_status_join,
                mb.docstatus as membership_docstatus
            FROM `tabMember` m
            LEFT JOIN `tabMembership` mb ON mb.member = m.name AND mb.status = 'Active' AND mb.docstatus = 1
            WHERE m.name IN %s AND m.status = 'Active'
            ORDER BY m.name
        """,
            [tuple(test_members)],
            as_dict=True,
        )

        result["main_query_result"] = main_query_result

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging membership periods: {str(e)}", "Membership Debug")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def debug_payment_history_for_member(member_name):
    """Debug payment history updates for a specific member"""
    try:
        # Get member
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_info": {
                "name": member.name,
                "full_name": member.full_name,
                "email": member.email,
                "customer": getattr(member, "customer", "No customer linked"),
            }
        }

        # Check today's invoices
        today_date = today()

        if hasattr(member, "customer") and member.customer:
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "creation": [">=", today_date + " 00:00:00"]},
                fields=["name", "creation", "grand_total", "status", "due_date", "posting_date"],
                order_by="creation desc",
            )

            result["todays_invoices"] = {"count": len(invoices), "invoices": invoices}
        else:
            result["todays_invoices"] = {"count": 0, "error": "No customer linked to member"}

        # Check payment history
        payment_history = getattr(member, "payment_history", [])
        result["payment_history"] = {"count": len(payment_history), "recent_entries": []}

        if payment_history:
            # Get last 5 entries
            for entry in payment_history[-5:]:
                result["payment_history"]["recent_entries"].append(
                    {
                        "invoice": getattr(entry, "invoice", "N/A"),
                        "amount": getattr(entry, "amount", "N/A"),
                        "posting_date": str(getattr(entry, "posting_date", "N/A")),
                        "payment_date": str(getattr(entry, "payment_date", "N/A")),
                        "payment_status": getattr(entry, "payment_status", "N/A"),
                    }
                )

        # Check if there's a mismatch between invoices and payment history
        if hasattr(member, "customer") and member.customer:
            all_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer},
                fields=["name"],
                order_by="creation desc",
                limit=20,
            )

            payment_history_invoice_ids = (
                [getattr(entry, "invoice", "") for entry in payment_history] if payment_history else []
            )

            missing_in_history = []
            for inv in all_invoices:
                if inv.name not in payment_history_invoice_ids:
                    missing_in_history.append(inv.name)

            result["analysis"] = {
                "total_invoices_for_customer": len(all_invoices),
                "invoices_in_payment_history": len(payment_history_invoice_ids),
                "missing_in_payment_history": missing_in_history[:10],  # First 10
            }

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging payment history: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def debug_payment_history_hooks():
    """Debug the payment history event handlers"""
    try:
        from verenigingen.hooks import payment_history_hooks

        result = {"hooks_defined": {}, "handler_functions": []}

        # Check what hooks are defined
        hooks_content = frappe.get_hooks()

        if "doc_events" in hooks_content:
            doc_events = hooks_content["doc_events"]
            if "Sales Invoice" in doc_events:
                result["hooks_defined"]["Sales Invoice"] = doc_events["Sales Invoice"]
            if "*" in doc_events:
                result["hooks_defined"]["All Documents"] = doc_events["*"]

        # Check if our payment history functions exist
        try:
            from verenigingen.utils.payment_history import sync_payment_history_on_invoice_save

            result["handler_functions"].append("sync_payment_history_on_invoice_save - EXISTS")
        except ImportError as e:
            result["handler_functions"].append(f"sync_payment_history_on_invoice_save - MISSING: {e}")

        try:
            from verenigingen.utils.payment_history import sync_payment_history_on_payment_save

            result["handler_functions"].append("sync_payment_history_on_payment_save - EXISTS")
        except ImportError as e:
            result["handler_functions"].append(f"sync_payment_history_on_payment_save - MISSING: {e}")

        return result

    except Exception as e:
        frappe.log_error(f"Error debugging payment history hooks: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def manually_update_payment_history(member_name):
    """Manually trigger payment history update for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        if not hasattr(member, "customer") or not member.customer:
            return {"error": "No customer linked to member"}

        # Get all invoices for this customer (including drafts)
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "docstatus": ["!=", 2]},  # Exclude cancelled
            fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
            order_by="posting_date desc",
        )

        # Clear existing payment history
        member.payment_history = []

        # Add all invoices to payment history
        for invoice in invoices:
            member.append(
                "payment_history",
                {
                    "invoice": invoice.name,
                    "posting_date": invoice.posting_date,
                    "amount": invoice.grand_total,
                    "outstanding_amount": invoice.outstanding_amount,
                    "payment_status": "Paid" if invoice.outstanding_amount == 0 else "Unpaid",
                },
            )

        # Save the member
        member.save()

        return {
            "success": True,
            "invoices_added": len(invoices),
            "message": f"Updated payment history with {len(invoices)} invoices",
        }

    except Exception as e:
        frappe.log_error(f"Error manually updating payment history: {str(e)}")
        return {"error": str(e)}
