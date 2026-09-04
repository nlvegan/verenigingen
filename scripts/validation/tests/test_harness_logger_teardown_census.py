#!/usr/bin/env python3
"""Unit tests for scripts/validation/harness_logger_teardown_validator.py.

Pure-Python (no bench/site needed). Run with:
    python -m unittest discover -s scripts/validation/tests -p 'test_harness_logger_teardown_census.py'

WHY THIS EXISTS, and why it is not merely a number-matching ratchet:

``_StderrHandler`` in ``verenigingen/tests/harness_logger.py`` mirrors records to
``sys.__stderr__`` only at ``>= ERROR``. That threshold is not arbitrary -- the
docstring justifies it by saying ERROR is the level of the class-teardown
records that must not be lost (three, as of #815), and explicitly accepts that
the other seventeen (16 WARNING + 1 DEBUG) ARE lost.

That justification holds only while the census does. Add a class-teardown route
that logs at WARNING something which must not be lost, and the gate silently
stops covering it: no test fails, no reviewer is prompted, and the docstring
still reads as though it had been checked.

The figure has already been wrong twice for exactly that reason -- it entered as
"nine sites, all ERROR" (#564) and its first correction was also wrong (#571).
Both survived because nobody could re-run the measurement.
"""
import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "harness_logger_teardown_validator.py"
_spec = importlib.util.spec_from_file_location("harness_logger_teardown_validator", _MOD_PATH)
v = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v
_spec.loader.exec_module(v)

# Loaded by spec, NOT via sys.path.insert. Prepending scripts/validation/ would
# put 19 top-level module names plus the directories tests/, features/,
# framework/, ... on the import path for every other test in the process -- and
# `tests` collides with the app's own package. The sibling validator suites load
# by spec for the same reason; see
# verenigingen/tests/test_secure_operation_result_validator.py.

BASELINE = Path(__file__).resolve().parents[1] / "harness_logger_teardown_baseline.txt"

# The figures verenigingen/tests/harness_logger.py cites, and which this suite
# exists to keep honest. Changing one of these is a deliberate act: read the
# `>= ERROR` gate rationale before touching it, because the gate loses
# everything below ERROR that class teardown emits.
MRO_CALLS, MRO_ERRORS, MRO_TEARDOWNS = 20, 3, 11
NAME_CALLS, NAME_ERRORS = 35, 7
RESIDUAL_BELOW_ERROR = 17  # unchanged: the new call moved warning->error, not added a new below-ERROR site


