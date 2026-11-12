"""#2479: nothing may import BaseRoleProfileManager through the retired utils path.

The module moved to ``verenigingen.services.member.account``. A DeprecationWarning shim
used to be left at the old path, which kept stale importers working silently. The shim is
deleted, so a stale importer would now fail at import time; this scan finds them first,
in both ``verenigingen/`` and ``scripts/`` (the latter is not covered by the import-path
validator, which only looks at the files pre-commit hands it).
"""

import ast
import importlib
import unittest
from pathlib import Path

STALE = "verenigingen.utils.base_role_profile_manager"
CANONICAL = "verenigingen.services.member.account.base_role_profile_manager"
APP_ROOT = Path(__file__).resolve().parents[3].parent  # .../apps/verenigingen (repo root)


def _stale_importers():
    hits = []
    for top in ("verenigingen", "scripts"):
        for path in (APP_ROOT / top).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                    if node.module == "verenigingen.utils":
                        names += [f"verenigingen.utils.{a.name}" for a in node.names]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if STALE in names:
                    hits.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    return hits


class TestRoleProfileManagerImportPath(unittest.TestCase):
    def test_no_file_imports_the_retired_utils_path(self):
        self.assertEqual(_stale_importers(), [])

    def test_canonical_module_exports_what_the_validators_need(self):
        mod = importlib.import_module(CANONICAL)
        for name in ("BaseRoleProfileManager", "EntityConfig", "ERROR_CODES"):
            self.assertTrue(hasattr(mod, name), name)
