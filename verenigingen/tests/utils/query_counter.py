"""Shared SQL-query-counting test helper.

Extracted from verenigingen/tests/member/test_member_performance_optimization.py
so that module and verenigingen/tests/backend/unit/api/test_membership_application_api.py
share one implementation instead of two near-identical copies (the Duplicate
Helper Guard flags exactly this shape -- a copy-pasted helper is where a fix
goes to die: the next person fixes one copy and the others keep the bug).
"""

from contextlib import contextmanager

import frappe


class QueryCounter:
    """Holder exposing the queries captured by ``count_queries``."""

    def __init__(self):
        self.queries = []


@contextmanager
def count_queries():
    """Count ``frappe.db.sql`` calls made inside the block.

    Frappe v16's ``assertQueryCount`` no longer yields an object exposing the
    executed queries, so this helper restores ``ctx.queries`` access.

    Patches the INSTANCE attribute, not the class, and *deletes* it on exit
    rather than re-assigning: a re-assignment (``frappe.db.sql = orig_sql``)
    leaves a permanent instance attribute that shadows any later class-level
    patch (e.g. the built-in ``assertQueryCount``), silently zeroing every
    query counter that runs afterwards in the same process.
    ``tests/integration/test_query_optimization_suite.py`` does exactly that
    re-assignment, which is what made ``test_member_dashboard_caching`` fail
    in CI and never locally: with nothing counted, ``first_load > cached_load``
    was ``0 > 0``, and every upper-bound assertion elsewhere passed vacuously
    in any shard where that module ran first.
    """
    counter = QueryCounter()
    had_own_sql = "sql" in frappe.db.__dict__
    orig_sql = frappe.db.sql

    def _sql_with_count(*args, **kwargs):
        ret = orig_sql(*args, **kwargs)
        counter.queries.append(str(args[0]) if args else "")
        return ret

    try:
        frappe.db.sql = _sql_with_count
        yield counter
    finally:
        if had_own_sql:
            frappe.db.sql = orig_sql
        else:
            del frappe.db.sql
