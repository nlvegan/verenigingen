"""Bank Transaction's per-account reference key scope predicate and derivation (#1267).

The point of these tests is the SEAM: the "is this row in scope" predicate exists twice --
once in Python for the `validate` hook, once in SQL for the backfill patch. Two expressions
of one rule drift the moment only one is edited, and the drift is silent in both directions: a
row the Python half skips keeps a stale key, and a row the SQL half skips never gets one.
`test_sql_and_python_predicates_agree` runs both halves against one corpus so an edit to
either is caught.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    IN_SCOPE_SQL_CONDITION,
    build_reference_key,
    is_in_scope,
)

# (bank_account, reference_number) pairs, real shapes profiled on veg11 per the #1267
# maintainer decision: EB-<mutation_id> (e-Boekhouden), Mollie tr_/stl_/baltr_, Ponto ids,
# MT940 bank references.
IN_SCOPE = [
    ("Triodos - NL01TRIO0123456789", "EB-48213"),
    ("Mollie Sweep Bank - NL02INGB0001234567", "tr_WDqYK6vllg"),
    ("Kas - NL03ABNA0009876543", "baltr_9pqmnGh8"),
]
OUT_OF_SCOPE = [
    ("Triodos - NL01TRIO0123456789", ""),
    ("Triodos - NL01TRIO0123456789", None),
    ("", "EB-48213"),
    (None, "EB-48213"),
    ("", ""),
    (None, None),
]


class TestBankTransactionReferenceKey(FrappeTestCase):
    def test_in_scope_pairs_get_a_key(self):
        for bank_account, reference_number in IN_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                self.assertTrue(is_in_scope(bank_account, reference_number))
                self.assertIsNotNone(build_reference_key(bank_account, reference_number))

    def test_out_of_scope_pairs_get_none_not_empty_string(self):
        # None is what exempts the row from the unique index. "" would NOT: MariaDB
        # enforces uniqueness across empty strings, so every blank-reference row on one
        # account would collide with every other one.
        for bank_account, reference_number in OUT_OF_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                self.assertFalse(is_in_scope(bank_account, reference_number))
                self.assertIsNone(build_reference_key(bank_account, reference_number))

    def test_key_separates_two_accounts_sharing_one_reference(self):
        # The whole reason the index is scoped: different banks do not coordinate
        # reference numbering, and #383's idempotency lookup already depends on this.
        first = build_reference_key("Triodos - NL01TRIO0123456789", "REF123")
        second = build_reference_key("Kas - NL03ABNA0009876543", "REF123")
        self.assertNotEqual(first, second)

    def test_key_is_sensitive_to_every_component(self):
        base = build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213")
        self.assertNotEqual(base, build_reference_key("Kas - NL03ABNA0009876543", "EB-48213"))
        self.assertNotEqual(base, build_reference_key("Triodos - NL01TRIO0123456789", "EB-48214"))

    def test_key_is_deterministic_and_fits_the_column(self):
        key = build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213")
        self.assertEqual(key, build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213"))
        # Data is varchar(140); bank_account (140) + reference_number (unbounded TEXT) can
        # exceed it, which is why the key is hashed.
        self.assertLessEqual(len(key), 140)

    def test_separator_cannot_be_shifted_between_components(self):
        # Without a separator the concatenation is ambiguous: ("ab", "c") and ("a", "bc")
        # would hash identically.
        self.assertNotEqual(
            build_reference_key("ab", "c"),
            build_reference_key("a", "bc"),
        )

    def test_sql_and_python_predicates_agree(self):
        for bank_account, reference_number in IN_SCOPE + OUT_OF_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                ba_literal = "NULL" if bank_account is None else frappe.db.escape(bank_account)
                ref_literal = "NULL" if reference_number is None else frappe.db.escape(reference_number)
                matched = frappe.db.sql(
                    f"""
                    SELECT CASE WHEN {IN_SCOPE_SQL_CONDITION} THEN 1 ELSE 0 END AS matched
                    FROM (SELECT {ba_literal} AS bank_account, {ref_literal} AS reference_number) AS corpus
                    """
                )[0][0]
                self.assertEqual(
                    bool(matched),
                    is_in_scope(bank_account, reference_number),
                    f"SQL and Python scope predicates disagree on {(bank_account, reference_number)!r}",
                )
