"""Bank Transaction's per-account reference key scope predicate and derivation (#1267, #1349).

The point of these tests is the SEAM: the "is this row in scope" predicate exists twice --
once in Python for the `validate` hook, once in SQL for the backfill patch. Two expressions
of one rule drift the moment only one is edited, and the drift is silent in both directions: a
row the Python half skips keeps a stale key, and a row the SQL half skips never gets one.
`test_sql_and_python_predicates_agree` runs both halves against one corpus so an edit to
either is caught.

The scope is SYSTEM-issued references, as marked by their WRITER (#1349): the Check field
`custom_reference_is_system_issued` (Mollie, e-Boekhouden) or `custom_ponto_transaction_id`
(Ponto). It is NOT the shape of the reference: a payer can type "EB-2024" or "tr_x" on a
statement line. `OUT_OF_SCOPE` below therefore holds unflagged rows with every old prefix.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    build_reference_key,
    in_scope_sql_condition,
    is_system_issued_reference,
    legacy_prefix_matches,
    legacy_prefix_sql_condition,
)

# (bank_account, reference_number, ponto_transaction_id, system_issued) rows. The signals are
# the ones the real writers set: system_issued by dues_payment_processor.py,
# balance_transaction_processor.py, bulk_transaction_importer.py, payment_processors.py,
# bank_transaction_creator.create_from_mollie_payment/create_from_settlement (Mollie ids) and
# the two e-Boekhouden writers (EB-<mutation_id>); ponto_transaction_id by
# ponto/clients/transaction_importer.py (a bare UUID, nothing in its shape to go on).
IN_SCOPE = [
    ("Triodos - NL01TRIO0123456789", "EB-48213", None, 1),
    ("Mollie Sweep Bank - NL02INGB0001234567", "tr_WDqYK6vllg", None, 1),
    ("Kas - NL03ABNA0009876543", "baltr_9pqmnGh8", None, 1),
    ("Kas - NL03ABNA0009876543", "stl_jDk30akdN", None, 1),
    # The writer is the authority, whatever the string looks like.
    ("Triodos - NL01TRIO0123456789", "no-prefix-at-all", None, 1),
    (
        "Ponto Account - BE00000000000000",
        "550e8400-e29b-41d4-a716-446655440000",
        "550e8400-e29b-41d4-a716-446655440000",
        0,
    ),
]
OUT_OF_SCOPE = [
    ("Triodos - NL01TRIO0123456789", "", None, 1),
    ("Triodos - NL01TRIO0123456789", None, None, 1),
    ("", "EB-48213", None, 1),
    (None, "EB-48213", None, 1),
    ("", "", None, 0),
    (None, None, None, 0),
    # MT940 / manual: a payer-chosen reference is not system-issued no matter how it looks.
    ("Triodos - NL01TRIO0123456789", "SHARED-REF-42", None, 0),
    ("Triodos - NL01TRIO0123456789", "NONREF", None, 0),
    # #1349: the old system prefixes, typed by a payer. Unflagged, so unconstrained.
    ("Triodos - NL01TRIO0123456789", "EB-2024", None, 0),
    ("Triodos - NL01TRIO0123456789", "eb-2024", None, 0),
    ("Triodos - NL01TRIO0123456789", "tr_payer", None, 0),
    ("Triodos - NL01TRIO0123456789", "stl_payer", None, 0),
    ("Triodos - NL01TRIO0123456789", "baltr_payer", None, 0),
    # A bare UUID with NO custom_ponto_transaction_id set: the shape alone proves nothing.
    ("Ponto Account - BE00000000000000", "550e8400-e29b-41d4-a716-446655440001", None, 0),
]


def _expected_in_scope(bank_account, reference_number, ponto_id, system_issued):
    return bool(bank_account) and bool(reference_number) and is_system_issued_reference(
        reference_number, ponto_id, system_issued
    )


class TestBankTransactionReferenceKey(FrappeTestCase):
    def test_in_scope_triples_get_a_key(self):
        for bank_account, reference_number, ponto_id, flag in IN_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                self.assertTrue(is_system_issued_reference(reference_number, ponto_id, flag))
                self.assertIsNotNone(build_reference_key(bank_account, reference_number, ponto_id, flag))

    def test_out_of_scope_triples_get_none_not_empty_string(self):
        # None is what exempts the row from the unique index. "" would NOT: MariaDB
        # enforces uniqueness across empty strings, so every out-of-scope row on one
        # account would collide with every other one.
        for bank_account, reference_number, ponto_id, flag in OUT_OF_SCOPE:
            with self.subTest(bank_account=bank_account, reference_number=reference_number):
                self.assertIsNone(build_reference_key(bank_account, reference_number, ponto_id, flag))

    def test_mt940_style_reference_is_not_system_issued(self):
        # The regression #1340's review reproduced: a payer's own end-to-end reference can
        # legitimately repeat across distinct payments. If this ever fails, the scope has
        # widened back to "any non-blank reference" and MT940 imports will start colliding
        # again.
        self.assertFalse(is_system_issued_reference("SHARED-REF-42"))

    def test_a_system_looking_prefix_without_the_writer_flag_is_not_system_issued(self):
        # #1349: the old rule classified by prefix, so a payer-typed "EB-2024" was constrained.
        for reference in ("EB-2024", "eb-2024", "tr_x", "stl_x", "baltr_x"):
            with self.subTest(reference=reference):
                self.assertFalse(is_system_issued_reference(reference))
                self.assertIsNone(build_reference_key("Triodos - NL01TRIO0123456789", reference))

    def test_the_writer_flag_alone_decides_whatever_the_reference_looks_like(self):
        self.assertTrue(is_system_issued_reference("no-prefix-at-all", system_issued=1))
        self.assertTrue(is_system_issued_reference("EB-2024", system_issued=1))

    def test_ponto_shaped_reference_without_the_writer_signal_is_not_system_issued(self):
        # The shape (a bare UUID) is indistinguishable from an unusual manual entry, so
        # only the writer's own custom_ponto_transaction_id signal may put it in scope.
        self.assertFalse(is_system_issued_reference("550e8400-e29b-41d4-a716-446655440001"))

    def test_key_separates_two_accounts_sharing_one_reference(self):
        # The whole reason the index is scoped: different banks/gateways do not coordinate
        # reference numbering, and #383's idempotency lookup already depends on this.
        first = build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213", system_issued=1)
        second = build_reference_key("Kas - NL03ABNA0009876543", "EB-48213", system_issued=1)
        self.assertNotEqual(first, second)

    def test_key_is_sensitive_to_every_component(self):
        base = build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213", system_issued=1)
        self.assertNotEqual(base, build_reference_key("Kas - NL03ABNA0009876543", "EB-48213", system_issued=1))
        self.assertNotEqual(base, build_reference_key("Triodos - NL01TRIO0123456789", "EB-48214", system_issued=1))

    def test_key_is_deterministic_and_fits_the_column(self):
        key = build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213", system_issued=1)
        self.assertEqual(key, build_reference_key("Triodos - NL01TRIO0123456789", "EB-48213", system_issued=1))
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
        flag_column_live = frappe.db.has_column("Bank Transaction", "custom_reference_is_system_issued")
        self.assertTrue(flag_column_live, "custom_reference_is_system_issued is not installed")

        for bank_account, reference_number, ponto_id, flag in IN_SCOPE + OUT_OF_SCOPE:
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
                               {ponto_literal} AS custom_ponto_transaction_id,
                               {int(flag)} AS custom_reference_is_system_issued
                    ) AS corpus
                    """
                )[0][0]
                self.assertEqual(
                    bool(matched),
                    _expected_in_scope(bank_account, reference_number, ponto_id, flag),
                    f"SQL and Python scope predicates disagree on "
                    f"{(bank_account, reference_number, ponto_id, flag)!r}",
                )

    def test_legacy_sql_and_python_prefix_rules_agree(self):
        # The frozen pre-#1349 rule exists twice too (the patches classify old rows with the
        # SQL half, `build_reference_key(system_issued=legacy_prefix_matches(...))` with the
        # Python half).
        condition = legacy_prefix_sql_condition()
        for reference in ("EB-1", "eb-1", "tr_a", "TR_a", "stl_a", "baltr_a", "SHARED-1", "test_a", "", None):
            with self.subTest(reference=reference):
                ref_literal = "NULL" if reference is None else frappe.db.escape(reference)
                matched = frappe.db.sql(
                    f"""
                    SELECT CASE WHEN {condition} THEN 1 ELSE 0 END
                    FROM (SELECT 'Acct' AS bank_account, {ref_literal} AS reference_number) AS corpus
                    """
                )[0][0]
                self.assertEqual(bool(matched), legacy_prefix_matches(reference))
