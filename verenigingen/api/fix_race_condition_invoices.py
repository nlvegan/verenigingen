"""API to fix invoices affected by the payment history race condition"""

import frappe
from frappe import _
from frappe.utils import add_days, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def check_and_fix_invoice(invoice_name):
    """Check and fix a specific invoice in payment history"""

    # Input validation
    if not invoice_name or not isinstance(invoice_name, str):
        frappe.throw(_("Invalid invoice name provided"), frappe.ValidationError)

    # Sanitize input
    invoice_name = frappe.db.escape(invoice_name.strip())

    try:
        # Log the operation for audit
        frappe.logger("verenigingen.race_condition_fix").info(
            f"Checking invoice {invoice_name} for race condition fix by user {frappe.session.user}"
        )

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
@high_security_api(operation_type=OperationType.ADMIN)
def fix_recent_missing_invoices(days_back=7):
    """Find and fix invoices that are missing from payment history due to race condition"""

    # Input validation and sanitization
    try:
        days_back = int(days_back)
        if days_back < 1 or days_back > 90:
            frappe.throw(_("Days back must be between 1 and 90"), frappe.ValidationError)
    except (ValueError, TypeError):
        frappe.throw(_("Invalid days_back value - must be a number"), frappe.ValidationError)

    # Log the bulk operation for audit
    frappe.logger("verenigingen.race_condition_fix").warning(
        f"Bulk race condition fix initiated by {frappe.session.user} for last {days_back} days"
    )

    # Get invoices from the specified days back
    recent_date = add_days(today(), -days_back)

    # Query for recent invoices - using parameterized query for security
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
        (recent_date,),
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
                    # Log the error for debugging but sanitize the message
                    frappe.log_error(
                        f"Failed to add invoice {invoice_data.invoice_name} to member {invoice_data.member_name}: {str(e)}",
                        "Race Condition Fix Error",
                    )
                    details.append(
                        {
                            "invoice": invoice_data.invoice_name,
                            "member": invoice_data.member_name,
                            "status": "error",
                            "message": "Failed to update payment history - see error log",
                        }
                    )
            else:
                already_exists_count += 1

        except Exception as e:
            error_count += 1
            # Log the error for debugging
            frappe.log_error(f"Error processing invoice data: {str(e)}", "Race Condition Fix Error")
            details.append(
                {
                    "invoice": getattr(invoice_data, "invoice_name", "Unknown"),
                    "member": getattr(invoice_data, "member_name", "Unknown"),
                    "status": "error",
                    "message": "Processing error - see error log",
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
