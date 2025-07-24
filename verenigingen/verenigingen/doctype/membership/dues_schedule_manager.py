import frappe
from frappe import _
from frappe.utils import today


def sync_membership_with_dues_schedule(membership_doc):
    """
    Synchronize membership with Membership Dues Schedule
    - Update payment status based on dues schedule invoices
    - Track payment history
    """
    if not membership_doc.dues_schedule:
        return

    member = frappe.get_doc("Member", membership_doc.member)

    if not member.customer:
        return

    # Get invoices linked to this member/customer
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": member.customer,
            "docstatus": 1,
            "posting_date": [">=", membership_doc.start_date],
        },
        fields=["name", "status", "outstanding_amount", "posting_date"],
        order_by="posting_date desc",
    )

    if not invoices:
        return

    # Check latest invoice status
    if invoices:
        latest_invoice = invoices[0]

        # Update membership payment status based on invoice
        if latest_invoice.status == "Paid":
            membership_doc.last_payment_date = latest_invoice.posting_date
            membership_doc.unpaid_amount = 0
        elif latest_invoice.status == "Overdue":
            membership_doc.unpaid_amount = latest_invoice.outstanding_amount
        elif latest_invoice.status == "Return":
            membership_doc.unpaid_amount = 0
        else:
            membership_doc.unpaid_amount = latest_invoice.outstanding_amount or 0

    # Save membership document
    membership_doc.flags.ignore_validate_update_after_submit = True
    membership_doc.save()

    # Return information about linked invoices for display
    return invoices


def get_membership_payment_history(membership_doc):
    """
    Get payment history for a membership from linked dues schedule
    """
    if not membership_doc.dues_schedule:
        return []

    # Get member customer
    member = frappe.get_doc("Member", membership_doc.member)
    if not member.customer:
        return []

    # Get invoices from member/customer
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": member.customer,
            "docstatus": 1,
            "posting_date": [">=", membership_doc.start_date],
        },
        fields=["name", "status", "posting_date", "grand_total", "outstanding_amount"],
        order_by="posting_date desc",
    )

    payment_history = []

    for invoice_info in invoices:
        invoice = frappe.get_doc("Sales Invoice", invoice_info.name)

        # Get linked payments
        payments = frappe.get_all(
            "Payment Entry Reference", filters={"reference_name": invoice.name}, fields=["parent"]
        )

        payment_entries = []
        for payment in payments:
            payment_doc = frappe.get_doc("Payment Entry", payment.parent)
            payment_entries.append(
                {
                    "payment_entry": payment_doc.name,
                    "amount": payment_doc.paid_amount,
                    "date": payment_doc.posting_date,
                    "mode": payment_doc.mode_of_payment,
                    "status": payment_doc.status,
                }
            )

        payment_history.append(
            {
                "invoice": invoice.name,
                "date": invoice.posting_date,
                "amount": invoice.grand_total,
                "status": invoice.status,
                "payments": payment_entries,
            }
        )

    return payment_history


