"""Bank Transaction's per-account reference uniqueness as a database constraint (#1267).

`bank_transaction_creator.py` already checks "does MY account already have this reference"
before creating a row (`_find_matching_bank_transaction`, #383), but that is a check-then-act:
two concurrent writers can both read "no" and both insert. These tests assert the backstop --
a second row sharing (bank_account, reference_number) is refused by the database itself.

They fail loudly rather than skip when the field is missing. A skip here would be the #1267
failure again in test form -- the guard silently absent, with a green run over it.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_bank_transaction_creator_coverage import (
    COMPANY,
    _BankTxnFixtureMixin,
)
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    build_reference_key,
)


class TestBankTransactionReferenceConstraint(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _make_transaction(self, bank_account, reference_number, amount=10.0):
        doc = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "bank_account": bank_account,
                "company": COMPANY,
                "deposit": amount,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": reference_number,
                "description": "PROBE constraint test",
                "status": "Unreconciled",
                "unallocated_amount": amount,
                "allocated_amount": 0.0,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def test_the_field_and_its_unique_index_are_installed(self):
        self.assertTrue(
            frappe.get_meta("Bank Transaction").has_field(FIELDNAME),
            f"Bank Transaction.{FIELDNAME} is not installed - the guard cannot be active",
        )
        index = frappe.db.sql(
            f"SHOW INDEX FROM `tabBank Transaction` WHERE Column_name = '{FIELDNAME}' AND Non_unique = 0"
        )
        self.assertTrue(index, f"no UNIQUE index on Bank Transaction.{FIELDNAME}")

    def test_a_second_transaction_on_one_account_with_the_same_reference_is_refused(self):
        ref = self._ref("dup")
        first = self._make_transaction(self.bank_account, ref)
        self.assertIsNotNone(
            first.get(FIELDNAME), "the validate hook did not derive a key for a real reference"
        )

        with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
            self._make_transaction(self.bank_account, ref)

    def test_the_same_reference_on_two_different_accounts_is_allowed(self):
        # The whole reason the index is scoped per account (#383, #1267): different banks
        # do not coordinate reference numbering.
        other_gl_account = self._ensure_gl_account(name_suffix=" ConstraintOther")
        other_bank_account = self._ensure_bank_account(other_gl_account, name_suffix=" ConstraintOther")

        ref = self._ref("crossacct")
        first = self._make_transaction(self.bank_account, ref)
        second = self._make_transaction(other_bank_account, ref)

        self.assertNotEqual(first.get(FIELDNAME), second.get(FIELDNAME))

    def test_repeated_blank_references_on_one_account_are_allowed(self):
        # MT940 NONREF and several writers default a missing reference to "".
        first = self._make_transaction(self.bank_account, "")
        second = self._make_transaction(self.bank_account, "")

        self.assertIsNone(first.get(FIELDNAME))
        self.assertIsNone(second.get(FIELDNAME))

    def test_submitting_an_edited_draft_moves_the_key(self):
        # The regression that `before_save` allows and `validate` closes: run_before_save_methods
        # dispatches before_save ONLY for _action == "save"; a bare .submit() runs
        # validate + before_submit. With the handler on before_save the persisted key stays
        # the hash of the pre-edit reference, guarding a tuple the row no longer has and
        # reserving a slot nothing occupies.
        txn = self._make_transaction(self.bank_account, self._ref("presubmit"))
        moved_to = self._ref("postsubmit")
        txn.reference_number = moved_to
        txn.submit()

        self.assertEqual(
            frappe.db.get_value("Bank Transaction", txn.name, FIELDNAME),
            build_reference_key(self.bank_account, moved_to),
        )
