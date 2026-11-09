# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""#2239: tests that re-import a module must not leave a second copy of it behind.

One CI shard is one process. A test that deletes a module from sys.modules and imports it again leaves
the process holding two copies of every class and function in it: a test module that bound the first
copy at import then patches an object production no longer calls (#2055).

Each test here runs the offending test code for real, then compares the process state with what it was
before. No mock stands in for the offender.
"""

import importlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).parent


def _hooks_state():
    names = ("verenigingen.hooks", "verenigingen.hooks.")
    return {k: v for k, v in sys.modules.items() if k == names[0] or k.startswith(names[1])}


class TestReimportingTestsLeaveNoSecondCopy(unittest.TestCase):
    def test_hooks_package_import_test_puts_the_original_modules_back(self):
        """Runs TestHooksPackageImport.test_hooks_package_import_succeeds (it forces a fresh import)."""
        from verenigingen.tests.test_hooks_modules import TestHooksPackageImport

        importlib.import_module("verenigingen.hooks")
        before = _hooks_state()
        package = importlib.import_module("verenigingen")
        attribute_before = getattr(package, "hooks")

        result = unittest.TextTestRunner(stream=io.StringIO()).run(
            unittest.TestSuite([TestHooksPackageImport("test_hooks_package_import_succeeds")])
        )

        self.assertTrue(result.wasSuccessful(), "the offender must itself still pass")
        after = _hooks_state()
        self.assertEqual(set(after), set(before))
        for name, module in before.items():
            self.assertIs(after[name], module, f"{name} was replaced by a second copy")
        self.assertIs(getattr(package, "hooks"), attribute_before)

    def test_team_role_profile_sync_import_leaves_team_management_and_validator_alone(self):
        """Executes test_team_role_profile_sync's module body (its import-time patch and reload)."""
        import verenigingen.api.team_management as team_management
        import verenigingen.utils.validation.api_validators as validators

        validator_before = validators.validate_api_input
        namespace_before = dict(vars(team_management))
        functions_before = {
            k: v for k, v in namespace_before.items() if callable(v) and not isinstance(v, type)
        }

        def undo_whatever_the_probe_did():
            validators.validate_api_input = validator_before
            vars(team_management).update(namespace_before)

        self.addCleanup(undo_whatever_the_probe_did)

        path = TESTS_DIR / "chapter" / "test_team_role_profile_sync.py"
        spec = importlib.util.spec_from_file_location("_probe_team_role_profile_sync_2239", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertIs(validators.validate_api_input, validator_before, "validator patch leaked")
        for name, fn in functions_before.items():
            self.assertIs(getattr(team_management, name, None), fn, f"team_management.{name} was re-created")
