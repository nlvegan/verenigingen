#!/usr/bin/env python3
"""Unit tests for scripts/testing/summarise_chaos_result.py.

Pure-Python. This exists as a script rather than shell-with-embedded-python inside
chaos-shards.yml because the embedded version cannot be tested, and a summary step that
silently produces nothing is indistinguishable from a run that found nothing -- the
exact confusion the chaos job exists to remove.

Run with:  python -m pytest this_file.py
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "summarise_chaos_result.py"
_spec = importlib.util.spec_from_file_location("summarise_chaos_result", _MOD_PATH)
scr = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scr
_spec.loader.exec_module(scr)


def _result(**overrides):
    data = {
        "site": "test_site",
        "tests_run": 1464,
        "failures": [],
        "errors": [],
        "n_failures": 0,
        "n_errors": 0,
        "ok": True,
    }
    data.update(overrides)
    return data


class RenderTest(unittest.TestCase):
    def test_it_reports_the_counts(self):
        out = scr.render(_result())
        self.assertIn("1464", out)

    def test_a_clean_shard_says_so_explicitly(self):
        """Silence would read as "the summary broke", not "nothing was found"."""
        out = scr.render(_result())
        self.assertIn("No failures under this layout", out)

    def test_it_names_each_failing_test(self):
        out = scr.render(
            _result(failures=["a.b.C.test_one", "a.b.C.test_two"], n_failures=2, ok=False)
        )
        self.assertIn("a.b.C.test_one", out)
        self.assertIn("a.b.C.test_two", out)

    def test_errors_are_listed_as_well_as_failures(self):
        """An error is a finding too -- most order-dependence surfaces in setUp."""
        out = scr.render(_result(errors=["a.b.C.test_boom"], n_errors=1, ok=False))
        self.assertIn("a.b.C.test_boom", out)

    def test_a_long_list_is_truncated_with_the_remainder_stated(self):
        """A whole shard can fail; 300 bullets would bury the summary."""
        names = [f"a.b.C.test_{i:03}" for i in range(60)]
        out = scr.render(_result(failures=names, n_failures=60, ok=False))
        self.assertIn("a.b.C.test_000", out)
        self.assertNotIn("a.b.C.test_059", out)
        self.assertIn("20 more", out)

    def test_missing_counts_do_not_crash_it(self):
        """The detector's JSON shape is not this script's to guarantee."""
        out = scr.render({"failures": ["x.y.Z.test_a"]})
        self.assertIn("x.y.Z.test_a", out)


class MainTest(unittest.TestCase):
    def test_it_reads_the_file_and_prints(self):
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "r.json"
            path.write_text(json.dumps(_result(failures=["a.b.C.test_x"], n_failures=1)))
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = scr.main([str(path)])
        self.assertEqual(0, rc)
        self.assertIn("a.b.C.test_x", buf.getvalue())

    def test_a_missing_file_reports_instead_of_raising(self):
        """The shard may have died before writing it; the summary still has to render."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = scr.main(["/nonexistent/chaos.json"])
        self.assertEqual(0, rc)
        self.assertIn("did not finish", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
