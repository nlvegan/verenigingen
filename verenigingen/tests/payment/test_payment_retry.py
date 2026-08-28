"""
Real-integration tests for
verenigingen/verenigingen_payments/utils/payment_retry.py
(previously ~0% coverage).

This module manages automated retry scheduling for failed SEPA payments via the
``PaymentRetryManager`` class plus three module-level whitelisted entrypoints:
``execute_payment_retry``, ``check_payment_retry_status`` and (indirectly)
``schedule_retry``.

Approach
--------
* The pure-logic surface (retry config, next-retry-date computation, weekend /
  holiday skipping, get-or-create of the SEPA Payment Retry record) is exercised
  against REAL Member / Customer / Sales Invoice / Membership / SEPA Payment
  Retry documents built with the SEPA/enhanced factories. No business logic is
  mocked.
* The ONLY boundaries stubbed are genuinely external/side-effecting ones:
  - ``frappe.enqueue`` inside ``create_retry_job`` (backgrounds work),
  - the SEPA / escalation notification managers (email sends),
  so that scheduling state transitions can be asserted deterministically without
  a worker or SMTP.
* Date-dependent assertions patch ``today()``-derived inputs only via real config
  (retry_config dict on the manager instance) — never by asserting ambient site
  date.

Tests run as Administrator, satisfying the @critical_api(FINANCIAL) gates.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.utils import payment_retry as retry
from verenigingen.verenigingen_payments.utils.payment_retry import PaymentRetryManager


class RetryBase(EnhancedTestCase):
    """Shared fixtures for payment-retry tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.company = self._company
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.manager = PaymentRetryManager()

    # --- fixture builders -------------------------------------------------

    def _make_member_with_customer(self, first_name="Retry"):
        member = self.sepa.create_test_member(first_name=first_name)
        if not member.customer:
            customer = self.sepa.create_test_customer(
                customer_name=f"Cust {member.full_name}"
            ).name
            member.db_set("customer", customer)
            member.reload()
        # Back-reference so get_or_create_retry_record resolves the member via
        # Member.customer lookup.
        frappe.db.set_value("Customer", member.customer, "member", member.name)
        return member

    def _make_unpaid_invoice(self, member, grand_total=25.0):
        si = self.sepa.create_test_sales_invoice(
            customer=member.customer,
            member=member.name,
            grand_total=grand_total,
            status="Unpaid",
            company=self.company,
            submit=True,
        )
        si.reload()
        return si

    def _make_retry_record(self, member, invoice, **kwargs):
        """Persist a SEPA Payment Retry directly (helper-only DB write)."""
        doc = frappe.new_doc("SEPA Payment Retry")
        doc.invoice = invoice.name
        doc.member = member.name
        doc.original_amount = kwargs.pop("original_amount", invoice.outstanding_amount)
        doc.retry_count = kwargs.pop("retry_count", 0)
        doc.status = kwargs.pop("status", "Pending")
        for k, v in kwargs.items():
            setattr(doc, k, v)
        doc.insert(ignore_permissions=True)
        return doc


# =============================================================================
# PaymentRetryManager.get_retry_config
# =============================================================================
class TestRetryConfig(RetryBase):
    def test_config_defaults(self):
        cfg = self.manager.get_retry_config()
        self.assertEqual(cfg["retry_intervals"], [3, 7, 14])
        self.assertTrue(cfg["skip_weekends"])
        self.assertTrue(cfg["skip_holidays"])
        self.assertIn("max_retries", cfg)

    def test_max_retries_reads_setting(self):
        """max_retries comes from sepa_max_retries on Verenigingen Settings (or 3
        default). Patch the in-memory settings attribute (config boundary)."""
        self.manager.settings.sepa_max_retries = 5
        cfg = self.manager.get_retry_config()
        self.assertEqual(cfg["max_retries"], 5)


