import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.utils.iban_validator import derive_bic_from_iban


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
        from verenigingen.utils.sepa_notifications import SEPAMandateNotificationManager

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
        member = frappe.db.get_value("Membership", {"name": invoice.membership}, "member")

        retry_doc = frappe.new_doc("SEPA Payment Retry")
        retry_doc.invoice = invoice_name
        retry_doc.membership = invoice.membership
        retry_doc.member = member
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
        job_name = f"retry_payment_{retry_record.name}"

        # Remove existing job if any
        frappe.db.delete("Scheduled Job Type", {"job_name": job_name})

        # Create new scheduled job
        scheduled_job = frappe.new_doc("Scheduled Job Type")
        scheduled_job.method = "verenigingen.utils.payment_retry.execute_payment_retry"
        scheduled_job.job_name = job_name
        scheduled_job.frequency = "Daily"
        scheduled_job.parameters = json.dumps({"retry_record": retry_record.name})
        scheduled_job.enabled = 1
        scheduled_job.insert()

        return scheduled_job

    def escalate_payment_failure(self, retry_record):
        """Escalate payment failure after max retries"""
        retry_record.status = "Escalated"
        retry_record.escalated_on = now_datetime()
        retry_record.save()

        # Send notification to administrators
        self.send_escalation_notification(retry_record)

        # Update membership status if needed
        membership = frappe.get_doc("Membership", retry_record.membership)
        if membership.status == "Active":
            membership.payment_status = "Failed"
            membership.add_comment(
                "Comment",
                f"Payment retry failed after {retry_record.retry_count} attempts. Escalated for manual review.",
            )
            membership.save()

    def send_escalation_notification(self, retry_record):
        """Send notification about escalated payment failure"""
        member = frappe.get_doc("Member", retry_record.member)

        # Get admin users
        admins = frappe.get_all("Has Role", filters={"role": "Membership Manager"}, fields=["parent as user"])

        recipients = [admin.user for admin in admins]

        if recipients:
            frappe.sendmail(
                recipients=recipients,
                subject=f"Payment Failure Escalation - {member.full_name}",
                message="""
                <h3>Payment Retry Escalation</h3>
                <p>Payment collection has failed after {retry_record.retry_count} attempts.</p>

                <h4>Member Details:</h4>
                <ul>
                    <li>Name: {member.full_name}</li>
                    <li>Member ID: {member.name}</li>
                    <li>Invoice: {retry_record.invoice}</li>
                    <li>Amount: €{retry_record.original_amount}</li>
                </ul>

                <h4>Failure History:</h4>
                <ul>
                    <li>Last Failure Reason: {retry_record.last_failure_reason}</li>
                    <li>Total Attempts: {retry_record.retry_count}</li>
                </ul>

                <p>Please review and take manual action.</p>
                """,
                delayed=False,
            )


@frappe.whitelist()
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

        # Get active SEPA mandate
        mandate = member.get_active_sepa_mandate()
        if not mandate:
            retry_doc.status = "Failed"
            retry_doc.add_comment("Comment", "No active SEPA mandate found")
            retry_doc.save()
            return

        # Create single invoice batch for retry
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_type = "RCUR"  # Recurring
        batch.description = f"Retry payment for {member.full_name} - Attempt {retry_doc.retry_count}"

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
                "mandate_date": mandate.sign_date,
            },
        )

        batch.insert()
        batch.submit()

        # Update retry record
        retry_doc.last_retry_date = today()
        retry_doc.status = "Retried"
        retry_doc.save()

        # Log the retry
        frappe.logger().info(f"Payment retry executed for invoice {invoice.name}")

    except Exception as e:
        frappe.log_error(f"Payment retry failed: {str(e)}", "Payment Retry Error")
        retry_doc.status = "Error"
        retry_doc.last_error = str(e)
        retry_doc.save()


@frappe.whitelist()
def check_payment_retry_status(invoice):
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
