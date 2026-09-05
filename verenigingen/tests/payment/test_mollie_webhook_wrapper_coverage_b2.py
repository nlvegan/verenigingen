"""
Real-DB coverage gap-fill for the unified Mollie webhook wrapper service.

Target: verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py
        -> UnifiedWebhookWrapperService._process_pending_refunds
        -> UnifiedWebhookWrapperService._update_missing_payment_history

These are DB-heavy refund/history backfill helpers. The existing
test_mollie_gap_unified_webhook_handlers.py and test_unified_webhook_wrapper_service.py
cover the handler dispatch / reversal-webhook paths. This file gap-fills the two
extracted batch helpers using REAL submitted Donation documents and a REAL
Payment Entry.

What is covered (no external boundary touched):
  * _process_pending_refunds early-return on empty list
  * _process_pending_refunds Mollie-config-error branch (the bank-account config
    on the test site has no clearing account, so the real config call returns an
    error and the helper returns a single error result WITHOUT any HTTP call)
  * _update_missing_payment_history early-return on empty list (returns (0, None))
  * _update_missing_payment_history idempotent skip when the PE row already exists
  * _update_missing_payment_history real backfill: appends a Refunded payment
    history row pointing at a real Payment Entry and persists it

OUT OF SCOPE (require live Mollie config + REST): the refund *success* path of
_process_pending_refunds (it creates a Bank Transaction via the Mollie bank
account config + a refund Journal Entry). The test site has no Mollie clearing
account, so that path cannot run without a real token — we exercise its
config-error branch instead, which is the deterministic, no-HTTP slice.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)


class WrapperBase(EnhancedTestCase):
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
        self.pid = f"tr_{frappe.generate_hash(length=20)}"
        self.service = UnifiedWebhookWrapperService()

    def _make_submitted_donation(self):
        """Create and submit a Donation linked to a Donor (with Customer).

        _update_missing_payment_history / _process_pending_refunds set
        ignore_validate_update_after_submit, so the donation must be submitted.
        """
        donor = self._make_donor()
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "company": self.company,
                "donor": donor,
                "amount": 25.0,
                "donation_date": today(),
                "currency": "EUR",
                "paid": 1,
                "mode_of_payment": "Bank Transfer",
                "payment_id": self.pid,
            }
        )
        donation.insert(ignore_permissions=True)
        donation.submit()
        return donation

    def _make_donor(self):
        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": f"WrapDonor {frappe.generate_hash(length=5)}",
                "donor_type": "Individual",
                "donor_email": f"wrap.donor.{frappe.generate_hash(length=8)}@example.com",
                "currency": "EUR",
            }
        )
        donor.insert(ignore_permissions=True)
        return donor.name

    def _make_submitted_payment_entry(self, customer=None):
        """Build a minimal submitted Payment Entry (docstatus set directly in DB)
        for the history-backfill path, mirroring the recovery test approach. The
        helper only reads posting_date from it."""
        receivable = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Receivable", "is_group": 0},
            "name",
        )
        bank = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Bank", "is_group": 0},
            "name",
        )
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.company = self.company
        pe.posting_date = today()
        pe.paid_amount = 10.0
        pe.received_amount = 10.0
        pe.reference_no = f"{self.pid}_refund_re_{frappe.generate_hash(length=6)}"
        pe.reference_date = today()
        pe.paid_from = bank
        pe.paid_to = receivable
        pe.flags.ignore_validate = True
        pe.flags.ignore_mandatory = True
        pe.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value("Payment Entry", pe.name, "docstatus", 1, update_modified=False)
        pe.reload()
        return pe


# =============================================================================
# _process_pending_refunds
# =============================================================================
class TestProcessPendingRefunds(WrapperBase):
    def test_empty_list_returns_empty(self):
        donation = self._make_submitted_donation()
        with self.assertNoErrorLog():
            results = self.service._process_pending_refunds(donation, self.pid, [])
        self.assertEqual(results, [])

    def test_config_error_returns_single_error_result(self):
        """When no Mollie clearing account is configured, the real bank-account
        config call returns an error and the helper returns one error result for
        'all' refunds WITHOUT touching the Mollie HTTP API. On a site where the
        clearing account IS configured (e.g. the canonical veg11) this branch is
        unreachable without live HTTP, so the assertion is scoped to the
        genuine no-config case (which is what fresh CI test sites exercise)."""
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        if not get_bank_transaction_creator().get_mollie_bank_account_config().get("error"):
            self.skipTest(
                "Mollie clearing account configured on this site; the config-error "
                "branch is unreachable without a live Mollie HTTP call"
            )
        donation = self._make_submitted_donation()
        pending = [{"refund_id": "re_abc", "amount": 5.0, "refund_date": today()}]
        # The Mollie bank-account config validation logs an (intentional, expected)
        # Error Log row about the missing clearing account; register it so the
        # automatic tearDown guard ignores it. This is the deterministic no-HTTP
        # slice of the refund path.
        self.expectErrorLog("Clearing Account", "Configuration validation")
        results = self.service._process_pending_refunds(donation, self.pid, pending)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(results[0]["refund_id"], "all")
        self.assertTrue(results[0]["message"])


# =============================================================================
# _update_missing_payment_history
# =============================================================================
class TestUpdateMissingPaymentHistory(WrapperBase):
    def test_empty_list_returns_zero_and_no_failure(self):
        donation = self._make_submitted_donation()
        with self.assertNoErrorLog():
            count, failure = self.service._update_missing_payment_history(donation, self.pid, [])
        self.assertEqual(count, 0)
        self.assertIsNone(failure)

    def test_backfills_missing_payment_entry_row(self):
        """A refund with a real Payment Entry but no history row gets a Refunded
        row appended (amount negated) and persisted."""
        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        missing = [
            {"refund_id": "re_xyz", "payment_entry": pe.name, "amount": 10.0}
        ]
        with self.assertNoErrorLog():
            count, failure = self.service._update_missing_payment_history(
                donation, self.pid, missing
            )
        self.assertEqual(count, 1)
        self.assertIsNone(failure)
        donation.reload()
        rows = [
            p
            for p in donation.payments
            if getattr(p, "payment_entry", None) == pe.name
        ]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.payment_status, "Refunded")
        self.assertEqual(float(row.amount), -10.0)  # negated for refund
        self.assertEqual(row.mollie_payment_id, "re_xyz")

    def test_idempotent_skip_when_entry_exists(self):
        """A second call with the same Payment Entry must not add a duplicate row
        and returns (0, None) -- already exists, NOT a failure."""
        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        missing = [
            {"refund_id": "re_dup", "payment_entry": pe.name, "amount": 10.0}
        ]
        first_count, first_failure = self.service._update_missing_payment_history(
            donation, self.pid, missing
        )
        self.assertEqual(first_count, 1)
        self.assertIsNone(first_failure)
        donation.reload()
        with self.assertNoErrorLog():
            second_count, second_failure = self.service._update_missing_payment_history(
                donation, self.pid, missing
            )
        self.assertEqual(second_count, 0)
        self.assertIsNone(second_failure, "nothing-to-do must not read as a failure")
        donation.reload()
        rows = [
            p
            for p in donation.payments
            if getattr(p, "payment_entry", None) == pe.name
        ]
        self.assertEqual(len(rows), 1, "no duplicate row should be added")

    def test_save_failure_returns_zero_and_a_reason_not_silent_success(self):
        """#478: a failed batch save must be distinguishable from 'nothing to
        add' -- both used to return the same bare 0. A caller that only checks
        `count > 0` cannot tell them apart; the second element of the tuple is
        what a caller must now branch on.
        """
        from unittest.mock import patch

        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        missing = [{"refund_id": "re_boom", "payment_entry": pe.name, "amount": 10.0}]

        self.expectErrorLog("Payment History Backfill Error")
        with patch.object(type(donation), "save", side_effect=Exception("db exploded")):
            count, failure = self.service._update_missing_payment_history(
                donation, self.pid, missing
            )

        self.assertEqual(count, 0)
        self.assertIsNotNone(
            failure,
            "a failed backfill must not be reported the same way as 'nothing to add'",
        )
        self.assertIn("db exploded", failure)


# =============================================================================
# #478: the two callers of _update_missing_payment_history must ACT on the
# (count, failure) distinction, not just receive it.
# =============================================================================
class TestMissingPaymentHistoryCallerPropagation(WrapperBase):
    def _missing_entry(self, refund_id, pe_name):
        return [{"refund_id": refund_id, "payment_entry": pe_name, "amount": 5.0}]

    def test_fully_processed_handler_reports_backfill_failure(self):
        """_handle_fully_processed_payment used to call
        _update_missing_payment_history and discard the return value entirely
        (line 680 pre-fix) -- a failed backfill answered Mollie 200 and the
        refund history row stayed missing forever.

        Patching ``save`` on the CLASS fails every Donation save for the
        duration of the block, not just the backfill's -- safe here only
        because ``pending_refunds`` is empty (no refund booking touches
        ``donation.save``) and there is no donation-status write on this
        handler's path.
        """
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
            PaymentIdempotencyCheckResult,
        )

        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        state = PaymentIdempotencyCheckResult(self.pid)
        state.payment_history_missing = self._missing_entry("re_fail1", pe.name)

        self.expectErrorLog("Payment History Backfill Error")
        with patch.object(type(donation), "save", side_effect=Exception("backfill boom")):
            result = self.service._handle_fully_processed_payment(self.pid, state, 0.0)

        self.assertEqual(
            result["status"],
            "error",
            "a failed missing-payment-history backfill must not be reported as success",
        )
        failure_entries = [
            r for r in result["refund_processing"] if r.get("failure_kind") == "payment_history"
        ]
        self.assertEqual(len(failure_entries), 1)
        self.assertIn("backfill boom", failure_entries[0]["message"])

    def test_fully_processed_handler_noop_backfill_still_succeeds(self):
        """Control for the test above: when the backfill genuinely has nothing to
        do (the row already exists), the handler must still report success --
        the fix must distinguish failure from no-op, not just fail everything
        that touches payment_history_missing."""
        from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
            PaymentIdempotencyCheckResult,
        )

        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        entry = self._missing_entry("re_dup2", pe.name)
        first_count, first_failure = self.service._update_missing_payment_history(
            donation, self.pid, entry
        )
        self.assertEqual((first_count, first_failure), (1, None))
        donation.reload()

        state = PaymentIdempotencyCheckResult(self.pid)
        state.payment_history_missing = entry

        with self.assertNoErrorLog():
            result = self.service._handle_fully_processed_payment(self.pid, state, 0.0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            [r for r in result["refund_processing"] if r.get("failure_kind") == "payment_history"],
            [],
        )
        # Prove the idempotent-skip branch actually ran against the real row
        # rather than the assertion above passing for a reason unconnected to
        # the backfill (e.g. no duplicate because nothing touched the table).
        donation.reload()
        rows = [p for p in donation.payments if getattr(p, "payment_entry", None) == pe.name]
        self.assertEqual(len(rows), 1, "no duplicate row should be added by the no-op path")

    def test_partial_handler_reports_backfill_failure(self):
        """_handle_partial_processing used to read `refund_history_count > 0`
        (line 1149 pre-fix) -- 0 from a failed save was silently read as
        'nothing to do' and the handler answered success/component_failures=[].

        `donation_status` is deliberately left missing and stubbed to succeed
        independently of the patched ``save`` below: without a real, unrelated
        component present, `results` stays empty regardless of the backfill's
        outcome, and the pre-existing ``if results and ... else "error"`` check
        makes ``status == "error"`` true for a reason that has nothing to do
        with THIS fix (caught in skeptical review). Stubbing keeps that
        component's success independent of the ``save`` patch, so the failure
        below is the only thing that can flip the status.
        """
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
            PaymentIdempotencyCheckResult,
        )

        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        state = PaymentIdempotencyCheckResult(self.pid)
        state.payment_entry_exists = True
        state.payment_history_updated = True
        state.donation_status_updated = False
        state.payment_history_missing = self._missing_entry("re_pfail", pe.name)

        self.service._update_donation_status = lambda *a, **k: None  # succeeds, independent of save patch

        self.expectErrorLog("Payment History Backfill Error")
        with patch.object(
            self.service, "_fetch_payment_from_mollie", return_value={"status": "paid"}
        ), patch.object(type(donation), "save", side_effect=Exception("partial backfill boom")):
            result = self.service._handle_partial_processing(self.pid, {}, state, 0.0)

        self.assertEqual(
            result["status"],
            "error",
            "a failed refund-history backfill during partial processing must not read as success",
        )
        self.assertIn("refund payment history", result["component_failures"])
        self.assertIn(
            "Donation status updated",
            result["components_processed"],
            "the independent component must have actually run and succeeded",
        )

    def test_partial_handler_noop_backfill_still_succeeds(self):
        """Control: nothing new to backfill (already present) plus a real
        completed component must still report success."""
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
            PaymentIdempotencyCheckResult,
        )

        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        entry = self._missing_entry("re_pdup", pe.name)
        first_count, first_failure = self.service._update_missing_payment_history(
            donation, self.pid, entry
        )
        self.assertEqual((first_count, first_failure), (1, None))
        donation.reload()

        state = PaymentIdempotencyCheckResult(self.pid)
        state.payment_entry_exists = True
        state.payment_history_updated = True
        # donation_status_updated left False so the handler has a real component
        # to complete -- otherwise an empty `results` list independently forces
        # "error", which is not what this test is checking.
        state.payment_history_missing = entry

        with patch.object(
            self.service, "_fetch_payment_from_mollie", return_value={"status": "paid"}
        ), self.assertNoErrorLog():
            result = self.service._handle_partial_processing(self.pid, {}, state, 0.0)

        self.assertEqual(result["status"], "success", f"unexpected: {result}")
        self.assertEqual(result["component_failures"], [])
        # Prove the idempotent-skip branch actually ran against the real row.
        donation.reload()
        rows = [p for p in donation.payments if getattr(p, "payment_entry", None) == pe.name]
        self.assertEqual(len(rows), 1, "no duplicate row should be added by the no-op path")