# =============================================================================
# calculate_next_retry_date / business-day / holiday logic
# =============================================================================
class TestNextRetryDate(RetryBase):
    def _record_with_count(self, count):
        rec = frappe._dict(retry_count=count)
        return rec

    def test_interval_index_clamped_to_last(self):
        """retry_count beyond the interval list clamps to the last interval (14
        days). We disable weekend/holiday skipping to isolate the interval math."""
        self.manager.retry_config["skip_weekends"] = False
        self.manager.retry_config["skip_holidays"] = False
        nd = self.manager.calculate_next_retry_date(self._record_with_count(10))
        self.assertEqual(getdate(nd), getdate(add_days(today(), 14)))

    def test_first_retry_uses_first_interval(self):
        self.manager.retry_config["skip_weekends"] = False
        self.manager.retry_config["skip_holidays"] = False
        nd = self.manager.calculate_next_retry_date(self._record_with_count(0))
        self.assertEqual(getdate(nd), getdate(add_days(today(), 3)))

    def test_second_retry_uses_second_interval(self):
        self.manager.retry_config["skip_weekends"] = False
        self.manager.retry_config["skip_holidays"] = False
        nd = self.manager.calculate_next_retry_date(self._record_with_count(1))
        self.assertEqual(getdate(nd), getdate(add_days(today(), 7)))

    def test_get_next_business_day_pushes_weekend_to_monday(self):
        # 2025-01-04 is a Saturday; expect Monday 2025-01-06.
        result = self.manager.get_next_business_day(date(2025, 1, 4))
        self.assertEqual(result.weekday(), 0)
        self.assertEqual(result, date(2025, 1, 6))

    def test_get_next_business_day_keeps_weekday(self):
        # 2025-01-07 is a Tuesday; unchanged.
        result = self.manager.get_next_business_day(date(2025, 1, 7))
        self.assertEqual(result, date(2025, 1, 7))

    def test_weekend_skipping_applied_in_calculation(self):
        """With skip_weekends on, the resulting date is never Sat/Sun."""
        self.manager.retry_config["skip_holidays"] = False
        nd = self.manager.calculate_next_retry_date(self._record_with_count(0))
        self.assertLess(getdate(nd).weekday(), 5)

    def test_skip_holidays_noop_without_holiday_list(self):
        """No holiday_list configured -> skip_holidays returns the date
        unchanged."""
        self.manager.settings.holiday_list = None
        d = date(2025, 1, 7)
        self.assertEqual(self.manager.skip_holidays(d), d)

    def test_skip_holidays_advances_past_holiday(self):
        """A holiday on the candidate date is skipped to the next non-holiday
        business day. We build a real Holiday List + Holiday and point the
        manager's settings at it (config boundary)."""
        holiday_list = self._make_holiday_list_with(date(2025, 1, 7))
        self.manager.settings.holiday_list = holiday_list
        result = self.manager.skip_holidays(date(2025, 1, 7))
        self.assertNotEqual(getdate(result), date(2025, 1, 7))
        self.assertGreater(getdate(result), date(2025, 1, 7))

    def _make_holiday_list_with(self, holiday_date):
        name = f"Test Holidays {frappe.generate_hash(length=6)}"
        hl = frappe.new_doc("Holiday List")
        hl.holiday_list_name = name
        hl.from_date = date(2025, 1, 1)
        hl.to_date = date(2025, 12, 31)
        hl.append(
            "holidays", {"holiday_date": holiday_date, "description": "Test Holiday"}
        )
        hl.insert(ignore_permissions=True)
        return hl.name


# =============================================================================
# get_or_create_retry_record
# =============================================================================
class TestGetOrCreateRetryRecord(RetryBase):
    def test_creates_record_resolving_member(self):
        member = self._make_member_with_customer("GoC")
        invoice = self._make_unpaid_invoice(member)

        rec = self.manager.get_or_create_retry_record(invoice.name)
        self.assertEqual(rec.invoice, invoice.name)
        self.assertEqual(rec.member, member.name)
        self.assertEqual(rec.retry_count, 0)
        self.assertEqual(rec.status, "Pending")
        self.assertEqual(rec.original_amount, invoice.outstanding_amount)

    def test_returns_existing_record(self):
        member = self._make_member_with_customer("Existing")
        invoice = self._make_unpaid_invoice(member)
        first = self.manager.get_or_create_retry_record(invoice.name)
        second = self.manager.get_or_create_retry_record(invoice.name)
        self.assertEqual(first.name, second.name)

    def test_creates_record_when_member_unlinked(self):
        """Invoice whose customer has no Member back-reference -> member/
        membership stay None but the record is still created."""
        customer = self.sepa.create_test_customer(
            customer_name=f"Orphan {frappe.generate_hash(length=4)}"
        )
        invoice = self.sepa.create_test_sales_invoice(
            customer=customer.name,
            grand_total=15.0,
            status="Unpaid",
            company=self.company,
            submit=True,
        )
        invoice.reload()
        rec = self.manager.get_or_create_retry_record(invoice.name)
        self.assertIsNone(rec.member)
        self.assertIsNone(rec.membership)
        self.assertEqual(rec.invoice, invoice.name)

    def test_links_active_membership(self):
        member = self._make_member_with_customer("WithMembership")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        rec = self.manager.get_or_create_retry_record(invoice.name)
        self.assertEqual(rec.membership, membership.name)


