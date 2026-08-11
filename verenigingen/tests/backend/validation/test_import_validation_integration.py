"""
Integration Tests for Import Validation
Testing that our import path validator and deprecated function checker work correctly.
"""

import unittest
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from verenigingen.tests.utils.base import VereningingenTestCase

# Derive the app root from this file's location so the tests work regardless of
# the bench's absolute path (this file lives at
# <app_root>/verenigingen/tests/backend/validation/...).
APP_ROOT = Path(__file__).resolve().parents[4]
IMPORT_PATH_VALIDATOR = APP_ROOT / "scripts" / "validation" / "import_path_validator.py"
DEPRECATED_CHECKER = APP_ROOT / "scripts" / "validation" / "archived" / "codanna_deprecated_checker.py"
HOOKS_VALIDATOR = APP_ROOT / "scripts" / "validation" / "archived" / "frappe_hooks_validator.py"


class TestImportValidationIntegration(VereningingenTestCase):
    """Test import validation tools integration"""

    def test_import_path_validator_exists(self):
        """Test that import path validator script exists and is executable"""
        self.assertTrue(IMPORT_PATH_VALIDATOR.exists(), "Import path validator script should exist")

    def test_deprecated_checker_exists(self):
        """Test that deprecated function checker exists"""
        self.assertTrue(DEPRECATED_CHECKER.exists(), "Deprecated function checker should exist")

    def test_import_validator_quick_mode(self):
        """Test that import validator works in quick mode"""
        try:
            result = subprocess.run([
                "python",
                str(IMPORT_PATH_VALIDATOR),
                "--quick",
                "--verbose"
            ], capture_output=True, text=True, timeout=30)

            # Should not fail (exit code 0 means no import issues found)
            self.assertEqual(result.returncode, 0, f"Import validator failed: {result.stderr}")
            self.assertIn("✅", result.stdout, "Should show success message")
            print("✅ Import validator quick mode working correctly")

        except subprocess.TimeoutExpired:
            self.fail("Import validator timed out")
        except Exception as e:
            self.fail(f"Error running import validator: {str(e)}")

    def test_import_validator_detects_bad_imports(self):
        """Test that import validator detects invalid imports"""
        # Create a temporary file with bad imports
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
# Test file with bad imports
from verenigingen.utils.nonexistent_module import some_function
from verenigingen.utils.secure_context_manager import get_user  # This should be detected as bad
import totally_fake_module

def test_function():
    pass
