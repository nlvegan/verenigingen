#!/usr/bin/env python3
"""Unit tests for scripts/validation/db_clock_date_window_validator.py.

Pure-Python (no bench/site needed): each case is a source snippet written to a
temp file and run through scan_file(). Run with:
    python -m pytest this_file.py
or plain:
    python scripts/validation/tests/test_db_clock_date_window_validator.py
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "db_clock_date_window_validator.py"
_spec = importlib.util.spec_from_file_location("db_clock_date_window_validator", _MOD_PATH)
dcv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dcv
_spec.loader.exec_module(dcv)


def _scan(src: str):
    """Return (findings, bad_pragmas) for a snippet."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "snippet.py"
        p.write_text(src)
        return dcv.scan_file(p)


def _flagged(src: str) -> list:
    return _scan(src)[0]


class PlantedViolationTest(unittest.TestCase):
    """The CONTROL: the validator must reject the exact shapes #668 describes.

    Without this, a clean scan of the real tree is equally consistent with
    "there is nothing left to find" and "the detector cannot find anything" --
    see CLAUDE.md's rule 2 ("a check without a control proves nothing").
    """

    def test_the_sharpest_site_from_668_is_flagged(self):
        """security_monitoring.py's own rapid-SEPA-mandate-creation query,
        verbatim, before its fix."""
        findings = _flagged(
            "def check_sepa_operation_anomalies(self):\n"
            "    rapid_sepa = frappe.db.sql('''\n"
            "        SELECT owner, COUNT(*) as count\n"
            "        FROM `tabSEPA Mandate`\n"
            "        WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)\n"
            "        GROUP BY owner\n"
            "        HAVING count > 5\n"
            "    ''')\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "check_sepa_operation_anomalies")

    def test_date_sub_curdate_is_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql('SELECT * FROM t WHERE d >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_datediff_against_curdate_is_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql('SELECT DATEDIFF(CURDATE(), next_invoice_date) FROM t')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_timestampdiff_against_curdate_is_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql('SELECT TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) FROM t')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_curdate_minus_interval_is_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql('SELECT * FROM t WHERE d >= CURDATE() - INTERVAL 7 DAY')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_direct_comparison_against_now_is_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql('SELECT * FROM t WHERE last_execution < DATE_SUB(NOW(), INTERVAL 25 HOUR)')\n"
        )
        self.assertEqual(len(findings), 1)

    def test_year_curdate_equality_is_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql('SELECT * FROM t WHERE YEAR(posting_date) = YEAR(CURDATE())')\n"
        )
        self.assertEqual(len(findings), 1)


class AcceptsCorrectCallTest(unittest.TestCase):
    """The validator must NOT flag the fixed shape, or a Python-side `now()`."""

    def test_parameterized_boundary_is_not_flagged(self):
        """The actual fix shape: compute the boundary in Python, bind it."""
        findings = _flagged(
            "def f():\n"
            "    cutoff = add_to_date(now_datetime(), hours=-1)\n"
            "    frappe.db.sql('SELECT * FROM t WHERE creation > %s', (cutoff,))\n"
        )
        self.assertEqual(findings, [])

    def test_lowercase_now_python_call_is_not_flagged(self):
        """Lowercase now() is frappe.utils.now() -- the SITE clock, correct."""
        findings = _flagged(
            "def f(doc):\n"
            "    doc.last_updated = now()\n"
        )
        self.assertEqual(findings, [])

    def test_bare_now_with_no_comparison_is_not_flagged(self):
        """An instant with nothing to get wrong -- not a date WINDOW."""
        findings = _flagged(
            "def f():\n"
            "    return frappe.db.sql('SELECT NOW()')\n"
        )
        self.assertEqual(findings, [])

    def test_commented_out_predicate_is_not_flagged(self):
        findings = _flagged(
            "def f():\n"
            "    # WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)\n"
            "    pass\n"
        )
        self.assertEqual(findings, [])

    def test_prose_mentioning_curdate_with_no_operator_is_not_flagged(self):
        """The exact false-positive #668 grep tripped on: prose in a docstring
        that merely NAMES the database's CURDATE(), with no comparison."""
        findings = _flagged(
            "def f():\n"
            "    '''today is passed as a parameter rather than left to\n"
            "    the database's ``CURDATE()``: the two name different days.\n"
            "    '''\n"
        )
        self.assertEqual(findings, [])

    def test_insert_values_now_is_not_flagged(self):
        """A raw INSERT writing creation/modified as NOW() is #453's WRITE-side
        bug, not this (READ-side) validator's concern."""
        findings = _flagged(
            "def f():\n"
            "    frappe.db.sql(\n"
            "        'INSERT INTO `tabMember` (name, creation, modified) "
            "VALUES (%s, NOW(), NOW())'\n"
            "    )\n"
        )
        self.assertEqual(findings, [])