# =============================================================================
# schedule_retry
# =============================================================================
class TestScheduleRetry(RetryBase):
    def setUp(self):
        super().setUp()
        # Stub the two side-effecting boundaries: enqueue (worker) + notification.
        self.enqueue_patch = patch("frappe.enqueue", return_value=None)
        self.enqueue_patch.start()
        self.addCleanup(self.enqueue_patch.stop)
        self.notif_patch = patch(
            "verenigingen.verenigingen_payments.utils.sepa_notifications."
            "SEPAMandateNotificationManager.send_payment_retry_notification",
            return_value=None,
        )
        self.notif_patch.start()
        self.addCleanup(self.notif_patch.stop)

    def test_first_failure_schedules_retry(self):
        member = self._make_member_with_customer("Sched1")
        invoice = self._make_unpaid_invoice(member)

        result = self.manager.schedule_retry(
            invoice.name, reason_code="AM04", reason_message="Insufficient funds"
        )
        self.assertTrue(result["scheduled"])
        self.assertEqual(result["attempt_number"], 1)
        self.assertIsNotNone(result["next_retry"])

        rec = frappe.get_doc("SEPA Payment Retry", {"invoice": invoice.name})
        self.assertEqual(rec.retry_count, 1)
        self.assertEqual(rec.status, "Scheduled")
        self.assertEqual(rec.last_failure_reason, "AM04")
        self.assertEqual(rec.last_failure_message, "Insufficient funds")
        # Retry log row appended.
        self.assertEqual(len(rec.retry_log), 1)
        self.assertEqual(rec.retry_log[0].reason_code, "AM04")

    def test_default_reason_when_omitted(self):
        member = self._make_member_with_customer("SchedDefault")
        invoice = self._make_unpaid_invoice(member)
        self.manager.schedule_retry(invoice.name)
        rec = frappe.get_doc("SEPA Payment Retry", {"invoice": invoice.name})
        self.assertEqual(rec.last_failure_reason, "Unknown")
        self.assertEqual(rec.last_failure_message, "Payment failed")

    def test_repeated_failures_increment_count(self):
        member = self._make_member_with_customer("SchedInc")
        invoice = self._make_unpaid_invoice(member)
        self.manager.schedule_retry(invoice.name, "R1", "first")
        self.manager.schedule_retry(invoice.name, "R2", "second")
        rec = frappe.get_doc("SEPA Payment Retry", {"invoice": invoice.name})
        self.assertEqual(rec.retry_count, 2)
        self.assertEqual(len(rec.retry_log), 2)

    def test_max_retries_escalates(self):
        """When retry_count already at max, schedule_retry escalates instead of
        scheduling. Requires a membership (escalation comments on it)."""
        member = self._make_member_with_customer("Escalate")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)

        rec = self._make_retry_record(
            member, invoice, retry_count=3, membership=membership.name
        )
        self.manager.settings.sepa_max_retries = 3
        self.manager.retry_config = self.manager.get_retry_config()

        # Stub escalation email send (boundary).
        with patch.object(self.manager, "send_escalation_notification", return_value=None):
            result = self.manager.schedule_retry(invoice.name, "FINAL", "give up")

        self.assertFalse(result["scheduled"])
        self.assertIn("escalated", result["message"].lower())
        rec.reload()
        self.assertEqual(rec.status, "Escalated")
        self.assertIsNotNone(rec.escalated_on)

    def test_create_retry_job_enqueue_failure_reverts_to_pending(self):
        """If frappe.enqueue raises, create_retry_job logs and reverts status to
        Pending, returning job_scheduled False."""
        member = self._make_member_with_customer("EnqFail")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(member, invoice)

        # Make enqueue blow up (overrides the no-op patch from setUp).
        with patch("frappe.enqueue", side_effect=Exception("redis down")):
            out = self.manager.create_retry_job(rec)
        self.assertFalse(out["job_scheduled"])
        rec.reload()
        self.assertEqual(rec.status, "Pending")

    def test_create_retry_job_success(self):
        member = self._make_member_with_customer("EnqOk")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(member, invoice)
        out = self.manager.create_retry_job(rec)
        self.assertTrue(out["job_scheduled"])
        self.assertEqual(out["retry_record"], rec.name)
        rec.reload()
        self.assertEqual(rec.status, "Scheduled")


