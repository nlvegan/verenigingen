"""#2700: ``except frappe.db.DatabaseError`` named an attribute that does not exist.

``frappe.db`` has no ``DatabaseError``. Python evaluates an ``except`` expression only
while an exception is already propagating, so every guarded query that failed -- an
ordinary SQL error or a 1213 deadlock alike -- surfaced as
``AttributeError: 'MariaDBDatabase' object has no attribute 'DatabaseError'`` and the
documented fallback (``None`` / ``[]`` / fail closed) was dead code.

The fault is injected by patching ``frappe.db.sql`` / ``frappe.db.get_value`` to raise: there
is no way to make a healthy test DB fail a query on demand. The permission-system tests also
stand in for the member->volunteer lookup with a fixed ``(member, volunteer)`` pair
(``get_volunteer_for_user`` patched) so that the failing query is the one under test; that is a
probe shortcut, and the lookup itself is exercised for real in ``test_volunteer_lookup_cache``.

Neither ``QueryDeadlockError`` nor ``QueryTimeoutError`` subclasses the driver's
``DatabaseError`` (both derive from plain ``Exception``; measured), so the driver base class
does not swallow them by itself. The permission functions, though, also have a trailing
``except Exception`` that would, so they re-raise ``NON_RESUMABLE_DB_ERRORS`` ahead of it.
"""

from unittest.mock import patch

import frappe
import pymysql

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import project_permissions as pp
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    PaymentReconciliationManager,
)

USER = "nobody-2700@example.com"


def _sql_error():
    """An ordinary, resumable SQL failure (1064), as the driver raises it."""
    return pymysql.err.ProgrammingError(1064, "You have an error in your SQL syntax")


class _LoggedErrors:
    """Capture frappe.log_error titles/messages without touching Error Log."""

    def __enter__(self):
        self.messages = []
        self._patch = patch.object(
            frappe, "log_error", side_effect=lambda *a, **k: self.messages.append(str(k.get("message") or a))
        )
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class TestReconciliationDbErrorHandlers(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # The constructor logs (never raises) when this site has no Mollie account set up.
        self.expectErrorLog("Mollie Account Configuration")
        self.mgr = PaymentReconciliationManager()
        self.txn = {"deposit": 12.5, "reference_number": "REF-2700", "date": frappe.utils.today()}

    # (method, args, fallback)
    def _calls(self):
        return [
            ("match_by_amount_and_reference", (self.txn,), None),
            ("fuzzy_match_member_name", ("SOME NAME", 12.5), None),
        ]

    def test_ordinary_sql_error_degrades_to_the_fallback(self):
        for name, args, fallback in self._calls():
            with self.subTest(name), patch.object(frappe.db, "sql", side_effect=_sql_error()):
                with _LoggedErrors() as logged:
                    self.assertEqual(getattr(self.mgr, name)(*args), fallback)
                self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)

    def test_unpaid_invoices_sql_error_degrades_to_empty_list(self):
        with patch.object(frappe.db, "sql_list", side_effect=_sql_error()), _LoggedErrors() as logged:
            self.assertEqual(self.mgr.get_member_unpaid_invoices("MEM-X", 12.5), [])
        self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)

    def test_deadlock_and_timeout_escape_with_their_own_class(self):
        for exc in (frappe.QueryDeadlockError("1213"), frappe.QueryTimeoutError("1205")):
            for name, args, _ in self._calls():
                with self.subTest(name, exc=type(exc).__name__), patch.object(
                    frappe.db, "sql", side_effect=exc
                ), _LoggedErrors() as logged:
                    with self.assertRaises(type(exc)):
                        getattr(self.mgr, name)(*args)
                    self.assertEqual(logged.messages, [])
            with self.subTest("get_member_unpaid_invoices", exc=type(exc).__name__), patch.object(
                frappe.db, "sql_list", side_effect=exc
            ), _LoggedErrors() as logged:
                with self.assertRaises(type(exc)):
                    self.mgr.get_member_unpaid_invoices("MEM-X", 12.5)
                self.assertEqual(logged.messages, [])

    def test_a_non_database_error_is_not_swallowed(self):
        """Control: the handler is a DB-error handler, not a catch-all."""
        with patch.object(frappe.db, "sql", side_effect=ValueError("not a db error")):
            with self.assertRaises(ValueError):
                self.mgr.fuzzy_match_member_name("SOME NAME", 12.5)


