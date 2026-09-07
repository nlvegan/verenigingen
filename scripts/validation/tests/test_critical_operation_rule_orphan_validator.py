#!/usr/bin/env python3
"""Unit tests for scripts/validation/critical_operation_rule_orphan_validator.py.

Pure-Python (no bench/site needed): each case builds a throwaway fake "repo
root" containing its own verenigingen/fixtures/*.json and a handful of .py
files, then runs find_orphans() against it. Run with:
    python -m pytest scripts/validation/tests/test_critical_operation_rule_orphan_validator.py
or plain:
    python scripts/validation/tests/test_critical_operation_rule_orphan_validator.py
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "critical_operation_rule_orphan_validator.py"
_spec = importlib.util.spec_from_file_location("critical_operation_rule_orphan_validator", _MOD_PATH)
corov = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = corov
_spec.loader.exec_module(corov)


def _build_fake_repo(tmp_dir: Path, fixture_rows: dict, py_files: dict) -> Path:
    """fixture_rows: {fixture_filename: [operation_name, ...]}
    py_files: {relative_path: source_text} -- relative to `tmp_dir` itself, so
        a path must include its scan-root prefix, e.g. "verenigingen/api/foo.py"
        or "scripts/database/create_sepa_indexes.py".
    """
    fixtures_dir = tmp_dir / "verenigingen" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    for fname, op_names in fixture_rows.items():
        rows = [{"doctype": "Critical Operation Rule", "name": op, "operation_name": op} for op in op_names]
        (fixtures_dir / fname).write_text(json.dumps(rows))

    for rel_path, source in py_files.items():
        full = tmp_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(source)

    return tmp_dir


class FindOrphansTest(unittest.TestCase):
    """The validator must flag a rule whose operation_name has no matching def,
    and must NOT flag one that does (or that is on the allowlist)."""

    def test_operation_name_with_no_matching_def_is_orphaned(self):
        with tempfile.TemporaryDirectory() as d:
            root = _build_fake_repo(
                Path(d),
                fixture_rows={"critical_operation_rule.json": ["deleted_long_ago_function"]},
                py_files={"verenigingen/api/foo.py": "def some_other_function():\n    pass\n"},
            )
            orphans = corov.find_orphans(root)
            self.assertEqual(
                orphans,
                {"critical_operation_rule.json::deleted_long_ago_function": "deleted_long_ago_function"},
            )

    def test_operation_name_matching_a_live_def_is_not_orphaned(self):
        with tempfile.TemporaryDirectory() as d:
            root = _build_fake_repo(
                Path(d),
                fixture_rows={"critical_operation_rule.json": ["submit_sepa_batch"]},
                py_files={
                    "verenigingen/api/sepa.py": (
                        "@frappe.whitelist()\n"
                        "@critical_api()\n"
                        "def submit_sepa_batch(batch_id):\n"
                        "    pass\n"
                    )
                },
            )
            orphans = corov.find_orphans(root)
            self.assertEqual(orphans, {})

    def test_generic_api_fallback_is_allowlisted_despite_no_def(self):
        with tempfile.TemporaryDirectory() as d:
            root = _build_fake_repo(
                Path(d),
                fixture_rows={"critical_operation_rule.json": ["_generic_api_fallback"]},
                py_files={"verenigingen/api/foo.py": "def unrelated():\n    pass\n"},
            )
            orphans = corov.find_orphans(root)
            self.assertEqual(orphans, {})

    def test_orphan_in_a_sibling_fixture_file_is_also_found(self):
        """The gap #1033 itself flagged: three sibling fixture files exist besides
        critical_operation_rule.json, and a census that only reads the main file
        misses orphans living in the other three."""
        with tempfile.TemporaryDirectory() as d:
            root = _build_fake_repo(
                Path(d),
                fixture_rows={
                    "critical_operation_rule.json": [],
                    "critical_operation_rule_ponto_debug.json": ["renamed_away_ponto_helper"],
                },
                py_files={"verenigingen/api/foo.py": "def some_other_function():\n    pass\n"},
            )
            orphans = corov.find_orphans(root)
            self.assertEqual(
                orphans,
                {
                    "critical_operation_rule_ponto_debug.json::renamed_away_ponto_helper": (
                        "renamed_away_ponto_helper"
                    )
                },
            )

    def test_def_under_scripts_root_is_not_orphaned(self):
        """Regression: `scripts/` is a real importable package at the app root
        (its own __init__.py; `import scripts` resolves from <bench>/sites)
        holding whitelisted, security-decorated endpoints of its own
        (e.g. scripts.database.create_sepa_indexes). A validator that only
        scanned verenigingen/ mislabelled 122 such live functions as orphans
        (11% of the baseline) -- caught by a skeptical review before merge.
        """
        with tempfile.TemporaryDirectory() as d:
            root = _build_fake_repo(
                Path(d),
                fixture_rows={"critical_operation_rule.json": ["create_sepa_indexes_api"]},
                py_files={
                    "scripts/database/create_sepa_indexes.py": (
                        "@frappe.whitelist()\n"
                        "@critical_api()\n"
                        "def create_sepa_indexes_api():\n"
                        "    pass\n"
                    )
                },
            )
            orphans = corov.find_orphans(root)
            self.assertEqual(orphans, {})

    def test_matching_is_by_bare_name_not_qualified_path(self):
        """rate_limit_engine.py:96 keys off operation_key.split('.')[-1] -- the
        BARE function name -- so a def nested arbitrarily deep still counts as a
        match, matching the runtime behaviour exactly."""
        with tempfile.TemporaryDirectory() as d:
            root = _build_fake_repo(
                Path(d),
                fixture_rows={"critical_operation_rule.json": ["get_dashboard_stats"]},
                py_files={
                    "verenigingen/deep/nested/module.py": (
                        "class Foo:\n" "    def get_dashboard_stats(self):\n" "        pass\n"
                    )
                },
            )
            orphans = corov.find_orphans(root)
            self.assertEqual(orphans, {})


class NewFindingsTest(unittest.TestCase):
    """The baseline comparison itself: a key not in the baseline is 'new'."""

    def test_orphan_already_in_baseline_is_not_new(self):
        orphans = {"critical_operation_rule.json::old_orphan": "old_orphan"}
        baseline = {"critical_operation_rule.json::old_orphan": 1}
        self.assertEqual(corov.new_findings(orphans, baseline), {})

    def test_orphan_not_in_baseline_is_new(self):
        orphans = {"critical_operation_rule.json::fresh_orphan": "fresh_orphan"}
        baseline = {}
        self.assertEqual(
            corov.new_findings(orphans, baseline),
            {"critical_operation_rule.json::fresh_orphan": "fresh_orphan"},
        )


if __name__ == "__main__":
    unittest.main()
