import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import add_days, getdate, today


class SEPAMandateNotificationManager:
    """Manages notifications for SEPA mandate status changes"""

    def __init__(self):
        self.settings = frappe.get_single("Verenigingen Settings")

    def send_mandate_created_notification(self, mandate):
        """Send notification when a new mandate is created"""
        member = frappe.get_doc("Member", mandate.member)

        if not member.email:
            return

        context = {
            "member_name": member.full_name,
            "mandate_id": mandate.mandate_id,
            "iban": self._mask_iban(mandate.iban),
            "bank_name": self._get_bank_name(mandate.iban),
            "sign_date": frappe.utils.format_date(mandate.sign_date),
            "company_name": self.settings.company_name,
        }

        self._send_email(
            recipients=[member.email],
            subject=_("SEPA Direct Debit Mandate Activated"),
            template="sepa_mandate_created",
            context=context,
            member=member.name,
        )

    def send_mandate_cancelled_notification(self, mandate, reason=None):
        """Send notification when a mandate is cancelled"""
        member = frappe.get_doc("Member", mandate.member)

        if not member.email:
            return

        context = {
            "member_name": member.full_name,
            "mandate_id": mandate.mandate_id,
            "iban": self._mask_iban(mandate.iban),
            "cancellation_date": frappe.utils.format_date(today()),
            "cancellation_reason": reason or _("Cancelled by member request"),
            "company_name": self.settings.company_name,
            "support_email": self.settings.support_email,
        }

        self._send_email(
            recipients=[member.email],
            subject=_("SEPA Direct Debit Mandate Cancelled"),
            template="sepa_mandate_cancelled",
            context=context,
            member=member.name,
        )

    def send_mandate_expiring_notification(self, mandate, days_until_expiry):
        """Send notification when a mandate is about to expire"""
        member = frappe.get_doc("Member", mandate.member)

        if not member.email:
            return

        context = {
            "member_name": member.full_name,
            "mandate_id": mandate.mandate_id,
            "expiry_date": frappe.utils.format_date(mandate.expiry_date),
            "days_until_expiry": days_until_expiry,
            "iban": self._mask_iban(mandate.iban),
            "company_name": self.settings.company_name,
            "renewal_link": f"{frappe.utils.get_url()}/bank_details",
        }

        self._send_email(
            recipients=[member.email],
            subject=_("SEPA Mandate Expiring Soon - Action Required"),
            template="sepa_mandate_expiring",
            context=context,
            member=member.name,
        )

    def send_payment_retry_notification(self, retry_record):
        """Send notification about payment retry attempts"""
        invoice = frappe.get_doc("Sales Invoice", retry_record.invoice)
        member = frappe.get_doc("Member", retry_record.member)

        if not member.email:
            return

        context = {
            "member_name": member.full_name,
            "invoice_number": invoice.name,
            "amount": frappe.utils.fmt_money(retry_record.original_amount, currency="EUR"),
            "retry_date": frappe.utils.format_date(retry_record.next_retry_date),
            "retry_count": retry_record.retry_count,
            "failure_reason": retry_record.last_failure_reason or _("Payment failed"),
            "company_name": self.settings.company_name,
            "payment_link": f"{frappe.utils.get_url()}/payment-dashboard",
        }

        if retry_record.status == "Scheduled":
            self._send_email(
                recipients=[member.email],
                subject=_("Payment Retry Scheduled - {0}").format(invoice.name),
                template="payment_retry_scheduled",
                context=context,
                member=member.name,
            )
        elif retry_record.status == "Failed":
            self._send_email(
                recipients=[member.email],
                subject=_("Payment Failed - Action Required"),
                template="payment_retry_failed",
                context=context,
                member=member.name,
            )

    def send_payment_success_notification(self, payment_entry):
        """Send notification when a payment is successful"""
        if payment_entry.party_type != "Customer":
            return

        # Find member from customer
        member = frappe.db.get_value("Member", {"customer": payment_entry.party}, "name")
        if not member:
            return

        member_doc = frappe.get_doc("Member", member)
        if not member_doc.email:
            return

        context = {
            "member_name": member_doc.full_name,
            "payment_reference": payment_entry.name,
            "amount": frappe.utils.fmt_money(
                payment_entry.paid_amount, currency=payment_entry.paid_to_account_currency
            ),
            "payment_date": frappe.utils.format_date(payment_entry.posting_date),
            "payment_method": payment_entry.mode_of_payment,
            "company_name": self.settings.company_name,
            "receipt_link": f"{frappe.utils.get_url()}/payment-dashboard",
        }

        self._send_email(
            recipients=[member_doc.email],
            subject=_("Payment Received - Thank You"),
            template="payment_success",
            context=context,
            member=member_doc.name,
        )

    def check_and_send_expiry_notifications(self):
        """Check for expiring mandates and send notifications
        Called by scheduler"""

        # Get mandates expiring in 30 days
        thirty_days_ahead = add_days(today(), 30)

        expiring_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"status": "Active", "expiry_date": ["between", [today(), thirty_days_ahead]]},
            fields=["name", "member", "expiry_date", "mandate_id", "iban"],
        )

        for mandate_data in expiring_mandates:
            # Check if we already sent a notification recently
            last_notification = frappe.db.get_value(
                "Communication",
                {
                    "reference_doctype": "SEPA Mandate",
                    "reference_name": mandate_data.name,
                    "communication_type": "Automated Message",
                    "subject": ["like", "%Expiring Soon%"],
                    "creation": [">", add_days(today(), -7)],
                },
                "name",
            )

            if not last_notification:
                days_until_expiry = (getdate(mandate_data.expiry_date) - getdate(today())).days
                mandate = frappe.get_doc("SEPA Mandate", mandate_data.name)
                self.send_mandate_expiring_notification(mandate, days_until_expiry)

    def _send_email(self, recipients, subject, template, context, member=None):
        """Send email using template"""
        try:
            # Get email template
            template_path = f"verenigingen/templates/emails/{template}.html"

            # Add common context
            context.update(
                {
                    "current_year": frappe.utils.now_datetime().year,
                    "website_url": frappe.utils.get_url(),
                    "unsubscribe_link": f"{frappe.utils.get_url()}/email-preferences",
                }
            )

            # Render template
            message = frappe.render_template(template_path, context)

            # Send email
            make(
                recipients=recipients,
                subject=subject,
                content=message,
                send_email=True,
                doctype="Member" if member else None,
                name=member if member else None,
                communication_type="Automated Message",
            )

            # Log the notification
            if member:
                frappe.get_doc(
                    {
                        "doctype": "Comment",
                        "comment_type": "Info",
                        "reference_doctype": "Member",
                        "reference_name": member,
                        "content": f"Notification sent: {subject}",
                    }
                ).insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Failed to send SEPA notification: {str(e)}", f"SEPA Notification Error - {subject}"
            )

    def _mask_iban(self, iban):
        """Mask IBAN for security"""
        if not iban or len(iban) < 8:
            return iban

        # Show first 4 and last 4 characters
        return f"{iban[:4]}****{iban[-4:]}"

    def _get_bank_name(self, iban):
        """Get bank name from IBAN"""
        try:
            from verenigingen.utils.iban_validator import get_bank_from_iban

            bank_info = get_bank_from_iban(iban)
            return bank_info.get("bank_name", "Unknown Bank") if bank_info else "Unknown Bank"
        except Exception:
            return "Unknown Bank"


def check_and_send_expiry_notifications():
    """Scheduled function to check and send expiry notifications"""
    try:
        manager = SEPAMandateNotificationManager()
        manager.check_and_send_expiry_notifications()
    except Exception as e:
        frappe.log_error(f"Failed to check SEPA mandate expiry: {str(e)}", "SEPA Expiry Notification Error")


@frappe.whitelist()
def test_mandate_notification(mandate_id, notification_type="created"):
    """Test function to send a mandate notification"""
    mandate = frappe.get_doc("SEPA Mandate", mandate_id)
    manager = SEPAMandateNotificationManager()

    if notification_type == "created":
        manager.send_mandate_created_notification(mandate)
    elif notification_type == "cancelled":
        manager.send_mandate_cancelled_notification(mandate, "Test cancellation")
    elif notification_type == "expiring":
        manager.send_mandate_expiring_notification(mandate, 15)

    return {"success": True, "message": f"Test notification sent for {notification_type}"}