class TestProjectPermissionDbErrorHandlers(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        pp.invalidate_volunteer_lookup_memo()
        self.addCleanup(pp.invalidate_volunteer_lookup_memo)
        patcher = patch.object(pp, "get_volunteer_for_user", return_value=("MEM-2700", "VOL-2700"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _project_row(self, **extra):
        return frappe._dict(project_name="Some Project", **extra)

    # name -> (callable, patched attr, closed-outcome check)
    def _sql_sites(self):
        return {
            "team_projects": (lambda: pp.user_has_any_team_projects(USER), "sql", "raises"),
            "chapter_projects": (lambda: pp.user_has_any_chapter_projects(USER), "sql", "raises"),
            "team_access": (
                lambda: pp.user_has_project_team_access(USER, "PROJ-2700", "read"),
                "sql",
                "raises",
            ),
            "chapter_access": (
                lambda: pp.user_has_project_chapter_access(USER, "PROJ-2700", "read"),
                "sql",
                "raises",
            ),
            "query_conditions": (lambda: pp.get_project_permission_query_conditions(USER), "sql", "1=0"),
        }

    def _patched(self, attr, exc):
        project = self._project_row(custom_team=None, custom_chapter=None)
        stack = [patch.object(frappe.db, attr, side_effect=exc)]
        if attr == "sql":
            stack.append(patch.object(frappe.db, "get_value", return_value=project))
            # get_roles() itself runs frappe.db.sql, which is patched to fail here.
            stack.append(patch.object(frappe, "get_roles", return_value=["Guest"]))
        return stack

    def _run(self, fn, attr, exc):
        from contextlib import ExitStack

        with ExitStack() as es:
            for p in self._patched(attr, exc):
                es.enter_context(p)
            return fn()

    def test_ordinary_sql_error_fails_closed_through_the_database_branch(self):
        for name, (fn, attr, closed) in self._sql_sites().items():
            with self.subTest(name), _LoggedErrors() as logged:
                if closed == "raises":
                    with self.assertRaises(pp.PermissionSystemError) as ctx:
                        self._run(fn, attr, _sql_error())
                    self.assertIn("Database error", str(ctx.exception))
                else:
                    self.assertEqual(self._run(fn, attr, _sql_error()), closed)
                    self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)

    def test_volunteer_lookup_sql_error_raises_the_database_branch(self):
        with patch.object(frappe.db, "sql", side_effect=_sql_error()), _LoggedErrors() as logged:
            with self.assertRaises(pp.PermissionSystemError) as ctx:
                pp._query_volunteer_for_user(USER)
        self.assertIn("Database error", str(ctx.exception))
        self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)

    def test_role_level_lookups_deny_through_the_database_branch(self):
        for fn in (pp.get_chapter_permission_level, pp.get_team_permission_level):
            with self.subTest(fn.__name__), _LoggedErrors() as logged:
                with patch.object(frappe.db, "get_value", side_effect=_sql_error()):
                    self.assertIs(fn("X-2700", "VOL-2700", "read"), False)
                self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)

    def test_deadlock_and_timeout_escape_with_their_own_class(self):
        """The trailing ``except Exception`` must not turn 1213/1205 into a quiet deny."""
        sites = dict(self._sql_sites())
        sites["volunteer_lookup"] = (lambda: pp._query_volunteer_for_user(USER), "sql", "raises")
        sites["chapter_level"] = (lambda: pp.get_chapter_permission_level("X", "V", "read"), "get_value", "")
        sites["team_level"] = (lambda: pp.get_team_permission_level("X", "V", "read"), "get_value", "")
        for exc in (frappe.QueryDeadlockError("1213"), frappe.QueryTimeoutError("1205")):
            self.assertIsInstance(exc, NON_RESUMABLE_DB_ERRORS)
            for name, (fn, attr, _closed) in sites.items():
                # log_error is captured: unpatched it would re-run the patched, failing SQL
                # inside the handler and re-raise the injected error by accident.
                with self.subTest(name, exc=type(exc).__name__), _LoggedErrors() as logged:
                    with self.assertRaises(type(exc)):
                        self._run(fn, attr, exc)
                    self.assertEqual(logged.messages, [])
