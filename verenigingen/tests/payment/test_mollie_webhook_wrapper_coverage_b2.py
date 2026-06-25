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
  * _update_missing_payment_history early-return on empty list (returns 0)
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
    def test_empty_list_returns_zero(self):
        donation = self._make_submitted_donation()
        with self.assertNoErrorLog():
            count = self.service._update_missing_payment_history(donation, self.pid, [])
        self.assertEqual(count, 0)

    def test_backfills_missing_payment_entry_row(self):
        """A refund with a real Payment Entry but no history row gets a Refunded
        row appended (amount negated) and persisted."""
        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        missing = [
            {"refund_id": "re_xyz", "payment_entry": pe.name, "amount": 10.0}
        ]
        with self.assertNoErrorLog():
            count = self.service._update_missing_payment_history(
                donation, self.pid, missing
            )
        self.assertEqual(count, 1)
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
        and returns 0 (already exists)."""
        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        missing = [
            {"refund_id": "re_dup", "payment_entry": pe.name, "amount": 10.0}
        ]
        first = self.service._update_missing_payment_history(donation, self.pid, missing)
        self.assertEqual(first, 1)
        donation.reload()
        with self.assertNoErrorLog():
            second = self.service._update_missing_payment_history(
                donation, self.pid, missing
            )
        self.assertEqual(second, 0)
        donation.reload()
        rows = [
            p
            for p in donation.payments
            if getattr(p, "payment_entry", None) == pe.name
        ]
        self.assertEqual(len(rows), 1, "no duplicate row should be added")
