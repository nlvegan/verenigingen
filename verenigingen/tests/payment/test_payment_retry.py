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
from unittest.mock import patch

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

    @unittest.expectedFailure
    def test_due_retry_fails_on_missing_mandate_method(self):
        """PRODUCT BUG: payment_retry.py:273 — execute_payment_retry calls
        ``member.get_active_sepa_mandate()`` (singular), but the Member controller
        only defines ``get_active_sepa_mandates()`` (plural, in
        member/mixins/sepa_mixin.py:35). The singular method does not exist, so
        every due retry raises AttributeError, is swallowed by the broad
        ``except Exception`` at payment_retry.py:314, and the record is parked in
        status 'Error' — meaning NO retry can EVER execute. The CORRECT behaviour
        for a member with NO active mandate is status 'Failed' with the comment
        'No active SEPA mandate found' (lines 274-278), which this test asserts;
        it currently fails because the code errors out before reaching the
        mandate-None check.

        A member with no SEPA mandate is used here so the expected terminal state
        is the well-defined 'Failed' branch rather than a live batch submission."""
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

    def test_due_retry_currently_errors_on_mandate_call(self):
        """Companion to the xfail above: documents the CURRENT (buggy) behaviour
        so the error path (payment_retry.py:314-318) is covered. The singular
        get_active_sepa_mandate() AttributeError is caught and the record is set
        to status 'Error' with last_error populated."""
        member = self._make_member_with_customer("DueErrors")
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
        self.assertEqual(rec.status, "Error")
        self.assertIsNotNone(rec.last_error)
        self.assertIn("get_active_sepa_mandate", rec.last_error)


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


if __name__ == "__main__":
    unittest.main()
