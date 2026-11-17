"""
#2447: the remaining bare ``insert(); submit()`` Payment Entry writers must leave nothing behind.

Sweep of #2406 / #2384. Real writers, real Payment Entry / Bank Transaction; the only stub is a
submit-time failure injected on the doctype class: ``submit`` raising leaves a DRAFT behind,
``on_submit`` raising leaves a row already written as docstatus 1 with no GL. Each test reads the
table after the failure and then retries with the failure removed.

Writers covered (the others named in the issue are covered by a direct-call test in the same file):
  * ``sepa_reconciliation.create_manual_payment_entry`` + ``manual_sepa_reconciliation`` (caller
    swallows the exception and the request commits)
  * ``sepa_duplicate_prevention._create_payment_entry`` (the duplicate guard counts DRAFT
    Payment Entry References, so a leftover draft makes the retry refuse as "fully paid")
  * ``MollieDebugService._submit_processed_documents`` (submits an existing draft; swallows)

Run:
    PYTHONPATH=<worktree> bench --site test_site_11 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_insert_submit_atomic_sweep_2447
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.bank_transaction.bank_transaction import BankTransaction
from erpnext.accounts.doctype.journal_entry.journal_entry import get_default_bank_cash_account
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe.utils import today

from verenigingen.api import sepa_duplicate_prevention as dup
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    _PontoPaymentRequestFixtures,
)
from verenigingen.tests.payment.test_sepa_reconciliation import ReconBase
from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.api import sepa_reconciliation as recon


def fail_submit(how, doctype_cls=PaymentEntry):
    """before_posting: ``submit`` raises (draft stays). on_submit: docstatus 1 is written first."""
    if how == "before_posting":
        return patch.object(doctype_cls, "submit", side_effect=frappe.ValidationError("period closed"))
    return patch.object(doctype_cls, "on_submit", side_effect=frappe.ValidationError("bad account"))


class _SepaFixture(ReconBase):
    def _fixture(self, name):
        it = self._make_member_with_invoice(first_name=name, grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(), description="SEPA DD")
        return it, batch, bt

    def _rows(self, bt):
        return frappe.get_all(
            "Payment Entry", filters={"custom_bank_transaction": bt.name}, fields=["name", "docstatus"]
        )

    def _assert_sepa_booked_once_2447(self, bt, pe_name):
        self.assertTrue(pe_name, "the retry did not book the payment")
        self.assertEqual([r.name for r in self._rows(bt) if r.docstatus == 1], [pe_name])
        self.assertEqual([r.name for r in self._rows(bt)], [pe_name], "a second row exists for the item")
        live_gl = frappe.db.count(
            "GL Entry", {"voucher_type": "Payment Entry", "voucher_no": pe_name, "is_cancelled": 0}
        )
        self.assertGreater(live_gl, 0, "the booked Payment Entry posted no GL rows")


class TestManualReconciliationFailedSubmit(_SepaFixture):
    def _manual_item_2447(self, it):
        return {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0}

    def _writer_fails_then_retries(self, how):
        it, _, bt = self._fixture("M2447" + how[:2])
        with fail_submit(how), self.assertRaises(frappe.ValidationError):
            recon.create_manual_payment_entry(bt, self._manual_item_2447(it))
        self.assertEqual(self._rows(bt), [], "the failed submit left a Payment Entry behind")
        result = recon.create_manual_payment_entry(bt, self._manual_item_2447(it))
        self._assert_sepa_booked_once_2447(bt, result["payment_entry"])

    def test_failed_submit_before_posting_leaves_no_draft(self):
        self._writer_fails_then_retries("before_posting")

    def test_failed_submit_after_docstatus_written_leaves_no_row(self):
        self._writer_fails_then_retries("on_submit")

    def test_endpoint_reports_failure_and_leaves_no_row(self):
        """The endpoint swallows the exception into ``success: False`` and the request then
        COMMITS, so whatever the writer left is permanent."""
        it, _, bt = self._fixture("M2447End")
        self.expectErrorLog("Error in manual SEPA reconciliation")
        items = json.dumps([{"reconcile": True, **self._manual_item_2447(it)}])
        with fail_submit("on_submit"):
            result = recon.manual_sepa_reconciliation(bt.name, items)
        self.assertFalse(result["success"], result)
        self.assertEqual(self._rows(bt), [], "the failed submit left a Payment Entry behind")
        retry = recon.manual_sepa_reconciliation(bt.name, items)
        self.assertTrue(retry["success"], retry)
        self._assert_sepa_booked_once_2447(bt, retry["reconciled_items"][0]["payment_entry"])


class TestDuplicatePreventionFailedSubmit(_SepaFixture):
    def _payment_data(self, it, batch, bt):
        invoice = frappe.get_doc("Sales Invoice", it["invoice"].name)
        bank = get_default_bank_cash_account(invoice.company, "Bank").get("account")
        item = batch.invoices[0]
        return {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "company": invoice.company,
            "party_type": "Customer",
            "party": it["customer"],
            "posting_date": bt.date,
            "paid_amount": 25.0,
            "received_amount": 25.0,
            "paid_from": invoice.debit_to,
            "paid_to": bank,
            "paid_from_account_currency": "EUR",
            "paid_to_account_currency": "EUR",
            "target_exchange_rate": 1,
            "source_exchange_rate": 1,
            "reference_no": bt.reference_number,
            "reference_date": bt.date,
            "mode_of_payment": "SEPA Direct Debit",
            "custom_bank_transaction": bt.name,
            "custom_sepa_batch": batch.name,
            "custom_sepa_batch_item": item.name,
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "total_amount": 25.0,
                    "outstanding_amount": 25.0,
                    "allocated_amount": 25.0,
                }
            ],
        }

    def _dup_fails_then_retries_2447(self, how):
        it, batch, bt = self._fixture("D2447" + how[:2])
        data = self._payment_data(it, batch, bt)
        invoice = it["invoice"].name
        with fail_submit(how), self.assertRaises(frappe.ValidationError):
            dup.create_payment_entry_with_duplicate_check(invoice, 25.0, data)
        self.assertEqual(self._rows(bt), [], "the failed submit left a Payment Entry behind")
        # The guard sums Payment Entry Reference rows of ANY docstatus: a leftover draft would
        # count as an allocation and the retry would be refused as "already fully paid".
        result = dup.create_payment_entry_with_duplicate_check(invoice, 25.0, data)
        self._assert_sepa_booked_once_2447(bt, result["payment_entry"])

    def test_failed_submit_before_posting_leaves_no_draft_and_retry_books(self):
        self._dup_fails_then_retries_2447("before_posting")

    def test_failed_submit_after_docstatus_written_leaves_no_row_and_retry_books(self):
        self._dup_fails_then_retries_2447("on_submit")


class TestDebugServiceFailedSubmit(_SepaFixture):
    """MollieDebugService._submit_processed_documents submits a draft the orchestrator made."""

    def _service(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        return MollieDebugService.__new__(MollieDebugService)

    def _logger_stub(self, service):
        service.logger = SimpleNamespace(error=lambda *a, **k: None, info=lambda *a, **k: None)

    def _run(self, **documents):
        service = self._service()
        self._logger_stub(service)
        payment_result = {}
        service._submit_processed_documents(
            SimpleNamespace(
                bank_transaction=documents.get("bank_transaction"),
                payment_entry=documents.get("payment_entry"),
            ),
            "tr_2447",
            payment_result,
        )
        return payment_result

    def test_control_failed_bank_transaction_submit_leaves_the_draft_intact(self):
        """CONTROL, green before and after: Bank Transaction has no ``on_submit`` (ERPNext's
        controller or this app's doc_events), so every submit failure it can raise comes from
        ``before_submit``/``validate``, before the row is written as docstatus 1. The BT branch of
        the debug service is therefore harmless today; the savepoint there is defence in depth."""
        bt = self._make_bank_transaction(deposit=10.0, description="debug 2447")
        self.assertEqual(bt.docstatus, 0)
        with patch.object(BankTransaction, "before_submit", side_effect=frappe.ValidationError("no")):
            result = self._run(bank_transaction=bt.name)
        self.assertIn("submit_error", result)
        self.assertNotIn("bank_transaction_submitted", result)
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "docstatus"), 0)
        self.assertTrue(self._run(bank_transaction=bt.name).get("bank_transaction_submitted"))

    def test_failed_payment_entry_submit_leaves_the_draft_intact(self):
        it, _, bt = self._fixture("G2447")
        with patch.object(PaymentEntry, "submit", lambda self: None):  # leave a real draft
            pe_name = recon.create_manual_payment_entry(
                bt, {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0}
            )["payment_entry"]
        self.assertEqual(frappe.db.get_value("Payment Entry", pe_name, "docstatus"), 0)
        with fail_submit("on_submit"):
            result = self._run(payment_entry=pe_name)
        self.assertIn("submit_error", result)
        self.assertEqual(
            frappe.db.get_value("Payment Entry", pe_name, "docstatus"),
            0,
            "a failed submit left the Payment Entry half-posted (docstatus 1, no GL)",
        )
        self.assertTrue(self._run(payment_entry=pe_name).get("payment_entry_submitted"))
        self.assertGreater(
            frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": pe_name}), 0
        )


class TestPontoCreatePaymentEntryFailedSubmit(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """Both production callers wrap this in ``atomic_status_transition`` (a rollback to that
    savepoint undoes the insert), so the leftover row is HARMLESS today. Driven directly, with no
    outer savepoint, to pin that the writer itself no longer relies on its callers."""

    def _rows(self, req, **extra):
        return frappe.get_all(
            "Payment Entry", filters={"reference_no": req.name, **extra}, fields=["name", "docstatus"]
        )

    def _ponto_fails_then_retries_2447(self, how):
        req = self._create_ponto_request(
            self._create_supplier("Atomic" + how[:2]), status="Signed", track_priority=6
        )
        with fail_submit(how), self.assertRaises(frappe.ValidationError):
            req.create_payment_entry()
        self.assertEqual(self._rows(req), [], "the failed submit left a Payment Entry behind")
        req.create_payment_entry()
        self.factory.track_document("Payment Entry", req.payment_entry, priority=6)
        self.assertEqual([r.name for r in self._rows(req)], [req.payment_entry])
        self.assertEqual(frappe.db.get_value("Payment Entry", req.payment_entry, "docstatus"), 1)

    def test_failed_submit_before_posting_leaves_no_draft(self):
        self._ponto_fails_then_retries_2447("before_posting")

    def test_failed_submit_after_docstatus_written_leaves_no_row(self):
        self._ponto_fails_then_retries_2447("on_submit")


class TestPaymentPlanCreatePaymentEntryFailedSubmit(EnhancedTestCase):
    """``process_payment`` wraps this in a savepoint, so the leftover row is HARMLESS today (the
    only production caller); driven directly to pin the writer itself."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.company = get_eur_test_company()

    def _make_plan_2447(self, member_name):
        plan = frappe.new_doc("Payment Plan")
        plan.member = member_name
        plan.plan_type = "Equal Installments"
        plan.total_amount = 90.0
        plan.number_of_installments = 3
        plan.frequency = "Monthly"
        plan.start_date = today()
        plan.status = "Active"
        plan.reason = "test"
        plan.payment_method = "Bank Transfer"
        plan.save()
        self.track_doc("Payment Plan", plan.name)
        return plan

    def _plan_fails_then_retries_2447(self, how):
        member = member_with_customer(self, "PlanAtomic" + how[:2])
        plan = self._make_plan_2447(member.name)
        reference = f"PLAN2447-{how}"
        filters = {"party": member.customer, "reference_no": reference}
        with singleton_backup("Verenigingen Settings"):
            settings = frappe.get_single("Verenigingen Settings")
            settings.company = self.company
            settings.save()
            with fail_submit(how), self.assertRaises(frappe.ValidationError):
                plan.create_payment_entry(30.0, reference, today())
            self.assertEqual(frappe.get_all("Payment Entry", filters=filters), [], "a failed submit left a row")
            plan.create_payment_entry(30.0, reference, today())
        rows = frappe.get_all("Payment Entry", filters=filters, fields=["name", "docstatus"])
        self.assertEqual([r.docstatus for r in rows], [1])
        self.factory.track_document("Payment Entry", rows[0].name, priority=6)

    def test_failed_submit_before_posting_leaves_no_draft(self):
        self._plan_fails_then_retries_2447("before_posting")

    def test_failed_submit_after_docstatus_written_leaves_no_row(self):
        self._plan_fails_then_retries_2447("on_submit")


class TestInsertAndSubmitReloadOption(EnhancedTestCase):
    """``reload_before_submit`` keeps the #609 reload, inside the savepoint, between insert and submit."""

    def _order(self, **kwargs):
        from verenigingen.utils.transaction_errors import insert_and_submit_atomically

        calls = []
        doc = SimpleNamespace(
            insert=lambda: calls.append("insert"),
            reload=lambda: calls.append("reload"),
            submit=lambda: calls.append("submit"),
        )
        insert_and_submit_atomically(doc, **kwargs)
        return calls

    def test_reload_runs_once_between_insert_and_submit(self):
        self.assertEqual(self._order(reload_before_submit=True), ["insert", "reload", "submit"])

    def test_no_reload_by_default(self):
        self.assertEqual(self._order(), ["insert", "submit"])
