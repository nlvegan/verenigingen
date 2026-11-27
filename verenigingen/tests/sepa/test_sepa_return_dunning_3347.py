"""Dunning on a failed SEPA collection (#3347).

Every status assertion goes through the REAL return flow
(``process_individual_return`` -> ``reverse_failed_sepa_payment`` and the pain.002
``process_sepa_return_file``), not a direct call of the dunning service.

Probe shortcuts, stated once: (1) the invoice is linked to its dues schedule with
``db_set("membership_dues_schedule_display")`` (the dues generator does this in production);
(2) the sweep tests back-date Payment Entry / marker Comment ``creation`` with
``db.set_value`` to stand in for elapsed days; (3) the Suspended/auto-apply setting is
written with ``set_single_value``.
"""

import frappe
from frappe.utils import add_days, add_to_date, cint, getdate, now_datetime, today

from verenigingen.services.billing import sepa_return_dunning_service as dunning
from verenigingen.tests.payment.test_sepa_reconciliation import ReconBase
from verenigingen.tests.support.invoice_payments import receive_against_invoice
from verenigingen.verenigingen_payments.api import sepa_reconciliation as recon
from verenigingen.verenigingen_payments.utils import bank_transaction_reconciliation as btr


class TestSepaReturnDunning3347(ReconBase):
    def setUp(self):
        super().setUp()
        self.it = self._make_member_with_invoice(first_name="Dun3347", grand_total=31.0)
        self.member_id = frappe.db.get_value("Member", self.it["member"].name, "member_id")
        self.schedule = self.sepa.create_test_membership_dues_schedule(member=self.it["member"].name).name
        self._amount = 31.0

    # ---- builders -----------------------------------------------------------

    def _collect(self):
        """A new dues invoice of a unique amount, settled by a SEPA Direct Debit PE."""
        self._amount += 1.0
        it = self.it
        invoice = self.sepa.create_test_sales_invoice(
            customer=it["customer"],
            member=it["member"].name,
            membership=it["membership"].name,
            grand_total=self._amount,
            submit=True,
        )
        invoice.db_set("membership_dues_schedule_display", self.schedule)
        _, pe = receive_against_invoice(
            self, invoice.name, self._amount, mode_of_payment="SEPA Direct Debit"
        )
        return invoice, pe

    def _return(self, amount):
        return recon.process_individual_return(
            {
                "member_reference": self.member_id,
                "amount": amount,
                "return_reason": "Insufficient funds",
                "return_code": "AM04",
            }
        )

    def _fail_once(self):
        invoice, pe = self._collect()
        result = self._return(self._amount)
        self.assertEqual(result["status"], "processed", msg=result)
        return invoice, pe

    def _schedule(self):
        return frappe.db.get_value(
            "Membership Dues Schedule",
            self.schedule,
            ["status", "consecutive_failures", "grace_period_until"],
            as_dict=True,
        )

    def _settings(self, auto_apply, days=None):
        frappe.db.set_single_value("Verenigingen Settings", "grace_period_auto_apply", auto_apply)
        frappe.db.set_single_value("Verenigingen Settings", "default_grace_period_days", days or 0)

    # ---- failure side ---------------------------------------------------------

    def test_first_return_moves_schedule_to_grace_period(self):
        self._settings(auto_apply=1, days=12)
        self.assertEqual(self._schedule().status, "Active")
        self._fail_once()
        sched = self._schedule()
        self.assertEqual(sched.status, "Grace Period")
        self.assertEqual(cint(sched.consecutive_failures), 1)
        self.assertEqual(getdate(sched.grace_period_until), getdate(add_days(today(), 12)))

    def test_empty_grace_days_setting_defaults_to_30(self):
        self._settings(auto_apply=1, days=0)
        self._fail_once()
        self.assertEqual(getdate(self._schedule().grace_period_until), getdate(add_days(today(), 30)))

    def test_third_consecutive_return_suspends_when_auto_apply_is_on(self):
        self._settings(auto_apply=1)
        for _ in range(2):
            self._fail_once()
        self.assertEqual(self._schedule().status, "Grace Period")
        self._fail_once()
        sched = self._schedule()
        self.assertEqual(sched.status, "Suspended")
        self.assertEqual(cint(sched.consecutive_failures), 3)

    def test_third_consecutive_return_extends_grace_when_auto_apply_is_off(self):
        self._settings(auto_apply=0, days=10)
        for _ in range(3):
            self._fail_once()
        sched = self._schedule()
        self.assertEqual(sched.status, "Grace Period")
        self.assertEqual(cint(sched.consecutive_failures), 3)
        self.assertEqual(getdate(sched.grace_period_until), getdate(add_days(today(), 10)))

    def test_same_bank_return_processed_twice_counts_once(self):
        self._fail_once()
        again = self._return(self._amount)
        self.assertEqual(again["status"], "not_found", msg=again)
        self.assertEqual(cint(self._schedule().consecutive_failures), 1)

    def test_a_return_that_reverses_nothing_does_not_dun(self):
        """Control: a same-amount invoice paid by bank transfer is not a SEPA collection."""
        self._amount += 1.0
        invoice = self.sepa.create_test_sales_invoice(
            customer=self.it["customer"],
            member=self.it["member"].name,
            membership=self.it["membership"].name,
            grand_total=self._amount,
            submit=True,
        )
        invoice.db_set("membership_dues_schedule_display", self.schedule)
        receive_against_invoice(self, invoice.name, self._amount, mode_of_payment="Wire Transfer")
        self.expectErrorLog("SEPA Return Not Reversed")
        self.assertEqual(self._return(self._amount)["status"], "not_reversed")
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)
        self.assertEqual(self._schedule().status, "Active")

    def test_paused_schedule_is_not_dunned(self):
        frappe.db.set_value("Membership Dues Schedule", self.schedule, "status", "Paused")
        self._fail_once()
        self.assertEqual(self._schedule().status, "Paused")
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)

    # ---- pain.002 path ----------------------------------------------------------

    def _pain002(self, invoice_name, reason_text):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
  <CstmrPmtStsRpt><OrgnlPmtInfAndSts><TxInfAndSts>
    <OrgnlEndToEndId>E2E-{invoice_name}</OrgnlEndToEndId>
    <TxSts>RJCT</TxSts>
    <StsRsnInf><Rsn><Cd>AM04</Cd></Rsn><AddtlInf>{reason_text}</AddtlInf></StsRsnInf>
  </TxInfAndSts></OrgnlPmtInfAndSts></CstmrPmtStsRpt>