class TestHarnessLoggerTeardownCensus(unittest.TestCase):
    def test_census_matches_committed_baseline(self):
        """The ratchet. A drift here is a prompt to re-read the >= ERROR gate."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = v.main([])
        self.assertEqual(
            rc,
            0,
            f"Class-teardown harness-logger census drifted from {BASELINE.name}.\n\n"
            f"{err.getvalue()}\n"
            "Do NOT just regenerate the baseline. The >= ERROR mirror gate in "
            "harness_logger.py loses everything below ERROR from class teardown; "
            "decide whether the new route can afford that, THEN regenerate.",
        )

    def test_the_three_error_sites_the_docstring_names_are_reached(self):
        """The gate's rationale names three ERROR sites. Assert all, and the count.

        Keyed on the full (path, lineno, level) tuple, not (path, level): a
        SECOND error() added to any one of these files and reached from
        teardown would otherwise collapse into the existing entry and keep
        this green while the docstring's "exactly three" became false.

        The third (enhanced_test_factory.py) was added by #815: a WARNING
        there was reachable from EnhancedTestCase.tearDown(), which the
        chapter_permission_service_integration.py route drags onto a
        class-teardown path, so it would have been silently lost by the
        >= ERROR mirror gate. Promoted to ERROR rather than left at WARNING.
        """
        _routes, sites, _fns = v.census("mro")
        errors = {s for s in sites if s[2] == "error"}
        paths = {s[0] for s in errors}
        self.assertIn("verenigingen/tests/fixtures/singleton_backup.py", paths)
        self.assertIn("verenigingen/tests/utils/error_log_guard.py", paths)
        self.assertIn("verenigingen/tests/fixtures/enhanced_test_factory.py", paths)
        self.assertEqual(
            len(errors),
            MRO_ERRORS,
            "harness_logger.py says exactly three class-teardown records are at ERROR, "
            f"and that this is why the mirror gate sits there. Now: {sorted(errors)}",
        )

    def test_the_residual_limit_is_still_the_documented_size(self):
        """17 of 20 records are below ERROR and are LOST. The docstring says so."""
        _routes, sites, _fns = v.census("mro")
        below = [s for s in sites if s[2] not in ("error", "critical", "exception")]
        self.assertEqual(
            len(below),
            RESIDUAL_BELOW_ERROR,
            "harness_logger.py's 'residual limit' paragraph says seventeen of the "
            f"twenty class-teardown records are below ERROR and lost. Now {len(below)}. "
            "Update the paragraph, not just the baseline.",
        )

    def test_both_resolution_modes_produce_their_documented_figures(self):
        """The docstring's central methodological claim, pinned to real numbers.

        assertLess alone would not do: name-mode reachability is a superset of
        mro-mode by construction, so an inequality is nearly free and stays
        green even if MRO resolution silently degraded.
        """
        mro_routes, mro_sites, _ = v.census("mro")
        _name_routes, name_sites, _ = v.census("name")
        self.assertEqual((len(mro_routes), len(mro_sites)), (MRO_TEARDOWNS, MRO_CALLS))
        self.assertEqual(len(name_sites), NAME_CALLS)
        self.assertEqual(sum(1 for s in name_sites if s[2] == "error"), NAME_ERRORS)
        self.assertTrue(
            mro_sites < name_sites,
            "MRO-resolved sites must be a strict SUBSET of name-resolved ones -- "
            "name-only resolution is the deliberate over-approximation that bounds "
            "the claim from above. If it is not a superset, it can no longer bound "
            "anything.",
        )

    def test_self_check_fires_when_the_MATCHER_is_blinded(self):
        """Control 1 -- #564's failure: a binding shape the matcher cannot see.

        The original instrument matched `logger = get_harness_logger(...)` but
        not inline `get_harness_logger(...).error(...)`, and silently missed a
        whole file. Blinding it that way must fail loudly, not return a smaller
        plausible number.
        """
        original = v._is_factory_call
        saved = dict(v._SCAN_CACHE)
        try:
            v._is_factory_call = lambda node: False
            # The cache holds FunctionInfo objects whose .logs the REAL matcher
            # populated, so without this clear the monkeypatch is a no-op and
            # this test passes vacuously. A control defeated by an optimisation
            # is worse than no control.
            v._SCAN_CACHE.clear()
            _routes, sites, _fns = v.census("mro")
            self.assertEqual(len(sites), 0, "blinding did not actually blind the matcher")
            self.assertEqual(len(v.self_check(sites)), len(v.CONTROL_SITES))
        finally:
            v._is_factory_call = original
            v._SCAN_CACHE.clear()
            v._SCAN_CACHE.update(saved)  # restore: a cleared cache makes the next test rescan

    def test_self_check_fires_when_only_the_ALIAS_shape_is_blinded(self):
        """Control 1b -- PARTIAL matcher blindness, the mirror of #564.

        Blinding the matcher *completely* is the easy case and proves little.
        The dangerous case is losing ONE binding shape: 13 of the 19 sites are
        alias-form (`logger = get_harness_logger(...)`) and 6 are inline. Both
        ERROR sites named in the docstring are inline, so an alias-only failure
        used to leave every control site reachable -- measured, the census fell
        19 -> 6 and `--report` still exited 0. CONTROL_SITES now carries an
        alias-form entry so each shape has a control.
        """
        original_init = v.ModuleScanner.__init__
        saved = dict(v._SCAN_CACHE)

        class _SwallowAliases(set):
            def add(self, item):  # record nothing, leaving attr_types intact
                pass

        def _patched(self, path):
            original_init(self, path)
            self._alias = _SwallowAliases()

        try:
            v.ModuleScanner.__init__ = _patched
            v._SCAN_CACHE.clear()
            _routes, sites, _fns = v.census("mro")
            self.assertLess(len(sites), MRO_CALLS, "alias blinding did not blind anything")
            self.assertTrue(
                v.self_check(sites),
                "Losing the alias binding shape drops 13 of 19 sites, and the "
                "self-check did not notice. Every binding shape needs a control "
                "site; see CONTROL_SITES.",
            )
        finally:
            v.ModuleScanner.__init__ = original_init
            v._SCAN_CACHE.clear()
            v._SCAN_CACHE.update(saved)

    def test_self_check_fires_when_the_CALL_GRAPH_is_blinded(self):
        """Control 2 -- #571's failure, and the one the first control missed.

        #571's bug was a resolution filter that dropped a real edge class: the
        matcher worked perfectly and the WALK went nowhere. A self-check that
        inspects parsed functions reports "all present" for a call graph that
        resolves to nothing, so it must inspect what the walk REACHED.
        """
        original = v.resolve
        try:
            v.resolve = lambda *a, **k: []
            _routes, sites, _fns = v.census("mro")
            self.assertEqual(len(sites), 0)
            self.assertEqual(
                len(v.self_check(sites)),
                len(v.CONTROL_SITES),
                "A walk that reaches NOTHING passed the self-check. That is exactly "
                "the shape of the #571 defect this control exists to catch.",
            )
        finally:
            v.resolve = original

    def test_report_mode_refuses_to_print_a_total_it_cannot_vouch_for(self):
        """--report is the command harness_logger.py tells a reader to run.

        It must not print a plausible-looking census when the instrument is
        broken; the early return for --report used to bypass the control.
        """
        original = v.resolve
        try:
            v.resolve = lambda *a, **k: []
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = v.main(["--report"])
            self.assertEqual(rc, 2, "--report exited 0 on a dead walk")
            self.assertIn("SELF-CHECK FAILED", err.getvalue())
        finally:
            v.resolve = original

    def test_baseline_site_counts_agree_with_the_census(self):
        """The baseline's per-file counts must be the real per-file counts.

        Asserting only the line shape would re-assert format_baseline's f-string
        against its own output -- a line number is `.isdigit()` too.
        """
        from collections import defaultdict

        _routes, sites, _fns = v.census("mro")
        expected = defaultdict(int)
        for path, _ln, lvl in sites:
            expected[(path, lvl)] += 1
        found = {}
        for line in BASELINE.read_text(encoding="utf-8").splitlines():
            if line.startswith("site "):
                _, path, lvl, count = line.split()
                found[(path, lvl)] = int(count)
        self.assertEqual(found, dict(expected))


if __name__ == "__main__":
    unittest.main()
