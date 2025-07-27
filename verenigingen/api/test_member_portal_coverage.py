"""
Test member portal coverage display functionality
"""

import frappe


@frappe.whitelist()
def test_member_portal_coverage(member_name=None):
    """Test coverage display for a specific member"""

    if not member_name:
        # Find Foppe de Haan or any member
        foppe = frappe.get_all("Member", {"first_name": "Foppe", "last_name": "de Haan"}, "name", limit=1)
        if foppe:
            member_name = foppe[0].name
        else:
            members = frappe.get_all("Member", fields=["name"], limit=1)
            if members:
                member_name = members[0].name

    if not member_name:
        return {"error": "No member found to test"}

    try:
        # Get member details
        member = frappe.get_doc("Member", member_name)

        # Get membership
        membership = frappe.db.get_value(
            "Membership",
            {"member": member_name, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )

        # Import and test the payment status function
        from verenigingen.templates.pages.member_portal import get_payment_status

        payment_status = get_payment_status(member, membership)

        result = {
            "member_name": member.full_name,
            "member_id": member_name,
            "has_payment_status": bool(payment_status),
        }

        if payment_status:
            result.update(
                {
                    "outstanding_amount": payment_status.get("outstanding_amount", 0),
                    "outstanding_invoices_count": len(payment_status.get("outstanding_invoices", [])),
                    "billing_frequency": payment_status.get("billing_frequency", "Unknown"),
                }
            )

            # Check the outstanding invoices for coverage periods
            outstanding_invoices = payment_status.get("outstanding_invoices", [])
            if outstanding_invoices:
                result["sample_invoices"] = []
                for invoice in outstanding_invoices[:3]:  # First 3 invoices
                    result["sample_invoices"].append(
                        {
                            "name": invoice.get("name"),
                            "amount": invoice.get("outstanding"),
                            "due_date": str(invoice.get("due_date")) if invoice.get("due_date") else None,
                            "coverage_period": invoice.get("coverage_period"),
                            "has_coverage_period": bool(
                                invoice.get("coverage_period")
                                and invoice.get("coverage_period") != str(invoice.get("due_date"))
                            ),
                        }
                    )

        return {"success": True, "data": result}

    except Exception as e:
        frappe.log_error(f"Error testing member portal coverage: {e}")
        return {"error": str(e)}


@frappe.whitelist()
def populate_coverage_for_outstanding_invoices():
    """Populate coverage data for outstanding invoices"""
    frappe.only_for("System Manager")

    # Get outstanding invoices without coverage data
    invoices = frappe.db.sql(
        """
        SELECT si.name, si.due_date, si.posting_date, si.customer, c.customer_name
        FROM `tabSales Invoice` si
        LEFT JOIN `tabCustomer` c ON si.customer = c.name
        WHERE si.docstatus = 1
        AND si.outstanding_amount > 0
        AND (si.custom_coverage_start_date IS NULL OR si.custom_coverage_end_date IS NULL)
        ORDER BY si.posting_date DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    if not invoices:
        return {"message": "No invoices need coverage data"}

    from datetime import datetime

    from frappe.utils import add_days, add_months, getdate

    updated = []

    for invoice in invoices:
        try:
            # Calculate coverage period based on due date
            if invoice.due_date:
                due_date = getdate(invoice.due_date)
                # For monthly billing, coverage ends on due date, starts ~30 days before
                coverage_end = due_date
                coverage_start = add_months(due_date, -1)
                coverage_start = add_days(coverage_start, 1)
            else:
                # Use posting date as fallback
                posting_date = getdate(invoice.posting_date)
                coverage_start = posting_date.replace(day=1)  # Start of month
                coverage_end = add_months(coverage_start, 1)
                coverage_end = add_days(coverage_end, -1)  # End of month

            # Update invoice
            frappe.db.set_value(
                "Sales Invoice",
                invoice.name,
                {"custom_coverage_start_date": coverage_start, "custom_coverage_end_date": coverage_end},
            )

            updated.append(
                {
                    "invoice": invoice.name,
                    "customer": invoice.customer_name,
                    "coverage": f"{coverage_start} to {coverage_end}",
                }
            )

        except Exception as e:
            frappe.log_error(f"Error updating invoice {invoice.name}: {e}")

    frappe.db.commit()

    return {
        "success": True,
        "message": f"Updated {len(updated)} invoices with coverage data",
        "updated": updated,
    }
