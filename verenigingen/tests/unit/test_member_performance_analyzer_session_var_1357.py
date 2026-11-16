"""member_performance_analyzer must not change SESSION variables (#1357).

``analyze_member_creation`` ran ``SET SESSION query_cache_type = OFF`` and never put it
back. Measured on test_site_11 (10.11.14-MariaDB): the query cache is disabled GLOBALLY
(``query_cache_type = OFF``), and the server refuses to turn it on for one session
(error 1925), so on such a server the statement is a no-op and a session-value
comparison cannot go red. The line was therefore deleted rather than wrapped in a
restore, and the red-capable assertion is on the statements the analyzer issues: a
pass-through recorder (the real ``frappe.db.sql`` still runs) must see no ``SET SESSION``.
"""

import re

import frappe

from scripts.member_performance_analyzer import MemberPerformanceAnalyzer
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.query_counter import count_queries

# Any non-GLOBAL ``SET`` is session-scoped: ``SET SESSION x``, ``SET @@session.x``,
# ``SET x = ...`` (session is the default scope), in any case or spacing.
_1357_SESSION_SET = re.compile(r"^\s*set\s+(?!global\b)", re.IGNORECASE)


def _1357_session_sets(queries):
    return [q for q in queries if _1357_SESSION_SET.match(q)]


class TestMemberPerformanceAnalyzerSessionVar1357(VereningingenTestCase):
    def test_analysis_issues_no_set_session_statement(self):
        with count_queries() as ctx:
            # Control: the counter sees a statement issued through frappe.db.sql.
            frappe.db.sql("SELECT 1")
            try:
                MemberPerformanceAnalyzer().analyze_member_creation()
            except AttributeError as exc:
                # #2637: the analyzer is separately broken; frappe has no
                # ``query_log_context`` / ``get_query_log``, so it dies right after the
                # point where the SET used to run. Tolerate only "frappe lacks an
                # attribute", so a partial fix of #2637 does not redden this test for an
                # unrelated reason; the statements issued before it are what is inspected.
                if "module 'frappe' has no attribute" not in str(exc):
                    raise
        self.assertIn("SELECT 1", ctx.queries)
        self.assertEqual(_1357_session_sets(ctx.queries), [])

    def test_session_set_matcher_catches_every_spelling(self):
        # Control for the matcher itself: each spelling a mutant could use is seen,
        # a GLOBAL set and a SELECT are not.
        for stmt in (
            "SET SESSION query_cache_type = OFF",
            "SET @@session.query_cache_type = OFF",
            "SET  query_cache_type=OFF",
            "  set session query_cache_type = off",
        ):
            self.assertEqual(_1357_session_sets([stmt]), [stmt])
        self.assertEqual(_1357_session_sets(["SET GLOBAL query_cache_type = OFF", "SELECT 1"]), [])
