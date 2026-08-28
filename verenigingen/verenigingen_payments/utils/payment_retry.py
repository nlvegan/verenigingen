import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.validation.iban_validator import derive_bic_from_iban
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config
from verenigingen.verenigingen_payments.utils.mandate_candidates import unambiguous_active_mandate
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


# Cap for one daily sweep. See the comment at the query for why an unbounded
# get_all on a 300s queue is the wrong shape for a path that moves money.
DAILY_RETRY_SWEEP_LIMIT = 200


def _discard_unsent_retry_batch(batch_name):
    """Remove a retry batch whose submit failed before any SEPA file was produced.

    What makes this safe is the caller's rollback, not this check. `batch_name` is
    always a batch this same call created moments earlier; the fence committed it as
    an EMPTY DRAFT, and everything submit() did afterwards -- the docstatus flip,
    sepa_message_id, sepa_file, sepa_file_generated, the attached File -- is written
    with db_set(commit=False) and is undone by that rollback. What remains is exactly
    the empty draft the fence committed, so deleting it is correct.

    This is NOT about money already moving: Direct Debit Batch has no transmission
    path. on_submit only generates and attaches an XML file, which a human later
    downloads and takes to the bank -- and nobody can have done so in the
    milliseconds between generation and the exception.

    The field check is defence in depth for a future change: if some path inside
    generation ever commits its own writes, they would survive the rollback and a
    file could outlive the transaction. Then leave the batch alone and let a human
    reconcile it -- the Error status and the logged traceback are how they find it.
    `sepa_message_id` is written BEFORE the XML is built and `sepa_file_generated`
    after it, so the pair errs toward keeping.
    """
    if not batch_name:
        return
    row = frappe.db.get_value(
        "Direct Debit Batch",
        batch_name,
        ["docstatus", "sepa_message_id", "sepa_file_generated"],
        as_dict=True,
    )
    if not row or row.docstatus != 0 or row.sepa_message_id or row.sepa_file_generated:
        return
    # Security: ignore_permissions is required because this runs from the daily
    # scheduler, where frappe.session.user is Administrator-less background context and
    # no interactive user holds delete rights on Direct Debit Batch. The bypass is
    # tightly bounded -- the target is a batch this same function created moments
    # earlier, still draft, carrying no generated SEPA file, identified by a name the
    # caller never supplies. It cannot reach any batch that exists independently.
    frappe.delete_doc(
        "Direct Debit Batch", batch_name, force=True, ignore_permissions=True, delete_permanently=True
    )
    # Commit the release so it survives a later failure in this same handler: the
    # sweep's per-record rollback would otherwise undo the delete and strand the batch
    # again, which is the exact thing this function exists to prevent.
    frappe.db.commit()


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def execute_payment_retry(retry_record=None):
    """Execute a scheduled payment retry"""
    if not retry_record:
        return

    retry_doc = frappe.get_doc("SEPA Payment Retry", retry_record)
    batch_name = None

    # Not yet due. The guard is one-sided on purpose: a retry must never run
    # BEFORE its scheduled date, but an OVERDUE one must still run. The daily
    # sweep selects next_retry_date <= today so that a date the scheduler missed
    # (an outage, a timezone day-roll) is picked up on the next run; an equality
    # test here would silently drop exactly the records the sweep exists to
    # rescue, which is #622 narrowed rather than fixed.
    if getdate(retry_doc.next_retry_date) > getdate(today()):
        return

    # Check if already processed today
    if retry_doc.last_retry_date and getdate(retry_doc.last_retry_date) == getdate(today()):
        return

    try:
        # Get invoice and create new direct debit batch
        invoice = frappe.get_doc("Sales Invoice", retry_doc.invoice)
        membership = frappe.get_doc("Membership", retry_doc.membership)
        member = frappe.get_doc("Member", retry_doc.member)

        # The member's single Active MEMBERSHIP mandate. This retries a membership
        # invoice -- the Membership document is loaded two lines above -- and the
        # mandate chosen here supplies the `iban` that is debited by the batch this
        # function SUBMITS, so it must not be a guess.
        #
        # It was `member.get_active_sepa_mandates()[0]`: `order_by="creation desc"`
        # with no purpose filter, taking the first row. A member may legitimately
        # hold an Active membership mandate and an Active donation mandate at once
        # (#584), so for that member this debited whichever account was registered
        # most recently (#605). `unambiguous_active_mandate` filters by purpose and
        # REFUSES rather than orders when a choice remains.
        choice = unambiguous_active_mandate(member.name, "Payment retry mandate resolution")
        if not choice:
            retry_doc.status = "Failed"
            # A refusal is not "none found". Collapsing the two is how #581 billed a
            # member a third period: an operator reading "no mandate" creates one,
            # which makes the ambiguity worse rather than resolving it.
            retry_doc.add_comment(
                "Comment",
                "Member has more than one Active SEPA mandate for memberships; "
                "cancel all but one before this retry can be collected."
                if choice.is_ambiguous
                else "No active SEPA mandate found",
            )
            retry_doc.save()
            return

        mandate = frappe.get_doc("SEPA Mandate", choice.mandate["name"])

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
        batch_name = batch.name

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
        # Discard the failed submit's own writes first. The fence commit above is the
        # transaction boundary, so this cannot lose the retry record -- it undoes only
        # what batch.submit() got through before raising.
        frappe.db.rollback()

        # A stranded batch locks the invoice out of EVERY future retry: the guard above
        # matches any Direct Debit Batch with docstatus != 2, so a batch left behind by
        # a failed attempt is indistinguishable from one that is genuinely collecting,
        # and the daily sweep, the enqueued job and the desk button will all refuse the
        # invoice from then on. Before the daily sweep existed this needed a human to
        # press the button, one record at a time; now it happens unattended.
        _discard_unsent_retry_batch(batch_name)

        # Re-read: the rollback discarded the in-memory doc's uncommitted state, so
        # saving the stale object would raise TimestampMismatchError over the real one.
        retry_doc = frappe.get_doc("SEPA Payment Retry", retry_doc.name)
        frappe.log_error(f"Payment retry failed: {str(e)}", "Payment Retry Error")
        retry_doc.status = "Error"
        retry_doc.last_error = str(e)
        retry_doc.save()