def create_direct_debit_batch(date=None):
    """
    Create a direct debit batch for unpaid membership invoices
    """
    if not date:
        date = today()

    # Find all unpaid invoices linked to membership dues schedules
    unpaid_invoices = []

    # Get all active memberships with dues schedules
    memberships = frappe.get_all(
        "Membership",
        filters={
            "status": "Active",
        },
        fields=["name", "member", "member_name"],
    )

    for membership in memberships:
        # Get member and check payment method
        member = frappe.get_doc("Member", membership.member)
        if not hasattr(member, "payment_method") or member.payment_method != "SEPA Direct Debit":
            continue

        # Get unpaid invoices from member's customer
        if not member.customer:
            continue

        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "docstatus": 1, "status": ["in", ["Unpaid", "Overdue"]]},
            fields=["name", "grand_total", "currency", "due_date"],
            order_by="creation desc",
        )

        for invoice_info in invoices:
            invoice = frappe.get_doc("Sales Invoice", invoice_info.name)

            if invoice.status == "Unpaid" or invoice.status == "Overdue":
                # Get bank details from member
                bank_info = get_member_bank_details(member.name)

                if bank_info:
                    unpaid_invoices.append(
                        {
                            "invoice": invoice.name,
                            "membership": membership.name,
                            "member": membership.member,
                            "member_name": membership.member_name,
                            "amount": invoice.grand_total,
                            "currency": invoice.currency,
                            "due_date": invoice.due_date,
                            "bank_account": bank_info.get("account_number"),
                            "iban": bank_info.get("iban"),
                            "mandate_reference": bank_info.get("mandate_reference"),
                        }
                    )

    if not unpaid_invoices:
        return None

    # Create a batch entry
    batch = frappe.new_doc("SEPA Direct Debit Batch")
    batch.batch_date = date
    batch.batch_description = f"Membership payments batch - {date}"
    batch.batch_type = "CORE"  # Dutch direct debit type

    for invoice in unpaid_invoices:
        batch.append(
            "invoices",
            {
                "invoice": invoice["invoice"],
                "membership": invoice["membership"],
                "member": invoice["member"],
                "member_name": invoice["member_name"],
                "amount": invoice["amount"],
                "currency": invoice["currency"],
                "bank_account": invoice["bank_account"],
                "iban": invoice["iban"],
                "mandate_reference": invoice["mandate_reference"],
            },
        )

    batch.total_amount = sum(invoice["amount"] for invoice in unpaid_invoices)
    batch.currency = unpaid_invoices[0]["currency"] if unpaid_invoices else "EUR"
    batch.entry_count = len(unpaid_invoices)

    batch.insert()

    return batch


def get_member_bank_details(member_name):
    """
    Get bank details for a member
    - This is a placeholder - replace with your actual bank details storage mechanism
    """
    # This is where you would implement retrieval of bank details
    # For now, we'll return a placeholder

    # Future implementation might look like:
    # bank_details = frappe.get_all(
    #     "Bank Account",
    #     filters={"party_type": "Member", "party": member_name},
    #     fields=["name", "account_number", "iban", "mandate_reference"]
    # )

    # For now, return empty dict
    return {}


@frappe.whitelist()
def get_unpaid_membership_invoices():
    """
    Get all unpaid invoices related to memberships
    Used by SEPA Direct Debit Batch for selecting invoices
    """
    # Get all active memberships with dues schedules
    memberships = frappe.get_all(
        "Membership",
        filters={
            "status": ["in", ["Active", "Pending"]],
            "dues_schedule": ["is", "set"],
        },
        fields=["name", "member", "member_name"],
    )

    if not memberships:
        return []

    unpaid_invoices = []

    for membership in memberships:
        # Get member and check payment method
        member_doc = frappe.get_doc("Member", membership.member)
        if not hasattr(member_doc, "payment_method") or member_doc.payment_method != "SEPA Direct Debit":
            continue

        if not member_doc.customer:
            continue

        # Get unpaid invoices from member's customer
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": member_doc.customer,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue"]],
            },
            fields=["name", "grand_total", "currency"],
            order_by="creation desc",
        )

        for invoice_info in invoices:
            # Check if invoice is unpaid
            invoice = frappe.get_doc("Sales Invoice", invoice_info.name)

            if invoice.status in ["Unpaid", "Overdue"]:
                # Get bank details from member
                bank_account = ""
                iban = ""
                mandate_reference = ""

                # Try to get bank details from member
                # This is a placeholder - replace with your actual implementation
                # You could store these in custom fields or in a separate doctype

                # Example using custom fields
                if hasattr(member_doc, "bank_account"):
                    bank_account = member_doc.bank_account

                if hasattr(member_doc, "iban"):
                    iban = member_doc.iban

                if hasattr(member_doc, "mandate_reference"):
                    mandate_reference = member_doc.mandate_reference

                # Only add invoices with bank details
                if iban and mandate_reference:
                    unpaid_invoices.append(
                        {
                            "invoice": invoice.name,
                            "membership": membership.name,
                            "member": membership.member,
                            "member_name": membership.member_name,
                            "amount": invoice.grand_total,
                            "currency": invoice.currency,
                            "bank_account": bank_account,
                            "iban": iban,
                            "mandate_reference": mandate_reference,
                        }
                    )

    return unpaid_invoices


