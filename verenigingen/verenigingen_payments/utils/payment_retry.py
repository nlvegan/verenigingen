import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.validation.iban_validator import derive_bic_from_iban
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config
from verenigingen.verenigingen_payments.utils.shared.recipient_resolver import get_recipients_by_roles


class PaymentRetryManager:
    """Manages automated retry logic for failed SEPA payments"""

    def __init__(self):
        self.settings = frappe.get_single("Verenigingen Settings")
        self.retry_config = self.get_retry_config()

    def get_retry_config(self):
        """Get retry configuration from settings or use defaults"""
        return {
            "max_retries": getattr(self.settings, "sepa_max_retries", 3),
            "retry_intervals": [3, 7, 14],  # Days between retries
            "skip_weekends": True,
            "skip_holidays": True,
            "retry_time": "10:00:00",  # Best time for SEPA processing
            "escalate_after": 2,  # Escalate after X failures
        }

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def schedule_retry(self, failed_invoice, reason_code=None, reason_message=None):
        """Schedule a retry for a failed payment"""

        # Get or create retry record
        retry_record = self.get_or_create_retry_record(failed_invoice)

        if retry_record.retry_count >= self.retry_config["max_retries"]:
            self.escalate_payment_failure(retry_record)
            return {"scheduled": False, "message": _("Maximum retry attempts reached. Payment escalated.")}

        # Calculate next retry date
        next_retry_date = self.calculate_next_retry_date(retry_record)

        # Update retry record
        retry_record.retry_count += 1
        retry_record.next_retry_date = next_retry_date
        retry_record.last_failure_reason = reason_code or "Unknown"
        retry_record.last_failure_message = reason_message or "Payment failed"
        retry_record.status = "Scheduled"

        # Add to retry log
        retry_record.append(
            "retry_log",
            {
                "attempt_date": now_datetime(),
                "reason_code": reason_code,
                "reason_message": reason_message,
                "scheduled_retry": next_retry_date,
            },
        )

        retry_record.save()

        # Create scheduled job
        self.create_retry_job(retry_record)

        # Send notification about scheduled retry
        from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager

        notification_manager = SEPAMandateNotificationManager()
        notification_manager.send_payment_retry_notification(retry_record)

        return {
            "scheduled": True,
            "next_retry": next_retry_date,
            "attempt_number": retry_record.retry_count,
            "message": _("Payment retry scheduled for {0}").format(next_retry_date),
        }

    def get_or_create_retry_record(self, invoice_name):
        """Get existing retry record or create new one"""
        existing = frappe.db.exists("SEPA Payment Retry", {"invoice": invoice_name})

        if existing:
            return frappe.get_doc("SEPA Payment Retry", existing)

        # Create new retry record
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Find member through Customer link (Sales Invoice -> Customer -> Member)
        member = frappe.db.get_value("Member", {"customer": invoice.customer}, "name")

        # Find active membership for the member (if any)
        membership = None
        if member:
            membership = frappe.db.get_value(
                "Membership", {"member": member, "status": "Active"}, "name", order_by="start_date desc"
            )

        retry_doc = frappe.new_doc("SEPA Payment Retry")
        retry_doc.invoice = invoice_name
        retry_doc.membership = membership  # Can be None if no active membership
        retry_doc.member = member  # Can be None if not linked to a member
        retry_doc.original_amount = invoice.outstanding_amount
        retry_doc.retry_count = 0
        retry_doc.status = "Pending"
        retry_doc.insert()

        return retry_doc

    def calculate_next_retry_date(self, retry_record):
        """Calculate next retry date based on retry count and configuration"""

        # Get interval for this retry attempt
        interval_index = min(retry_record.retry_count, len(self.retry_config["retry_intervals"]) - 1)
        days_to_add = self.retry_config["retry_intervals"][interval_index]

        # Start from today
        next_date = add_days(today(), days_to_add)

        # Skip weekends if configured
        if self.retry_config["skip_weekends"]:
            next_date = self.get_next_business_day(next_date)

        # Skip holidays if configured
        if self.retry_config["skip_holidays"]:
            next_date = self.skip_holidays(next_date)

        return next_date

    def get_next_business_day(self, date):
        """Get next business day (Mon-Fri)"""
        date_obj = getdate(date)

        # 5 = Saturday, 6 = Sunday
        while date_obj.weekday() >= 5:
            date_obj = date_obj + timedelta(days=1)

        return date_obj

    def skip_holidays(self, date):
        """Skip holidays based on holiday list"""
        holiday_list = getattr(self.settings, "holiday_list", None)

        if not holiday_list:
            return date

        holidays = frappe.get_all(
            "Holiday",
            filters={"parent": holiday_list, "holiday_date": [">=", date]},
            fields=["holiday_date"],
            order_by="holiday_date",
        )

        holiday_dates = [h.holiday_date for h in holidays]

        date_obj = getdate(date)
        while date_obj in holiday_dates:
            date_obj = date_obj + timedelta(days=1)
            # Also check if new date is weekend
            date_obj = self.get_next_business_day(date_obj)

        return date_obj

    def create_retry_job(self, retry_record):
        """Create scheduled job for payment retry"""
        # Use frappe.enqueue instead of Scheduled Job Type which has a different schema
        # This is simpler and doesn't require custom fields on core DocTypes
        retry_record.status = "Scheduled"
        retry_record.save()

        try:
            frappe.enqueue(
                "verenigingen.verenigingen_payments.utils.payment_retry.execute_payment_retry",
                retry_record=retry_record.name,
                queue="default",
                now=False,
                enqueue_after_commit=True,
            )
        except Exception:
            frappe.log_error("Payment retry enqueue failed", f"Retry record: {retry_record.name}")
            retry_record.status = "Pending"
            retry_record.save()
            return {"job_scheduled": False, "retry_record": retry_record.name}

        return {"job_scheduled": True, "retry_record": retry_record.name}

    def escalate_payment_failure(self, retry_record):
        """Escalate payment failure after max retries"""
        retry_record.status = "Escalated"
        retry_record.escalated_on = now_datetime()
        retry_record.save()

        # Send notification to administrators
        self.send_escalation_notification(retry_record)

        # Add comment to membership for audit trail
        membership = frappe.get_doc("Membership", retry_record.membership)
        membership.add_comment(
            "Comment",
            f"Payment retry failed after {retry_record.retry_count} attempts. Escalated for manual review.",
        )
        membership.save()

    def send_escalation_notification(self, retry_record):
        """Send notification about escalated payment failure"""
        member = frappe.get_doc("Member", retry_record.member)

        # Resolve escalation recipients via shared resolver (enabled users with email holding
        # the Verenigingen Staff role).  The original queried Has Role directly returning user
        # names; the resolver returns email addresses for enabled users only.
        recipients = get_recipients_by_roles([Roles.VERENIGINGEN_STAFF])

        if recipients:
            # MIGRATED: Use unified EmailService with payment notification template
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()

            context = {
                "member_name": Roles.VERENIGINGEN_STAFF,
                "notification_message": f"Payment collection has failed after {retry_record.retry_count} attempts for member {member.full_name}.",
                "payment_reference": retry_record.invoice,
                "amount": f"€{retry_record.original_amount}",
                "payment_date": str(frappe.utils.today()),
                "payment_method": "Failed Payment Retry",
                "action_required": f"Member: {member.full_name} (ID: {member.name}). Last Failure Reason: {retry_record.last_failure_reason}. Total Attempts: {retry_record.retry_count}.",
                "next_steps": "Please review and take manual action to resolve the payment failure.",
                "company": get_mollie_config().get_default_company(),
            }

            email_service.send_templated_email(
                template_name="payment_notification",
                recipients=recipients,
                context=context,
                subject_override=f"Payment Failure Escalation - {member.full_name}",
                reference_doctype="Member",
                reference_name=member.name,
                priority="high",
                notification_key="payment_failure_final",
            )


