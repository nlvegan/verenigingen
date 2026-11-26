"""#2711: ``except frappe.DatabaseError`` / ``except frappe.InternalError`` named classes that do not exist.

Neither name exists on ``frappe`` (measured). Python evaluates an ``except`` expression only
while an exception is already propagating, so a failing query surfaced as
``AttributeError: module 'frappe' has no attribute 'DatabaseError'`` and the handler's
documented fallback -- and, in the member payment-history hooks, the trailing
``except Exception`` -- was dead code.

The rule applied per site is #2700's: an ordinary SQL error (the active driver's
``DatabaseError``) degrades as the site documents; ``QueryDeadlockError`` /
``QueryTimeoutError`` (1213 / 1205) are never logged-and-continued and reach the
transaction owner as themselves. Where a trailing ``except Exception`` exists they are
re-raised ahead of it.

Probe shortcut, stated: the faults are injected by patching ``frappe.db.sql`` /
``get_single_value`` / ``get_doc`` to raise, because a healthy test DB cannot be made to
fail a query on demand. The SQL error is built as ``frappe.db.ProgrammingError`` so it is of
the class the ACTIVE driver raises (mysqlclient here and in CI; its errors are not pymysql
errors). One test per shape also drives a REAL server-side rejection through the actual
``frappe.db.sql`` of the SEPA reference generator.
"""

import ast
import importlib
import os
from unittest.mock import patch

import frappe

from verenigingen.services.member.chapter.chapter_management_service import ChapterManagementService
from verenigingen.services.payment.sepa_mandate_manager import SEPAMandateManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.member import member_utils

APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _driver_sql_error_2711():
    """An ordinary, resumable SQL failure (1064) of the class frappe's ACTIVE driver raises."""
    return frappe.db.ProgrammingError(1064, "You have an error in your SQL syntax")


NON_RESUMABLE = (frappe.QueryDeadlockError("1213"), frappe.QueryTimeoutError("1205"))


class _LoggedErrors:
    """Capture frappe.log_error messages without touching Error Log."""

    def __enter__(self):
        self.messages = []
        self._patch = patch.object(
            frappe,
            "log_error",
            side_effect=lambda *a, **k: self.messages.append(str(k.get("message") or a)),
        )
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class TestChapterManagementEnabledCheck(EnhancedTestCase):
    """member_utils.py:68 and chapter_management_service.py:77 -- both default to enabled."""

    def _callers(self):
        service = ChapterManagementService()
        return {
            "member_utils": member_utils._chapter_management_enabled,
            "service": service.is_chapter_management_enabled,
        }

    def test_sql_error_defaults_to_enabled(self):
        for name, fn in self._callers().items():
            with self.subTest(name), _LoggedErrors():
                with patch.object(frappe.db, "get_single_value", side_effect=_driver_sql_error_2711()):
                    self.assertIs(fn(), True)

    def test_member_utils_logs_the_database_branch(self):
        with patch.object(frappe.db, "get_single_value", side_effect=_driver_sql_error_2711()), _LoggedErrors() as logged:
            member_utils._chapter_management_enabled()
        self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)

    def test_deadlock_and_timeout_escape_with_their_own_class(self):
        for exc in NON_RESUMABLE:
            for name, fn in self._callers().items():
                with self.subTest(name, exc=type(exc).__name__), _LoggedErrors() as logged:
                    with patch.object(frappe.db, "get_single_value", side_effect=exc):
                        with self.assertRaises(type(exc)):
                            fn()
                    self.assertEqual(logged.messages, [])

    def test_a_non_database_error_is_not_swallowed(self):
        """Control: this is a DB-error handler, not a catch-all."""
        for name, fn in self._callers().items():
            with self.subTest(name):
                with patch.object(frappe.db, "get_single_value", side_effect=ValueError("not a db error")):
                    with self.assertRaises(ValueError):
                        fn()