</Document>"""

    def _unpaid_linked_invoice(self):
        self._amount += 1.0
        invoice = self.sepa.create_test_sales_invoice(
            customer=self.it["customer"],
            member=self.it["member"].name,
            membership=self.it["membership"].name,
            grand_total=self._amount,
            submit=True,
        )
        invoice.db_set("membership_dues_schedule_display", self.schedule)
        return invoice

    def test_pain002_rejection_duns_and_the_same_file_counts_once(self):
        # PaymentReconciliationManager() logs the unconfigured Mollie accounts of a test site.
        self.expectErrorLog("Mollie Account Configuration")
        self._settings(auto_apply=1)
        invoice = self._unpaid_linked_invoice()
        xml = self._pain002(invoice.name, "first")
        btr.process_sepa_return_file(xml, file_type="pain.002")
        self.assertEqual(self._schedule().status, "Grace Period")
        self.assertEqual(cint(self._schedule().consecutive_failures), 1)
        btr.process_sepa_return_file(xml, file_type="pain.002")
        self.assertEqual(cint(self._schedule().consecutive_failures), 1)

    def test_pain002_a_different_file_for_the_same_invoice_counts_again(self):
        # PaymentReconciliationManager() logs the unconfigured Mollie accounts of a test site.
        self.expectErrorLog("Mollie Account Configuration")
        """Control for the dedupe key: it must not be so coarse that a second real return is lost."""
        invoice = self._unpaid_linked_invoice()
        btr.process_sepa_return_file(self._pain002(invoice.name, "first"), file_type="pain.002")
        btr.process_sepa_return_file(self._pain002(invoice.name, "second"), file_type="pain.002")
        self.assertEqual(cint(self._schedule().consecutive_failures), 2)

    # ---- sweep (success side) -----------------------------------------------------

    def _age_failures(self, days):
        """Back-date the counted-failure markers (probe shortcut: time travel)."""
        when = add_to_date(now_datetime(), days=-days)
        for name in frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Membership Dues Schedule",
                "reference_name": self.schedule,
                "content": ["like", f"{dunning.FAILURE_MARKER_PREFIX}%"],
            },
            pluck="name",
        ):
            frappe.db.set_value("Comment", name, "creation", when, update_modified=False)

    def _age_collection(self, pe, days):
        frappe.db.set_value(
            "Payment Entry", pe.name, "creation", add_to_date(now_datetime(), days=-days), update_modified=False
        )

    def _after_one_failure(self):
        self._settings(auto_apply=1)
        self._fail_once()
        self._age_failures(days=dunning.SEPA_RETURN_WINDOW_DAYS + 6)

    def test_collection_surviving_the_window_resets_counter_and_returns_to_active(self):
        self._after_one_failure()
        _, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 1)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 1)
        sched = self._schedule()
        self.assertEqual(cint(sched.consecutive_failures), 0)
        self.assertEqual(sched.status, "Active")
        self.assertFalse(sched.grace_period_until)

    def test_sweep_is_idempotent(self):
        self._after_one_failure()
        _, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 1)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 1)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        self.assertEqual(self._schedule().status, "Active")

    def test_collection_still_inside_the_window_does_not_reset(self):
        """The plausible wrong fix: reset as soon as a Payment Entry exists."""
        self._after_one_failure()
        _, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS - 3)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        sched = self._schedule()
        self.assertEqual(cint(sched.consecutive_failures), 1)
        self.assertEqual(sched.status, "Grace Period")

    def test_collection_returned_inside_the_window_does_not_reset(self):
        self._after_one_failure()
        invoice, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 1)
        # The bank returns it before the sweep runs: a second failure, PE cancelled.
        self.assertEqual(self._return(self._amount)["status"], "processed")
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        sched = self._schedule()
        self.assertEqual(cint(sched.consecutive_failures), 2)
        self.assertEqual(sched.status, "Grace Period")

    def test_collection_booked_before_the_latest_failure_does_not_reset(self):
        self._after_one_failure()
        _, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 30)  # older than the failure
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        self.assertEqual(cint(self._schedule().consecutive_failures), 1)

    def test_manual_non_sepa_payment_does_not_reset(self):
        """Not ruled (#3347): a transfer must not reset until the maintainer decides."""
        self._after_one_failure()
        self._amount += 1.0
        invoice = self._unpaid_linked_invoice()
        _, pe = receive_against_invoice(self, invoice.name, self._amount, mode_of_payment="Wire Transfer")
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 1)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        self.assertEqual(cint(self._schedule().consecutive_failures), 1)

    def test_suspended_schedule_keeps_status_but_counter_resets(self):
        self._settings(auto_apply=1)
        for _ in range(3):
            self._fail_once()
        self.assertEqual(self._schedule().status, "Suspended")
        self._age_failures(days=dunning.SEPA_RETURN_WINDOW_DAYS + 6)
        _, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 1)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 1)
        sched = self._schedule()
        self.assertEqual(cint(sched.consecutive_failures), 0)
        self.assertEqual(sched.status, "Suspended")

    def test_sweep_is_registered_in_the_daily_scheduler(self):
        from verenigingen.hooks.scheduler import scheduler_events

        self.assertIn(
            "verenigingen.services.billing.sepa_return_dunning_service.reset_failures_after_clean_window",
            scheduler_events["daily"],
        )
