import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from verenigingen.utils.error_handling import handle_api_error, validate_required_fields
from verenigingen.utils.migration_performance import BatchProcessor
from verenigingen.utils.performance_utils import performance_monitor


@handle_api_error
@frappe.whitelist()
def load_unpaid_invoices(date_range="overdue", membership_type=None, limit=100):
    """Load unpaid invoices for batch processing"""

    filters = {"status": ["in", ["Unpaid", "Overdue"]], "docstatus": 1}

    # Add date range filter
    if date_range == "overdue":
        filters["due_date"] = ["<", today()]
    elif date_range == "due_this_week":
        filters["due_date"] = ["between", [today(), add_days(today(), 7)]]
    elif date_range == "due_this_month":
        filters["due_date"] = ["between", [today(), add_days(today(), 30)]]

    # Add membership type filter if specified
    if membership_type:
        # Get memberships of this type
        memberships = frappe.get_all("Membership", filters={"membership_type": membership_type}, pluck="name")
        if memberships:
            filters["membership"] = ["in", memberships]

    # Get invoices
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name as invoice",
            "customer",
            "outstanding_amount as amount",
            "currency",
            "due_date",
            "membership",
        ],
        order_by="due_date",
        limit=limit,
    )

    # Enrich with member and mandate information
    for invoice in invoices:
        if invoice.membership:
            member = frappe.db.get_value("Membership", invoice.membership, "member")
            if member:
                invoice["member"] = member
                member_doc = frappe.get_doc("Member", member)
                invoice["member_name"] = member_doc.full_name

                # Get active SEPA mandate
                mandate = member_doc.get_active_sepa_mandate()
                if mandate:
                    invoice["iban"] = mandate.iban
                    invoice["bic"] = mandate.bic
                    invoice["mandate_reference"] = mandate.mandate_id
                    invoice["mandate_date"] = str(mandate.sign_date)
                else:
                    invoice["iban"] = ""
                    invoice["bic"] = ""
                    invoice["mandate_reference"] = ""
                    invoice["mandate_date"] = ""

    return invoices


@frappe.whitelist()
def get_invoice_mandate_info(invoice):
    """Get mandate information for an invoice"""

    invoice_doc = frappe.get_doc("Sales Invoice", invoice)

    if not invoice_doc.membership:
        return None

    member = frappe.db.get_value("Membership", invoice_doc.membership, "member")
    if not member:
        return None

    member_doc = frappe.get_doc("Member", member)
    mandate = member_doc.get_active_sepa_mandate()

    if mandate:
        return {
            "iban": mandate.iban,
            "bic": mandate.bic,
            "mandate_reference": mandate.mandate_id,
            "mandate_date": str(mandate.sign_date),
            "valid": True,
        }

    return {"valid": False, "error": _("No active SEPA mandate found")}


@frappe.whitelist()
def validate_invoice_mandate(invoice, member):
    """Validate mandate for a specific invoice"""

    try:
        member_doc = frappe.get_doc("Member", member)
        mandate = member_doc.get_active_sepa_mandate()

        if not mandate:
            return {"valid": False, "error": _("No active SEPA mandate")}

        # Validate IBAN
        from verenigingen.utils.validation.iban_validator import validate_iban

        iban_validation = validate_iban(mandate.iban)

        if not iban_validation["valid"]:
            return {"valid": False, "error": iban_validation["message"]}

        # Check mandate expiry
        if mandate.expiry_date and getdate(mandate.expiry_date) < getdate(today()):
            return {"valid": False, "error": _("Mandate has expired")}

        return {
            "valid": True,
            "iban": mandate.iban,
            "bic": mandate.bic,
            "mandate_reference": mandate.mandate_id,
            "mandate_date": str(mandate.sign_date),
        }

    except Exception as e:
        return {"valid": False, "error": str(e)}


@handle_api_error
@frappe.whitelist()
def get_batch_analytics(batch_name):
    """Get detailed analytics for a batch"""

    batch = frappe.get_doc("Direct Debit Batch", batch_name)

    analytics = {
        "summary": {
            "total_invoices": len(batch.invoices),
            "total_amount": batch.total_amount,
            "status": batch.status,
        },
        "by_status": {},
        "by_member": {},
        "issues": [],
    }

    # Analyze by status
    status_counts = {}
    status_amounts = {}

    for inv in batch.invoices:
        status = inv.status or "Pending"
        status_counts[status] = status_counts.get(status, 0) + 1
        status_amounts[status] = status_amounts.get(status, 0) + inv.amount

        # Check for issues
        if not inv.iban:
            analytics["issues"].append(
                {"invoice": inv.invoice, "member": inv.member_name, "issue": "Missing IBAN"}
            )
        elif not inv.mandate_reference:
            analytics["issues"].append(
                {"invoice": inv.invoice, "member": inv.member_name, "issue": "Missing mandate reference"}
            )

    analytics["by_status"] = [
        {"status": status, "count": count, "amount": status_amounts.get(status, 0)}
        for status, count in status_counts.items()
    ]

    return analytics


@frappe.whitelist()
def preview_sepa_xml(batch_name):
    """Preview SEPA XML content before generation"""

    batch = frappe.get_doc("Direct Debit Batch", batch_name)

    # Generate preview data
    preview = {
        "header": {
            "message_id": f"BATCH-{batch.name}",
            "creation_datetime": frappe.utils.now(),
            "number_of_transactions": len(batch.invoices),
            "control_sum": batch.total_amount,
        },
        "payment_info": {
            "collection_date": str(batch.batch_date),
            "batch_type": batch.batch_type,
            "creditor_name": frappe.db.get_single_value("Verenigingen Settings", "company_name"),
            "creditor_iban": frappe.db.get_single_value("Verenigingen Settings", "company_iban"),
            "creditor_id": frappe.db.get_single_value("Verenigingen Settings", "creditor_id"),
        },
        "transactions": [],
    }

    # Add transaction preview (first 5)
    for i, inv in enumerate(batch.invoices[:5]):
        preview["transactions"].append(
            {
                "end_to_end_id": f"E2E-{inv.invoice}",
                "amount": inv.amount,
                "debtor_name": inv.member_name,
                "debtor_iban": inv.iban[:4] + "****" + inv.iban[-4:] if inv.iban else "Missing",
                "mandate_id": inv.mandate_reference or "Missing",
                "description": f"Invoice {inv.invoice}",
            }
        )

    if len(batch.invoices) > 5:
        preview["more_transactions"] = len(batch.invoices) - 5

    return preview
