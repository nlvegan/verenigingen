"""Tests for verenigingen.utils.sql_like.escape_sql_like_wildcards.

#1153: three production copies of this escape idiom (plus one in test code)
disagreed on the order of the three ``.replace()`` calls, and the copy in
``sepa_mandate_manager.py`` escaped the backslash LAST -- which doubles the
backslashes the ``%``/``_`` steps just inserted, producing a pattern that
matches neither the literal it protects nor the over-match it blocks.

A test that only checks "the escaped literal still matches some row" cannot
catch this: on a bench with no colliding row, a correct and a broken escape
return identical (empty) results. These tests instead put the built pattern
in front of MariaDB's own ``LIKE`` with both the literal case (must match)
and the over-match case (must NOT match) spelled out.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.sql_like import escape_sql_like_wildcards


def _like_matches(value: str, pattern: str) -> bool:
    """Ask MariaDB directly whether `value LIKE pattern` (with backslash escapes)."""
    row = frappe.db.sql("SELECT %s LIKE %s AS m", (value, pattern))
    return bool(row[0][0])


class TestEscapeSqlLikeWildcards(EnhancedTestCase):
    """Regression coverage for the LIKE-escape order (#1153)."""

    def test_percent_wildcard_is_escaped_correctly(self):
        """A literal containing `%` must match itself and must NOT over-match."""
        literal = "ABC%DEF"
        overmatch = "ABCZZZDEF"  # what an UNESCAPED `%` would additionally match

        pattern = f"{escape_sql_like_wildcards(literal)}"

        self.assertTrue(
            _like_matches(literal, pattern),
            f"escaped pattern {pattern!r} must match its own literal {literal!r}",
        )
        self.assertFalse(
            _like_matches(overmatch, pattern),
            f"escaped pattern {pattern!r} must NOT match the wildcard over-match {overmatch!r}",
        )

    def test_underscore_wildcard_is_escaped_correctly(self):
        """A literal containing `_` must match itself and must NOT over-match."""
        literal = "ABC_DEF"
        overmatch = "ABCXDEF"  # what an UNESCAPED `_` would additionally match

        pattern = escape_sql_like_wildcards(literal)

        self.assertTrue(_like_matches(literal, pattern))
        self.assertFalse(_like_matches(overmatch, pattern))

    def test_literal_backslash_is_escaped_before_wildcard_chars(self):
        """A literal backslash must not be re-doubled by the later `%`/`_` steps.

        This is the exact defect: escaping the backslash LAST doubles the
        backslashes those steps just inserted. Escaping it FIRST (this
        helper's order) means a value that already contains a backslash
        still round-trips correctly alongside a real wildcard character.
        """
        literal = "AB\\C%D"
        overmatch = "AB\\CZZZD"

        pattern = escape_sql_like_wildcards(literal)

        self.assertTrue(_like_matches(literal, pattern))
        self.assertFalse(_like_matches(overmatch, pattern))

    def test_broken_order_is_the_documented_counter_example(self):
        """Pin the exact broken order from #1153 as a permanent counter-example.

        This does not exercise the helper -- it demonstrates why the helper's
        order is the only correct one, by showing the wrong order matches
        neither case. If this test ever goes green, MariaDB's LIKE/backslash
        semantics changed underneath the whole app.
        """
        literal = "ABC%DEF"
        overmatch = "ABCZZZDEF"
        broken_pattern = str(literal).replace("%", "\\%").replace("_", "\\_").replace("\\", "\\\\")

        self.assertFalse(_like_matches(literal, broken_pattern))
        self.assertFalse(_like_matches(overmatch, broken_pattern))

    def test_None_raises_instead_of_silently_becoming_the_string_None(self):
        """Consolidating three call sites must not soften the strictest one.

        Before #1153 these were three inline `.replace()` chains, and they did
        NOT agree on coercion: `sepa_mandate_manager.py` wrote `str(member_id)`
        deliberately (a `member_id` can arrive as an int), while
        `periodic_donation_operations.py` called `.replace()` straight on
        `file_stem` -- so a `None` there raised `AttributeError` at once.

        An unconditional `str()` in the shared helper would turn that loud
        failure into a silent one: `None` becomes the literal `"None"`, the
        caller builds `LIKE 'None%'`, and the query returns nothing at all
        while looking like it worked. Unreachable today (`file_stem` is always
        an f-string), but this is a new shared contract with four callers and
        more to come, and a helper that answers a programming error with an
        empty result set is a footgun.

        So: `None` raises, ints still coerce.
        """
        with self.assertRaises(TypeError):
            escape_sql_like_wildcards(None)

        self.assertEqual(
            escape_sql_like_wildcards(123),
            "123",
            "int coercion is load-bearing for sepa_mandate_manager's member_id",
        )
