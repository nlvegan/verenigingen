"""
Tier-1 unit tests for the pure logic in MolliePaymentOrchestrator.

Covers the stateless pieces of
verenigingen/verenigingen_payments/services/mollie_payment_orchestrator.py:
    - is_payment_successful()
    - ProcessingStatus dataclass (to_dict / is_complete / is_partial)
    - PaymentProcessingResult dataclass (to_dict)
    - MolliePaymentOrchestrator._determine_final_status()
    - MolliePaymentOrchestrator._determine_failed_step()

The two _determine_* methods are called as unbound methods with a hand-built
result object, so no orchestrator construction (and therefore no Mollie client /
DB) is needed. Mollie payments are stood in with SimpleNamespace stubs (the SDK
boundary). No unittest.mock is used.
"""

import unittest
from types import SimpleNamespace

from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
    PaymentProcessingResult,
    ProcessingStatus,
    is_payment_successful,
)


class TestIsPaymentSuccessful(unittest.TestCase):
    def test_paid_is_successful(self):
        self.assertTrue(is_payment_successful(SimpleNamespace(status="paid")))

    def test_other_statuses_not_successful(self):
        for status in ("open", "pending", "failed", "canceled", "expired", "authorized"):
            self.assertFalse(is_payment_successful(SimpleNamespace(status=status)))

    def test_missing_status_not_successful(self):
        self.assertFalse(is_payment_successful(SimpleNamespace()))


class TestProcessingStatus(unittest.TestCase):
    def test_defaults_are_unprocessed(self):
        s = ProcessingStatus(payment_id="tr_1")
        self.assertEqual(s.status, "unprocessed")
        self.assertFalse(s.is_complete)
        self.assertFalse(s.is_partial)
        self.assertFalse(s.has_bank_transaction)
        self.assertEqual(s.missing_documents, [])

    def test_complete_flag(self):
        s = ProcessingStatus(payment_id="tr_1", status="complete")
        self.assertTrue(s.is_complete)
        self.assertFalse(s.is_partial)

    def test_partial_flag(self):
        s = ProcessingStatus(payment_id="tr_1", status="partial")
        self.assertTrue(s.is_partial)
        self.assertFalse(s.is_complete)

    def test_to_dict_round_trips_fields(self):
        s = ProcessingStatus(
            payment_id="tr_1",
            has_bank_transaction=True,
            bank_transaction="BT-1",
            has_payment_entry=True,
            payment_entry="PE-1",
            has_sales_invoice=False,
            bt_pe_linked=True,
            member="Assoc-Member-0001",
            status="partial",
            missing_documents=["Sales Invoice"],
        )
        d = s.to_dict()
        self.assertEqual(d["payment_id"], "tr_1")
        self.assertEqual(d["bank_transaction"], "BT-1")
        self.assertEqual(d["payment_entry"], "PE-1")
        self.assertTrue(d["bt_pe_linked"])
        self.assertEqual(d["member"], "Assoc-Member-0001")
        self.assertEqual(d["missing_documents"], ["Sales Invoice"])
        # is_complete is a computed property surfaced in the dict
        self.assertIn("is_complete", d)
        self.assertFalse(d["is_complete"])

    def test_distinct_instances_do_not_share_missing_documents(self):
        # Regression guard for default_factory mutability
        a = ProcessingStatus(payment_id="tr_a")
        b = ProcessingStatus(payment_id="tr_b")
        a.missing_documents.append("Bank Transaction")
        self.assertEqual(b.missing_documents, [])


class TestPaymentProcessingResult(unittest.TestCase):
    def test_to_dict_includes_diagnostics(self):
        r = PaymentProcessingResult(payment_id="tr_2")
        r.status = "error"
        r.error = "boom"
        r.exception_type = "ValueError"
        r.failed_step = "create_payment_entry"
        r.actions_taken.append("did a thing")
        d = r.to_dict()
        self.assertEqual(d["status"], "error")
        self.assertEqual(d["error"], "boom")
        self.assertEqual(d["exception_type"], "ValueError")
        self.assertEqual(d["failed_step"], "create_payment_entry")
        self.assertEqual(d["actions_taken"], ["did a thing"])

    def test_defaults(self):
        r = PaymentProcessingResult(payment_id="tr_2")
        self.assertEqual(r.status, "pending")
        self.assertFalse(r.reconciled)
        self.assertEqual(r.actions_taken, [])


class TestDetermineFinalStatus(unittest.TestCase):
    """MolliePaymentOrchestrator._determine_final_status — called unbound."""

    def _run(self, **kwargs):
        r = PaymentProcessingResult(payment_id="tr_3")
        for k, v in kwargs.items():
            setattr(r, k, v)
        MolliePaymentOrchestrator._determine_final_status(None, r)
        return r

    def test_failed_step_makes_it_partial(self):
        r = self._run(failed_step="create_payment_entry", bank_transaction="BT-1")
        self.assertEqual(r.status, "partial")
        self.assertIn("create_payment_entry", r.error)

    def test_both_docs_present_is_success(self):
        r = self._run(bank_transaction="BT-1", payment_entry="PE-1")
        self.assertEqual(r.status, "success")

    def test_only_bt_is_partial_missing_pe(self):
        r = self._run(bank_transaction="BT-1")
        self.assertEqual(r.status, "partial")
        self.assertIn("Payment Entry", r.error)

    def test_only_pe_is_partial_missing_bt(self):
        r = self._run(payment_entry="PE-1")
        self.assertEqual(r.status, "partial")
        self.assertIn("Bank Transaction", r.error)

    def test_no_docs_is_error(self):
        r = self._run()
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "No documents created")


class TestDetermineFailedStep(unittest.TestCase):
    """MolliePaymentOrchestrator._determine_failed_step — called unbound."""

    def _run(self, **kwargs):
        r = PaymentProcessingResult(payment_id="tr_4")
        for k, v in kwargs.items():
            setattr(r, k, v)
        MolliePaymentOrchestrator._determine_failed_step(None, r)
        return r

    def test_nothing_created_blames_invoice_matching(self):
        r = self._run()
        self.assertEqual(r.failed_step, "invoice_matching")

    def test_invoice_but_no_bt_blames_bt_creation(self):
        r = self._run(sales_invoice="SINV-1")
        self.assertEqual(r.failed_step, "create_bank_transaction")

    def test_bt_but_no_pe_blames_pe_creation(self):
        r = self._run(sales_invoice="SINV-1", bank_transaction="BT-1")
        self.assertEqual(r.failed_step, "create_payment_entry")

    def test_all_present_blames_link(self):
        r = self._run(sales_invoice="SINV-1", bank_transaction="BT-1", payment_entry="PE-1")
        self.assertEqual(r.failed_step, "link_bt_pe")


if __name__ == "__main__":
    unittest.main()