# =============================================================================
# escalate_payment_failure
# =============================================================================
class TestEscalation(RetryBase):
    def test_escalation_sets_status_and_comments_membership(self):
        member = self._make_member_with_customer("EscDirect")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(
            member, invoice, retry_count=3, membership=membership.name
        )

        with patch.object(self.manager, "send_escalation_notification", return_value=None):
            self.manager.escalate_payment_failure(rec)

        rec.reload()
        self.assertEqual(rec.status, "Escalated")
        self.assertIsNotNone(rec.escalated_on)
        # A comment was added to the membership for the audit trail.
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Membership",
                "reference_name": membership.name,
                "comment_type": "Comment",
            },
            pluck="content",
        )
        self.assertTrue(any("Escalated for manual review" in c for c in comments))


# =============================================================================
# execute_payment_retry
# =============================================================================
class TestExecutePaymentRetry(RetryBase):
    def test_noop_when_no_record_passed(self):
        # Returns None without error.
        self.assertIsNone(retry.execute_payment_retry(retry_record=None))

    def test_skips_when_not_due_today(self):
        """next_retry_date in the future -> early return, status unchanged."""
        member = self._make_member_with_customer("NotDue")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(
            member, invoice, status="Scheduled", next_retry_date=add_days(today(), 5)
        )
        retry.execute_payment_retry(retry_record=rec.name)
        rec.reload()
        self.assertEqual(rec.status, "Scheduled")
        self.assertIsNone(rec.last_retry_date)

    def test_skips_when_already_retried_today(self):
        """last_retry_date == today and next_retry_date == today -> guarded out."""
        member = self._make_member_with_customer("AlreadyToday")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(
            member,
            invoice,
            status="Retried",
            next_retry_date=today(),
            last_retry_date=today(),
        )
        retry.execute_payment_retry(retry_record=rec.name)
        rec.reload()
        # Untouched.
        self.assertEqual(rec.status, "Retried")

    def test_due_retry_fails_on_missing_mandate(self):
        """A due retry for a member with NO active SEPA mandate ends in status
        'Failed' with the comment 'No active SEPA mandate found'
        (payment_retry.py:274-278).

        Regression for a fixed PRODUCT BUG: execute_payment_retry used to call
        ``member.get_active_sepa_mandate()`` (singular), which does not exist on
        the Member controller — only ``get_active_sepa_mandates()`` (plural, in
        member/mixins/sepa_mixin.py:35). That AttributeError was swallowed by the
        broad ``except Exception`` and parked every due retry in status 'Error',
        so NO retry could ever execute. The fix uses the plural method, selects
        the first active mandate, and preserves the no-mandate 'Failed' branch
        asserted here."""
        member = self._make_member_with_customer("DueNoMandate")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(
            member,
            invoice,
            status="Scheduled",
            retry_count=1,
            next_retry_date=today(),
            membership=membership.name,
        )
        retry.execute_payment_retry(retry_record=rec.name)
        rec.reload()
        self.assertEqual(rec.status, "Failed")
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "SEPA Payment Retry",
                "reference_name": rec.name,
            },
            pluck="content",
        )
        self.assertTrue(any("No active SEPA mandate" in c for c in comments))

    def test_due_retry_with_active_mandate_creates_batch(self):
        """Happy path (previously unreachable because of the singular-method bug):
        a due retry for a member WITH an active SEPA mandate builds and submits a
        Direct Debit Batch carrying that invoice + mandate and advances the retry
        record to status 'Retried'.

        The ONLY boundary stubbed is the external SEPA-XML file generation
        (``sepa_xml_service.generate_sepa_xml_for_batch``, invoked from the batch's
        on_submit) — it requires live org SEPA credentials / a clean creditor name
        and writes a physical XML file, neither of which is relevant to the
        mandate-selection fix under test. Batch creation, child-row population from
        the selected full mandate doc (iban/bic/mandate_id/sign_date), and the
        status transition all run for real."""
        member = self._make_member_with_customer("DueWithMandate")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        mandate = self.sepa.create_test_sepa_mandate(
            member=member.name, status="Active", used_for_memberships=1
        )
        rec = self._make_retry_record(
            member,
            invoice,
            status="Scheduled",
            retry_count=1,
            next_retry_date=today(),
            membership=membership.name,
        )

        with patch(
            "verenigingen.verenigingen_payments.services.sepa_xml_generation_service."
            "sepa_xml_service.generate_sepa_xml_for_batch",
            return_value="/files/dummy-sepa.xml",
        ):
            retry.execute_payment_retry(retry_record=rec.name)

        rec.reload()
        self.assertEqual(rec.status, "Retried")
        self.assertEqual(getdate(rec.last_retry_date), getdate(today()))

        # A Direct Debit Batch carrying this invoice + selected mandate was created
        # and submitted; the mandate fields were sourced from the full mandate doc.
        rows = frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"invoice": invoice.name, "mandate_reference": mandate.mandate_id},
            fields=["parent", "iban"],
        )
        self.assertTrue(rows)
        self.assertEqual(rows[0].iban, mandate.iban)
        batch = frappe.get_doc("Direct Debit Batch", rows[0].parent)
        self.assertEqual(batch.docstatus, 1)

    def test_due_retry_skips_when_invoice_already_in_open_batch(self):
        """DOUBLE-RUN / double-charge guard: a due retry whose invoice is ALREADY
        in a live (submitted, docstatus 1) Direct Debit Batch must NOT create a
        second batch — it lands in the terminal 'Failed' state with an
        explanatory comment, and exactly one batch references the invoice.

        Without the guard a redelivered RQ job / manual re-run / crash between
        batch.submit() and the last_retry_date save would debit the member twice
        (this submitted path MOVES MONEY). Mirrors the exclusion the monthly batch
        flow applies in sepa_mandate_service.get_unpaid_sepa_invoices."""
        member = self._make_member_with_customer("DoubleRun")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        mandate = self.sepa.create_test_sepa_mandate(
            member=member.name, status="Active", used_for_memberships=1
        )
        rec = self._make_retry_record(
            member,
            invoice,
            status="Scheduled",
            retry_count=1,
            next_retry_date=today(),
            membership=membership.name,
        )

        xml_stub = patch(
            "verenigingen.verenigingen_payments.services.sepa_xml_generation_service."
            "sepa_xml_service.generate_sepa_xml_for_batch",
            return_value="/files/dummy-sepa.xml",
        )

        # First run: creates + submits a Direct Debit Batch for the invoice.
        with xml_stub:
            retry.execute_payment_retry(retry_record=rec.name)
        rec.reload()
        self.assertEqual(rec.status, "Retried")
        first_batches = frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"invoice": invoice.name},
            pluck="parent",
        )
        self.assertEqual(len(set(first_batches)), 1)
        first_batch = list(set(first_batches))[0]

        # Re-arm the record so it is "due today" again (simulating a redelivered
        # job / manual re-run) and execute a SECOND time. The open-batch guard
        # must fire BEFORE any batch is created.
        rec.db_set("status", "Scheduled")
        rec.db_set("last_retry_date", None)
        rec.reload()

        with xml_stub:
            retry.execute_payment_retry(retry_record=rec.name)

        rec.reload()
        self.assertEqual(rec.status, "Failed")
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "SEPA Payment Retry",
                "reference_name": rec.name,
            },
            pluck="content",
        )
        self.assertTrue(any("already present in an open Direct Debit Batch" in c for c in comments))

        # STILL exactly one batch references the invoice — no double charge.
        all_batches = frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"invoice": invoice.name},
            pluck="parent",
        )
        self.assertEqual(set(all_batches), {first_batch})


    def test_a_failed_submit_does_not_strand_the_batch(self):
        """A submit that fails must leave the invoice retryable.

        The open-batch guard matches any Direct Debit Batch with docstatus != 2, and
        the fence COMMITS the freshly inserted (still draft) batch before calling
        submit -- deliberately, so a redelivered job cannot double-charge. The
        consequence is that a submit which then raises leaves a committed draft batch
        holding the invoice, and every later attempt -- the daily sweep, the enqueued
        job, the desk button -- refuses it with "already present in an open Direct
        Debit Batch". Permanently.

        Before the daily sweep existed this needed a human pressing the button on one
        record; the sweep makes it unattended and daily, over the whole backlog on its
        first run, which is why it is fixed here rather than left as pre-existing.

        The batch is only discarded when nothing left the building: no sepa_message_id
        and no sepa_file_generated. The stubbed boundary is the same one this file
        already stubs everywhere else; here it raises instead of returning a path.
        """
        member = self._make_member_with_customer("SubmitFails")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        self.sepa.create_test_sepa_mandate(member=member.name, status="Active", used_for_memberships=1)
        rec = self._make_retry_record(
            member,
            invoice,
            status="Scheduled",
            retry_count=1,
            next_retry_date=today(),
            membership=membership.name,
        )

        with patch(
            "verenigingen.verenigingen_payments.services.sepa_xml_generation_service."
            "sepa_xml_service.generate_sepa_xml_for_batch",
            side_effect=RuntimeError("SEPA generation blew up after the fence"),
        ):
            retry.execute_payment_retry(retry_record=rec.name)

        self.assertFalse(
            retry._invoice_in_open_batch(invoice.name),
            "a failed submit left a batch holding the invoice; it can never be retried again",
        )
        rec.reload()
        self.assertEqual(rec.status, "Error")


