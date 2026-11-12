"""The #1349 data patch keeps pre-existing system-issued rows constrained.

Rows written before #1349 carry no `custom_reference_is_system_issued` flag, but `validate`
recomputes `custom_reference_number_key` from the flag on EVERY save. Unpatched, the next save
of an old Mollie row (a reconciliation, a Payment Entry link) would clear its key and release
it from the unique index. The patch flags exactly the rows the prefix rule had constrained.

Probe shortcut, stated: a "legacy" row is built by inserting a flagged row through the ORM
(so its key is the one the prefix era computed) and then clearing the flag with
`frappe.db.set_value`, which is what a row written before the field existed looks like. The
tests call the patch's functions directly, not `execute()`: its DDL would autocommit a
Custom Field inside a test transaction.
"""

import frappe
from frappe.modules import patch_handler
from frappe.utils import today

from verenigingen.patches.v2_2 import mark_system_issued_bank_transaction_references_1349 as patch
from verenigingen.setup import patch_fragments
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_bank_transaction_creator_coverage import (
    COMPANY,
    _BankTxnFixtureMixin,
)
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    SYSTEM_ISSUED_FIELDNAME,
)


class TestMarkSystemIssuedBankTransactionReferences(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.bank_account = self._ensure_bank_account(self._ensure_gl_account())

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _insert(self, reference, flagged):
        doc = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "bank_account": self.bank_account,
                "company": COMPANY,
                "deposit": 10.0,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": reference,
                "description": "PROBE 1349 patch",
                "unallocated_amount": 10.0,
                "allocated_amount": 0.0,
                SYSTEM_ISSUED_FIELDNAME: 1 if flagged else 0,
            }
        )
        doc.insert()
        return doc

    def _legacy_row(self, reference):
        """A row as the prefix era left it: keyed, but with no flag."""
        doc = self._insert(reference, flagged=True)
        key = doc.get(FIELDNAME)
        self.assertTrue(key)
        frappe.db.set_value("Bank Transaction", doc.name, SYSTEM_ISSUED_FIELDNAME, 0, update_modified=False)
        return doc.name, key

    def _resave(self, name):
        doc = frappe.get_doc("Bank Transaction", name)
        doc.description = f"{doc.description} (resaved)"
        doc.save()
        return frappe.db.get_value("Bank Transaction", name, FIELDNAME)

    def _key(self, name):
        return frappe.db.get_value("Bank Transaction", name, FIELDNAME)

    def test_without_the_patch_a_resave_releases_a_legacy_row_from_the_index(self):
        # The harm the patch exists for. If this stops holding, the patch is unnecessary.
        name, _key = self._legacy_row(f"tr_{frappe.generate_hash(length=10)}")
        self.assertIsNone(self._resave(name))

    def test_after_the_patch_a_resave_keeps_a_legacy_rows_key(self):
        name, key = self._legacy_row(f"tr_{frappe.generate_hash(length=10)}")

        patch.flag_prefix_constrained_rows()

        self.assertEqual(frappe.db.get_value("Bank Transaction", name, SYSTEM_ISSUED_FIELDNAME), 1)
        self.assertEqual(self._resave(name), key)

    def test_every_old_prefix_is_flagged(self):
        names = {
            prefix: self._legacy_row(f"{prefix}{frappe.generate_hash(length=8)}")[0]
            for prefix in ("tr_", "stl_", "baltr_", "EB-", "eb-")
        }

        patch.flag_prefix_constrained_rows()

        for prefix, name in names.items():
            with self.subTest(prefix=prefix):
                self.assertEqual(frappe.db.get_value("Bank Transaction", name, SYSTEM_ISSUED_FIELDNAME), 1)

    def test_an_unprefixed_unflagged_row_is_left_alone(self):
        # The control: the patch must not flag what the prefix rule never constrained.
        mt940 = self._insert(f"PAYER-{frappe.generate_hash(length=8)}", flagged=False)
        blank = self._insert("", flagged=False)
        self.assertIsNone(mt940.get(FIELDNAME))

        patch.flag_prefix_constrained_rows()

        for name in (mt940.name, blank.name):
            self.assertEqual(frappe.db.get_value("Bank Transaction", name, SYSTEM_ISSUED_FIELDNAME), 0)
            self.assertIsNone(self._key(name))

    def test_a_rerun_flags_nothing_new(self):
        self._legacy_row(f"tr_{frappe.generate_hash(length=10)}")
        patch.flag_prefix_constrained_rows()
        self.assertEqual(patch.flag_prefix_constrained_rows(), 0)

    def test_the_patch_is_registered_as_a_post_model_sync_fragment(self):
        patch_fragments.install()
        # Through the module attribute: install() REPLACES it, so a name imported earlier is the original.
        registered = patch_handler.get_patches_from_app("verenigingen")
        self.assertIn(
            "verenigingen.patches.v2_2.mark_system_issued_bank_transaction_references_1349",
            registered,
        )
