"""security-permission-check.yml must trigger on scripts/ changes (#1076 item 2).

The workflow's ``paths:`` filter named only ``verenigingen/**/*.py`` on both
``pull_request`` and ``push``, so a PR touching only ``scripts/`` (a real package that
holds live whitelisted endpoints) never ran ``Check Permission Bypasses`` at all: 35
checks on such a PR against 49 on a ``verenigingen/`` one. The job body already diffs
every ``*.py`` and the validator scans whatever files it is handed, so the trigger was
the only gap.

Text, not PyYAML: CI's stdlib-only validation job must not depend on it (a missing
module would skip the test and hide a regression). The matcher below is a deliberate
miniature of GitHub's path-filter glob: ``**`` crosses directories, ``*`` does not.
"""

import re
import unittest
from pathlib import Path

_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "security-permission-check.yml"
)
_NESTED_SCRIPT = "scripts/validation/security/permission_bypass_validator.py"
_TOP_SCRIPT = "scripts/some_endpoint.py"
_APP_FILE = "verenigingen/api/member_management.py"


def _secperm_trigger_paths(text, event):
    """The ``paths:`` entries under ``on: <event>:`` (line-based; no YAML parser)."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "on:")
    paths, in_event, in_paths = [], False, False
    for ln in lines[start + 1 :]:
        if ln and not ln.startswith(" "):
            break  # next top-level key ends the on: block
        if re.match(r"^  \S", ln):
            in_event, in_paths = ln.strip() == f"{event}:", False
        elif in_event and re.match(r"^    paths:\s*$", ln):
            in_paths = True
        elif in_event and in_paths and ln.strip().startswith("- "):
            paths.append(ln.strip()[2:].strip().strip("'\""))
        elif in_event and re.match(r"^    \S", ln):
            in_paths = False
    return paths


def _secperm_glob_matches(pattern, path):
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
    regex = regex.replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def _covered(text, event, path):
    return any(_secperm_glob_matches(p, path) for p in _secperm_trigger_paths(text, event))


class SecurityPermissionCheckTriggersTests(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW.read_text()

    def test_control_the_verenigingen_tree_still_triggers_both_events(self):
        for event in ("pull_request", "push"):
            self.assertTrue(_covered(self.text, event, _APP_FILE), event)

    def test_control_the_matcher_rejects_a_path_outside_both_roots(self):
        for event in ("pull_request", "push"):
            self.assertFalse(_covered(self.text, event, "docs/notes.py"), event)

    def test_a_scripts_only_pull_request_triggers_the_check(self):
        for path in (_NESTED_SCRIPT, _TOP_SCRIPT):
            self.assertTrue(_covered(self.text, "pull_request", path), path)

    def test_a_scripts_only_push_triggers_the_check(self):
        for path in (_NESTED_SCRIPT, _TOP_SCRIPT):
            self.assertTrue(_covered(self.text, "push", path), path)

    def test_no_paths_entry_is_a_negation(self):
        """The matcher ignores `!` entries (GitHub would exclude those paths), so fail closed."""
        for event in ("pull_request", "push"):
            for entry in _secperm_trigger_paths(self.text, event):
                self.assertFalse(entry.startswith("!"), (event, entry))

    def test_both_scripts_globs_are_listed_on_both_events(self):
        """`scripts/*.py` is insurance for `**/` zero-directory semantics (top-level files)."""
        for event in ("pull_request", "push"):
            paths = _secperm_trigger_paths(self.text, event)
            self.assertIn("scripts/*.py", paths, event)
            self.assertIn("scripts/**/*.py", paths, event)

    def test_the_job_diffs_every_python_file_not_just_verenigingen(self):
        self.assertIn("-- '*.py'", self.text)
        self.assertNotIn("-- 'verenigingen", self.text)

    def test_the_matcher_distinguishes_single_level_from_recursive_globs(self):
        self.assertFalse(_secperm_glob_matches("scripts/*.py", _NESTED_SCRIPT))
        self.assertTrue(_secperm_glob_matches("scripts/**/*.py", _NESTED_SCRIPT))
        self.assertTrue(_secperm_glob_matches("scripts/**/*.py", _TOP_SCRIPT))


if __name__ == "__main__":
    unittest.main()