class TestRetryDebitsTheMembershipMandate(RetryBase):
    """The retry debits the mandate it picks, and it used to pick by recency.

    `execute_payment_retry` resolved the mandate with
    `member.get_active_sepa_mandates()[0]` -- `order_by="creation desc"` with no
    purpose filter, the shape #584 was filed about -- and wrote that mandate's
    `iban`, `bic`, `mandate_id` and `sign_date` into a Direct Debit Batch row it
    then SUBMITS. `hooks/scheduler.py` runs it daily.

    A member may legitimately hold an Active membership mandate and an Active
    donation mandate at once (#584), and this retries a MEMBERSHIP invoice: it
    loads the Membership document two lines above. So for that member the retry
    debited whichever account was registered most recently (#605).
    """

    XML_STUB = (
        "verenigingen.verenigingen_payments.services.sepa_xml_generation_service."
        "sepa_xml_service.generate_sepa_xml_for_batch"
    )

    def _due_retry_for_member_with_both_mandates(self):
        member = self._make_member_with_customer("PurposeRetry")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)

        membership_mandate = self.sepa.create_test_sepa_mandate(
            member=member.name,
            status="Active",
            iban="NL91ABNA0417164300",
            used_for_memberships=1,
            used_for_donations=0,
        )
        donation_mandate = self.sepa.create_test_sepa_mandate(
            member=member.name,
            status="Active",
            iban="NL02ABNA0123456789",
            used_for_memberships=0,
            used_for_donations=1,
        )
        # Pin `creation` rather than trusting insert order: "newest wins" and
        # "membership wins" have to give different answers for the assertion below
        # to discriminate, and a same-second collision would make that arbitrary.
        frappe.db.set_value(
            "SEPA Mandate", membership_mandate.name, "creation", "2020-01-01 00:00:00",
            update_modified=False,
        )
        frappe.db.set_value(
            "SEPA Mandate", donation_mandate.name, "creation", "2021-01-01 00:00:00",
            update_modified=False,
        )

        rec = self._make_retry_record(
            member,
            invoice,
            status="Scheduled",
            retry_count=1,
            next_retry_date=today(),
            membership=membership.name,
        )
        return member, invoice, membership_mandate, donation_mandate, rec

    def test_the_batch_row_carries_the_membership_mandate(self):
        (
            _member,
            invoice,
            membership_mandate,
            donation_mandate,
            rec,
        ) = self._due_retry_for_member_with_both_mandates()

        with patch(self.XML_STUB, return_value="/files/dummy-sepa.xml"):
            retry.execute_payment_retry(retry_record=rec.name)

        rows = frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"invoice": invoice.name},
            fields=["mandate_reference", "iban"],
        )
        self.assertEqual(len(rows), 1, f"expected one batch row, got {rows}")
        self.assertEqual(
            rows[0].mandate_reference,
            membership_mandate.mandate_id,
            "the retry debited the member's donation mandate for a membership invoice",
        )
        self.assertNotEqual(rows[0].mandate_reference, donation_mandate.mandate_id)

    def test_two_membership_mandates_are_refused_as_such_not_as_none(self):
        """A refusal is not "no mandate found" -- #581 billed a member a third
        period by collapsing those two.

        The second Active membership mandate is forced past
        `validate_single_active_mandate_per_purpose` with `frappe.db.set_value`,
        which bypasses `validate` entirely -- the same bypass
        `test_mandate_candidates` needs, and the reason
        `unambiguous_active_mandate` exists even though the guard should make the
        state unreachable.
        """
        member, invoice, _membership_mandate, _donation, rec = (
            self._due_retry_for_member_with_both_mandates()
        )
        # The refusal records itself through `frappe.log_error` -- that IS the
        # behaviour under test succeeding, so declare it rather than letting the
        # harness's automatic Error Log check read it as an incident.
        self.expectErrorLog("Payment retry mandate resolution")
        second = self.sepa.create_test_sepa_mandate(
            member=member.name,
            status="Draft",
            iban="NL39RABO0300065264",
            used_for_memberships=1,
            used_for_donations=0,
        )
        frappe.db.set_value("SEPA Mandate", second.name, "status", "Active", update_modified=False)

        with patch(self.XML_STUB, return_value="/files/dummy-sepa.xml"):
            retry.execute_payment_retry(retry_record=rec.name)

        rec.reload()
        self.assertEqual(rec.status, "Failed")
        self.assertFalse(
            frappe.get_all("Direct Debit Batch Invoice", filters={"invoice": invoice.name}),
            "nothing may be debited while it is a guess which account to debit",
        )
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "SEPA Payment Retry", "reference_name": rec.name},
            pluck="content",
        )
        self.assertTrue(
            any("more than one" in c.lower() for c in comments),
            f"the refusal must say what it was; got {comments}",
        )
        self.assertFalse(
            any("No active SEPA mandate" in c for c in comments),
            "reporting a refusal as 'none found' is what sends the operator to create another",
        )