class SuppressionMarkerTest(unittest.TestCase):
    def test_valid_reason_suppresses(self):
        findings, bad = _scan(
            "def f():\n"
            "    q = 'WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)'  "
            "# db-clock-window-ok: false-positive\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(bad, [])

    def test_invalid_reason_is_reported_but_still_suppressed(self):
        findings, bad = _scan(
            "def f():\n"
            "    q = 'WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)'  "
            "# db-clock-window-ok: because-reasons\n"
        )
        self.assertEqual(findings, [])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0][1], "because-reasons")


class ModuleLevelAndNestingTest(unittest.TestCase):
    def test_module_level_predicate_is_flagged_once(self):
        findings = _flagged("QUERY = 'WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)'\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "<module>")

    def test_predicate_inside_method_is_attributed_to_the_method(self):
        findings = _flagged(
            "class Foo:\n"
            "    def bar(self):\n"
            "        return 'WHERE creation > DATE_SUB(NOW(), INTERVAL 1 HOUR)'\n"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], "Foo.bar")


class RatchetMechanicsTest(unittest.TestCase):
    """The comparison `main()` actually runs -- see
    log_error_arg_order_validator's identical rationale: a second copy of the
    same one-line dict comprehension could pass even if `>` silently became
    `>=`."""

    def test_new_findings_only_reports_sites_over_baseline(self):
        counts = {"a.py::f": 2, "b.py::g": 1}
        baseline = {"a.py::f": 1}
        new = dcv.new_findings(counts, baseline)
        self.assertEqual(new, {"a.py::f": 2, "b.py::g": 1})

    def test_new_findings_empty_when_counts_match_baseline(self):
        counts = {"a.py::f": 2}
        baseline = {"a.py::f": 2}
        self.assertEqual(dcv.new_findings(counts, baseline), {})

    def test_new_findings_ignores_a_shrunk_site(self):
        counts = {"a.py::f": 0}
        baseline = {"a.py::f": 2}
        self.assertEqual(dcv.new_findings(counts, baseline), {})


class BaselineIsSelfConsistentTest(unittest.TestCase):
    """The committed baseline must equal a fresh scan of this tree, and the
    validator must never flag its OWN documentation.

    CLAUDE.md's own history names the failure mode this guards against: "a
    ratchet whose allowlist names 3 files covered 0 of 93 occurrences" -- a
    baseline that quietly stops matching reality is worse than no ratchet at
    all, because it reads as green.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo_root = dcv.REPO_ROOT
        cls.baseline = dcv.load_baseline(dcv.DEFAULT_BASELINE)
        cls.counts, cls.problems = dcv._counts(
            [str(cls.repo_root / root) for root in dcv.SCAN_ROOTS]
        )

    def test_baseline_file_exists_and_is_non_trivial(self):
        self.assertTrue(dcv.DEFAULT_BASELINE.exists())
        self.assertGreater(len(self.baseline), 0)

    def test_fresh_scan_matches_the_committed_baseline_exactly(self):
        self.assertEqual(
            self.counts,
            self.baseline,
            "the committed baseline has drifted from a fresh scan of the tree -- "
            "regenerate with `python scripts/validation/db_clock_date_window_"
            "validator.py --update-baseline` and review the diff before committing",
        )

    def test_baseline_total_matches_the_documented_count(self):
        """Pinned so a silent change to either the tree OR the detection rules
        is visible in a diff, not just in the baseline file."""
        self.assertEqual(sum(self.counts.values()), 90)
        self.assertEqual(len(self.counts), 45)

    def test_the_validators_own_file_is_never_a_finding(self):
        """The self-exclusion this file's docstrings need (they quote the bad
        shape as worked examples) must not silently swallow real findings
        from anywhere else."""
        self.assertFalse(
            any(key.startswith("db_clock_date_window_validator.py::") for key in self.counts)
        )

    def test_no_bad_pragmas_in_the_real_tree(self):
        self.assertEqual(self.problems, [])


if __name__ == "__main__":
    unittest.main()
