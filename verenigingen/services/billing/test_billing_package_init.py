"""
Guard: the billing package __init__ must not import its own submodules.

A package __init__ that re-exports its submodules means every
`import verenigingen.services.billing.<anything>` runs all of those imports
first. CPython takes the *submodule* lock before it takes the *package* lock
(importlib._bootstrap._find_and_load), so while one thread is inside the
package __init__ holding the package lock, a second thread importing a
submodule directly holds the submodule lock and waits for the package - and
when the __init__ reaches that same submodule the cycle closes. Under a
threaded web worker that surfaced as

    _frozen_importlib._DeadlockError: deadlock detected by
    _ModuleLock('verenigingen.services.billing.template_configuration_service')

raised out of a permission_query_conditions hook on Membership Dues Schedule.

Import from the defining submodule instead; this file keeps the __init__ empty.

Two checks, because neither alone is enough: the AST one names every offender
so the failure explains itself, and the runtime one is what actually matters -
it survives importlib.import_module(), a PEP 562 __getattr__ lazy loader, and
any other form the AST walk cannot see.
"""

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

PACKAGE = "verenigingen.services.billing"


def _is_type_checking_guard(node) -> bool:
    """True for `if TYPE_CHECKING:` - those imports never run."""
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _runtime_imports(path: Path) -> list[str]:
    """Every module name the file imports, excluding TYPE_CHECKING-only imports."""
    names = []
    stack = [ast.parse(path.read_text(), filename=str(path))]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            stack.extend(node.orelse)  # the else branch does run
            continue
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                names.append(node.module)
            elif node.level == 1:
                # `from .x import y` - resolves inside this package
                names.append(f"{PACKAGE}.{node.module}" if node.module else PACKAGE)
            # level >= 2 resolves to an ancestor package, never to this one
        stack.extend(ast.iter_child_nodes(node))
    return [n for n in names if n]


def _is_own_submodule(name: str) -> bool:
    # `verenigingen.services.billing_extra` shares the prefix but is a sibling
    return name == PACKAGE or name.startswith(PACKAGE + ".")


class TestBillingPackageInit(unittest.TestCase):
    def test_init_does_not_import_its_own_submodules(self):
        init = Path(__file__).parent / "__init__.py"

        offenders = [name for name in _runtime_imports(init) if _is_own_submodule(name)]

        self.assertEqual(
            offenders,
            [],
            f"{init} imports its own submodules {offenders}. That re-opens the concurrent-import "
            "deadlock window - callers must import from the defining submodule instead.",
        )

    def test_importing_the_package_loads_no_submodule(self):
        """The property the AST check only approximates.

        Runs in a subprocess because sibling tests in this process have already
        imported half the package, so sys.modules here proves nothing.
        """
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
        probe = (
            f"import {PACKAGE}, sys, json;"
            f"print(json.dumps(sorted(m for m in sys.modules if m.startswith({PACKAGE!r} + '.'))))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=120
        )
        self.assertEqual(result.returncode, 0, f"probe failed: {result.stderr}")

        loaded = ast.literal_eval(result.stdout.strip())

        self.assertEqual(
            loaded,
            [],
            f"importing {PACKAGE} pulled in {loaded}. Whatever caused that - an import in "
            "__init__.py, a lazy __getattr__, importlib - re-opens the deadlock window.",
        )
