#!/usr/bin/env python3
"""Unit tests for scripts/validation/cache_guard_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a temp
file and run through check_file(). Run with:  python -m pytest this_file.py
or plain:  python scripts/validation/tests/test_cache_guard_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "cache_guard_validator.py"
_spec = importlib.util.spec_from_file_location("cache_guard_validator", _MOD_PATH)
cg = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cg  # dataclass @ load-time needs the module registered
_spec.loader.exec_module(cg)


def _run(src: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "test_snippet.py"
        p.write_text(src)
        return cg.check_file(p)


class CacheGuardValidatorTest(unittest.TestCase):
    def _active(self, findings):
        return [f for f in findings if not f.suppressed and f.bad_reason is None]

    def test_offender_reader_before_set_user(self):
        """The canonical #182 shape: reader assertion before frappe.set_user()."""
        findings = self._run_offender()
        active = self._active(findings)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].reader, "has_permission")
        self.assertLess(active[0].line, active[0].switch_line)

    def _run_offender(self):
        return _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        self.assertFalse(frappe.has_permission('PE', 'create', user=u))\n"
            "        frappe.set_user(u)\n"
            "        with self.assertRaises(frappe.PermissionError):\n"
            "            do_thing()\n"
        )

    def test_offender_before_with_as_user(self):
        """Switch expressed as `with self.as_user(...)` still anchors the boundary."""
        findings = _run(
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        self.assertTrue(frappe.has_permission('PE', 'create', user=u))\n"
            "        with self.as_user(u):\n"
            "            do_thing()\n"
        )
        self.assertEqual(len(self._active(findings)), 1)

    def test_clean_reader_after_switch_is_safe(self):
        """Switch-then-read is the correct pattern -> no finding."""
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        frappe.set_user(u)\n"
            "        self.assertFalse(frappe.has_permission('PE', 'create'))\n"
        )
        self.assertEqual(self._active(findings), [])

    def test_reader_inside_as_user_body_is_safe(self):
        """A reader inside the `with as_user` body runs post-switch (fresh) -> safe."""
        findings = _run(
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        with self.as_user(u):\n"
            "            self.assertFalse(doc.has_permission('write'))\n"
        )
        self.assertEqual(self._active(findings), [])

    def test_no_switch_no_finding(self):
        """No user-switch in the function -> not the pre-switch-guard shape."""
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        self.assertTrue(frappe.has_permission('PE', 'read'))\n"
        )
        self.assertEqual(self._active(findings), [])

    def test_nested_function_reader_not_flagged(self):
        """A reader inside a closure defined in the test (code-under-test executed
        later, often inside `with as_user`) must NOT be flagged as a pre-switch guard."""
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        @critical_api()\n"
            "        def inner():\n"
            "            roles = frappe.get_roles(frappe.session.user)\n"
            "            return roles\n"
            "        with self.as_user(u):\n"
            "            inner()\n"
        )
        self.assertEqual(self._active(findings), [])

    def test_suppressed_valid_reason(self):
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        self.assertTrue(frappe.has_permission('PE', 'read', user=u))"
            "  # cache-guard-ok: baseline-intentional\n"
            "        frappe.set_user(u)\n"
            "        do_thing()\n"
        )
        self.assertEqual(self._active(findings), [])
        self.assertTrue(any(f.suppressed for f in findings))

    def test_suppressed_invalid_reason_is_reported(self):
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        self.assertTrue(frappe.has_permission('PE', 'read', user=u))"
            "  # cache-guard-ok: because-i-said-so\n"
            "        frappe.set_user(u)\n"
            "        do_thing()\n"
        )
        self.assertEqual(self._active(findings), [])  # not an active finding...
        self.assertTrue(any(f.bad_reason == "because-i-said-so" for f in findings))

    def test_switch_and_read_inside_try_is_safe(self):
        """Regression: set_user and the reader BOTH inside a try block, reader after
        the switch. A statement-line comparison would false-positive on the `try:`
        header preceding the switch; call-granular comparison must not."""
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def test_x(self):\n"
            "        original = frappe.session.user\n"
            "        try:\n"
            "            frappe.set_user(u)\n"
            "            self.assertFalse(frappe.has_permission('SEPA Audit Log', 'create'))\n"
            "            do_thing()\n"
            "        finally:\n"
            "            frappe.set_user(original)\n"
        )
        self.assertEqual(self._active(findings), [])

    def test_setup_method_is_scanned(self):
        """setUp is analysed too (readers there hit the same stale-cache layer)."""
        findings = _run(
            "import frappe\n"
            "class T(EnhancedTestCase):\n"
            "    def setUp(self):\n"
            "        self.assertTrue(frappe.has_permission('PE', 'read', user=u))\n"
            "        frappe.set_user(u)\n"
        )
        self.assertEqual(len(self._active(findings)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
