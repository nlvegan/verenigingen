"""#2861: the pre-push enhanced-field-validator hook must skip test paths, like the
validator's own tree mode (validate_app(pre_commit=True)), CI and the baseline do.

pre-commit applies a hook's `exclude` with re.search on the repo-relative path. The
regex used to be anchored at the root (`^(tests/|test_|...)`), so a nested
`verenigingen/tests/x.py` or `.../doctype/foo/test_foo.py` was passed to the hook and
refused pushes on findings CI never sees.
"""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]

# The tree-mode skip list, enhanced_field_reference_validator.validate_app(pre_commit=True).
TREE_MODE_SKIPS = ("/tests/", "/test_", "/debug_", "/scripts/testing/", "/scripts/debug/")


def _field_hook_exclude_2861():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    for repo in config["repos"]:
        for hook in repo.get("hooks", []):
            if hook["id"] == "enhanced-field-validator":
                return re.compile(hook["exclude"])
    raise AssertionError("enhanced-field-validator hook not found")


class FieldHookSkipsTestPaths2861(unittest.TestCase):
    TEST_PATHS = [
        "verenigingen/tests/member/test_member_lifecycle_comprehensive.py",
        "verenigingen/verenigingen/doctype/chapter/test_chapter.py",
        "verenigingen/tests/backend/components/test_membership_status.py",
        "scripts/validation/tests/test_enhanced_field_reference_validator.py",
        "tests/test_root_level.py",
        "verenigingen/e_boekhouden/utils/debug_helpers.py",
        "verenigingen/debug_api.py",
        "scripts/testing/pytest_precommit_runner.py",
        "scripts/debug/x.py",
        "debug_root_script.py",  # root level: only the (^|/) anchor catches it
    ]
    PRODUCTION_PATHS = [
        "verenigingen/verenigingen/doctype/chapter/chapter.py",
        "verenigingen/services/member/lifecycle/member_cleanup_service.py",
        "verenigingen/api/payment_dashboard.py",
        "verenigingen/templates/pages/contest.py",  # contains "test" but is not a test path
        "verenigingen/utils/latest_report.py",  # mid-name "test_": an unanchored exclude would drop it
    ]

    def test_nested_test_paths_are_excluded(self):
        exclude = _field_hook_exclude_2861()
        kept = [p for p in self.TEST_PATHS if not exclude.search(p)]
        self.assertEqual(kept, [], "test files still reach the pre-push field hook")

    def test_production_paths_are_still_checked(self):
        # Control: an always-matching exclude would pass the test above.
        exclude = _field_hook_exclude_2861()
        dropped = [p for p in self.PRODUCTION_PATHS if exclude.search(p)]
        self.assertEqual(dropped, [], "production files must still be validated")

    def test_hook_agrees_with_tree_mode_on_every_path(self):
        exclude = _field_hook_exclude_2861()
        for p in self.TEST_PATHS + self.PRODUCTION_PATHS:
            tree_mode_skips = any(s in "/" + p for s in TREE_MODE_SKIPS)
            self.assertEqual(bool(exclude.search(p)), tree_mode_skips, p)


if __name__ == "__main__":
    unittest.main()
