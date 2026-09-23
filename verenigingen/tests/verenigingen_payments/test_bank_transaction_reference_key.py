"""Bank Transaction's per-account reference key scope predicate and derivation (#1267).

The point of these tests is the SEAM: the "is this row in scope" predicate exists twice --
once in Python for the `validate` hook, once in SQL for the backfill patch. Two expressions
of one rule drift the moment only one is edited, and the drift is silent in both directions: a
row the Python half skips keeps a stale key, and a row the SQL half skips never gets one.
`test_sql_and_python_predicates_agree` runs both halves against one corpus so an edit to
either is caught.

The scope itself is narrower than "any non-blank reference" (amended maintainer decision,
after PR #1340's review found the wider scope silently dropped distinct MT940 payments that
happened to share a payer-chosen reference): only SYSTEM-issued references -- Mollie, e-
Boekhouden, Ponto -- get a key at all. `OUT_OF_SCOPE` below includes MT940-shaped references
specifically to pin that a non-blank, non-system reference stays unconstrained.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    build_reference_key,
    in_scope_sql_condition,
    is_system_issued_reference,
)

# (bank_account, reference_number, ponto_transaction_id) triples. System-issued shapes are
# real, profiled against actual writers (see the module docstring): Mollie tr_/stl_/baltr_
# (dues_payment_processor.py, balance_transaction_processor.py,
# bulk_transaction_importer.py), e-Boekhouden EB-<mutation_id> (payment_entry_handler.py,
# processors/payment_processor.py), Ponto ids surfaced via custom_ponto_transaction_id
# (ponto/clients/transaction_importer.py) -- never guessed from reference_number's shape
# alone, since a Ponto id is a bare UUID with nothing distinguishing it.
IN_SCOPE = [
    ("Triodos - NL01TRIO0123456789", "EB-48213", None),
    ("Mollie Sweep Bank - NL02INGB0001234567", "tr_WDqYK6vllg", None),
    ("Kas - NL03ABNA0009876543", "baltr_9pqmnGh8", None),
    ("Kas - NL03ABNA0009876543", "stl_jDk30akdN", None),
    # Case-insensitive, to match reference_number's utf8mb4_unicode_ci collation.
    ("Triodos - NL01TRIO0123456789", "eb-99001", None),
    ("Triodos - NL01TRIO0123456789", "TR_UPPERCASE123", None),
    (
        "Ponto Account - BE00000000000000",
        "550e8400-e29b-41d4-a716-446655440000",
        "550e8400-e29b-41d4-a716-446655440000",
    ),
]
OUT_OF_SCOPE = [
    ("Triodos - NL01TRIO0123456789", "", None),
    ("Triodos - NL01TRIO0123456789", None, None),
    ("", "EB-48213", None),
    (None, "EB-48213", None),
    ("", "", None),
    (None, None, None),
    # MT940 / manual: the whole reason the scope narrowed. A payer-chosen reference is not
    # system-issued no matter how it happens to look, or whether it repeats.
    ("Triodos - NL01TRIO0123456789", "SHARED-REF-42", None),
    ("Triodos - NL01TRIO0123456789", "NONREF", None),
    # A bare UUID with NO custom_ponto_transaction_id set: the shape alone proves nothing.
    ("Ponto Account - BE00000000000000", "550e8400-e29b-41d4-a716-446655440001", None),
]


def _expected_in_scope(bank_account, reference_number, ponto_id):
    return bool(bank_account) and bool(reference_number) and is_system_issued_reference(
        reference_number, ponto_id
    )


class TestBankTransactionReferenceKey(FrappeTestCase):
    def test_in_scope_triples_get_a_key(self):
        for bank_account, reference_number, ponto_id in IN_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                self.assertTrue(is_system_issued_reference(reference_number, ponto_id))
                self.assertIsNotNone(build_reference_key(bank_account, reference_number, ponto_id))

    def test_out_of_scope_triples_get_none_not_empty_string(self):
        # None is what exempts the row from the unique index. "" would NOT: MariaDB
        # enforces uniqueness across empty strings, so every out-of-scope row on one
        # account would collide with every other one.
        for bank_account, reference_number, ponto_id in OUT_OF_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                self.assertIsNone(build_reference_key(bank_account, reference_number, ponto_id))

    def test_mt940_style_reference_is_not_system_issued(self):
        # The regression #1340's review reproduced: a payer's own end-to-end reference can
        # legitimately repeat across distinct payments. If this ever fails, the scope has
        # widened back to "any non-blank reference" and MT940 imports will start colliding
        # again.
        self.assertFalse(is_system_issued_reference("SHARED-REF-42"))

    def test_mollie_test_prefix_is_not_system_issued(self):
        # Deliberately excluded: this app's own test factory defaults references to
        # "test_..." shapes, so treating "test_" as Mollie-issued would drag ordinary test
        # fixtures into the constraint.
        self.assertFalse(is_system_issued_reference("test_payment_abc123"))

    def test_ponto_shaped_reference_without_the_writer_signal_is_not_system_issued(self):
        # The shape (a bare UUID) is indistinguishable from an unusual manual entry, so
        # only the writer's own custom_ponto_transaction_id signal may put it in scope.
        self.assertFalse(is_system_issued_reference("550e8400-e29b-41d4-a716-446655440001"))

    def test_key_separates_two_accounts_sharing_one_reference(self):
        # The whole reason the index is scoped: different banks/gateways do not coordinate
        # reference numbering, and #383's idempotency lookup already depends on this.
        first = build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213")
        second = build_reference_key("Kas - NL03ABNA0009876543", "EB-48213")
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
        # would hash identically. Uses a truthy ponto_transaction_id to put both pairs in
        # scope regardless of reference_number's own shape (which is not system-issued-
        # looking for either "c" or "bc"), isolating this from the scope predicate.
        self.assertNotEqual(
            build_reference_key("ab", "c", ponto_transaction_id="x"),
            build_reference_key("a", "bc", ponto_transaction_id="x"),
        )

    def test_sql_and_python_predicates_agree(self):
        condition = in_scope_sql_condition()
        ponto_column_live = frappe.db.has_column("Bank Transaction", "custom_ponto_transaction_id")

        for bank_account, reference_number, ponto_id in IN_SCOPE + OUT_OF_SCOPE:
            if ponto_id and not ponto_column_live:
                # The SQL half only gates on this column when it actually exists (see
                # in_scope_sql_condition's docstring); a corpus row that depends on it
                # cannot be meaningfully compared when the column is absent.
                continue
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                ba_literal = "NULL" if bank_account is None else frappe.db.escape(bank_account)
                ref_literal = "NULL" if reference_number is None else frappe.db.escape(reference_number)
                ponto_literal = "NULL" if not ponto_id else frappe.db.escape(ponto_id)
                matched = frappe.db.sql(
                    f"""
                    SELECT CASE WHEN {condition} THEN 1 ELSE 0 END AS matched
                    FROM (
                        SELECT {ba_literal} AS bank_account,
                               {ref_literal} AS reference_number,
                               {ponto_literal} AS custom_ponto_transaction_id
                    ) AS corpus
                    """
                )[0][0]
                self.assertEqual(
                    bool(matched),
                    _expected_in_scope(bank_account, reference_number, ponto_id),
                    f"SQL and Python scope predicates disagree on "
                    f"{(bank_account, reference_number, ponto_id)!r}",
                )
