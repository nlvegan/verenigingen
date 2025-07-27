"""
Helper function to generate invoice for a specific dues schedule
"""

import frappe

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@critical_api(operation_type=OperationType.FINANCIAL)
@frappe.whitelist()
def generate_invoice_for_schedule(schedule_name, force=False):
    """
    Generate invoice for a specific dues schedule
    """
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    # Check if we can generate
    can_generate, reason = schedule.can_generate_invoice()

    result = {
        "schedule_name": schedule_name,
        "member": schedule.member,
        "member_name": schedule.member_name,
        "can_generate": can_generate,
        "reason": reason,
        "force": force,
    }

    if can_generate or force:
        try:
            invoice = schedule.generate_invoice(force=force)
            if invoice:
                result["success"] = True
                result["invoice"] = invoice.name if hasattr(invoice, "name") else invoice
                result["message"] = f"Invoice {result['invoice']} generated successfully"
            else:
                result["success"] = False
                result["message"] = "Invoice generation returned None"
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            result["message"] = f"Error generating invoice: {str(e)}"
    else:
        result["success"] = False
        result["message"] = f"Cannot generate invoice: {reason}"

    return result
