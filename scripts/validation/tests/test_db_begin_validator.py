#!/usr/bin/env python3
"""Unit tests for scripts/validation/db_begin_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through check_file(). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_db_begin_validator.py
"""

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "db_begin_validator.py"
_spec = importlib.util.spec_from_file_location("db_begin_validator", _MOD_PATH)
dbv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dbv  # dataclass @ load-time needs the module registered
_spec.loader.exec_module(dbv)


def _run(src: str, name: str = "service.py"):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(src)
        return dbv.check_file(p)


class DbBeginValidatorTest(unittest.TestCase):
    def _active(self, findings):
        return [f for f in findings if not f.suppressed and f.bad_reason is None]

    # ---- detection -------------------------------------------------------

    def test_flags_frappe_db_begin(self):
        findings = self._active(_run("import frappe\ndef f():\n    frappe.db.begin()\n"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, dbv.KIND_BEGIN)
        self.assertEqual(findings[0].func, "f")
        self.assertEqual(findings[0].line, 3)

    def test_flags_nested_db_attribute_chain(self):
        """frappe.local.db.begin() is the same call through a longer chain."""
        findings = self._active(_run("import frappe\ndef f():\n    frappe.local.db.begin()\n"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, dbv.KIND_BEGIN)
        self.assertEqual(findings[0].line, 3)

    def test_reports_innermost_enclosing_function(self):
        src = (
            "import frappe\n"
            "def outer():\n"
            "    def inner():\n"
            "        frappe.db.begin()\n"
            "    return inner\n"
        )
        self.assertEqual(self._active(_run(src))[0].func, "inner")

    def test_ignores_unrelated_begin_calls(self):
        """A begin() that is not on a .db attribute is someone else's API."""
        src = "def f():\n    tracer.begin()\n    self.begin()\n    begin()\n"
        self.assertEqual(self._active(_run(src)), [])

    def test_ignores_commit_and_rollback(self):
        src = "import frappe\ndef f():\n    frappe.db.commit()\n    frappe.db.rollback()\n"
        self.assertEqual(self._active(_run(src)), [])

    # ---- raw TRUNCATE ----------------------------------------------------

    def test_flags_raw_truncate(self):
        src = "import frappe\ndef f():\n    frappe.db.sql('TRUNCATE TABLE `tabFoo`')\n"
        findings = self._active(_run(src))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].kind, dbv.KIND_DDL)

    def test_truncate_match_is_case_and_whitespace_insensitive(self):
        src = 'import frappe\ndef f():\n    frappe.db.sql("""\n        truncate table `tabFoo`""")\n'
        self.assertEqual(len(self._active(_run(src))), 1)

    def test_sql_ddl_truncate_is_the_fix_and_not_flagged(self):
        src = "import frappe\ndef f():\n    frappe.db.sql_ddl('TRUNCATE TABLE `tabFoo`')\n"
        self.assertEqual(self._active(_run(src)), [])

    def test_non_truncate_sql_not_flagged(self):
        src = "import frappe\ndef f():\n    frappe.db.sql('SELECT name FROM `tabFoo`')\n"
        self.assertEqual(self._active(_run(src)), [])

    def test_runtime_built_truncate_is_not_guessed_at(self):
        """Deliberate limitation: only literal first arguments are inspected."""
        src = "import frappe\ndef f():\n    frappe.db.sql(f'TRUNCATE TABLE `{table}`')\n"
        self.assertEqual(self._active(_run(src)), [])

    # ---- suppression -----------------------------------------------------

    def test_valid_suppression_silences_the_finding(self):
        src = "import frappe\ndef f():\n    frappe.db.begin()  # db-begin-ok: own-connection\n"
        findings = _run(src)
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].suppressed)
        self.assertEqual(self._active(findings), [])

    def test_every_documented_reason_is_accepted(self):
        """Hard-coded on purpose: iterating dbv.VALID_REASONS would pass even if
        a reason were renamed or dropped, silently turning every existing
        annotation in the tree into a reported error."""
        documented = [
            "false-positive",
            "idempotent-bootstrap",
            "own-connection",
            "patch-context",
            "verified-clean-caller",
        ]
        self.assertEqual(sorted(dbv.VALID_REASONS), documented)
        for reason in documented:
            src = f"import frappe\ndef f():\n    frappe.db.begin()  # db-begin-ok: {reason}\n"
            self.assertTrue(_run(src)[0].suppressed, reason)

    def test_unknown_reason_is_reported_not_honoured(self):
        src = "import frappe\ndef f():\n    frappe.db.begin()  # db-begin-ok: because-i-said-so\n"
        finding = _run(src)[0]
        self.assertFalse(finding.suppressed)
        self.assertEqual(finding.bad_reason, "because-i-said-so")

    def test_missing_reason_is_reported(self):
        src = "import frappe\ndef f():\n    frappe.db.begin()  # db-begin-ok:\n"
        self.assertEqual(_run(src)[0].bad_reason, "(missing)")

    def test_marker_on_any_line_of_a_multiline_statement(self):
        src = (
            "import frappe\n"
            "def f():\n"
            "    frappe.db.sql(\n"
            "        'TRUNCATE TABLE `tabFoo`'\n"
            "    )  # db-begin-ok: patch-context\n"
        )
        self.assertTrue(_run(src)[0].suppressed)

    def test_flags_other_implicit_commit_statements(self):
        """ALTER/DROP/CREATE/START trip the same guard as TRUNCATE."""
        for stmt in (
            "ALTER TABLE `tabFoo` ADD COLUMN x int",
            "DROP TABLE `tabFoo`",
            "CREATE TABLE IF NOT EXISTS `tabFoo` (id int)",
            "START TRANSACTION",
        ):
            src = f"import frappe\ndef f():\n    frappe.db.sql('{stmt}')\n"
            findings = self._active(_run(src))
            self.assertEqual(len(findings), 1, stmt)
            self.assertEqual(findings[0].kind, dbv.KIND_DDL, stmt)

    def test_select_and_insert_are_not_flagged(self):
        for stmt in ("SELECT 1", "INSERT INTO `tabFoo` VALUES (1)", "UPDATE `tabFoo` SET x=1"):
            src = f"import frappe\ndef f():\n    frappe.db.sql('{stmt}')\n"
            self.assertEqual(self._active(_run(src)), [], stmt)

    def test_marker_does_not_bleed_between_calls_in_one_statement(self):
        """Two flagged calls can share a statement; a marker written for one must
        not silence the other (they are separate call nodes)."""
        src = (
            "import frappe\n"
            "def f():\n"
            "    ops = [\n"
            "        frappe.db.begin(),\n"
            "        frappe.db.sql('TRUNCATE TABLE `tabFoo`'),  # db-begin-ok: patch-context\n"
            "    ]\n"
        )
        findings = _run(src)
        self.assertEqual(len(findings), 2)
        by_kind = {f.kind: f for f in findings}
        self.assertFalse(by_kind[dbv.KIND_BEGIN].suppressed, "begin() was silenced by its neighbour")
        self.assertTrue(by_kind[dbv.KIND_DDL].suppressed)

    def test_marker_inside_a_string_literal_does_not_suppress(self):
        """The scan sees COMMENT tokens only, not string contents."""
        src = (
            "import frappe\n"
            "def f():\n"
            "    frappe.db.sql('TRUNCATE TABLE `tabFoo`', values=['# db-begin-ok: own-connection'])\n"
        )
        findings = _run(src)
        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0].suppressed)

    # ---- CLI -------------------------------------------------------------

    def test_main_is_advisory_by_default_and_blocking_with_strict(self):
        import contextlib

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "service.py"
            p.write_text("import frappe\ndef f():\n    frappe.db.begin()\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                advisory = dbv.main(["prog", str(p)])
                strict = dbv.main(["prog", "--strict", str(p)])
        self.assertEqual(advisory, 0)
        self.assertEqual(strict, 1)

    def test_main_returns_zero_on_a_clean_file(self):
        import contextlib

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "service.py"
            p.write_text("import frappe\ndef f():\n    frappe.db.commit()\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dbv.main(["prog", "--strict", str(p)]), 0)

    def test_main_usage_error_without_paths(self):
        import contextlib

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(dbv.main(["prog"]), 2)

    # ---- file scoping ----------------------------------------------------

    def test_test_modules_are_not_production_files(self):
        self.assertFalse(dbv.is_production_file(Path("verenigingen/tests/test_thing.py")))
        self.assertFalse(dbv.is_production_file(Path("a/b/thing_test.py")))
        self.assertFalse(dbv.is_production_file(Path("verenigingen/tests/helpers.py")))
        self.assertFalse(dbv.is_production_file(Path("archived_unused/old_service.py")))
        self.assertFalse(dbv.is_production_file(Path("verenigingen/services/thing.md")))

    def test_production_service_is_in_scope(self):
        self.assertTrue(dbv.is_production_file(Path("verenigingen/services/billing/thing.py")))

    # ---- robustness ------------------------------------------------------

    def test_unparseable_file_is_skipped_not_crashed(self):
        self.assertEqual(_run("def f( :\n"), [])

    def test_clean_file_yields_nothing(self):
        src = "import frappe\ndef f():\n    frappe.db.savepoint('sp')\n    frappe.db.commit()\n"
        self.assertEqual(_run(src), [])


if __name__ == "__main__":
    unittest.main()