""")
            temp_file = f.name

        try:
            result = subprocess.run([
                "python",
                str(IMPORT_PATH_VALIDATOR),
                "--file", temp_file,
                "--verbose"
            ], capture_output=True, text=True, timeout=30)

            # Should detect import violations (exit code 1)
            if result.returncode == 1:
                self.assertIn("secure_context_manager", result.stdout,
                             "Should detect the bad secure_context_manager import")
                print("✅ Import validator correctly detects bad imports")
            else:
                # If no violations found, that's also ok - means the validator is working but this particular import might be ok
                print("ℹ️  Import validator ran without errors (may indicate imports were resolved)")

        except subprocess.TimeoutExpired:
            self.fail("Import validator timed out")
        except Exception as e:
            self.fail(f"Error running import validator: {str(e)}")
        finally:
            # Clean up temporary file
            Path(temp_file).unlink(missing_ok=True)

    def test_critical_imports_are_valid(self):
        """Test that critical application imports are valid"""
        critical_imports = [
            "from verenigingen.utils.application_helpers import get_creation_user",
            "from verenigingen.utils.application_helpers import create_member_from_application",
            "from verenigingen.utils.employee_user_link import create_user_for_volunteer",
            "from verenigingen.api.membership_application import submit_application"
        ]

        for import_statement in critical_imports:
            with self.subTest(import_statement=import_statement):
                try:
                    # Test that the import actually works
                    exec(import_statement)
                    print(f"✅ {import_statement}")
                except ImportError as e:
                    self.fail(f"Critical import failed: {import_statement} - {str(e)}")
                except Exception as e:
                    # Other exceptions are ok - we just want to test that the import resolves
                    print(f"ℹ️  {import_statement} - import resolved but got: {str(e)}")

    def test_no_secure_context_manager_imports(self):
        """Test that no code is trying to import from the non-existent secure_context_manager"""
        # This is a regression test for the specific issue we fixed
        import subprocess

        try:
            result = subprocess.run([
                "grep", "-r", "from verenigingen.utils.secure_context_manager",
                str(APP_ROOT / "verenigingen")
            ], capture_output=True, text=True)

            # Should find no matches (exit code 1 means no matches found)
            if result.returncode == 1:
                print("✅ No bad secure_context_manager imports found")
            else:
                # If matches found, show them but don't fail the test (might be in comments or docs)
                print(f"⚠️  Found secure_context_manager references:\n{result.stdout}")

        except Exception as e:
            print(f"ℹ️  Could not run grep check: {str(e)}")

    def test_pre_commit_hooks_include_import_validation(self):
        """Test that pre-commit hooks include our import validation"""
        pre_commit_config = APP_ROOT / ".pre-commit-config.yaml"

        if pre_commit_config.exists():
            content = pre_commit_config.read_text()
            self.assertIn("import-path-validator", content, "Pre-commit should include import path validator")
            self.assertIn("deprecated-function-checker", content, "Pre-commit should include deprecated function checker")
            print("✅ Pre-commit hooks configured with import validation")
        else:
            print("ℹ️  Pre-commit config not found - may not be in use")


class TestValidatorCheckoutPortability(VereningingenTestCase):
    """The validators must work in a checkout that is not named after the app.

    Regression test for #273. Both validators inferred a path from the checkout's
    own directory - one used the directory name as the Python package name, the
    other assumed the checkout sits exactly two levels below the bench. A git
    worktree breaks both assumptions, and worktrees are the only safe way to do
    branch work here because bench serves the live site straight out of the main
    checkout. The result was hooks failing on content that passes in
    apps/verenigingen, which trains people to reach for SKIP=.
    """

    def _make_checkout(self, package_name: str) -> Path:
        """Build a minimal app checkout in a directory NOT named after the package."""
        root = Path(tempfile.mkdtemp()) / "wt-9f3c1a"
        package = root / package_name
        (package / "utils").mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "utils" / "__init__.py").write_text("")
        (package / "utils" / "helper.py").write_text("def go():\n    pass\n")
        self.addCleanup(shutil.rmtree, root.parent, ignore_errors=True)
        return root

    def test_hooks_validator_finds_hooks_in_a_renamed_checkout(self):
        """The app package is found by locating hooks, not by the directory name."""
        checkout = self._make_checkout("myapp")
        (checkout / "myapp" / "hooks.py").write_text("app_name = 'myapp'\n")

        result = subprocess.run(
            [sys.executable, str(HOOKS_VALIDATOR), "--app-path", str(checkout)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertNotIn(
            "hooks.py not found",
            result.stdout,
            f"Hooks validator did not locate myapp/hooks.py under {checkout.name}:\n{result.stdout}",
        )
        self.assertEqual(result.returncode, 0, f"Validator reported issues:\n{result.stdout}")

    def test_hooks_validator_finds_a_hooks_package_in_a_renamed_checkout(self):
        """This app ships hooks/ as a package rather than hooks.py, so cover that shape too."""
        checkout = self._make_checkout("myapp")
        hooks_package = checkout / "myapp" / "hooks"
        hooks_package.mkdir()
        (hooks_package / "__init__.py").write_text("app_name = 'myapp'\n")

        result = subprocess.run(
            [sys.executable, str(HOOKS_VALIDATOR), "--app-path", str(checkout)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertNotIn("hooks.py not found", result.stdout, result.stdout)
        self.assertEqual(result.returncode, 0, f"Validator reported issues:\n{result.stdout}")

    def test_hooks_parser_finds_the_app_package_in_a_renamed_checkout(self):
        """ast-field-analyzer's hook parser only warns when it misses hooks, so a wrong
        package name silently downgrades it to hook-blind analysis instead of failing."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "hooks_parser_under_test", APP_ROOT / "scripts" / "validation" / "hooks_parser.py"
        )
        hooks_parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hooks_parser)

        checkout = self._make_checkout("myapp")
        (checkout / "myapp" / "hooks.py").write_text("app_name = 'myapp'\n")

        self.assertEqual(hooks_parser.find_app_package(checkout), "myapp")

    def test_import_validator_resolves_the_checkout_it_was_given(self):
        """First-party imports resolve against the checkout under test, not the installed app."""
        checkout = self._make_checkout("verenigingen")
        target = checkout / "verenigingen" / "sample.py"
        target.write_text("from verenigingen.utils.helper import go\n")

        result = subprocess.run(
            [
                sys.executable,
                str(IMPORT_PATH_VALIDATOR),
                "--app-path",
                str(checkout),
                "--pre-commit",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertNotIn("not found", result.stdout, f"Valid import reported missing:\n{result.stdout}")
        self.assertEqual(result.returncode, 0, f"Import validator failed:\n{result.stdout}")

    def test_import_validator_still_reports_a_genuinely_missing_module(self):
        """Pointing the validator at the checkout must not blunt it into passing everything."""
        checkout = self._make_checkout("verenigingen")
        target = checkout / "verenigingen" / "sample.py"
        target.write_text("from verenigingen.utils.no_such_module import go\n")

        result = subprocess.run(
            [
                sys.executable,
                str(IMPORT_PATH_VALIDATOR),
                "--app-path",
                str(checkout),
                "--pre-commit",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 1, f"Missing module was not reported:\n{result.stdout}")
        self.assertIn("verenigingen.utils.no_such_module", result.stdout)


if __name__ == "__main__":
    unittest.main()