import frappe
from frappe import _
from frappe.utils import today


def sync_membership_with_subscription(membership_doc):
    """
    Synchronize membership with ERPNext subscription
    - Update payment status based on subscription invoices
    - Track payment history
    """
    if not membership_doc.subscription:
        return

    subscription = frappe.get_doc("Subscription", membership_doc.subscription)

    # Get invoices linked to this subscription
    invoices = frappe.get_all(
        "Subscription Invoice",
        filters={"subscription": subscription.name},
        fields=["invoice", "status"],
        order_by="creation desc",
    )

    if not invoices:
        return

    # Check latest invoice status
    latest_invoice = invoices[0]
    invoice_doc = frappe.get_doc("Sales Invoice", latest_invoice.invoice)

    # Update membership payment status based on invoice
    if invoice_doc.status == "Paid":
        membership_doc.payment_status = "Paid"
        membership_doc.paid_amount = invoice_doc.grand_total
        membership_doc.payment_date = invoice_doc.posting_date
    elif invoice_doc.status == "Overdue":
        membership_doc.payment_status = "Overdue"
    elif invoice_doc.status == "Return":
        membership_doc.payment_status = "Refunded"
    else:
        membership_doc.payment_status = "Unpaid"

    # Save membership document
    membership_doc.flags.ignore_validate_update_after_submit = True
    membership_doc.save()

    # Return information about linked invoices for display
    return invoices


def get_membership_payment_history(membership_doc):
    """
    Get payment history for a membership from linked subscription
    """
    if not membership_doc.subscription:
        return []

    # Get invoices from subscription
    invoices = frappe.get_all(
        "Subscription Invoice",
        filters={"subscription": membership_doc.subscription},
        fields=["invoice", "status", "creation"],
        order_by="creation desc",
    )

    payment_history = []

    for invoice_info in invoices:
        invoice = frappe.get_doc("Sales Invoice", invoice_info.invoice)

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

    # Find all unpaid invoices linked to membership subscriptions
    unpaid_invoices = []

    # Get all active memberships with subscriptions
    memberships = frappe.get_all(
        "Membership",
        filters={
            "status": "Active",
            "payment_status": "Unpaid",
            "subscription": ["is", "set"],
            "payment_method": "SEPA Direct Debit",
        },
        fields=["name", "subscription", "member", "member_name"],
    )

    for membership in memberships:
        # Get unpaid invoices from subscription
        invoices = frappe.get_all(
            "Subscription Invoice",
            filters={"subscription": membership.subscription},
            fields=["invoice"],
            order_by="creation desc",
        )

        for invoice_info in invoices:
            invoice = frappe.get_doc("Sales Invoice", invoice_info.invoice)

            if invoice.status == "Unpaid" or invoice.status == "Overdue":
                # Get bank details from member
                member = frappe.get_doc("Member", membership.member)
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
    # Get all active memberships with subscriptions
    memberships = frappe.get_all(
        "Membership",
        filters={
            "status": ["in", ["Active", "Pending"]],
            "payment_status": "Unpaid",
            "subscription": ["is", "set"],
            "payment_method": "SEPA Direct Debit",
        },
        fields=["name", "subscription", "member", "member_name"],
    )

    if not memberships:
        return []

    unpaid_invoices = []

    for membership in memberships:
        # Get unpaid invoices from subscription
        invoices = frappe.get_all(
            "Subscription Invoice",
            filters={"subscription": membership.subscription},
            fields=["invoice"],
            order_by="creation desc",
        )

        for invoice_info in invoices:
            # Check if invoice is unpaid
            invoice = frappe.get_doc("Sales Invoice", invoice_info.invoice)

            if invoice.status in ["Unpaid", "Overdue"]:
                # Get bank details from member
                bank_account = ""
                iban = ""
                mandate_reference = ""

                # Try to get bank details from member
                # This is a placeholder - replace with your actual implementation
                # You could store these in custom fields or in a separate doctype
                member_doc = frappe.get_doc("Member", membership.member)

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

    if not membership.subscription:
        frappe.throw(_("Membership must have a subscription to add to direct debit batch"))

    if membership.payment_status != "Unpaid":
        frappe.throw(_("Membership is already paid"))

    if membership.payment_method != "SEPA Direct Debit":
        frappe.throw(_("Membership payment method must be SEPA Direct Debit"))

    # Get unpaid invoices for this membership
    invoices = []
    subscription_invoices = frappe.get_all(
        "Subscription Invoice",
        filters={"subscription": membership.subscription},
        fields=["invoice"],
        order_by="creation desc",
    )

    for invoice_info in subscription_invoices:
        invoice = frappe.get_doc("Sales Invoice", invoice_info.invoice)

        if invoice.status in ["Unpaid", "Overdue"]:
            # Get bank details
            # Replace with your actual implementation
            member = frappe.get_doc("Member", membership.member)
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
