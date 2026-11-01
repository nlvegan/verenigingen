"""#1898: ING Checkout Transaction opened ``SAVEPOINT payment_entry_ICT-1261``.

Frappe interpolates the savepoint name unquoted, so the hyphen in the doc name is a
MariaDB 1064. The real method swallowed it into the generic ``except Exception`` and
marked a perfectly good Paid transaction "Paid - Payment Entry Failed".
"""

import re
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.transaction_errors import safe_savepoint_name

_FAILED = "Paid - Payment Entry Failed"


class TestINGTransactionSavepointName(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _paid_webhook(self):
        return {"object": {"status": {"code": 100}, "payments": []}}

    def _make_ing_paid_candidate(self):
        doc = frappe.new_doc("ING Checkout Transaction")
        doc.transaction_id = f"TXN-{frappe.generate_hash(length=8)}"
        doc.status = "Pending"
        doc.amount = 25.0
        doc.insert(ignore_permissions=True)
        return doc

    def test_paid_webhook_opens_a_valid_savepoint_and_stays_paid(self):
        txn = self._make_ing_paid_candidate()
        self.assertIn("-", txn.name, "fixture must carry the hyphenated autoname that triggered #1898")

        opened = []
        real_savepoint = frappe.db.savepoint

        def spy(name):
            opened.append(name)
            return real_savepoint(name)  # real SQL: a bad name raises the real 1064

        # The real service runs; no reference doc -> it returns an error dict, no exception.
        with patch.object(frappe.db, "savepoint", side_effect=spy):
            txn.update_from_webhook(self._paid_webhook())

        txn.reload()
        self.assertTrue(opened, "update_from_webhook never opened a savepoint")
        for name in opened:
            self.assertRegex(name, r"^[0-9A-Za-z_]+$")
        self.assertEqual(txn.status, "Paid", "a 1064 on the savepoint marked a paid txn as failed")
        self.assertNotEqual(txn.status, _FAILED)

    def test_helper_sanitizes_and_tolerates_none(self):
        self.assertEqual(safe_savepoint_name("payment_entry", "ICT-1261"), "payment_entry_ICT_1261")
        self.assertEqual(safe_savepoint_name("ing_x", None), "ing_x_unknown")
        self.assertIsNotNone(re.match(r"^[0-9A-Za-z_]+$", safe_savepoint_name("a", "b c-d.e/f")))
