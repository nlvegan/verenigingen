#!/usr/bin/env python3
"""Unit tests for scripts/validation/public_js_endpoint_resolver.py.

Pure-Python (no bench/site needed): each case builds a small file tree under a
temp directory, points the module's REPO_ROOT at it, and exercises resolve()/
find_targets()/main() directly. Run with:
    python -m pytest scripts/validation/tests/test_public_js_endpoint_resolver.py
or plain:
    python scripts/validation/tests/test_public_js_endpoint_resolver.py

The wildcard-import tests exist because the first version of this resolver
shipped a false positive on exactly this shape: it flagged two calls in
member/js_modules/payment-utils.js that actually resolve through
`from verenigingen....member_compat import *` plus member_compat.py's own
`__all__`. Caught by review before merge (see the module docstring); these
tests pin the fix.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from snippet_parse_guard import write_py_snippet
except ImportError:  # run by dotted name: python -m unittest scripts.validation.tests.<module>
    from .snippet_parse_guard import write_py_snippet

_MOD_PATH = Path(__file__).resolve().parents[1] / "public_js_endpoint_resolver.py"
_spec = importlib.util.spec_from_file_location("public_js_endpoint_resolver", _MOD_PATH)
resolver = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = resolver
_spec.loader.exec_module(resolver)


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith(".py"):
        write_py_snippet(p, content, encoding="utf-8")
    else:
        p.write_text(content, encoding="utf-8")
    return p


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self._orig_root = resolver.REPO_ROOT
        resolver.REPO_ROOT = self.root

    def tearDown(self):
        resolver.REPO_ROOT = self._orig_root
        self._tmpdir.cleanup()

    def test_direct_def_resolves(self):
        _write(self.root, "app/mod.py", "def real_func():\n    pass\n")
        self.assertTrue(resolver.resolve("app.mod.real_func"))

    def test_missing_file_is_dead(self):
        self.assertFalse(resolver.resolve("app.nope.func"))

    def test_missing_function_in_real_file_is_dead(self):
        _write(self.root, "app/mod.py", "def other():\n    pass\n")
        self.assertFalse(resolver.resolve("app.mod.func"))

    def test_wildcard_reexport_via_dunder_all_resolves(self):
        """Pins the member_compat.py bug: `from X import *` + X's __all__."""
        _write(
            self.root,
            "app/compat.py",
            "from app.real import target_func\n"
            "__all__ = ['target_func']\n",
        )
        _write(self.root, "app/real.py", "def target_func():\n    pass\n")
        _write(self.root, "app/facade.py", "from app.compat import *\n")
        self.assertTrue(resolver.resolve("app.facade.target_func"))

    def test_wildcard_reexport_excludes_names_missing_from_dunder_all(self):
        _write(
            self.root,
            "app/compat.py",
            "from app.real import target_func, private_helper\n"
            "__all__ = ['target_func']\n",
        )
        _write(
            self.root,
            "app/real.py",
            "def target_func():\n    pass\n\ndef private_helper():\n    pass\n",
        )
        _write(self.root, "app/facade.py", "from app.compat import *\n")
        self.assertFalse(resolver.resolve("app.facade.private_helper"))

    def test_wildcard_without_dunder_all_exports_public_names(self):
        _write(self.root, "app/compat.py", "def target_func():\n    pass\n")
        _write(self.root, "app/facade.py", "from app.compat import *\n")
        self.assertTrue(resolver.resolve("app.facade.target_func"))

    def test_wildcard_without_dunder_all_excludes_underscored_names(self):
        _write(self.root, "app/compat.py", "def _private():\n    pass\n")
        _write(self.root, "app/facade.py", "from app.compat import *\n")
        self.assertFalse(resolver.resolve("app.facade._private"))

    def test_relative_wildcard_import_resolves(self):
        _write(self.root, "app/compat.py", "def target_func():\n    pass\n")
        _write(self.root, "app/facade.py", "from .compat import *\n")
        self.assertTrue(resolver.resolve("app.facade.target_func"))

    def test_package_init_reexport_resolves(self):
        _write(self.root, "app/pkg/real.py", "def target_func():\n    pass\n")
        _write(self.root, "app/pkg/__init__.py", "from app.pkg.real import target_func\n")
        self.assertTrue(resolver.resolve("app.pkg.target_func"))


class FindTargetsTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self._orig_root = resolver.REPO_ROOT
        resolver.REPO_ROOT = self.root

    def tearDown(self):
        resolver.REPO_ROOT = self._orig_root
        self._tmpdir.cleanup()

    def test_extracts_method_call_target(self):
        _write(
            self.root,
            "public/js/thing.js",
            "frappe.call({\n    method: 'verenigingen.api.mod.func',\n});\n",
        )
        found = list(resolver.find_targets(["public/js"]))
        self.assertEqual([t for _, _, t in found], ["verenigingen.api.mod.func"])

    def test_extracts_xcall_target(self):
        _write(
            self.root,
            "public/js/thing.js",
            "frappe.xcall('verenigingen.api.mod.func', {})\n",
        )
        found = list(resolver.find_targets(["public/js"]))
        self.assertEqual([t for _, _, t in found], ["verenigingen.api.mod.func"])

    def test_skips_non_verenigingen_targets(self):
        _write(
            self.root,
            "public/js/thing.js",
            "frappe.call({ method: 'frappe.client.get_list' });\n",
        )
        self.assertEqual(list(resolver.find_targets(["public/js"])), [])

    def test_skips_bare_instance_method_names(self):
        """A `doc:`-bound whitelisted instance method has no dots -- out of scope."""
        _write(
            self.root,
            "public/js/thing.js",
            "frappe.call({ doc: frm.doc, method: 'refresh_financial_history' });\n",
        )
        self.assertEqual(list(resolver.find_targets(["public/js"])), [])


class BaselineGrowthGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self._orig_root = resolver.REPO_ROOT
        resolver.REPO_ROOT = self.root

    def tearDown(self):
        resolver.REPO_ROOT = self._orig_root
        self._tmpdir.cleanup()

    def test_update_baseline_refuses_to_grow(self):
        _write(
            self.root,
            "public/js/thing.js",
            "frappe.call({ method: 'verenigingen.api.nope.func' });\n",
        )
        baseline = self.root / "baseline.txt"
        baseline.write_text("# empty baseline\n", encoding="utf-8")
        rc = resolver.main(
            [
                "prog",
                "public/js",
                "--baseline",
                str(baseline),
                "--update-baseline",
            ]
        )
        self.assertEqual(rc, 1)
        self.assertNotIn("verenigingen.api.nope.func", baseline.read_text())

    def test_update_baseline_force_allows_growth(self):
        _write(
            self.root,
            "public/js/thing.js",
            "frappe.call({ method: 'verenigingen.api.nope.func' });\n",
        )
        baseline = self.root / "baseline.txt"
        baseline.write_text("# empty baseline\n", encoding="utf-8")
        rc = resolver.main(
            [
                "prog",
                "public/js",
                "--baseline",
                str(baseline),
                "--update-baseline",
                "--force",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertIn("verenigingen.api.nope.func", baseline.read_text())


class RealTreeEBoekhoudenScopeTest(unittest.TestCase):
    """#812: doctype JS under e_boekhouden was scanned by nothing and held 4 dead calls."""

    def test_scan_roots_cover_e_boekhouden_doctype_js(self):
        self.assertIn("verenigingen/e_boekhouden", resolver.SCAN_ROOTS)

    def test_no_e_boekhouden_js_call_target_is_dead(self):
        targets = list(resolver.find_targets(["verenigingen/e_boekhouden"]))
        # control: the scan really sees the migration form's calls
        self.assertTrue(
            any(rel.endswith("e_boekhouden_migration.js") for rel, _, _ in targets),
            "scan found no targets in e_boekhouden_migration.js",
        )
        dead = [(rel, n, t) for rel, n, t in targets if not resolver.resolve(t)]
        self.assertEqual(dead, [])

    def test_control_a_dead_target_is_reported_dead(self):
        self.assertFalse(resolver.resolve("verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection"))
        self.assertTrue(
            resolver.resolve("verenigingen.e_boekhouden.utils.eboekhouden_api.test_api_connection")
        )


if __name__ == "__main__":
    unittest.main()