# =============================================================================
# The DAILY SCHEDULER ENTRY (#622)
# =============================================================================
class TestScheduledRetrySweep(RetryBase):
    """The registered daily scheduler entry must actually execute due retries.

    Frappe runs a ``scheduler_events`` entry with NO arguments -- see
    ``ScheduledJobType.execute``, which does ``frappe.get_attr(self.method)()``
    (frappe/core/doctype/scheduled_job_type/scheduled_job_type.py:156). Nothing
    on the way supplies parameters: the ``@critical_api`` wrapper forwards
    ``func(*args, **validated_kwargs)`` and injects nothing.

    #622: the entry registered was ``execute_payment_retry(retry_record=None)``,
    whose first two lines are ``if not retry_record: return`` -- so the daily run
    was a silent no-op and no scheduled retry ever executed. The other automatic
    path cannot compensate: ``PaymentRetryManager.create_retry_job`` enqueues the
    retry immediately, but ``calculate_next_retry_date`` puts ``next_retry_date``
    at least 3 days out (``retry_intervals = [3, 7, 14]``), so that job is
    guaranteed to be filtered out by the due-date guard as well.

    These tests bind to the CONTRACT rather than to a function name: they resolve
    whichever ``payment_retry`` method the daily hook registers and call it the
    way the scheduler does. The observable is a due record for a member with NO
    active SEPA mandate, which the body parks in status 'Failed' -- reached only
    if the sweep passed the record through.
    """

    #: Read from the hooks module directly, not via ``frappe.get_hooks``, which
    #: is Redis-cached per site and can serve the installed checkout's copy
    #: rather than the tree under test.
    _PREFIX = "verenigingen.verenigingen_payments.utils.payment_retry."

    def _daily_entry(self):
        """The single daily scheduler entry belonging to payment_retry."""
        from verenigingen.hooks.scheduler import scheduler_events

        entries = [m for m in scheduler_events["daily"] if m.startswith(self._PREFIX)]
        self.assertEqual(
            len(entries),
            1,
            f"expected exactly one payment_retry daily scheduler entry, got {entries}",
        )
        return entries[0]

    def _scheduled_record(self, label, day_offset):
        """A 'Scheduled' retry due ``day_offset`` days from today, for a member
        with no active SEPA mandate."""
        member = self._make_member_with_customer(label)
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        return self._make_retry_record(
            member,
            invoice,
            status="Scheduled",
            retry_count=1,
            # getdate()/today() are site-tz; never Python's date.today() (#628).
            next_retry_date=add_days(getdate(today()), day_offset),
            membership=membership.name,
        )

    def _run_daily_entry(self):
        """Invoke the registered entry exactly as the scheduler does.

        The sweep is global, so it may also pick up 'Scheduled' rows left by
        other modules sharing this database. Stub only the external SEPA XML
        file generation so such a collateral record cannot demand live org SEPA
        credentials or write a file; every other guard runs for real.
        """
        with patch(
            "verenigingen.verenigingen_payments.services.sepa_xml_generation_service."
            "sepa_xml_service.generate_sepa_xml_for_batch",
            return_value="/files/dummy-sepa.xml",
        ):
            frappe.get_attr(self._daily_entry())()

    def _no_mandate_comment(self, rec):
        return frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "SEPA Payment Retry",
                "reference_name": rec.name,
            },
            pluck="content",
        )

    def test_daily_entry_executes_a_retry_due_today(self):
        """A retry due today is executed by the scheduled entry, with no argument
        supplied -- the whole point of #622."""
        rec = self._scheduled_record("SweepDueToday", 0)

        self._run_daily_entry()

        rec.reload()
        self.assertEqual(
            rec.status,
            "Failed",
            "due retry was not executed by the daily scheduler entry",
        )
        self.assertTrue(any("No active SEPA mandate" in c for c in self._no_mandate_comment(rec)))

    def test_daily_entry_executes_a_retry_whose_date_was_missed(self):
        """A retry whose date has already passed (scheduler outage, a tz-boundary
        day roll) must still be picked up -- otherwise it is stranded in
        'Scheduled' forever, which is #622 narrowed rather than fixed."""
        rec = self._scheduled_record("SweepOverdue", -4)

        self._run_daily_entry()

        rec.reload()
        self.assertEqual(
            rec.status,
            "Failed",
            "overdue retry was left behind by the daily scheduler entry",
        )

    def test_daily_entry_leaves_a_retry_that_is_not_yet_due(self):
        """The sweep is bounded: a retry scheduled for a future date is untouched,
        so 'it executed the due one' is not just 'it executes everything'."""
        rec = self._scheduled_record("SweepNotYetDue", 5)

        self._run_daily_entry()

        rec.reload()
        self.assertEqual(rec.status, "Scheduled")
        self.assertIsNone(rec.last_retry_date)

    def test_daily_entry_ignores_records_not_in_scheduled_status(self):
        """Only 'Scheduled' rows are swept. A record already 'Retried' today is
        not re-run, and an 'Escalated' one is not resurrected."""
        member = self._make_member_with_customer("SweepWrongStatus")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        escalated = self._make_retry_record(
            member,
            invoice,
            status="Escalated",
            retry_count=3,
            next_retry_date=getdate(today()),
            membership=membership.name,
        )

        self._run_daily_entry()

        escalated.reload()
        self.assertEqual(escalated.status, "Escalated")


