"""The Mollie idempotency key's scope predicate and derivation (#809).

The point of these tests is the SEAM: the predicate that decides "is this row in scope"
exists twice -- once in Python for the `before_save` hook, once in SQL for the backfill
patch. Two expressions of one rule drift the moment only one is edited, and the drift is
silent in both directions: a row the Python half skips keeps a stale key, and a row the
SQL half skips never gets one. `test_sql_and_python_predicates_agree` runs both halves
against one corpus so an edit to either is caught.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.utils.mollie_idempotency_key import (
    MOLLIE_REFERENCE_SQL_CONDITION,
    build_idempotency_key,
    is_mollie_style_reference,
)

# Real shapes from `unified_payment_entry_creator.py:56` (payment id + optional suffix)
# alongside the non-Mollie references this app legitimately reuses across many rows --
# 221 duplicate groups of them on veg11, which is the whole reason the index is scoped.
IN_SCOPE = [
    "tr_WDqYK6vllg",
    "re_4qqhO89gsT",
    "tr_WDqYK6vllg_refund_re_4qqhO89gsT",
    "tr_WDqYK6vllg_chargeback_chb_n9z0tp",
    # reference_no has a case-insensitive collation, so the SQL half matches this and a
    # naive Python `startswith` did not. Kept in the corpus so the two cannot diverge again.
    "TR_UPPERCASE123",
]
OUT_OF_SCOPE = [
    "nlvf-standfacturen-2024",
    "ticketshop-2024-rest-1",
    "M2025.6.1",
    "zettle-2024",
    "paypal-2024",
    "BATCH-001",
    "",
    None,
]


class TestMollieIdempotencyKey(FrappeTestCase):
    def test_in_scope_references_get_a_key(self):
        for reference_no in IN_SCOPE:
            with self.subTest(reference_no=reference_no):
                self.assertTrue(is_mollie_style_reference(reference_no))
                self.assertIsNotNone(build_idempotency_key(reference_no, "Receive", "CUST-0001"))

    def test_out_of_scope_references_get_none_not_empty_string(self):
        # None is what exempts the row from the unique index. "" would NOT: MariaDB
        # enforces uniqueness across empty strings, so every non-Mollie row sharing ""
        # would collide with every other one.
        for reference_no in OUT_OF_SCOPE:
            with self.subTest(reference_no=reference_no):
                self.assertFalse(is_mollie_style_reference(reference_no))
                self.assertIsNone(build_idempotency_key(reference_no, "Receive", "CUST-0001"))

    def test_key_separates_a_refund_from_its_original(self):
        # The two share a Mollie payment id and differ only by suffix and payment_type.
        # This is why the key is the composite and not custom_mollie_payment_id.
        original = build_idempotency_key("tr_WDqYK6vllg", "Receive", "CUST-0001")
        refund = build_idempotency_key("tr_WDqYK6vllg_refund_re_4qq", "Pay", "CUST-0001")
        self.assertNotEqual(original, refund)

    def test_key_is_sensitive_to_every_component(self):
        base = build_idempotency_key("tr_WDqYK6vllg", "Receive", "CUST-0001")
        self.assertNotEqual(base, build_idempotency_key("tr_WDqYK6vllh", "Receive", "CUST-0001"))
        self.assertNotEqual(base, build_idempotency_key("tr_WDqYK6vllg", "Pay", "CUST-0001"))
        self.assertNotEqual(base, build_idempotency_key("tr_WDqYK6vllg", "Receive", "CUST-0002"))

    def test_key_is_deterministic_and_fits_the_column(self):
        key = build_idempotency_key("tr_WDqYK6vllg", "Receive", "CUST-0001")
        self.assertEqual(key, build_idempotency_key("tr_WDqYK6vllg", "Receive", "CUST-0001"))
        # Data is varchar(140); the raw composite can exceed it (reference_no and party
        # are 140 each), which is why the key is hashed.
        self.assertLessEqual(len(key), 140)

    def test_separator_cannot_be_shifted_between_components(self):
        # Without a separator the concatenation is ambiguous: ("tr_ab", "c") and
        # ("tr_a", "bc") would hash identically.
        self.assertNotEqual(
            build_idempotency_key("tr_ab", "Receive", "c"),
            build_idempotency_key("tr_a", "Receive", "bc"),
        )

    def test_sql_and_python_predicates_agree(self):
        for reference_no in IN_SCOPE + OUT_OF_SCOPE:
            with self.subTest(reference_no=reference_no):
                # Escaped inline rather than passed as a parameter: the condition's
                # LIKE wildcards are literal `%`, which MySQLdb would try to read as
                # format specifiers the moment the query carries args.
                literal = "NULL" if reference_no is None else frappe.db.escape(reference_no)
                matched = frappe.db.sql(
                    f"""
                    SELECT CASE WHEN {MOLLIE_REFERENCE_SQL_CONDITION} THEN 1 ELSE 0 END AS matched
                    FROM (SELECT {literal} AS reference_no) AS corpus
                    """
                )[0][0]
                self.assertEqual(
                    bool(matched),
                    is_mollie_style_reference(reference_no),
                    f"SQL and Python scope predicates disagree on {reference_no!r}",
                )

    def test_sql_predicate_treats_the_underscore_as_a_literal(self):
        # 'tr\_%' escapes the underscore; unescaped, `_` is a LIKE single-char wildcard
        # and "trX..." would match. This app has already been bitten by an unescaped
        # wildcard in a Mollie id.
        matched = frappe.db.sql(
            f"""
            SELECT CASE WHEN {MOLLIE_REFERENCE_SQL_CONDITION} THEN 1 ELSE 0 END AS matched
            FROM (SELECT 'trXsomething' AS reference_no) AS corpus
            """
        )[0][0]
        self.assertFalse(bool(matched))