class TestOptimizedChapterQueryFallback(EnhancedTestCase):
    """chapter_management_service.py:237 -- an ordinary SQL error falls back to the 2-query path."""

    def setUp(self):
        super().setUp()
        self.service = ChapterManagementService()
        member = self.create_test_member(
            first_name="Chap",
            last_name="Fallback",
            birth_date="1990-01-01",
            email=f"chap.fallback.{frappe.generate_hash(length=8)}@example.com",
        )
        self.member_name = member.name
        self.sentinel = [{"chapter": "FALLBACK-2711"}]

    def _run(self, exc):
        real_sql = frappe.db.sql
        self.optimized_attempts = 0

        def fail_only_the_optimized_query(query, *args, **kwargs):
            # _validate_member_exists runs frappe.db.exists first, outside the try: leave it real
            if "tabChapter Member" in str(query):
                self.optimized_attempts += 1
                raise exc
            return real_sql(query, *args, **kwargs)

        with (
            patch.object(frappe.db, "sql", side_effect=fail_only_the_optimized_query),
            patch.object(self.service, "get_member_chapters", return_value=self.sentinel) as fallback,
        ):
            try:
                return self.service.get_member_chapters_optimized(self.member_name)
            finally:
                self.fallback_calls = fallback.call_count

    def test_sql_error_falls_back_to_the_non_optimized_query(self):
        result = self._run(_driver_sql_error_2711())
        self.assertEqual(result, self.sentinel)
        self.assertEqual(self.optimized_attempts, 1)
        self.assertEqual(self.fallback_calls, 1)

    def test_deadlock_and_timeout_do_not_fall_back(self):
        """After a 1213 the transaction is gone: a second query would run on a fresh one."""
        for exc in NON_RESUMABLE:
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(type(exc)):
                    self._run(exc)
                self.assertEqual(self.optimized_attempts, 1)
                self.assertEqual(self.fallback_calls, 0)


class TestPaymentHistoryHooks(EnhancedTestCase):
    """member_utils.py:153 and :201 -- per-member loops that end in ``except Exception``."""

    def _hooks(self):
        payment = frappe._dict(doctype="Payment Entry", party_type="Customer", party="CUST-2711", name="PE-2711")
        invoice = frappe._dict(doctype="Sales Invoice", customer="CUST-2711", name="SI-2711")
        return {
            "payment_entry": (member_utils.update_member_payment_history, payment),
            "invoice": (member_utils.update_member_payment_history_from_invoice, invoice),
        }

    @staticmethod
    def _history_logs(logged):
        return [m for m in logged.messages if "payment history" in m.lower()]

    def _call(self, hook, doc, exc):
        members = [frappe._dict(name="MEM-2711")]
        with (
            patch.object(frappe, "get_all", return_value=members),
            patch.object(frappe, "get_doc", side_effect=exc),
        ):
            return hook(doc)

    def test_sql_error_is_logged_through_the_database_branch_and_does_not_raise(self):
        for name, (hook, doc) in self._hooks().items():
            with self.subTest(name), _LoggedErrors() as logged:
                self._call(hook, doc, _driver_sql_error_2711())
                self.assertTrue(any("Database error" in m for m in logged.messages), logged.messages)
                self.assertFalse(any("Unexpected error" in m for m in logged.messages), logged.messages)

    def test_deadlock_and_timeout_escape_the_trailing_except_exception(self):
        for exc in NON_RESUMABLE:
            for name, (hook, doc) in self._hooks().items():
                with self.subTest(name, exc=type(exc).__name__), _LoggedErrors() as logged:
                    with self.assertRaises(type(exc)):
                        self._call(hook, doc, exc)
                    # the security decorator on the Payment Entry hook logs its own audit row
                    self.assertEqual(self._history_logs(logged), [])

    def test_a_non_database_error_still_reaches_the_catch_all(self):
        """Control: the trailing ``except Exception`` is unchanged for everything else."""
        for name, (hook, doc) in self._hooks().items():
            with self.subTest(name), _LoggedErrors() as logged:
                self._call(hook, doc, ValueError("not a db error"))
                self.assertTrue(any("Unexpected error" in m for m in logged.messages), logged.messages)


