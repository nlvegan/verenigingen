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
it catches some forms the AST walk cannot see, such as
`importlib.import_module(...)` assigned to a module-level name (see
runtime_own_names's own docstring for what it still cannot catch).

The AST/runtime helpers live in verenigingen/tests/utils/barrel_init_ast.py,
shared with the repo-wide ratchet in
verenigingen/tests/utils/test_barrel_init_no_self_import.py (issue #396) -
this file used to carry its own copy, which is exactly the kind of
copy-pasted static-analysis helper `duplicate_helper_validator.py` exists to
catch: a fix to one copy leaves the others with the bug.
"""

import unittest
from pathlib import Path

from verenigingen.tests.utils.barrel_init_ast import (
    eager_imports,
    is_own_submodule,
    runtime_own_names,
)

PACKAGE = "verenigingen.services.billing"


class TestBillingPackageInit(unittest.TestCase):
    def test_init_does_not_import_its_own_submodules(self):
        init = Path(__file__).parent / "__init__.py"

        offenders = [name for name in eager_imports(init, PACKAGE) if is_own_submodule(name, PACKAGE)]

        self.assertEqual(
            offenders,
            [],
            f"{init} imports its own submodules {offenders}. That re-opens the concurrent-import "
            "deadlock window - callers must import from the defining submodule instead.",
        )

    def test_importing_the_package_defines_no_new_name(self):
        """The property the AST check only approximates - see runtime_own_names."""
        own_names = runtime_own_names(PACKAGE)

        self.assertEqual(
            own_names,
            [],
            f"importing {PACKAGE} left {own_names} bound in its own namespace. Whatever caused "
            "that - an import in __init__.py, a lazy __getattr__, importlib bound to a name - "
            "re-opens the deadlock window.",
        )
