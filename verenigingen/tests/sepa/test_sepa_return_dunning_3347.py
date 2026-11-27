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
from verenigingen.verenigingen_payments.utils.sepa_return_parser import SEPA_RETURN_REASON_CODES
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

    def _return(self, amount, code="AM04"):
        return recon.process_individual_return(
            {
                "member_reference": self.member_id,
                "amount": amount,
                "return_reason": SEPA_RETURN_REASON_CODES.get(code, "x"),
                "return_code": code,
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

    def _pain002(self, invoice_name, reason_text, code="AM04"):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
  <CstmrPmtStsRpt><OrgnlPmtInfAndSts><TxInfAndSts>
    <OrgnlEndToEndId>E2E-{invoice_name}</OrgnlEndToEndId>
    <TxSts>RJCT</TxSts>
    <StsRsnInf><Rsn><Cd>{code}</Cd></Rsn><AddtlInf>{reason_text}</AddtlInf></StsRsnInf>
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
        """Back-date last_failure_on (probe shortcut: time travel)."""
        frappe.db.set_value(
            "Membership Dues Schedule",
            self.schedule,
            "last_failure_on",
            add_to_date(now_datetime(), days=-days),
            update_modified=False,
        )

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

    # ---- part 4 rulings ---------------------------------------------------------------

    def test_classification_of_every_return_code(self):
        """The debtor-fault set is exactly the ruled one; every other code in the app's table is out."""
        expected = {"AC04", "AC06", "AM04", "MS02", "MS03", "MD06", "AG01", "SL01"}
        self.assertEqual(set(dunning.DEBTOR_FAULT_RETURN_CODES), expected)
        self.assertTrue(expected <= set(SEPA_RETURN_REASON_CODES))
        for code in set(SEPA_RETURN_REASON_CODES) - expected:
            self.assertNotIn(code, dunning.DEBTOR_FAULT_RETURN_CODES)

    def test_non_debtor_fault_return_is_reversed_logged_and_never_dunned(self):
        for code in ("MD01", "FF01", "AM05", "AC01"):
            self.expectErrorLog("SEPA Return Not Dunned")
            self._collect()
            result = self._return(self._amount, code=code)
            self.assertEqual(result["status"], "processed", msg=result)
            self.assertNotIn("dunning_failed", result)
        sched = self._schedule()
        self.assertEqual(sched.status, "Active")
        self.assertEqual(cint(sched.consecutive_failures), 0)
        self.assertTrue(frappe.db.exists("Error Log", {"method": "SEPA Return Not Dunned"}))

    def test_part5_codes_dun(self):
        """MD06, AG01 and SL01 (ruling part 5) count as failed collections, one each."""
        for count, code in enumerate(("MD06", "AG01", "SL01"), start=1):
            self._collect()
            result = self._return(self._amount, code=code)
            self.assertEqual(result["status"], "processed", msg=result)
            self.assertEqual(cint(self._schedule().consecutive_failures), count, msg=code)

    def test_ac01_is_the_control_that_still_does_not_dun(self):
        self.expectErrorLog("SEPA Return Not Dunned")
        self._collect()
        self.assertEqual(self._return(self._amount, code="AC01")["status"], "processed")
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)

    def test_a_return_without_a_reason_code_is_not_dunned(self):
        self.expectErrorLog("SEPA Return Not Dunned")
        self._collect()
        self.assertEqual(self._return(self._amount, code="")["status"], "processed")
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)

    def test_pain002_rejection_with_a_technical_reason_is_not_dunned(self):
        self.expectErrorLog("Mollie Account Configuration")
        self.expectErrorLog("SEPA Return Not Dunned")
        invoice = self._unpaid_linked_invoice()
        btr.process_sepa_return_file(self._pain002(invoice.name, "x", code="FF01"), file_type="pain.002")
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)
        self.assertEqual(self._schedule().status, "Active")

    def test_staff_suspended_schedule_with_zero_failures_stays_suspended_with_one(self):
        frappe.db.set_value("Membership Dues Schedule", self.schedule, "status", "Suspended")
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)
        self._fail_once()
        sched = self._schedule()
        self.assertEqual(sched.status, "Suspended")
        self.assertEqual(cint(sched.consecutive_failures), 1)
        self.assertFalse(sched.grace_period_until)

    # ---- dedicated fields (R3, D1) ---------------------------------------------------------

    def test_failure_is_recorded_in_the_dedicated_fields(self):
        _, pe = self._fail_once()
        doc = frappe.get_doc("Membership Dues Schedule", self.schedule)
        self.assertTrue(doc.last_failure_on)
        self.assertEqual([row.return_key for row in doc.counted_returns], [pe.name])

    def test_keys_sharing_a_prefix_are_both_counted(self):
        """D1: the old LIKE '%key%' dedupe would drop ...-00012 as a duplicate of ...-0001.

        Calls the service directly (the key shape is what is under test)."""
        invoice, _ = self._collect()
        for key in ("PE-00012", "PE-0001"):
            self.assertEqual(
                dunning.record_failed_collection(invoice.name, key, "x", "AM04"), dunning.COUNTED
            )
        self.assertEqual(
            dunning.record_failed_collection(invoice.name, "PE-0001", "x", "AM04"), dunning.DUPLICATE
        )
        self.assertEqual(cint(self._schedule().consecutive_failures), 2)

    # ---- D2: counter without a timestamp ---------------------------------------------------------

    def test_hand_set_counter_without_timestamp_falls_back_to_modified_and_logs_once(self):
        """Probe shortcut: the counter is set directly, as legacy data / staff would."""
        self._settings(auto_apply=1)
        frappe.db.set_value(
            "Membership Dues Schedule",
            self.schedule,
            {
                "consecutive_failures": 2,
                "last_failure_on": None,
                "modified": add_to_date(now_datetime(), days=-30),
            },
            update_modified=False,
        )
        self.expectErrorLog("SEPA Return Dunning Unknown Failure Date")
        _, pe = self._collect()
        self._age_collection(pe, dunning.SEPA_RETURN_WINDOW_DAYS + 1)
        before = frappe.db.count("Error Log", {"method": "SEPA Return Dunning Unknown Failure Date"})
        self.assertEqual(dunning.reset_failures_after_clean_window(), 1)
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)
        self.assertEqual(
            frappe.db.count("Error Log", {"method": "SEPA Return Dunning Unknown Failure Date"}), before + 1
        )

    def test_hand_set_counter_with_only_a_young_collection_is_left_and_logged_once(self):
        frappe.db.set_value(
            "Membership Dues Schedule",
            self.schedule,
            {"consecutive_failures": 2, "last_failure_on": None, "modified": add_to_date(now_datetime(), days=-30)},
            update_modified=False,
        )
        self.expectErrorLog("SEPA Return Dunning Unknown Failure Date")
        _, pe = self._collect()
        self._age_collection(pe, 3)
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        n = frappe.db.count("Error Log", {"method": "SEPA Return Dunning Unknown Failure Date"})
        self.assertEqual(dunning.reset_failures_after_clean_window(), 0)
        self.assertEqual(frappe.db.count("Error Log", {"method": "SEPA Return Dunning Unknown Failure Date"}), n)
        self.assertEqual(cint(self._schedule().consecutive_failures), 2)

    # ---- D3: dunning failure is visible in the result ----------------------------------------------

    def test_a_dunning_failure_is_signalled_in_the_result_and_the_reversal_stands(self):
        from unittest.mock import patch

        self.expectErrorLog("SEPA Return Dunning Failed")
        invoice, pe = self._collect()
        # Mock justified: fault injected at the schedule save; no real input makes it raise here.
        with patch(
            "verenigingen.verenigingen.doctype.membership_dues_schedule."
            "membership_dues_schedule.MembershipDuesSchedule.save",
            side_effect=RuntimeError("boom-3347"),
        ):
            result = self._return(self._amount)
        self.assertEqual(result["status"], "processed", msg=result)
        self.assertTrue(result.get("dunning_failed"), msg=result)
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 2)
        self.assertEqual(cint(self._schedule().consecutive_failures), 0)
        self.assertTrue(frappe.db.exists("Error Log", {"method": "SEPA Return Dunning Failed"}))

    def test_a_dunning_failure_reddens_the_file_level_result(self):
        """process_sepa_return_file may not report success while a row's dunning failed."""
        from unittest.mock import patch

        self.expectErrorLog("SEPA Return Dunning Failed")
        self._collect()
        member_id = self.member_id
        csv_text = (
            "Member_ID,Amount,Return_Reason,Return_Code\n"
            f"{member_id},{self._amount},{SEPA_RETURN_REASON_CODES['AM04']},AM04\n"
        )
        # Mock justified: fault injected at the schedule save; no real input makes it raise here.
        with patch(
            "verenigingen.verenigingen.doctype.membership_dues_schedule."
            "membership_dues_schedule.MembershipDuesSchedule.save",
            side_effect=RuntimeError("boom-3347"),
        ):
            response = recon.process_sepa_return_file(csv_text, file_type="csv")
        self.assertEqual(response["status_counts"], {"processed": 1}, msg=response)
        self.assertEqual(response["dunning_failed"], 1, msg=response)
        self.assertFalse(response["success"], msg=response)
        # The dashboard shows this key; without it the user reads "Error: Unknown error".
        self.assertIn("SEPA Return Dunning Failed", response.get("message", ""), msg=response)
        self.assertIn("1 returns were reversed", response["message"], msg=response)

    def test_a_clean_file_stays_a_success_with_no_dunning_failures(self):
        """Control: the new aggregate does not redden a file whose dunning worked."""
        self._collect()
        csv_text = (
            "Member_ID,Amount,Return_Reason,Return_Code\n"
            f"{self.member_id},{self._amount},{SEPA_RETURN_REASON_CODES['AM04']},AM04\n"
        )
        response = recon.process_sepa_return_file(csv_text, file_type="csv")
        self.assertEqual(response["dunning_failed"], 0, msg=response)
        self.assertTrue(response["success"], msg=response)
        self.assertNotIn("message", response)

    def test_pain002_dunning_failure_is_surfaced_in_the_result(self):
        from unittest.mock import patch

        self.expectErrorLog("Mollie Account Configuration")
        self.expectErrorLog("SEPA Return Dunning Failed")
        invoice = self._unpaid_linked_invoice()
        # Mock justified: fault injected at the schedule save; no real input makes it raise here.
        with patch(
            "verenigingen.verenigingen.doctype.membership_dues_schedule."
            "membership_dues_schedule.MembershipDuesSchedule.save",
            side_effect=RuntimeError("boom-3347"),
        ):
            response = btr.process_sepa_return_file(self._pain002(invoice.name, "x"), file_type="pain.002")
            direct = btr.handle_payment_rejection(f"E2E-{invoice.name}", "AM04", "x", file_key="k3347")
        self.assertEqual(response.get("dunning_failed"), 1, msg=response)
        self.assertIn("SEPA Return Dunning Failed", response.get("message", ""), msg=response)
        self.assertEqual(direct, {"dunning_failed": True})