def execute_scheduled_payment_retries():
    """Daily scheduler entry: execute every payment retry that is due.

    Frappe runs a ``scheduler_events`` entry with NO arguments --
    ``ScheduledJobType.execute`` does ``frappe.get_attr(self.method)()`` -- so
    ``execute_payment_retry`` cannot be registered directly: its ``retry_record``
    would be None and it would return on its first line. That is why no scheduled
    retry ever ran (#622). This sweep is the entry point; it supplies the record.

    ``create_retry_job`` cannot stand in for it. It enqueues the retry
    immediately, but ``calculate_next_retry_date`` puts ``next_retry_date`` at
    least ``retry_intervals[0]`` = 3 days out, so that job always lands before
    the record is due and is filtered out by the guard in
    ``execute_payment_retry``. Without this sweep the only path that reaches the
    body is a human pressing "Retry Payment Now" on each record.
    """
    due = frappe.get_all(
        "SEPA Payment Retry",
        filters={
            "status": "Scheduled",
            # getdate()/today() are site-timezone; the machine clock can name a
            # different calendar day (#628).
            "next_retry_date": ["<=", getdate(today())],
        },
        pluck="name",
        order_by="next_retry_date asc, creation asc",
        # frappe.get_all forces limit_page_length=0 (unlimited) when it is not given,
        # despite its own docstring. A Daily scheduler entry runs on the `default`
        # queue, whose timeout is 300s (`long` gets 1500s) -- and each record here
        # inserts, saves, commits, submits and generates a SEPA XML file. An
        # unbounded first run over an accumulated backlog would be killed mid-loop by
        # RQ, stranding the in-flight record's batch. The sweep is idempotent day to
        # day, so a cap costs only latency: what it does not reach today it reaches
        # tomorrow, oldest first.
        limit_page_length=DAILY_RETRY_SWEEP_LIMIT,
    )
    if len(due) == DAILY_RETRY_SWEEP_LIMIT:
        # Say so rather than silently truncating -- a capped run must not read as
        # "everything was collected".
        print(
            f"execute_scheduled_payment_retries: hit the {DAILY_RETRY_SWEEP_LIMIT}-record "
            "cap; the remainder is picked up by the next daily run."
        )

    errors = 0
    for name in due:
        try:
            execute_payment_retry(retry_record=name)
        except Exception:
            # Isolate the record. This path moves money one record at a time, and
            # a single bad row -- deleted between the query and the call, or a
            # save conflict -- must not strand the rest of the day's retries.
            # The traceback goes in `message`: log_error treats a non-traceback
            # message AS the traceback, so passing anything else discards the
            # real one.
            errors += 1
            # Isolation needs the rollback, not just the `except`: execute_payment_retry
            # commits its own fence, so anything it wrote after that point is still
            # open when it raises, and the NEXT record's commit would otherwise adopt
            # it. Safe here -- the sweep itself only read before the loop, and every
            # record that succeeded has already committed.
            frappe.db.rollback()
            frappe.log_error(
                title=f"Scheduled payment retry failed: {name}",
                message=frappe.get_traceback(with_context=True),
            )

    return {"due": len(due), "errors": errors}


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
