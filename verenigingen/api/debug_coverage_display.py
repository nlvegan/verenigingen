"""
Debug coverage period display issues
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def debug_coverage_display():
    """Debug why coverage periods aren't displaying correctly"""

    # Get a specific invoice to examine
    invoice_name = "ACC-SINV-2025-20435"  # This was updated with coverage data

    try:
        # Check the database directly
        coverage_data = frappe.db.get_value(
            "Sales Invoice",
            invoice_name,
            ["custom_coverage_start_date", "custom_coverage_end_date", "due_date", "customer"],
            as_dict=True,
        )

        results = [f"🔍 Examining invoice {invoice_name}"]
        if coverage_data:
            results.append(f"✅ Coverage start: {coverage_data.custom_coverage_start_date}")
            results.append(f"✅ Coverage end: {coverage_data.custom_coverage_end_date}")
            results.append(f"📅 Due date: {coverage_data.due_date}")
            results.append(f"👤 Customer: {coverage_data.customer}")
        else:
            results.append("❌ No coverage data found")
            return {"error": "Invoice not found"}

        # Test the format_coverage_period function directly
        from verenigingen.utils.member_portal_utils import format_coverage_period

        if coverage_data.custom_coverage_start_date and coverage_data.custom_coverage_end_date:
            formatted_period = format_coverage_period(
                coverage_data.custom_coverage_start_date,
                coverage_data.custom_coverage_end_date,
                "Monthly",  # Test with monthly billing
            )
            results.append(f"🎨 Formatted period (Monthly): {formatted_period}")

            # Test with Daily billing too
            formatted_daily = format_coverage_period(
                coverage_data.custom_coverage_start_date, coverage_data.custom_coverage_end_date, "Daily"
            )
            results.append(f"🎨 Formatted period (Daily): {formatted_daily}")

        # Test the enhance function
        from verenigingen.utils.member_portal_utils import enhance_outstanding_invoices_with_coverage

        test_invoices = [{"name": invoice_name, "due_date": coverage_data.due_date}]

        enhanced = enhance_outstanding_invoices_with_coverage(test_invoices, "Monthly")
        if enhanced:
            results.append(f"📊 Enhanced invoice coverage: {enhanced[0].get('coverage_period', 'NOT FOUND')}")

        # Check what's actually in the member portal function
        results.append("\n🧪 Testing member portal integration...")

        # Find the customer's member record
        member = frappe.db.get_value("Member", {"customer": coverage_data.customer})
        if member:
            results.append(f"👤 Found member: {member}")

            # Get membership
            membership = frappe.db.get_value(
                "Membership",
                {"member": member, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )

            if membership:
                results.append(f"🎫 Found membership: {membership.name}")

                # Test payment status function
                from verenigingen.templates.pages.member_portal import get_payment_status

                member_doc = frappe.get_doc("Member", member)
                payment_status = get_payment_status(member_doc, membership)

                if payment_status and payment_status.get("outstanding_invoices"):
                    sample_invoice = payment_status["outstanding_invoices"][0]
                    results.append(
                        f"💳 Sample outstanding invoice coverage: {sample_invoice.get('coverage_period', 'NOT FOUND')}"
                    )
                    results.append(f"💳 Sample invoice name: {sample_invoice.get('name')}")

        return {"success": True, "results": results}

    except Exception as e:
        frappe.log_error(f"Debug coverage error: {e}")
        return {"error": str(e)}
