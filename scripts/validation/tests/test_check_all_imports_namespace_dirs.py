#!/usr/bin/env python3
"""#1067: the runtime import census must not skip directories without ``__init__.py``.

``pkgutil.walk_packages`` never descends into a directory that lacks ``__init__.py``, so
``verenigingen_payments/templates/pages/mollie_checkout.py`` (``make_payment`` is
``allow_guest=True``) and every other module under such a directory was never imported
by ``check_all_imports.py`` and never counted by a guest-methods census built the same
way. Pure Python (no bench): runs the discovery against the real source tree.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "check_all_imports.py"
_spec = importlib.util.spec_from_file_location("check_all_imports_1067", _SCRIPT)
cai = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cai)

_PKG_DIR = Path(__file__).resolve().parents[3] / "verenigingen"
_NAMESPACE_MODULE = "verenigingen.verenigingen_payments.templates.pages.mollie_checkout"


def _filesystem_module_names_1067():
    """Independent ground truth: every .py file under the package, as a dotted name."""
    names = set()
    for dirpath, dirnames, filenames in os.walk(_PKG_DIR):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            rel = Path(dirpath, filename).relative_to(_PKG_DIR).with_suffix("").parts
            if rel[-1] == "__init__":
                rel = rel[:-1]
            if rel:
                names.add("verenigingen." + ".".join(rel))
    return names


class CheckAllImportsNamespaceDirsTest(unittest.TestCase):
    def setUp(self):
        self.found = set(cai.discover_module_names([str(_PKG_DIR)], "verenigingen."))

    def test_control_the_known_namespace_dir_module_is_a_real_file_without_init(self):
        page_dir = _PKG_DIR / "verenigingen_payments" / "templates" / "pages"
        self.assertTrue((page_dir / "mollie_checkout.py").is_file())
        self.assertFalse((page_dir / "__init__.py").exists())

    def test_namespace_dir_module_is_discovered(self):
        self.assertIn(_NAMESPACE_MODULE, self.found)

    def test_discovery_covers_every_py_file_on_disk(self):
        missing = _filesystem_module_names_1067() - self.found
        self.assertEqual(sorted(missing)[:10], [], f"{len(missing)} modules never imported")

    def test_temp_tree_namespace_package_init_and_skips(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in (
                "pkg/__init__.py",
                "pkg/a.py",
                "pkg/ns/b.py",
                "pkg/ns/deep/c.py",
                "pkg/__pycache__/x.py",
                "pkg/node_modules/y.py",
                "pkg/notes.txt",
            ):
                path = Path(d, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            got = set(cai.discover_module_names([str(Path(d, "pkg"))], "pkg."))
        self.assertEqual(got, {"pkg.a", "pkg.ns.b", "pkg.ns.deep.c"})


if __name__ == "__main__":
    sys.exit(unittest.main())