# =============================================================================
# check_payment_retry_status
# =============================================================================
class TestCheckRetryStatus(RetryBase):
    def test_no_retry_returns_false(self):
        member = self._make_member_with_customer("NoRetryStatus")
        invoice = self._make_unpaid_invoice(member)
        out = retry.check_payment_retry_status(invoice=invoice.name)
        self.assertFalse(out["has_retry"])

    def test_existing_retry_returns_details(self):
        member = self._make_member_with_customer("HasRetryStatus")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(
            member, invoice, retry_count=2, status="Scheduled",
            next_retry_date=add_days(today(), 3),
        )
        out = retry.check_payment_retry_status(invoice=invoice.name)
        self.assertTrue(out["has_retry"])
        self.assertEqual(out["retry_count"], 2)
        self.assertEqual(out["status"], "Scheduled")
        self.assertFalse(out["max_retries_reached"])

    def test_max_retries_reached_flag(self):
        member = self._make_member_with_customer("MaxedStatus")
        invoice = self._make_unpaid_invoice(member)
        self._make_retry_record(member, invoice, retry_count=3, status="Escalated")
        out = retry.check_payment_retry_status(invoice=invoice.name)
        self.assertTrue(out["max_retries_reached"])


# =============================================================================
# Module-targeting sanity check
# =============================================================================
class TestModuleTarget(unittest.TestCase):
    def test_targets_verenigingen_payments_copy(self):
        self.assertIn(
            "verenigingen_payments/utils/payment_retry.py",
            retry.__file__,
        )