@frappe.whitelist()
def add_to_direct_debit_batch(membership_name):
    """
    Add a membership to a direct debit batch
    Creates a new batch if needed
    """
    membership = frappe.get_doc("Membership", membership_name)

    if not membership.dues_schedule:
        frappe.throw(_("Membership must have a dues schedule to add to direct debit batch"))

    if membership.unpaid_amount <= 0:
        frappe.throw(_("Membership has no unpaid amount"))

    member = frappe.get_doc("Member", membership.member)
    if not hasattr(member, "payment_method") or member.payment_method != "SEPA Direct Debit":
        frappe.throw(_("Member payment method must be SEPA Direct Debit"))

    # Get unpaid invoices for this membership
    invoices = []
    if not member.customer:
        frappe.throw(_("Member must have a customer to be added to direct debit batch"))

    member_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": member.customer, "docstatus": 1, "status": ["in", ["Unpaid", "Overdue"]]},
        fields=["name", "grand_total", "currency"],
        order_by="creation desc",
    )

    for invoice_info in member_invoices:
        invoice = frappe.get_doc("Sales Invoice", invoice_info.name)

        if invoice.status in ["Unpaid", "Overdue"]:
            # Get bank details
            # Replace with your actual implementation
            bank_account = getattr(member, "bank_account", "")
            iban = getattr(member, "iban", "")
            mandate_reference = getattr(member, "mandate_reference", "")

            if not iban or not mandate_reference:
                frappe.throw(_("Member must have bank details to be added to direct debit batch"))

            invoices.append(
                {
                    "invoice": invoice.name,
                    "membership": membership.name,
                    "member": membership.member,
                    "member_name": membership.member_name,
                    "amount": invoice.grand_total,
                    "currency": invoice.currency,
                    "bank_account": bank_account,
                    "iban": iban,
                    "mandate_reference": mandate_reference,
                }
            )

    if not invoices:
        frappe.throw(_("No unpaid invoices found for this membership"))

    # Check for existing draft batch
    batch = None
    existing_batches = frappe.get_all(
        "SEPA Direct Debit Batch",
        filters={"docstatus": 0, "status": "Draft"},
        order_by="creation desc",
        limit=1,
    )

    if existing_batches:
        batch = frappe.get_doc("SEPA Direct Debit Batch", existing_batches[0].name)
    else:
        # Create new batch
        batch = frappe.new_doc("SEPA Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = f"Membership payments batch - {today()}"
        batch.batch_type = "RCUR"
        batch.currency = invoices[0]["currency"]
        batch.status = "Draft"

    # Add invoices to batch
    for invoice in invoices:
        # Check if invoice already in batch
        existing = False
        for row in batch.invoices:
            if row.invoice == invoice["invoice"]:
                existing = True
                break

        if not existing:
            batch.append(
                "invoices",
                {
                    "invoice": invoice["invoice"],
                    "membership": invoice["membership"],
                    "member": invoice["member"],
                    "member_name": invoice["member_name"],
                    "amount": invoice["amount"],
                    "currency": invoice["currency"],
                    "bank_account": invoice["bank_account"],
                    "iban": invoice["iban"],
                    "mandate_reference": invoice["mandate_reference"],
                    "status": "Pending",
                },
            )

    # Calculate totals
    batch.total_amount = sum(row.amount for row in batch.invoices)
    batch.entry_count = len(batch.invoices)

    batch.save()
