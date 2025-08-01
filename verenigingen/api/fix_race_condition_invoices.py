"""API to fix invoices affected by the payment history race condition"""

import frappe
from frappe import _
from frappe.utils import add_days, today


@frappe.whitelist()
def check_and_fix_invoice(invoice_name):
    """Check and fix a specific invoice in payment history"""

    try:
        # Check if invoice exists
        if not frappe.db.exists("Sales Invoice", invoice_name):
            return {"success": False, "message": f"Invoice {invoice_name} does not exist"}

        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Find associated member
        members = frappe.get_all("Member", filters={"customer": invoice.customer}, fields=["name"])

        if not members:
            return {"success": False, "message": f"No member found for customer {invoice.customer}"}

        results = []

        for member_data in members:
            member = frappe.get_doc("Member", member_data.name)

            # Check if invoice is in payment history
            invoice_found = False
            for row in member.payment_history or []:
                if row.invoice == invoice_name:
                    invoice_found = True
                    results.append(
                        {
                            "member": member.name,
                            "status": "already_exists",
                            "payment_status": row.payment_status,
                            "amount": row.amount,
                        }
                    )
                    break

            if not invoice_found:
                try:
                    member.add_invoice_to_payment_history(invoice_name)
                    results.append(
                        {
                            "member": member.name,
                            "status": "added",
                            "message": "Successfully added invoice to payment history",
                        }
                    )
                except Exception as e:
                    results.append({"member": member.name, "status": "error", "message": str(e)})

        return {
            "success": True,
            "invoice": invoice_name,
            "customer": invoice.customer,
            "status": invoice.status,
            "docstatus": invoice.docstatus,
            "posting_date": str(invoice.posting_date),
            "grand_total": invoice.grand_total,
            "members": results,
        }

    except Exception as e:
        return {"success": False, "message": f"Error checking invoice {invoice_name}: {str(e)}"}


@frappe.whitelist()
def fix_recent_missing_invoices(days_back=7):
    """Find and fix invoices that are missing from payment history due to race condition"""

    # Get invoices from the specified days back
    recent_date = add_days(today(), -days_back)

    # Query for recent invoices
    invoices = frappe.db.sql(
        """
        SELECT
            si.name as invoice_name,
            si.customer,
            si.posting_date,
            si.grand_total,
            c.name as customer_name,
            m.name as member_name
        FROM `tabSales Invoice` si
        INNER JOIN `tabCustomer` c ON si.customer = c.name
        LEFT JOIN `tabMember` m ON m.customer = c.name
        WHERE si.posting_date >= %s
        AND si.docstatus = 1
        AND m.name IS NOT NULL
        ORDER BY si.posting_date DESC
        LIMIT 100
    """,
        recent_date,
        as_dict=True,
    )

    fixed_count = 0
    already_exists_count = 0
    error_count = 0
    details = []

    for invoice_data in invoices:
        try:
            member = frappe.get_doc("Member", invoice_data.member_name)

            # Check if invoice is already in payment history
            invoice_exists = False
            for row in member.payment_history or []:
                if row.invoice == invoice_data.invoice_name:
                    invoice_exists = True
                    break

            if not invoice_exists:
                try:
                    member.add_invoice_to_payment_history(invoice_data.invoice_name)
                    fixed_count += 1
                    details.append(
                        {
                            "invoice": invoice_data.invoice_name,
                            "member": invoice_data.member_name,
                            "status": "fixed",
                            "message": "Added to payment history",
                        }
                    )
                except Exception as e:
                    error_count += 1
                    details.append(
                        {
                            "invoice": invoice_data.invoice_name,
                            "member": invoice_data.member_name,
                            "status": "error",
                            "message": str(e),
                        }
                    )
            else:
                already_exists_count += 1

        except Exception as e:
            error_count += 1
            details.append(
                {
                    "invoice": invoice_data.invoice_name,
                    "member": invoice_data.member_name if invoice_data else "Unknown",
                    "status": "error",
                    "message": str(e),
                }
            )

    # Changes will be committed automatically by Frappe

    return {
        "success": True,
        "summary": {
            "total_checked": len(invoices),
            "fixed": fixed_count,
            "already_exists": already_exists_count,
            "errors": error_count,
        },
        "details": details[:20],  # Limit details to first 20 for readability
    }
