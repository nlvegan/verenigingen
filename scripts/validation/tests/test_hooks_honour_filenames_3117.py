#!/usr/bin/env python3
"""#3117: three hooks declare `pass_filenames: true` but ignored the filenames.

template_field_validator and template_variable_validator never read argv for files, and
javascript_doctype_field_validator treated argv[1] as a DIRECTORY. Run as the hooks run them
(a subprocess, file names as arguments), these tests require that the named files - and only
those - are checked, and that no arguments (CI's tree mode) still scans as before.

    python -m unittest scripts.validation.tests.test_hooks_honour_filenames_3117
"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_VALIDATION = Path(__file__).resolve().parents[1]
_FIELD = _VALIDATION / "production" / "template_field_validator.py"
_JS = _VALIDATION / "production" / "javascript_doctype_field_validator.py"
_VARS = _VALIDATION / "template_variable_validator.py"
_APP = _VALIDATION.parents[1]

# Jinja2 in a standalone .js is an error for the field validator, but only under a path
# containing "verenigingen/" (its own app-file test), hence the nested temp dir below.
_JINJA_IN_JS = "// probe\nvar user = {{ frappe.session.user }};\n"
_BAD_FIELD_JS = """// probe
frappe.ui.form.on('Member', {
    refresh(frm) {
        frm.set_value('zzz_not_a_member_field_3117', 1);
    }
});
"""
_CLEAN_JS = "// probe\nvar x = 1;\n"


def _run(script, *args):
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True, text=True, timeout=300, cwd=str(_APP),
    )


def _scanned(out):
    return int(re.search(r"Files scanned: (\d+)", out).group(1))


class TemplateFieldValidatorFilenames(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "verenigingen" / "public"
        self.dir.mkdir(parents=True)
        self.bad = self.dir / "bad.js"
        self.bad.write_text(_JINJA_IN_JS)
        self.clean = self.dir / "clean.js"
        self.clean.write_text(_CLEAN_JS)

    def test_a_named_bad_file_is_checked(self):
        result = _run(_FIELD, self.bad)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Jinja2 template syntax", result.stdout)

    def test_only_the_named_files_are_scanned(self):
        # The bad sibling sits in the same directory and is NOT named.
        result = _run(_FIELD, self.clean)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(_scanned(result.stdout), 1, result.stdout)

    def test_every_named_file_is_checked_not_just_the_first(self):
        # pre-commit passes many files; the bad one is deliberately second.
        result = _run(_FIELD, self.clean, self.bad)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(_scanned(result.stdout), 2, result.stdout)
        self.assertIn("Jinja2 template syntax", result.stdout)

    def test_no_arguments_is_still_tree_mode(self):
        result = _run(_FIELD)
        self.assertGreater(_scanned(result.stdout), 1, result.stdout)

    def test_a_non_matching_extension_is_ignored(self):
        notes = self.dir / "notes.md"
        notes.write_text("{{ x }}")
        result = _run(_FIELD, notes)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(_scanned(result.stdout), 0, result.stdout)


class JavascriptDoctypeValidatorFilenames(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.bad = self.dir / "bad.js"
        self.bad.write_text(_BAD_FIELD_JS)
        self.clean = self.dir / "clean.js"
        self.clean.write_text(_CLEAN_JS)

    def test_a_named_file_is_validated_as_a_file(self):
        result = _run(_JS, self.bad)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_not_a_member_field_3117", result.stdout)

    def test_a_named_clean_file_does_not_pull_in_its_bad_sibling(self):
        result = _run(_JS, self.clean)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("zzz_not_a_member_field_3117", result.stdout)

    def test_every_named_file_is_validated_not_just_the_first(self):
        result = _run(_JS, self.clean, self.bad)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_not_a_member_field_3117", result.stdout)

    def test_a_directory_argument_still_scans_the_directory(self):
        result = _run(_JS, self.dir)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("zzz_not_a_member_field_3117", result.stdout)


class TemplateVariableValidatorFilenames(unittest.TestCase):
    def _found(self, *args):
        out = _run(_VARS, *args).stdout
        return int(re.search(r"Found (\d+) templates to validate", out).group(1))

    def test_a_named_template_is_the_only_one_validated(self):
        template = next((_APP / "verenigingen" / "templates").rglob("*.html"))
        self.assertEqual(self._found(template.relative_to(_APP)), 1)

    def test_every_named_template_is_validated_not_just_the_first(self):
        templates = list((_APP / "verenigingen" / "templates").rglob("*.html"))[:2]
        self.assertEqual(self._found(*[t.relative_to(_APP) for t in templates]), 2)

    def test_no_arguments_is_still_tree_mode(self):
        self.assertGreater(self._found(), 1)

    def test_verbose_flag_is_not_mistaken_for_a_filename(self):
        self.assertGreater(self._found("--verbose"), 1)

    def test_a_non_template_file_matches_nothing_and_does_not_crash(self):
        result = _run(_VARS, "--verbose", "README.md")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._found("README.md"), 0)


if __name__ == "__main__":
    unittest.main()
