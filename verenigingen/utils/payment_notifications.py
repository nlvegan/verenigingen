import frappe


def on_payment_submit(doc, method):
    """Handle payment submission and send notifications"""
    try:
        # Check if this is a member payment
        if doc.party_type == "Customer" and doc.paid_amount > 0:
            # Check if this payment is for a member
            member = frappe.db.get_value("Member", {"customer": doc.party}, "name")

            if member:
                # Send payment success notification
                from verenigingen.utils.sepa_notifications import SEPAMandateNotificationManager

                notification_manager = SEPAMandateNotificationManager()
                notification_manager.send_payment_success_notification(doc)

                # Check if this resolves any failed payment retries
                check_and_resolve_payment_retries(doc, member)

    except Exception as e:
        # Log error but don't block payment submission
        frappe.log_error(f"Failed to send payment notification: {str(e)}", "Payment Notification Error")


def check_and_resolve_payment_retries(payment_entry, member):
    """Check if this payment resolves any failed payment retries"""

    # Find open payment retries for this member
    open_retries = frappe.get_all(
        "SEPA Payment Retry",
        filters={"member": member, "status": ["in", ["Scheduled", "Failed", "Pending"]]},
        fields=["name", "invoice", "original_amount"],
    )

    for retry in open_retries:
        # Check if this payment is for the same invoice
        if payment_entry.references:
            for ref in payment_entry.references:
                if ref.reference_doctype == "Sales Invoice" and ref.reference_name == retry.invoice:
                    # Mark retry as resolved
                    retry_doc = frappe.get_doc("SEPA Payment Retry", retry.name)
                    retry_doc.status = "Resolved"
                    retry_doc.resolution_date = payment_entry.posting_date
                    retry_doc.resolution_method = "Payment Received"
                    retry_doc.resolution_reference = payment_entry.name

                    # Add to retry log
                    retry_doc.append(
                        "retry_log",
                        {
                            "attempt_date": frappe.utils.now_datetime(),
                            "reason_code": "SUCCESS",
                            "reason_message": f"Payment received via {payment_entry.mode_of_payment}",
                            "payment_reference": payment_entry.name,
                        },
                    )

                    retry_doc.save(ignore_permissions=True)

                    # Update the sales invoice status if needed
                    invoice = frappe.get_doc("Sales Invoice", retry.invoice)
                    if invoice.outstanding_amount == 0:
                        frappe.db.set_value("Sales Invoice", retry.invoice, "status", "Paid")

                    break
