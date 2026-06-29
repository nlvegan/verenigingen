"""
Coverage sweep for UnifiedWebhookWrapperService — the refund *success* paths.

Target: verenigingen/verenigingen_payments/mollie/services/webhook_wrapper_service_unified.py

The existing suites cover:
- test_webhook_wrapper_unified_unit.py — routing, reversal *validation*, fetch
  normalisation, fully-processed aggregation, delegation.
- test_mollie_webhook_wrapper_coverage_b2.py — _process_pending_refunds empty +
  config-error branches, _update_missing_payment_history backfill/idempotency.

This module gap-fills the two largest still-uncovered orchestrations, exercising
their REAL business logic against REAL submitted Donation documents:

  1. _process_pending_refunds SUCCESS path (date parsing → Bank Transaction →
     refund Journal Entry → batch payment-history append → mark-processed), plus
     the per-refund Bank-Transaction-failure and Journal-Entry-failure arms and
     the batch idempotency skip.
  2. process_reversal_webhook SUCCESS path for both refunds and chargebacks
     (reversal Payment Entry creation → payment-history append with the correct
     Refunded/Chargeback status → mark-processed), plus the
     donation-not-found "ignored" arm and the PE-creation-failed error arm.

Boundaries stubbed (and ONLY these — never the wrapper logic under test):
- the GL-writing collaborator services that reach outside the process: the Bank
  Transaction creator, the refund Journal Entry creator, and the unified Payment
  Entry creator. Their *return values* are wired to REAL documents (a real,
  link-valid Journal Entry / Payment Entry) so the donation child-table Link
  validation runs for real on save.
- the idempotency manager's Mollie-API-backed state check (a module collaborator
  the existing unit suite also stubs) and its mark_*_processed log no-ops, spied
  to assert they are invoked.

Because those collaborators are module-level, this module is ``*_sweep.py`` but
relies on the same Tier-1 boundary-stub pattern; all permission-bypass inserts
live in ``_make_`` / setUp helpers per the test-quality enforcer.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)


class _OrigStateExists:
    """Minimal idempotency-state stand-in reporting the original payment exists."""

    payment_entry_exists = True


class _FakeBTCreator:
    """Stand-in for the Bank Transaction creator boundary.

    ``config`` is the dict returned by get_mollie_bank_account_config(); ``bt_name``
    is what create_from_dict returns (None to simulate a failed Bank Transaction).
    """

    def __init__(self, config, bt_name="BT-REFUND-STUB"):
        self._config = config
        self._bt_name = bt_name
        self.create_calls = []

    def get_mollie_bank_account_config(self):
        return self._config

    def create_from_dict(self, **kwargs):
        self.create_calls.append(kwargs)
        return self._bt_name


class _FakeRefundJECreator:
    """Stand-in for the refund Journal Entry creator boundary."""

    def __init__(self, je_name):
        self._je_name = je_name
        self.create_calls = []

    def create_refund_journal_entry(self, **kwargs):
        self.create_calls.append(kwargs)
        return self._je_name


class WrapperSweepBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        cls._ensure_mode_of_payment("Mollie")
        frappe.db.commit()

    @classmethod
    def _ensure_mode_of_payment(cls, name):
        if not frappe.db.exists("Mode of Payment", name):
            frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": name, "type": "Bank"}).insert(
                ignore_permissions=True
            )

    def setUp(self):
        super().setUp()
        self.company = self._company
        self.pid = f"tr_{frappe.generate_hash(length=20)}"
        self.service = UnifiedWebhookWrapperService()

    # ---- record builders (permission-bypass lives here, never in test bodies) ----
    def _make_donor(self):
        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": f"SweepDonor {frappe.generate_hash(length=5)}",
                "donor_type": "Individual",
                "donor_email": f"sweep.donor.{frappe.generate_hash(length=8)}@example.com",
                "currency": "EUR",
            }
        )
        donor.insert(ignore_permissions=True)
        return donor.name

    def _make_submitted_donation(self, payment_id=None):
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
                "payment_id": payment_id or self.pid,
            }
        )
        donation.insert(ignore_permissions=True)
        donation.submit()
        return donation

    def _bank_account(self):
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Bank", "is_group": 0},
            "name",
        )

    def _make_submitted_journal_entry(self):
        """Create a link-valid submitted Journal Entry.

        The donation payment-history row stores ``journal_entry`` as a Link to
        Journal Entry, so the refund-history append on donation.save() validates
        the link. We only need a real, submitted JE name; force docstatus in DB
        to avoid full JE balancing validation (the creator boundary is stubbed)."""
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = self.company
        je.posting_date = today()
        je.flags.ignore_validate = True
        je.flags.ignore_mandatory = True
        je.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value("Journal Entry", je.name, "docstatus", 1, update_modified=False)
        return je.name

    def _make_submitted_payment_entry(self):
        receivable = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Receivable", "is_group": 0},
            "name",
        )
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.company = self.company
        pe.posting_date = today()
        pe.paid_amount = 10.0
        pe.received_amount = 10.0
        pe.reference_no = f"{self.pid}_reversal_{frappe.generate_hash(length=6)}"
        pe.reference_date = today()
        pe.paid_from = self._bank_account()
        pe.paid_to = receivable
        pe.flags.ignore_validate = True
        pe.flags.ignore_mandatory = True
        pe.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value("Payment Entry", pe.name, "docstatus", 1, update_modified=False)
        pe.reload()
        return pe

    # ---- boundary wiring helpers ----
    def _wire_refund_creators(self, bt_creator, je_creator):
        """Patch the two GL-writing creator factories the refund path imports."""
        import verenigingen.verenigingen_payments.services.bank_transaction_creator as btc_mod
        import verenigingen.verenigingen_payments.services.donation_refund_journal_entry_creator as je_mod

        orig_bt = btc_mod.get_bank_transaction_creator
        orig_je = je_mod.get_donation_refund_journal_entry_creator
        btc_mod.get_bank_transaction_creator = lambda: bt_creator
        je_mod.get_donation_refund_journal_entry_creator = lambda: je_creator
        self.addCleanup(lambda: setattr(btc_mod, "get_bank_transaction_creator", orig_bt))
        self.addCleanup(lambda: setattr(je_mod, "get_donation_refund_journal_entry_creator", orig_je))

    def _spy_mark_refund(self):
        calls = []
        self.service.idempotency_manager.mark_refund_processed = lambda *a: calls.append(a)
        return calls

    def _spy_mark_chargeback(self):
        calls = []
        self.service.idempotency_manager.mark_chargeback_processed = lambda *a: calls.append(a)
        return calls


# =============================================================================
# _process_pending_refunds — SUCCESS / failure orchestration
# =============================================================================
class TestProcessPendingRefundsSuccess(WrapperSweepBase):
    def test_success_path_creates_refund_history_row_and_marks_processed(self):
        donation = self._make_submitted_donation()
        je_name = self._make_submitted_journal_entry()
        bt = _FakeBTCreator({"bank_account": self._bank_account(), "company": self.company})
        je = _FakeRefundJECreator(je_name)
        self._wire_refund_creators(bt, je)
        marks = self._spy_mark_refund()

        pending = [{"refund_id": "re_success", "amount": 5.0, "refund_date": "2025-03-15"}]
        results = self.service._process_pending_refunds(donation, self.pid, pending)

        # Per-refund result
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["refund_id"], "re_success")
        self.assertEqual(r["bank_transaction"], "BT-REFUND-STUB")
        self.assertEqual(r["journal_entry"], je_name)
        self.assertEqual(r["amount"], 5.0)

        # Bank Transaction was requested as a NEGATIVE withdrawal
        self.assertEqual(len(bt.create_calls), 1)
        self.assertEqual(bt.create_calls[0]["transaction_data"]["amount"], -5.0)
        self.assertEqual(
            bt.create_calls[0]["transaction_data"]["reference_number"],
            f"{self.pid}_refund_re_success",
        )

        # Real payment-history row appended (negative amount, Refunded, parsed date)
        donation.reload()
        rows = [p for p in donation.payments if getattr(p, "journal_entry", None) == je_name]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.payment_status, "Refunded")
        self.assertEqual(float(row.amount), -5.0)
        self.assertEqual(row.mollie_payment_id, "re_success")
        self.assertEqual(getdate(row.payment_date), getdate("2025-03-15"))

        # Idempotency manager notified with the JE name used for tracking
        self.assertEqual(marks, [(self.pid, "re_success", je_name)])

    def test_bank_transaction_failure_yields_error_result_and_no_history(self):
        donation = self._make_submitted_donation()
        bt = _FakeBTCreator({"bank_account": self._bank_account(), "company": self.company}, bt_name=None)
        je = _FakeRefundJECreator("JE-SHOULD-NOT-BE-USED")
        self._wire_refund_creators(bt, je)
        marks = self._spy_mark_refund()

        pending = [{"refund_id": "re_btfail", "amount": 7.0, "refund_date": today()}]
        results = self.service._process_pending_refunds(donation, self.pid, pending)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(results[0]["refund_id"], "re_btfail")
        self.assertIn("Bank Transaction", results[0]["message"])
        # JE creator never reached, nothing marked, no history row
        self.assertEqual(je.create_calls, [])
        self.assertEqual(marks, [])
        donation.reload()
        self.assertEqual(len(donation.payments or []), 0)

    def test_journal_entry_failure_yields_error_with_bank_transaction(self):
        donation = self._make_submitted_donation()
        bt = _FakeBTCreator({"bank_account": self._bank_account(), "company": self.company})
        je = _FakeRefundJECreator(None)  # JE creation fails
        self._wire_refund_creators(bt, je)
        marks = self._spy_mark_refund()

        pending = [{"refund_id": "re_jefail", "amount": 9.0, "refund_date": today()}]
        results = self.service._process_pending_refunds(donation, self.pid, pending)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(results[0]["refund_id"], "re_jefail")
        self.assertEqual(results[0]["bank_transaction"], "BT-REFUND-STUB")
        self.assertIn("Journal Entry", results[0]["message"])
        self.assertEqual(marks, [])
        donation.reload()
        self.assertEqual(len(donation.payments or []), 0)

    def test_batch_skips_history_row_that_already_exists(self):
        """Re-processing the same refund (same JE) must not append a duplicate
        payment-history row — the batch idempotency filter skips it."""
        donation = self._make_submitted_donation()
        je_name = self._make_submitted_journal_entry()
        bt = _FakeBTCreator({"bank_account": self._bank_account(), "company": self.company})
        je = _FakeRefundJECreator(je_name)
        self._wire_refund_creators(bt, je)
        self._spy_mark_refund()

        pending = [{"refund_id": "re_dup", "amount": 4.0, "refund_date": today()}]
        first = self.service._process_pending_refunds(donation, self.pid, pending)
        self.assertEqual(first[0]["status"], "success")

        donation.reload()
        second = self.service._process_pending_refunds(donation, self.pid, pending)
        # Per-refund processing still "succeeds" (BT+JE recreated by the stubs)…
        self.assertEqual(second[0]["status"], "success")
        # …but the duplicate history row is filtered out on the batch append.
        donation.reload()
        rows = [p for p in donation.payments if getattr(p, "journal_entry", None) == je_name]
        self.assertEqual(len(rows), 1, "no duplicate refund history row should be added")


# =============================================================================
# process_reversal_webhook — SUCCESS paths (refund + chargeback)
# =============================================================================
class TestProcessReversalWebhookSuccess(WrapperSweepBase):
    def _stub_existing_payment(self):
        self.service.idempotency_manager.check_payment_processing_state = (
            lambda payment_id, **k: _OrigStateExists()
        )

    def _stub_pe_creator(self, return_value):
        import verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator as upe_mod

        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return return_value

        orig = upe_mod.create_unified_payment_entry
        upe_mod.create_unified_payment_entry = fake_create
        self.addCleanup(lambda: setattr(upe_mod, "create_unified_payment_entry", orig))
        return captured

    def test_refund_creates_history_row_and_marks_processed(self):
        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        self._stub_existing_payment()
        captured = self._stub_pe_creator(pe)
        marks = self._spy_mark_refund()

        result = self.service.process_reversal_webhook(
            payment_id=self.pid,
            reversal_id="re_rev",
            amount=6.0,
            reversal_type="refund",
            reversal_date="2025-04-01",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["payment_entry_id"], pe.name)
        self.assertEqual(result["refund_id"], "re_rev")

        # Unified creator invoked with the outgoing ("Pay") reversal contract
        self.assertEqual(captured["payment_type"], "Pay")
        self.assertEqual(captured["reference_suffix"], "_refund_re_rev")
        self.assertEqual(captured["amount"], 6.0)

        # Real payment-history row: negative amount, Refunded, real PE link
        donation.reload()
        rows = [p for p in donation.payments if getattr(p, "payment_entry", None) == pe.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payment_status, "Refunded")
        self.assertEqual(float(rows[0].amount), -6.0)
        self.assertEqual(rows[0].mollie_payment_id, "re_rev")
        self.assertEqual(getdate(rows[0].payment_date), getdate("2025-04-01"))

        self.assertEqual(marks, [(self.pid, "re_rev", pe.name)])

    def test_chargeback_with_reason_builds_description_and_status(self):
        donation = self._make_submitted_donation()
        pe = self._make_submitted_payment_entry()
        self._stub_existing_payment()
        captured = self._stub_pe_creator(pe)
        marks = self._spy_mark_chargeback()

        result = self.service.process_reversal_webhook(
            payment_id=self.pid,
            reversal_id="cb_rev",
            amount=12.0,
            reversal_type="chargeback",
            reason={"code": "AC01", "description": "Account closed"},
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chargeback_id"], "cb_rev")
        # Chargeback description embeds the reason code/text
        self.assertIn("AC01", captured["description"])
        self.assertIn("Account closed", captured["description"])

        donation.reload()
        rows = [p for p in donation.payments if getattr(p, "payment_entry", None) == pe.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payment_status, "Chargeback")
        self.assertEqual(float(rows[0].amount), -12.0)
        self.assertEqual(rows[0].mollie_payment_id, "cb_rev")

        self.assertEqual(marks, [(self.pid, "cb_rev", pe.name)])

    def test_donation_not_found_returns_ignored(self):
        # Original payment exists per idempotency, but no Donation carries this id.
        self._stub_existing_payment()
        captured = self._stub_pe_creator("PE-NOT-CREATED")
        marks = self._spy_mark_refund()

        result = self.service.process_reversal_webhook(
            payment_id="tr_no_donation_xyz",
            reversal_id="re_none",
            amount=3.0,
            reversal_type="refund",
        )

        self.assertEqual(result["status"], "ignored")
        self.assertIn("not found", result["message"])
        # Creator never called, nothing marked.
        self.assertEqual(captured, {})
        self.assertEqual(marks, [])

    def test_pe_creation_failure_yields_error_and_no_history(self):
        donation = self._make_submitted_donation()
        self._stub_existing_payment()
        self._stub_pe_creator(None)  # unified creator returns no PE
        marks = self._spy_mark_refund()

        result = self.service.process_reversal_webhook(
            payment_id=self.pid,
            reversal_id="re_fail",
            amount=8.0,
            reversal_type="refund",
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["refund_id"], "re_fail")
        self.assertIn("Failed to create", result["message"])
        self.assertEqual(marks, [])
        donation.reload()
        self.assertEqual(len(donation.payments or []), 0)
