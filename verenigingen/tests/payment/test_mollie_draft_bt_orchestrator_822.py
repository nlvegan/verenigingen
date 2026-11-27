"""#822 (round 2): the orchestrator's own entry points must not treat a DRAFT Bank Transaction as done.

The admin dashboard now offers a payment whose only Bank Transaction is a draft. The orphan and
BT-only processors used to answer ``already_processed`` for it and never submit it; the
member-matched reconcile path linked a Payment Entry to a draft that stayed a draft.

Real flow: a real draft Bank Transaction inserted through the document API (what #383's
no-submit-permission branch leaves), the real processors, a real resubmit (``submit_atomically``).
The only seam used is ``_try_submit_existing_draft`` replaced by a no-op for the "submit refused"
outcome, and wrapped (``wraps=``) to count calls.

Run:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_9 \\
        verenigingen.tests.payment.test_mollie_draft_bt_orchestrator_822
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.payment.mollie_orphan_payment_stub import orphan_payment_stub
from verenigingen.tests.payment.test_mollie_orchestrator_coverage_b2 import OrchestratorBase
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_payments_settings,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator
from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
)

AMOUNT = 25.0


class TestOrchestratorDraftBankTransaction822(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()
        # The Payment Entry must hit the Bank Account's own GL account or the BT-PE link refuses it.
        clearing = frappe.db.get_value("Bank Account", self._mollie["bank_account"], "account")
        self.assertTrue(clearing, "fixture problem: Mollie bank account has no GL account")
        pin_verenigingen_settings(self, company=self.company)
        pin_mollie_clearing_account(self, clearing)
        pin_payments_settings(self, dues_income_account=self._get_or_create_income_account(self.company))
        self.member = self._make_member_with_customer(first_name="DraftBT")
        self.draft = self.real_draft_bank_transaction()

    def real_draft_bank_transaction(self):
        draft = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "bank_account": self._mollie["bank_account"],
                "company": self._mollie["company"],
                "deposit": AMOUNT,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": self.pid,
                "description": "draft left by a caller without submit permission",
                "status": "Unreconciled",
                "unallocated_amount": AMOUNT,
                "allocated_amount": 0.0,
                "custom_reference_is_system_issued": 1,
            }
        )
        draft.insert()
        self.assertEqual(draft.docstatus, 0, "fixture problem: not a draft")
        return draft.name

    def docstatus(self):
        return frappe.db.get_value("Bank Transaction", self.draft, "docstatus")

    def payment(self):
        return orphan_payment_stub(self.pid, AMOUNT, "draft 822", customer_id=None)

    def processors(self):
        return {
            "orphan": lambda: self.orch.process_orphaned_payment(self.pid, self.payment()),
            "bt_only": lambda: self.orch.process_bt_only_payment(
                self.pid, self.payment(), member_name=self.member.name
            ),
        }

    def test_orphan_and_bt_only_submit_a_draft_instead_of_reporting_it_processed(self):
        for name, run in self.processors().items():
            with self.subTest(processor=name):
                result = run()
                self.assertEqual(self.docstatus(), 1, "the draft must be submitted by a caller who may")
                self.assertEqual(result.bank_transaction, self.draft)
                self.assertEqual(result.status, "already_processed")
                frappe.db.set_value("Bank Transaction", self.draft, "docstatus", 0, update_modified=False)

    def test_a_refused_submit_is_reported_as_a_draft_not_as_processed(self):
        for name, run in self.processors().items():
            with self.subTest(processor=name), patch.object(
                # Mock justified: stands in for a caller without submit permission (the real #383 outcome).
                BankTransactionCreator,
                "_try_submit_existing_draft",
            ) as submit:
                result = run()
                self.assertEqual(submit.call_count, 1)
                self.assertEqual(self.docstatus(), 0)
                self.assertEqual(result.status, "error")
                self.assertIn("still a draft", result.error)
                self.assertEqual(result.bank_transaction, self.draft)

    def test_the_resubmit_is_attempted_once_per_call(self):
        for name, run in self.processors().items():
            with self.subTest(processor=name), patch.object(
                BankTransactionCreator,
                "_try_submit_existing_draft",
                autospec=True,
                side_effect=BankTransactionCreator._try_submit_existing_draft,
            ) as submit:
                run()
                self.assertEqual(submit.call_count, 1)
                frappe.db.set_value("Bank Transaction", self.draft, "docstatus", 0, update_modified=False)

    def test_a_submitted_bank_transaction_is_processed_without_any_resubmit(self):
        frappe.db.set_value("Bank Transaction", self.draft, "docstatus", 1, update_modified=False)
        for name, run in self.processors().items():
            with self.subTest(processor=name), patch.object(
                BankTransactionCreator, "_try_submit_existing_draft"
            ) as submit:
                result = run()
                submit.assert_not_called()
                self.assertEqual(result.status, "already_processed")

    def test_member_matched_reconcile_submits_the_draft_it_links(self):
        """bt_pe_reconcile (``process_payment``) with a real invoice and a real draft BT."""
        invoice = self._make_sales_invoice(self.member.customer, today(), today(), outstanding=AMOUNT)
        payment = SimpleNamespace(
            id=self.pid,
            status="paid",
            description="contributie",
            customer_id=None,
            subscription_id=None,
            amount={"value": f"{AMOUNT:.2f}", "currency": "EUR"},
            paid_at=f"{today()}T12:00:00+00:00",
            details=None,
        )
        result = self.orch.process_payment(
            self.pid, payment=payment, member_name=self.member.name, invoice_name=invoice.name
        )
        self.assertEqual(result.bank_transaction, self.draft, f"{result.to_dict()}")
        self.assertTrue(result.payment_entry, f"fixture problem: no Payment Entry. {result.to_dict()}")
        self.assertTrue(result.reconciled, f"fixture problem: link failed. {result.to_dict()}")
        self.assertEqual(self.docstatus(), 1, f"the linked Bank Transaction stayed a draft. {result.to_dict()}")

    # Round 3 (review F-A): a refused submit must stop BEFORE the Payment Entry step. Linking a
    # Payment Entry to a draft Bank Transaction makes get_processing_status() read the pair as
    # complete, so no later retry by a caller who CAN submit would ever reach the draft.

    def payment_entry_count(self):
        return frappe.db.count("Payment Entry", {"reference_no": self.pid})

    def bank_transaction_payment_rows(self):
        return frappe.db.count("Bank Transaction Payments", {"parent": self.draft})

    def member_matched_run(self):
        invoice = self._make_sales_invoice(self.member.customer, today(), today(), outstanding=AMOUNT)
        payment = SimpleNamespace(
            id=self.pid,
            status="paid",
            description="contributie",
            customer_id=None,
            subscription_id=None,
            amount={"value": f"{AMOUNT:.2f}", "currency": "EUR"},
            paid_at=f"{today()}T12:00:00+00:00",
            details=None,
        )
        return lambda: self.orch.process_payment(
            self.pid, payment=payment, member_name=self.member.name, invoice_name=invoice.name
        )

    def orphan_with_invoice_run(self):
        return lambda: self.orch.process_orphaned_payment_with_invoice(self.pid, self.payment())

    def assert_refused_then_allowed(self, run):
        with patch.object(
            # Mock justified: stands in for a caller without submit permission (the real #383 outcome).
            BankTransactionCreator,
            "_try_submit_existing_draft",
            autospec=True,
            side_effect=lambda *args, **kwargs: None,
        ) as submit:
            refused = run()
        self.assertEqual(submit.call_count, 1, "exactly one resubmit attempt per call")
        self.assertEqual(refused.status, "error", f"{refused.to_dict()}")
        self.assertIn("still a draft", refused.error)
        self.assertEqual(refused.bank_transaction, self.draft)
        self.assertEqual(self.docstatus(), 0)
        self.assertEqual(self.payment_entry_count(), 0, "a Payment Entry was booked against a draft")
        self.assertEqual(self.bank_transaction_payment_rows(), 0, "a Payment Entry was linked to a draft")

        allowed = run()
        self.assertEqual(self.docstatus(), 1, f"a caller who may submit never got to: {allowed.to_dict()}")
        self.assertEqual(self.payment_entry_count(), 1, f"{allowed.to_dict()}")
        self.assertEqual(self.bank_transaction_payment_rows(), 1, f"{allowed.to_dict()}")
        self.assertNotEqual(allowed.status, "error", f"{allowed.to_dict()}")

    def test_member_matched_reconcile_stops_at_a_draft_then_a_permitted_retry_processes_it(self):
        self.assert_refused_then_allowed(self.member_matched_run())

    def test_orphan_with_invoice_stops_at_a_draft_then_a_permitted_retry_processes_it(self):
        self.assert_refused_then_allowed(self.orphan_with_invoice_run())