def _invoice_in_open_batch(invoice_name):
    """Return True if the invoice is already in a live (non-cancelled) Direct
    Debit Batch.

    Mirrors the exclusion used by the monthly batch flow in
    ``sepa_mandate_service.get_unpaid_sepa_invoices`` (Direct Debit Batch Invoice
    joined to its parent Direct Debit Batch, parent ``docstatus != 2``). Used as
    the double-charge guard in ``execute_payment_retry``.
    """
    return bool(
        frappe.db.sql(
            """
            SELECT 1
            FROM `tabDirect Debit Batch Invoice` ddi
            JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
            WHERE ddi.invoice = %s AND ddb.docstatus != 2
            LIMIT 1
            """,
            invoice_name,
        )
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def execute_payment_retry(retry_record=None):
    """Execute a scheduled payment retry"""
    if not retry_record:
        return

    retry_doc = frappe.get_doc("SEPA Payment Retry", retry_record)

    # Check if retry should be executed today
    if getdate(retry_doc.next_retry_date) != getdate(today()):
        return

    # Check if already processed today
    if retry_doc.last_retry_date and getdate(retry_doc.last_retry_date) == getdate(today()):
        return

    try:
        # Get invoice and create new direct debit batch
        invoice = frappe.get_doc("Sales Invoice", retry_doc.invoice)
        membership = frappe.get_doc("Membership", retry_doc.membership)
        member = frappe.get_doc("Member", retry_doc.member)

        # Get active SEPA mandate. get_active_sepa_mandates() (plural) returns a
        # list of active mandates; mirror other callers (e.g. member_utils) by
        # selecting the first (most recent active) one. The list entries are
        # lightweight _dicts, so reload the full mandate doc for iban/bic/sign_date.
        active_mandates = member.get_active_sepa_mandates()
        if not active_mandates:
            retry_doc.status = "Failed"
            retry_doc.add_comment("Comment", "No active SEPA mandate found")
            retry_doc.save()
            return

        mandate = frappe.get_doc("SEPA Mandate", active_mandates[0].name)

        # IDEMPOTENCY GUARD: refuse to create a second Direct Debit Batch for an
        # invoice that is already in a live (non-cancelled) batch. This submitted
        # path MOVES MONEY, so a redelivered RQ job, a manual re-run, or a crash
        # between batch.submit() and the last_retry_date save below could
        # otherwise debit the member twice. Mirrors the exclusion the monthly
        # batch flow applies in sepa_mandate_service.get_unpaid_sepa_invoices
        # (Direct Debit Batch Invoice -> Direct Debit Batch on docstatus != 2).
        if _invoice_in_open_batch(invoice.name):
            retry_doc.last_retry_date = today()
            retry_doc.status = "Failed"
            retry_doc.add_comment(
                "Comment",
                "Invoice already present in an open Direct Debit Batch; "
                "skipped retry to avoid a double charge.",
            )
            retry_doc.save()
            return

        # Derive the SEPA sequence type from the mandate's collection history
        # instead of hardcoding RCUR: a retry of an invoice whose mandate has
        # never had a successfully Collected usage (or was renewed since) must be
        # FRST, not RCUR. Reuse the shared helper used by the batch processor.
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            get_mandate_sequence_type,
        )

        sequence_info = get_mandate_sequence_type(mandate.name, invoice.name)
        sequence_type = sequence_info["sequence_type"]

        # Create single invoice batch for retry
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = sequence_type  # SeqTp derived from mandate usage
        batch.batch_description = f"Retry payment for {member.full_name} - Attempt {retry_doc.retry_count}"

        # Add invoice to batch
        batch.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": membership.name,
                "member": member.name,
                "member_name": member.full_name,
                "amount": invoice.outstanding_amount,
                "currency": invoice.currency,
                "iban": mandate.iban,
                "bic": mandate.bic or derive_bic_from_iban(mandate.iban),
                "mandate_reference": mandate.mandate_id,
                "mandate_sign_date": mandate.sign_date,
                "sequence_type": sequence_type,
            },
        )

        batch.insert()

        # Fence concurrent runs BEFORE submit: record the terminal retry state and
        # commit so that a redelivered/duplicate job sees last_retry_date == today
        # (guarded out above) and the just-created batch is visible to the
        # open-batch check. Submit only after the fence is durably in place.
        retry_doc.last_retry_date = today()
        retry_doc.status = "Retried"
        retry_doc.save()
        frappe.db.commit()

        batch.submit()

        # Log the retry
        frappe.logger().info(f"Payment retry executed for invoice {invoice.name}")

    except Exception as e:
        frappe.log_error(f"Payment retry failed: {str(e)}", "Payment Retry Error")
        retry_doc.status = "Error"
        retry_doc.last_error = str(e)
        retry_doc.save()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def check_payment_retry_status(invoice: str):
    """Check if an invoice has retry scheduled"""
    retry = frappe.db.exists("SEPA Payment Retry", {"invoice": invoice})

    if not retry:
        return {"has_retry": False}

    retry_doc = frappe.get_doc("SEPA Payment Retry", retry)

    return {
        "has_retry": True,
        "retry_count": retry_doc.retry_count,
        "next_retry": retry_doc.next_retry_date,
        "status": retry_doc.status,
        "max_retries_reached": retry_doc.retry_count >= 3,
    }
