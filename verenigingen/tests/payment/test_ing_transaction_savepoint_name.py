"""#1898: ING Checkout Transaction opened ``SAVEPOINT payment_entry_ICT-1261``.

Frappe interpolates the savepoint name unquoted, so the hyphen in the doc name is a
MariaDB 1064. Before the fix the 1064 was NOT swallowed: the ``except`` handler's
``rollback_to_savepoint`` used the same hyphenated name and raised 1064 again, so the
exception escaped ``update_from_webhook`` and the webhook answered 500.
"""

import re
from unittest.mock import patch

import frappe
from frappe.utils import flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.transaction_errors import safe_savepoint_name
from verenigingen.verenigingen_payments.ing_checkout.tests import test_transaction_service as _txn_service_tests

# Reached through the module so the loader does not collect (and re-run) the borrowed class.
_InvoiceFixture = _txn_service_tests.TestCreatePaymentEntryWithInvoice
TEST_BANK_ACCOUNT = _txn_service_tests.TEST_BANK_ACCOUNT


class TestINGTransactionSavepointName(EnhancedTestCase):
    # Invoice fixture helpers, borrowed from the transaction-service tests (plain functions).
    _ensure_mode_of_payment = _InvoiceFixture._ensure_mode_of_payment
    _make_submitted_invoice = _InvoiceFixture._make_submitted_invoice
    _ensure_customer = _InvoiceFixture._ensure_customer
    _ensure_item = _InvoiceFixture._ensure_item

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        from verenigingen.tests.setup import ensure_test_fiscal_year_for_all_companies

        ensure_test_fiscal_year_for_all_companies()
        self._ensure_mode_of_payment()

    def _paid_webhook(self):
        return {"object": {"status": {"code": 100}, "payments": []}}

    def _insert_transaction(self, **extra):
        doc = frappe.new_doc("ING Checkout Transaction")
        doc.transaction_id = f"TXN-{frappe.generate_hash(length=8)}"
        doc.status = "Pending"
        doc.amount = 25.0
        doc.update(extra)
        doc.insert(ignore_permissions=True)
        return doc

    def _spy_savepoints(self):
        opened = []
        real = frappe.db.savepoint

        def spy(name):
            opened.append(name)
            return real(name)  # real SQL: a bad name raises the real 1064

        return opened, patch.object(frappe.db, "savepoint", side_effect=spy)

    def test_paid_webhook_books_a_payment_entry_for_a_hyphenated_transaction(self):
        invoice = self._make_submitted_invoice(rate=25.00)
        invoice.reload()
        outstanding = flt(invoice.outstanding_amount)
        txn = self._insert_transaction(
            reference_doctype="Sales Invoice", reference_name=invoice.name, amount=outstanding
        )
        self.assertIn("-", txn.name, "fixture must carry the hyphenated autoname that triggered #1898")

        opened, spy = self._spy_savepoints()
        settings = {"ing_checkout_bank_account": TEST_BANK_ACCOUNT}
        # get_transaction_service() builds a fresh service per call, so patch the settings source.
        with spy, patch("verenigingen.utils.settings_utils.get_payments_settings", return_value=settings):
            txn.update_from_webhook(self._paid_webhook())

        self.assertTrue(opened, "update_from_webhook never opened a savepoint")
        for name in opened:
            self.assertRegex(name, r"^[0-9A-Za-z_]+$")
        txn.reload()
        self.assertEqual(txn.status, "Paid")
        self.assertTrue(txn.payment_entry, "no Payment Entry was linked to the Paid transaction")
        self.assertEqual(frappe.db.get_value("Payment Entry", txn.payment_entry, "docstatus"), 1)
        invoice.reload()
        self.assertEqual(flt(invoice.outstanding_amount), 0.0)

    def test_paid_webhook_without_reference_does_not_raise(self):
        """No reference doc: the service returns an error dict; the savepoint must still be valid."""
        txn = self._insert_transaction()
        opened, spy = self._spy_savepoints()
        with spy:
            txn.update_from_webhook(self._paid_webhook())
        self.assertTrue(opened)
        txn.reload()
        self.assertEqual(txn.status, "Paid")

    def test_helper_sanitizes_and_only_none_becomes_unknown(self):
        self.assertEqual(safe_savepoint_name("payment_entry", "ICT-1261"), "payment_entry_ICT_1261")
        self.assertEqual(safe_savepoint_name("ing_x", None), "ing_x_unknown")
        self.assertEqual(safe_savepoint_name("ing_x", 0), "ing_x_0")
        self.assertEqual(safe_savepoint_name("ing_x", ""), "ing_x_")
        self.assertIsNotNone(re.match(r"^[0-9A-Za-z_]+$", safe_savepoint_name("a", "b c-d.e/f")))
