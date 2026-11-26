#!/usr/bin/env python3
"""#1339: import_path_validator must treat a directory of .py files without
``__init__.py`` as a (PEP 420 namespace) package, as the interpreter does.

Pure stdlib; builds a throwaway bench-less app tree, so no site is needed.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "import_path_validator.py"
_spec = importlib.util.spec_from_file_location("import_path_validator_1339", _SCRIPT)
ipv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ipv)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _validator_over(app: Path):
    validator = ipv.ImportPathValidator(str(app))
    validator.search_paths = [app]  # only the throwaway tree; no bench, no stdlib
    return validator


class NamespacePackageResolutionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app = Path(self._tmp.name) / "verenigingen"
        ns = self.app / "verenigingen" / "patches" / "v9_9"
        ns.mkdir(parents=True)
        (ns / "a_patch.py").write_text("def execute():\n    pass\n")
        # deliberately NO __init__.py anywhere under patches/
        self.validator = _validator_over(self.app)

    def test_control_fixture_really_has_no_init(self):
        self.assertEqual(list(self.app.rglob("__init__.py")), [])

    def test_namespace_package_dir_resolves(self):
        exists, _ = self.validator._check_module_exists("verenigingen.patches.v9_9")
        self.assertTrue(exists)

    def test_intermediate_namespace_dir_resolves(self):
        exists, _ = self.validator._check_module_exists("verenigingen.patches")
        self.assertTrue(exists)

    def test_module_inside_namespace_package_still_resolves(self):
        exists, path = self.validator._check_module_exists("verenigingen.patches.v9_9.a_patch")
        self.assertTrue(exists)
        self.assertEqual(path.name, "a_patch.py")

    def test_control_missing_module_is_still_reported(self):
        for missing in (
            "verenigingen.patches.v0_0",
            "verenigingen.patches.v9_9.no_such_patch",
            "verenigingen.nothing_here",
        ):
            exists, _ = self.validator._check_module_exists(missing)
            self.assertFalse(exists, missing)

    def test_control_directory_without_any_python_is_not_a_package(self):
        (self.app / "verenigingen" / "docs_only").mkdir()
        (self.app / "verenigingen" / "docs_only" / "readme.md").write_text("x")
        exists, _ = self.validator._check_module_exists("verenigingen.docs_only")
        self.assertFalse(exists)


class RealTreeTest(unittest.TestCase):
    def test_real_patches_imports_are_not_flagged(self):
        sample = Path(tempfile.mkdtemp()) / "sample_1339.py"
        sample.write_text(
            "from verenigingen.patches.v2_0 import add_donor_auto_creation_fields\n"
            "from verenigingen.patches.v1_0 import add_donor_auto_creation_fields\n"
            "from verenigingen.patches.v15_0 import add_team_chapter_notification_types\n"
            "from verenigingen.patches.v2_2 import seed_application_answer_masters\n"
            "import verenigingen.patches.v0_0_nonexistent\n"
        )
        self.addCleanup(sample.unlink)
        validator = ipv.ImportPathValidator(str(REPO_ROOT))
        flagged = [v.module_path for v in validator.validate_file(sample)]
        self.assertEqual(flagged, ["verenigingen.patches.v0_0_nonexistent"])


if __name__ == "__main__":
    unittest.main()
