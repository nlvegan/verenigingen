"""
Gap-analysis tests for UnifiedWebhookWrapperService handler branches.

Target:
    verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py

The existing test_unified_webhook_wrapper_service.py covers:
    - process_payment_webhook STEP-0 routing (order/dues/503/classification fallback)
    - process_reversal_webhook validation/idempotency/success
    - process_refund/chargeback delegation, _fetch_payment_from_mollie
    - _handle_new_payment_processing skip/no-donation early returns
    - find_donation_for_payment_by_id

This file closes the remaining branch gaps that a regression would slip through:

    1. _handle_partial_processing   — the entire method was untested: which
       components get completed, the success/error result shape, the
       refund-history backfill branch, and the exception handler.
    2. _handle_fully_processed_payment — the failed-refund branch that returns
       status="error" to trigger a Mollie retry (a regression here would
       silently swallow refund failures), the all-succeed branch, and the
       "no donation but pending refunds" error branch.
    3. _update_donation_status — recurring vs one-time routing + the
       exception-swallow contract.
    4. _update_donation_payment_history_atomic — idempotency skip vs real append.
    5. process_chargeback_webhook nested-id extraction (only refund nesting was
       previously asserted).

Strategy: the service is built with object.__new__ (no live Mollie/idempotency
setup); a real MollieLogger is attached and the idempotency_manager is a
MagicMock. Handlers are invoked directly with a PaymentIdempotencyCheckResult
test double and a REAL (DB-backed) Donation document, so payment-history appends
and donation.save() run against the database. Collaborators that reach the
Mollie SDK / bank docs (_create_donation_financial_entries) are stubbed on the
instance — they are collaborators of the handler, not its own logic, and have
their own coverage elsewhere.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_gap_unified_webhook_handlers
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.mollie.services import (
    webhook_wrapper_service_unified as wws,
)
from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
    PaymentIdempotencyCheckResult,
)


def _make_service(idempotency_manager=None):
    """Construct the wrapper without running __init__ (no live setup)."""
    from unittest.mock import MagicMock

    svc = object.__new__(wws.UnifiedWebhookWrapperService)
    svc.logger = wws.MollieLogger("test_gap_unified_webhook")
    svc._debug_mode = False
    svc.idempotency_manager = idempotency_manager or MagicMock()
    return svc


def _persist_donation(payment_id, with_payment_row=False):
    """Create a real draft Donation (Donation is not submittable).

    Drops any donation already holding this payment_id first. The services under
    test here commit (that is what "_atomic" means), which defeats the
    rollback() in tearDown, so these rows outlive the run. That was harmless
    until payment_id became unique (#345): the leaked row now makes the NEXT run
    of this module fail with a duplicate-key error, so the module has to clear
    its own path rather than assume a clean table.
    """
    for stale in frappe.get_all("Donation", filters={"payment_id": payment_id}, pluck="name"):
        frappe.delete_doc("Donation", stale, force=True, ignore_permissions=True, delete_permanently=True)

    donor = frappe.new_doc("Donor")
    donor.donor_name = "Gap Test Donor"
    donor.donor_type = "Individual"
    donor.donor_email = f"gap-{frappe.generate_hash(length=6)}@example.com"
    donor.flags.ignore_mandatory = True
    donor.insert(ignore_permissions=True)

    donation = frappe.new_doc("Donation")
    donation.donor = donor.name
    donation.amount = 10
    donation.donation_date = frappe.utils.nowdate()
    donation.mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name") or "Cash"
    donation.payment_id = payment_id
    donation.flags.ignore_mandatory = True
    if with_payment_row:
        donation.append(
            "payments",
            {
                "mollie_payment_id": payment_id,
                "amount": 10,
                "payment_date": frappe.utils.nowdate(),
                "payment_method": "Mollie",
                "payment_status": "Paid",
            },
        )
    donation.insert(ignore_permissions=True)
    return donation


class TestHandlePartialProcessing(FrappeTestCase):
    """_handle_partial_processing completes only the missing components."""

    def setUp(self):
        self.svc = _make_service()

    def tearDown(self):
        frappe.db.rollback()

    def test_only_missing_components_processed_and_reported(self):
        """PE exists + status set, history missing -> only history path runs.

        A regression that re-creates financial entries (already present) or
        re-updates status would show up as extra completed components, so we
        assert the EXACT set of work done.
        """
        donation = _persist_donation("tr_partial_hist")
        state = PaymentIdempotencyCheckResult("tr_partial_hist")
        state.payment_entry_exists = True  # financial entries already present
        state.donation_status_updated = True
        state.payment_history_updated = False  # only this is missing

        calls = []

        def fake_financial(donation_doc, payment_data):
            calls.append("financial")
            return {"bank_transaction_name": "BT-X", "journal_entry_name": "JE-X"}

        def fake_status(donation_doc, payment_data):
            calls.append("status")

        self.svc._create_donation_financial_entries = fake_financial
        self.svc._update_donation_status = fake_status
        self.svc._update_donation_payment_history_atomic = lambda *a, **k: calls.append("history") or True
        self.svc._update_donor_record = lambda *a, **k: calls.append("donor") or True
        self.svc._update_member_payment_history = lambda *a, **k: calls.append("member") or True

        with self._patch_fetch_and_find(donation):
            result = self.svc._handle_partial_processing("tr_partial_hist", {}, state, 0.0)

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["partial_processing"])
        # financial_entries + status were NOT in the missing set -> not run.
        self.assertNotIn("financial", calls)
        self.assertNotIn("status", calls)
        # history (+donor+member as part of the history branch) WAS run.
        self.assertIn("history", calls)
        self.assertIn("donor", calls)
        self.assertIn("member", calls)
        self.assertIn("payment_history", result["completed_components"])

    def test_history_backfill_looks_up_je_by_cheque_no_not_reference_no(self):
        """REGRESSION: when financial entries already exist but the JE name was
        not produced this call, the backfill looks up the existing Journal Entry
        from the DB. Journal Entry has NO `reference_no` column (the donation JE
        creator stores the Mollie payment id in `cheque_no`), so the previous
        `{"reference_no": payment_id}` filter raised "Unknown column
        'reference_no'" and aborted the entire partial-processing flow.

        We seed a real submitted-state Journal Entry carrying the payment id in
        cheque_no and assert the backfill (a) does NOT crash and (b) passes the
        discovered JE name through to the history updater.
        """
        donation = _persist_donation("tr_partial_je_lookup")
        je_name = self._make_journal_entry_with_cheque_no("tr_partial_je_lookup")

        state = PaymentIdempotencyCheckResult("tr_partial_je_lookup")
        state.payment_entry_exists = True  # financial entries present -> JE not created here
        state.donation_status_updated = True
        state.payment_history_updated = False  # only history missing

        captured = {}

        def fake_history(donation_doc, payment_data, journal_entry_name):
            captured["je"] = journal_entry_name
            return True

        self.svc._update_donation_payment_history_atomic = fake_history
        self.svc._update_donor_record = lambda *a, **k: True
        self.svc._update_member_payment_history = lambda *a, **k: True

        with self._patch_fetch_and_find(donation):
            result = self.svc._handle_partial_processing("tr_partial_je_lookup", {}, state, 0.0)

        self.assertEqual(result["status"], "success")
        # The existing JE was discovered via cheque_no and threaded through.
        self.assertEqual(captured["je"], je_name)

    def _make_journal_entry_with_cheque_no(self, payment_id):
        company = frappe.db.get_value("Company", {}, "name")
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = frappe.utils.nowdate()
        je.cheque_no = payment_id
        je.cheque_date = frappe.utils.nowdate()
        je.user_remark = "gap test je"
        # Two balancing rows against non-party accounts (Receivable/Payable need a
        # party). Content is irrelevant to the cheque_no lookup we are exercising.
        accounts = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "is_group": 0,
                "account_type": ["not in", ["Receivable", "Payable"]],
                "root_type": ["in", ["Asset", "Expense", "Income"]],
            },
            pluck="name",
            limit=2,
        )
        je.append("accounts", {"account": accounts[0], "debit_in_account_currency": 1})
        je.append("accounts", {"account": accounts[1], "credit_in_account_currency": 1})
        je.flags.ignore_mandatory = True
        je.flags.ignore_permissions = True
        je.insert(ignore_permissions=True)
        return je.name

    def test_all_missing_runs_financial_status_and_history(self):
        donation = _persist_donation("tr_partial_all")
        state = PaymentIdempotencyCheckResult("tr_partial_all")
        # Nothing processed yet.
        calls = []
        self.svc._create_donation_financial_entries = lambda *a, **k: (
            calls.append("financial") or {"bank_transaction_name": "BT-1", "journal_entry_name": "JE-1"}
        )
        self.svc._update_donation_status = lambda *a, **k: calls.append("status")
        self.svc._update_donation_payment_history_atomic = lambda *a, **k: calls.append("history") or True
        self.svc._update_donor_record = lambda *a, **k: True
        self.svc._update_member_payment_history = lambda *a, **k: True

        with self._patch_fetch_and_find(donation):
            result = self.svc._handle_partial_processing("tr_partial_all", {}, state, 0.0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls, ["financial", "status", "history"])
        # The status message references the actual created JE name.
        self.assertIn("JE-1", result["message"])

    def test_a_journal_entry_failure_is_not_reported_as_success(self):
        """The same half-booking defect as _handle_new_payment_processing.

        _create_donation_financial_entries returns a TRUTHY dict when the Bank
        Transaction landed and the Journal Entry did not. Before this fix,
        `results` still ended up non-empty (the "Journal Entry creation failed
        (partial)" string is itself appended to it), so `"success" if results
        else "error"` reported success anyway.
        """
        donation = _persist_donation("tr_partial_je_fail")
        state = PaymentIdempotencyCheckResult("tr_partial_je_fail")
        # Nothing processed yet -- financial_entries is the only missing piece
        # under test; leaving payment_history/donation_status missing too would
        # let their own "updated" results paper over the financial failure.
        state.payment_history_updated = True
        state.donation_status_updated = True

        self.svc._create_donation_financial_entries = lambda *a, **k: {
            "bank_transaction_name": "BT-partial",
            "journal_entry_name": None,
            "partial_success": True,
        }

        with self._patch_fetch_and_find(donation):
            result = self.svc._handle_partial_processing("tr_partial_je_fail", {}, state, 0.0)

        self.assertEqual(result["status"], "error", "a missing Journal Entry must fail the webhook")

    def test_partial_no_donation_errors(self):
        state = PaymentIdempotencyCheckResult("tr_partial_nodon")
        with self.svc_fetch_returns({"status": "paid"}), self._patch_find(None):
            result = self.svc._handle_partial_processing("tr_partial_nodon", {}, state, 0.0)
        self.assertEqual(result["status"], "error")
        self.assertIn("No donation found", result["message"])

    def test_partial_exception_returns_error_with_missing_components(self):
        donation = _persist_donation("tr_partial_boom")
        state = PaymentIdempotencyCheckResult("tr_partial_boom")
        # Force the financial-entries collaborator to raise after fetch+find.
        self.svc._create_donation_financial_entries = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("financial kaboom")
        )
        with self.svc_fetch_returns({"status": "paid"}), self._patch_find(donation):
            result = self.svc._handle_partial_processing("tr_partial_boom", {}, state, 0.0)
        self.assertEqual(result["status"], "error")
        self.assertIn("financial kaboom", result["message"])
        self.assertIn("financial_entries", result["missing_components"])

    # ---- helpers -------------------------------------------------------
    def _patch_fetch_and_find(self, donation):
        from contextlib import ExitStack
        from unittest.mock import patch

        stack = ExitStack()
        stack.enter_context(
            patch.object(self.svc, "_fetch_payment_from_mollie", return_value={"status": "paid"})
        )
        stack.enter_context(patch.object(wws, "find_donation_for_payment_by_id", return_value=donation))
        return stack

    def svc_fetch_returns(self, payload):
        from unittest.mock import patch

        return patch.object(self.svc, "_fetch_payment_from_mollie", return_value=payload)

    def _patch_find(self, donation):
        from unittest.mock import patch

        return patch.object(wws, "find_donation_for_payment_by_id", return_value=donation)


class TestHandleFullyProcessedRefundBranches(FrappeTestCase):
    """_handle_fully_processed_payment refund result aggregation."""

    def setUp(self):
        self.svc = _make_service()

    def tearDown(self):
        frappe.db.rollback()

    def test_failed_refund_returns_error_to_trigger_retry(self):
        """If a pending refund fails to process, the overall response MUST be
        status=error so Mollie retries -- otherwise a failed refund is lost."""
        donation = _persist_donation("tr_full_failrefund")
        state = PaymentIdempotencyCheckResult("tr_full_failrefund")
        state.payment_entry_exists = True
        state.payment_history_updated = True
        state.donation_status_updated = True
        state.pending_refunds = [{"refund_id": "re_1", "amount": 5, "refund_date": "2026-01-01"}]

        from unittest.mock import patch

        with patch.object(wws, "find_donation_for_payment_by_id", return_value=donation), patch.object(
            self.svc,
            "_process_pending_refunds",
            return_value=[{"status": "error", "refund_id": "re_1", "message": "bt failed"}],
        ):
            result = self.svc._handle_fully_processed_payment("tr_full_failrefund", state, 0.0)

        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["failed_refunds"]), 1)
        self.assertTrue(result["idempotent"])
        self.assertIn("requires retry", result["message"])

    def test_succeeded_refunds_return_success(self):
        donation = _persist_donation("tr_full_okrefund")
        state = PaymentIdempotencyCheckResult("tr_full_okrefund")
        state.payment_entry_exists = True
        state.payment_history_updated = True
        state.donation_status_updated = True
        state.pending_refunds = [{"refund_id": "re_ok", "amount": 5}]

        from unittest.mock import patch

        with patch.object(wws, "find_donation_for_payment_by_id", return_value=donation), patch.object(
            self.svc,
            "_process_pending_refunds",
            return_value=[{"status": "success", "refund_id": "re_ok"}],
        ):
            result = self.svc._handle_fully_processed_payment("tr_full_okrefund", state, 0.0)

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["unified_state"]["pending_operations_handled"], 1)

    def test_pending_refunds_but_no_donation_errors(self):
        state = PaymentIdempotencyCheckResult("tr_full_nodon")
        state.payment_entry_exists = True
        state.payment_history_updated = True
        state.donation_status_updated = True
        state.pending_refunds = [{"refund_id": "re_x", "amount": 5}]

        from unittest.mock import patch

        with patch.object(wws, "find_donation_for_payment_by_id", return_value=None):
            result = self.svc._handle_fully_processed_payment("tr_full_nodon", state, 0.0)

        # No donation + a failed refund result -> overall error.
        self.assertEqual(result["status"], "error")


class TestUpdateDonationStatus(FrappeTestCase):
    """_update_donation_status: recurring vs one-time + exception-swallow."""

    def setUp(self):
        self.svc = _make_service()

    def tearDown(self):
        frappe.db.rollback()

    def test_subscription_marks_recurring_and_paid(self):
        donation = _persist_donation("tr_status_recur")
        self.svc._update_donation_status(
            donation, {"id": "tr_status_recur", "metadata": {"subscription_id": "sub_1"}}
        )
        donation.reload()
        self.assertEqual(donation.status, "Recurring")
        self.assertEqual(donation.paid, 1)

    def test_no_subscription_marks_one_time(self):
        donation = _persist_donation("tr_status_one")
        self.svc._update_donation_status(donation, {"id": "tr_status_one", "metadata": {}})
        donation.reload()
        self.assertEqual(donation.status, "One-time")
        self.assertEqual(donation.paid, 1)

    def test_save_failure_is_swallowed(self):
        """Status-update errors must not bubble (webhook keeps processing)."""
        donation = _persist_donation("tr_status_boom")

        def boom():
            raise RuntimeError("save failed")

        donation.save = boom  # type: ignore[method-assign]
        # Should not raise.
        self.svc._update_donation_status(donation, {"id": "tr_status_boom", "metadata": {}})


class TestUpdateDonationPaymentHistoryAtomic(FrappeTestCase):
    """_update_donation_payment_history_atomic idempotency + append."""

    def setUp(self):
        self.svc = _make_service()

    def tearDown(self):
        frappe.db.rollback()

    def test_existing_entry_short_circuits(self):
        donation = _persist_donation("tr_hist_dup", with_payment_row=True)
        existing_count = len(donation.payments)
        result = self.svc._update_donation_payment_history_atomic(
            donation, {"id": "tr_hist_dup", "amount": {"value": "10.00", "currency": "EUR"}}, "JE-1"
        )
        self.assertTrue(result)
        # No new row appended (idempotent).
        self.assertEqual(len(donation.payments), existing_count)

    def test_new_entry_appended_and_persisted(self):
        donation = _persist_donation("tr_hist_new")
        result = self.svc._update_donation_payment_history_atomic(
            donation,
            {
                "id": "tr_hist_new",
                "amount": {"value": "10.00", "currency": "EUR"},
                "paid_at": "2026-02-01T12:00:00+00:00",
            },
            "JE-NEW",
        )
        self.assertTrue(result)
        # Re-read from DB: the atomic update commits the child row.
        reloaded = frappe.get_doc("Donation", donation.name)
        rows = [p for p in reloaded.payments if p.mollie_payment_id == "tr_hist_new"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].journal_entry, "JE-NEW")
        self.assertEqual(rows[0].payment_status, "Paid")


class TestProcessChargebackNestedExtraction(FrappeTestCase):
    """process_chargeback_webhook extracts the nested chargeback id + reason."""

    def setUp(self):
        self.svc = _make_service()

    def test_nested_chargeback_id_and_reason(self):
        captured = {}
        self.svc.process_reversal_webhook = lambda **kw: captured.update(kw) or {"status": "ok"}
        self.svc.process_chargeback_webhook(
            "tr_1",
            {
                "chargeback": {
                    "id": "chb_nested",
                    "amount": {"value": "20.00"},
                    "reason": {"code": "AC04"},
                }
            },
        )
        self.assertEqual(captured["reversal_id"], "chb_nested")
        self.assertEqual(captured["reversal_type"], "chargeback")
        self.assertEqual(captured["reason"], {"code": "AC04"})


if __name__ == "__main__":
    unittest.main()