# =============================================================================
# R7 parity: send_escalation_notification recipients via shared resolver
# =============================================================================
class TestEscalationRecipientResolution(RetryBase):
    """Parity test for R7: recipient resolution uses the shared resolver.

    Seeds a User with the Verenigingen Staff role, calls
    send_escalation_notification (with the outbound email stubbed), and asserts
    that the seeded user's email appears in the ``recipients`` argument passed
    to the email service.  Verifies that the resolver — not the old inline
    ``Has Role`` query — drives the recipient set.
    """

    _ROLE = "Verenigingen Staff"

    def _make_staff_user(self) -> frappe.Document:
        """Insert an enabled User with Verenigingen Staff role (helper write)."""
        email = f"r7-staff.{frappe.generate_hash(length=8)}@test.invalid"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "R7Staff"
        user.last_name = "Parity"
        user.enabled = 1
        user.send_welcome_email = 0
        user.append("roles", {"role": self._ROLE})
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    def test_staff_role_email_included_in_escalation_recipients(self):
        """User holding Verenigingen Staff role appears in escalation recipients."""
        staff_user = self._make_staff_user()

        member = self._make_member_with_customer("R7Parity")
        membership = self.sepa.create_test_membership(member=member.name, status="Active")
        invoice = self._make_unpaid_invoice(member)
        rec = self._make_retry_record(
            member, invoice, retry_count=3, membership=membership.name
        )

        captured_recipients = []
        fake_email_service = MagicMock()

        def capture_send(**kwargs):
            captured_recipients.extend(kwargs.get("recipients", []))

        fake_email_service.send_templated_email.side_effect = capture_send

        # Patch at the module where the symbol lives; payment_retry imports it
        # locally inside the if-recipients branch.
        with patch(
            "verenigingen.services.communication.email_service.get_email_service",
            return_value=fake_email_service,
        ):
            self.manager.send_escalation_notification(rec)

        self.assertIn(
            staff_user.email,
            captured_recipients,
            f"Expected {staff_user.email!r} in recipients {captured_recipients!r}",
        )


if __name__ == "__main__":
    unittest.main()
