"""generate_test_timings.py must weight a module by the time it really takes (#2184 follow-up).

The weights decide CI's shard layout (LPT bin-packing in the patched frappe runner). They were
built from the "(N.NNs)" durations frappe prints for tests over 2s, which cannot see time spent
OUTSIDE a test method, and its regex missed every duration of 100s or more, which frappe prints
in scientific notation (`(3.26e+02s)`, 24 such lines in 24 shard logs). Measured on run
42372760702 (develop, 2026-11-07): test_payment_history_scalability really took ~800s in shard 5
but weighed 59, and that shard ran 40.9 min of tests while the others ran 13.5-24.8. GitHub job logs prefix every
line with a timestamp, so the time between consecutive module headers is the module's real cost.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "generate_test_timings.py"
_spec = importlib.util.spec_from_file_location("generate_test_timings", _MOD_PATH)
gtt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gtt
_spec.loader.exec_module(gtt)

MOD_A = "verenigingen.tests.test_alpha"
MOD_B = "verenigingen.tests.test_beta"


def _ts(seconds):
    """A GitHub job-log timestamp `seconds` after a fixed origin."""
    m, s = divmod(seconds, 60)
    return f"2026-11-07T10:{m:02d}:{s:02d}.0000000Z"


def _log(*events):
    """Job-log text from (seconds, line) pairs, timestamped like GitHub's."""
    return "".join(f"{_ts(t)} {line}\n" for t, line in events)


class TestElapsedFromTimestamps(unittest.TestCase):
    def _write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_a_module_is_charged_until_the_next_module_header(self):
        path = self._write(
            _log(
                (0, f"{MOD_A}.TestA"),
                (100, f"{MOD_B}.TestB"),
                (130, "Tests: 12, Failing: 0, Errors: 0"),
            )
        )
        self.assertEqual(gtt.measured_elapsed_seconds([path]), {MOD_A: 100.0, MOD_B: 30.0})

    def test_a_class_not_named_test_star_still_keys_by_module(self):
        path = self._write(_log((0, f"{MOD_A}.BackgroundJobScalabilityTest"), (50, "Tests: 1")))
        self.assertEqual(gtt.measured_elapsed_seconds([path]), {MOD_A: 50.0})

    def test_several_classes_of_one_module_are_summed(self):
        path = self._write(
            _log((0, f"{MOD_A}.TestOne"), (40, f"{MOD_A}.TestTwo"), (100, "Tests: 4"))
        )
        self.assertEqual(gtt.measured_elapsed_seconds([path]), {MOD_A: 100.0})

    def test_the_max_across_logs_is_kept(self):
        fast = self._write(_log((0, f"{MOD_A}.TestA"), (20, "Tests: 1")))
        slow = self._write(_log((0, f"{MOD_A}.TestA"), (70, "Tests: 1")))
        self.assertEqual(gtt.measured_elapsed_seconds([fast, slow]), {MOD_A: 70.0})

    def test_nothing_after_the_summary_line_is_charged(self):
        path = self._write(_log((0, f"{MOD_A}.TestA"), (10, "Tests: 1"), (500, f"{MOD_B}.TestB"), (900, "x")))
        self.assertEqual(gtt.measured_elapsed_seconds([path]), {MOD_A: 10.0})

    def test_a_dotted_line_not_ending_in_a_class_does_not_start_a_span(self):
        # e.g. a logger or traceback line naming a module: it must not steal the module's time.
        path = self._write(
            _log((0, f"{MOD_A}.TestA"), (30, "verenigingen.tests.test_beta.helper"), (60, "Tests: 1"))
        )
        self.assertEqual(gtt.measured_elapsed_seconds([path]), {MOD_A: 60.0})

    def test_a_log_without_timestamps_measures_nothing(self):
        path = self._write(f"{MOD_A}.TestA\n(12.50s)\nTests: 1\n")
        self.assertEqual(gtt.measured_elapsed_seconds([path]), {})


class TestSlowDurationsAreAllRead(unittest.TestCase):
    """frappe prints a duration of 100s or more in scientific notation: `(3.26e+02s)`."""

    def test_a_scientific_notation_duration_is_counted(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
        f.write(f"{MOD_A}.TestA\n   test_slow  (3.26e+02s)\n   test_fast  (2.50s)\nTests: 2\n")
        f.close()
        self.addCleanup(os.unlink, f.name)
        secs, count = gtt.measured_slow_seconds([f.name])
        self.assertEqual((round(secs[MOD_A], 2), count[MOD_A]), (328.5, 2))


class TestMainUsesRealElapsedTime(unittest.TestCase):
    """The table main() writes: the behaviour the shard layout actually consumes."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root))
        tests_dir = Path(self.root, "apps", "verenigingen", "verenigingen", "tests")
        tests_dir.mkdir(parents=True)
        # Ten quick test methods: the count-based allowance alone would give ~6.
        body = "".join(f"    def test_{i}(self):\n        pass\n" for i in range(10))
        (tests_dir / "test_alpha.py").write_text(f"class TestA:\n{body}")
        (tests_dir / "test_beta.py").write_text("class TestB:\n    def test_x(self):\n        pass\n")
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)

    def _run(self, log_text):
        log = Path(self.root, "shard.log")
        log.write_text(log_text)
        self.assertEqual(gtt.main([str(log)]), 0)
        return json.loads(Path(self.root, gtt.OUT).read_text())

    def test_setup_heavy_module_gets_its_real_time_not_its_printed_durations(self):
        # 800s spent in setUpClass: no test prints a duration, exactly the shard-5 case.
        weights = self._run(_log((0, f"{MOD_A}.TestA"), (800, f"{MOD_B}.TestB"), (805, "Tests: 11")))
        self.assertEqual(weights[MOD_A], 800)
        self.assertEqual(weights[MOD_B], 5)

    def test_without_timestamps_the_old_formula_still_applies(self):
        # Control: a log with no timestamps keeps the slow-seconds + count allowance.
        weights = self._run(f"{MOD_A}.TestA\n   test_0 (12.00s)\nTests: 10\n")
        self.assertEqual(weights[MOD_A], round(12.0 + gtt.FAST_TEST_COST * 9))


if __name__ == "__main__":
    unittest.main()
