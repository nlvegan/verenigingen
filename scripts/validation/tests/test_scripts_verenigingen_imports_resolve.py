#!/usr/bin/env python3
"""Issue #2859: every literal ``verenigingen...`` import under ``scripts/`` must name a
module that exists in the tree.

Why a tree-wide test and not the import_path_validator hook: that hook runs on STAGED
files only, its pre-commit ``exclude`` skips ``scripts/debug/``, ``scripts/testing/`` and
every ``debug_*.py``, it needs a bench to resolve paths, and it cannot see
``importlib.import_module("literal")``. Nothing ever scanned the whole of ``scripts/``,
so seven imports of modules that were moved or never existed survived (#2641, #2859).

Pure stdlib (no bench, no site). Scope: the MODULE part of ``import a.b``,
``from a.b import c`` and ``import_module("a.b")``; the imported NAME ``c`` is not
checked. Relative imports and non-literal ``import_module`` arguments are out of scope.
"""
import ast
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Two sites owned by PR #2865 (#2641), which removes them. Cleanup tracked in #2918. Listed so this test is green
# on develop whichever of the two PRs merges first; delete these entries after #2865 lands.
PENDING_IN_PR_2865 = {
    ("scripts/api_maintenance/sepa_integration_setup.py", "verenigingen.setup.sepa_custom_fields"),
    ("scripts/api_maintenance/sepa_integration_setup.py", "verenigingen.api.sepa_test_data"),
}


def _module_exists(root: Path, dotted: str) -> bool:
    base = root / dotted.replace(".", "/")
    return base.with_suffix(".py").is_file() or base.is_dir()


def _literal_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", None))
            arg = node.args[0]
            if name == "import_module" and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield node.lineno, arg.value


def find_unresolved(root: Path):
    """Return sorted (relative path, line, module) for unresolved verenigingen imports."""
    found = []
    for path in sorted((root / "scripts").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for lineno, module in _literal_imports(tree):
            if module.split(".")[0] == "verenigingen" and not _module_exists(root, module):
                found.append((path.relative_to(root).as_posix(), lineno, module))
    return found


class ScriptsVerenigingenImportsResolveTest(unittest.TestCase):
    def test_every_literal_verenigingen_import_in_scripts_resolves(self):
        unresolved = [
            (p, line, m) for p, line, m in find_unresolved(REPO_ROOT) if (p, m) not in PENDING_IN_PR_2865
        ]
        self.assertEqual(unresolved, [], "scripts/ imports modules that do not exist")

    def test_control_scanner_flags_a_missing_module_and_passes_a_present_one(self):
        # Control: without it, a scanner that finds nothing is indistinguishable from success.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "verenigingen" / "utils").mkdir(parents=True)
            (root / "verenigingen" / "utils" / "present.py").write_text("")
            (root / "scripts" / "debug").mkdir(parents=True)
            (root / "scripts" / "debug" / "s.py").write_text(
                "from verenigingen.utils.present import x\n"
                "import verenigingen.utils.gone_import\n"
                "from verenigingen.utils.gone_from import y\n"
                "import importlib\n"
                "importlib.import_module('verenigingen.utils.gone_dynamic')\n"
                "importlib.import_module(some_variable)\n"
                "import os\n"
            )
            modules = [m for _, _, m in find_unresolved(root)]
        self.assertEqual(
            sorted(modules),
            [
                "verenigingen.utils.gone_dynamic",
                "verenigingen.utils.gone_from",
                "verenigingen.utils.gone_import",
            ],
        )


if __name__ == "__main__":
    unittest.main()
