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
"""

import ast
import unittest
from pathlib import Path

PACKAGE = "verenigingen.services.billing"


def _imported_modules(path: Path) -> list[str]:
    """Every module name the file imports at module level."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import, which resolves inside the package
            names.append(node.module if node.level == 0 else PACKAGE)
    return names


class TestBillingPackageInit(unittest.TestCase):
    def test_init_does_not_import_its_own_submodules(self):
        init = Path(__file__).parent / "__init__.py"

        offenders = [name for name in _imported_modules(init) if name and name.startswith(PACKAGE)]

        self.assertEqual(
            offenders,
            [],
            f"{init} imports its own submodules {offenders}. That re-opens the concurrent-import "
            "deadlock window - callers must import from the defining submodule instead.",
        )