class TestMandateReferenceDbErrors(EnhancedTestCase):
    """sepa_mandate_manager.py:506 -- the reference generator's FOR UPDATE sequence lookup."""

    def setUp(self):
        super().setUp()
        self.manager = SEPAMandateManager()
        self.sql_calls = 0

    def _generate(self, exc):
        def failing(*args, **kwargs):
            self.sql_calls += 1
            raise exc

        with patch.object(frappe.db, "sql", side_effect=failing):
            return self.manager.generate_mandate_reference("MEM-2711", member_id="2711")

    def test_sql_error_becomes_the_documented_validation_error(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._generate(_driver_sql_error_2711())
        self.assertIn("Please try again", str(ctx.exception))
        self.assertNotIn("1064", str(ctx.exception))

    def test_real_server_side_sql_error_becomes_the_documented_validation_error(self):
        """End to end: the server rejects the lookup; no injected exception class."""
        real_sql = frappe.db.sql

        def broken(query, *args, **kwargs):
            return real_sql(query.replace("SELECT", "SELEC", 1), *args, **kwargs)

        with patch.object(frappe.db, "sql", broken), self.assertRaises(frappe.ValidationError) as ctx:
            self.manager.generate_mandate_reference("MEM-2711", member_id="2711")
        self.assertIn("Please try again", str(ctx.exception))

    def test_deadlock_and_timeout_propagate_without_an_in_place_retry(self):
        """A 1213 rolls the whole transaction back, so retrying the lookup on the fresh one
        would let the caller carry on without the writes it made earlier in the request."""
        for exc in NON_RESUMABLE:
            self.sql_calls = 0
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(type(exc)):
                    self._generate(exc)
                # a retry would have issued the lookup again
                self.assertEqual(self.sql_calls, 1)

    def test_a_non_database_error_is_still_wrapped(self):
        """Control: the trailing ``except Exception`` is unchanged for everything else."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._generate(ValueError("boom-2711"))
        self.assertIn("boom-2711", str(ctx.exception))


class TestNoExceptClauseNamesAMissingAttribute(EnhancedTestCase):
    """The class sweep as a ratchet: every ``except <module>.<attr>`` must resolve."""

    @staticmethod
    def _chain(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        return [node.id, *reversed(parts)] if isinstance(node, ast.Name) else None

    @staticmethod
    def _imports(tree):
        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0],
                        None,
                    )
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for alias in node.names:
                    imports[alias.asname or alias.name] = (node.module, alias.name)
        return imports

    @staticmethod
    def _resolve(chain, imports):
        """Return True/False, or None when the root is not an import (a builtin or a local)."""
        if chain[0] not in imports:
            return None
        module, attr = imports[chain[0]]
        try:
            obj = importlib.import_module(module)
            if attr:
                obj = getattr(obj, attr) if hasattr(obj, attr) else importlib.import_module(f"{module}.{attr}")
        except Exception:
            return None
        for part in chain[1:]:
            if not hasattr(obj, part):
                return False
            obj = getattr(obj, part)
        return True

    def _scan_source(self, source):
        tree = ast.parse(source)
        imports = self._imports(tree)
        outcomes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            exprs = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            for expr in exprs:
                chain = self._chain(expr)
                if chain and len(chain) > 1:
                    outcomes.append((node.lineno, ".".join(chain), self._resolve(chain, imports)))
        return outcomes

    def test_control_the_scan_sees_a_missing_name(self):
        outcomes = self._scan_source(
            "import frappe\ntry:\n    pass\nexcept frappe.DatabaseError:\n    pass\n"
            "except (frappe.ValidationError, frappe.InternalError):\n    pass\n"
        )
        self.assertEqual(
            sorted((name, ok) for _, name, ok in outcomes),
            [
                ("frappe.DatabaseError", False),
                ("frappe.InternalError", False),
                ("frappe.ValidationError", True),
            ],
        )

    def test_every_dotted_except_name_in_the_app_and_scripts_exists(self):
        missing, resolved = [], 0
        for top in (APP_ROOT, os.path.join(os.path.dirname(APP_ROOT), "scripts")):
            for dirpath, _dirs, files in os.walk(top):
                if "node_modules" in dirpath:
                    continue
                for filename in files:
                    if not filename.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, filename)
                    try:
                        with open(path, encoding="utf-8") as handle:
                            outcomes = self._scan_source(handle.read())
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    for lineno, name, ok in outcomes:
                        resolved += ok is not None
                        if ok is False:
                            missing.append(f"{os.path.relpath(path, APP_ROOT)}:{lineno} {name}")
        # not vacuous: the sweep that found these six resolved ~1000 names
        self.assertGreater(resolved, 500)
        self.assertEqual(missing, [], "except clauses naming attributes that do not exist")
