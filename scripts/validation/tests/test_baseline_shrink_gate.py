#!/usr/bin/env python3
"""Unit tests for scripts/validation/baseline_shrink_gate.py.

Stdlib-only plus real `git` invocations against throwaway temp repos -- same
shape as test_bench_resolution.py, and for the same reason: this runs in the
Code Validation workflow's stdlib-only job, no bench or site needed.

Every positive case pairs with a control: a pure shrink that self-heals is
tested alongside a genuine addition that must still fail (the direction the
whole ratchet exists to catch), so a change that broke growth-detection
while "fixing" shrink-detection would be caught here too.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "baseline_shrink_gate.py"
_spec = importlib.util.spec_from_file_location("baseline_shrink_gate", _MOD_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gate
_spec.loader.exec_module(gate)


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30
    )


class TestParseBaseline(unittest.TestCase):
    def test_path_qualname_count(self):
        text = "scripts/a.py::Foo.bar::2\nscripts/b.py::baz::1\n"
        self.assertEqual(
            gate.parse_baseline(text),
            {"scripts/a.py::Foo.bar": 2, "scripts/b.py::baz": 1},
        )

    def test_path_qualname_reason_count(self):
        """test_quality_baseline.txt's 4-segment key -- rpartition still isolates the count."""
        text = "verenigingen/tests/test_x.py::Test.test_y::PERMISSION BYPASS::3\n"
        self.assertEqual(
            gate.parse_baseline(text),
            {"verenigingen/tests/test_x.py::Test.test_y::PERMISSION BYPASS": 3},
        )

    def test_count_with_trailing_comment(self):
        """duplicate_helper_baseline.txt's `N  # clone family, ...` shape."""
        text = "_account::3  # clone family, 33% of pairs near-identical\n"
        self.assertEqual(gate.parse_baseline(text), {"_account": 3})

    def test_trailing_comment_containing_its_own_double_colon(self):
        """A marker that itself contains '::' must not be swallowed into the key.

        duplicate_helper_validator.load_baseline strips the comment BEFORE
        rpartition-ing on '::' for exactly this reason -- an earlier version of
        this parser matched only leading digits on the raw tail, which would
        misparse this into {"_account::3  # see a::b": 5}.
        """
        text = "_account::3  # clone family, see a::b::5 for detail\n"
        self.assertEqual(gate.parse_baseline(text), {"_account": 3})

    def test_comments_and_blank_lines_ignored(self):
        text = "# a header comment\n\nfoo::1\n"
        self.assertEqual(gate.parse_baseline(text), {"foo": 1})

    def test_line_with_no_separator_is_skipped(self):
        self.assertEqual(gate.parse_baseline("not-a-baseline-line\n"), {})


class TestRealBaselinesAreFullyParsed(unittest.TestCase):
    """The four baselines actually wired to this gate must parse COMPLETELY.

    A silent partial parse is exactly the shape that made the gate blind to
    growth (see main()'s coverage check) -- this pins the four real files so a
    future baseline-format change is caught here, at low cost, rather than by
    the gate quietly passing on a PR that changed the format AND added a site.
    """

    WIRED_BASELINES = (
        "error_swallow_baseline.txt",
        "log_error_arg_order_baseline.txt",
        "test_quality_baseline.txt",
        "duplicate_helper_baseline.txt",
    )

    def test_every_data_line_parses(self):
        val_dir = Path(__file__).resolve().parents[1]
        for name in self.WIRED_BASELINES:
            path = val_dir / name
            text = path.read_text(encoding="utf-8")
            lines = gate.data_lines(text)
            covered = sum(1 for line in lines if gate._parse_line(line) is not None)
            with self.subTest(baseline=name):
                self.assertEqual(
                    covered, len(lines),
                    f"{name}: only {covered} of {len(lines)} data lines parsed as "
                    f"'<key>::<count>' -- the gate would refuse to run on this file.",
                )
                self.assertGreater(len(lines), 0, f"{name}: no data lines found at all")

    def test_harness_logger_teardown_baseline_is_NOT_wired_and_does_not_parse(self):
        """Confirms the deliberate exclusion: this format is aggregate prose
        ("teardowns 11", "calls 19", ...), not <key>::<count>, so wiring it to
        this gate would silently parse to {} and always self-heal -- exactly
        the C2 shape. It must stay unwired; see code-validation.yml.
        """
        val_dir = Path(__file__).resolve().parents[1]
        text = (val_dir / "harness_logger_teardown_baseline.txt").read_text(encoding="utf-8")
        self.assertEqual(gate.parse_baseline(text), {})


class TestClassify(unittest.TestCase):
    def test_pure_shrink_removed_key(self):
        grown, appeared, shrunk = gate.classify({"a": 1, "b": 2}, {"a": 1})
        self.assertEqual(grown, {})
        self.assertEqual(appeared, {})
        self.assertEqual(shrunk, {"b": (2, 0)})

    def test_pure_shrink_lower_count(self):
        grown, appeared, shrunk = gate.classify({"a": 3}, {"a": 1})
        self.assertEqual(grown, {})
        self.assertEqual(appeared, {})
        self.assertEqual(shrunk, {"a": (3, 1)})

    def test_growth_new_key(self):
        grown, appeared, shrunk = gate.classify({"a": 1}, {"a": 1, "b": 1})
        self.assertEqual(appeared, {"b": 1})
        self.assertEqual(grown, {})
        self.assertEqual(shrunk, {})

    def test_growth_higher_count(self):
        grown, appeared, shrunk = gate.classify({"a": 1}, {"a": 2})
        self.assertEqual(grown, {"a": (1, 2)})
        self.assertEqual(appeared, {})
        self.assertEqual(shrunk, {})

    def test_mixed_shrink_and_growth_both_reported(self):
        grown, appeared, shrunk = gate.classify({"a": 1, "b": 2}, {"a": 2})
        self.assertEqual(grown, {"a": (1, 2)})
        self.assertEqual(appeared, {})
        self.assertEqual(shrunk, {"b": (2, 0)})


class TestGateEndToEnd(unittest.TestCase):
    """Exercises main() directly (in-process) against a real committed baseline,
    then a real `git show` -- the one piece parse_baseline()/classify() alone
    cannot cover.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git("init", "-q", cwd=self.repo)
        _git("config", "user.email", "t@example.com", cwd=self.repo)
        _git("config", "user.name", "t", cwd=self.repo)
        self.baseline = self.repo / "some_baseline.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, text: str):
        self.baseline.write_text(text, encoding="utf-8")
        _git("add", "some_baseline.txt", cwd=self.repo)
        r = _git("commit", "-q", "-m", "baseline", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def _run_gate(self, *extra_args):
        return subprocess.run(
            [sys.executable, str(_MOD_PATH), str(self.baseline), "regen-cmd --update-baseline", *extra_args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_unchanged_baseline_passes(self):
        self._commit("a.py::foo::1\nb.py::bar::1\n")
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("matches the tree", result.stdout)

    def test_pure_deletion_self_heals(self):
        """The #750 shape: a baselined site's function was deleted entirely."""
        self._commit("a.py::foo::1\nb.py::bar::1\n")
        self.baseline.write_text("a.py::foo::1\n", encoding="utf-8")  # b.py::bar deleted
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("self-healing", result.stdout)
        self.assertIn("b.py::bar", result.stdout)

    def test_fail_on_shrink_flag_fails_pure_shrink_instead_of_healing(self):
        """The `push` CI shape (see code-validation.yml): a pure shrink still
        fails, but with the exact entries and command -- option (b), not a
        silent pass -- because nothing downstream is blocked by this failure
        and it is the only thing left that forces the baseline to tighten."""
        self._commit("a.py::foo::1\nb.py::bar::1\n")
        self.baseline.write_text("a.py::foo::1\n", encoding="utf-8")  # b.py::bar deleted
        result = self._run_gate("--fail-on-shrink")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("self-healing", result.stdout)
        self.assertIn("b.py::bar", result.stdout)
        self.assertIn("regen-cmd --update-baseline", result.stdout)

    def test_fail_on_shrink_flag_does_not_change_growth_handling(self):
        """The flag only changes the SHRINK branch -- growth still fails
        exactly as it does without the flag (this is not a "make everything
        stricter" switch)."""
        self._commit("a.py::foo::1\n")
        self.baseline.write_text("a.py::foo::1\nc.py::new_bad::1\n", encoding="utf-8")
        with_flag = self._run_gate("--fail-on-shrink")
        without_flag = self._run_gate()
        self.assertEqual(with_flag.returncode, 1, with_flag.stdout)
        self.assertEqual(without_flag.returncode, 1, without_flag.stdout)
        self.assertEqual(with_flag.stdout, without_flag.stdout)

    def test_pure_count_reduction_self_heals(self):
        self._commit("a.py::foo::3\n")
        self.baseline.write_text("a.py::foo::1\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("self-healing", result.stdout)
        self.assertIn("a.py::foo  (3 -> 1)", result.stdout)

    def test_new_site_fails(self):
        """Control: growth must still redden the build."""
        self._commit("a.py::foo::1\n")
        self.baseline.write_text("a.py::foo::1\nc.py::new_bad::1\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("out of sync", result.stdout)
        self.assertIn("c.py::new_bad", result.stdout)
        self.assertIn("regen-cmd --update-baseline", result.stdout)

    def test_higher_count_fails(self):
        """Control: an existing site's count rising must still redden the build."""
        self._commit("a.py::foo::1\n")
        self.baseline.write_text("a.py::foo::2\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("a.py::foo::1 -> a.py::foo::2", result.stdout)

    def test_mixed_growth_and_shrink_fails(self):
        """One key shrinking must not mask another key growing."""
        self._commit("a.py::foo::1\nb.py::bar::1\n")
        self.baseline.write_text("a.py::foo::2\n", encoding="utf-8")  # bar gone, foo grew
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        # The shrunk side is worth reporting too, so a reviewer of a mixed change
        # (some sites fixed, one added) doesn't have to re-derive it from the diff.
        self.assertIn("b.py::bar", result.stdout)

    def test_wipe_to_empty_does_not_self_heal(self):
        """A validator that silently found nothing must not be trusted."""
        self._commit("a.py::foo::1\nb.py::bar::1\n")
        self.baseline.write_text("", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("EMPTY", result.stdout)

    def test_no_committed_copy_is_not_an_error(self):
        # No commit at all -- HEAD is unborn, so `git show HEAD:...` cannot
        # resolve anything, but `git rev-parse --show-toplevel` still can
        # (it needs no commits) -- this must not be confused with the
        # toplevel-resolution failure, which IS a hard error.
        self.baseline.write_text("a.py::foo::1\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_baseline_new_in_this_change_is_not_an_error(self):
        """HEAD exists (an unrelated file was committed) but this baseline
        path never appeared in any past commit -- a different code path from
        "no commits at all" (HEAD is unborn there)."""
        (self.repo / "unrelated.txt").write_text("x", encoding="utf-8")
        _git("add", "unrelated.txt", cwd=self.repo)
        r = _git("commit", "-q", "-m", "unrelated", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.baseline.write_text("a.py::foo::1\n", encoding="utf-8")  # never committed
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unresolvable_toplevel_is_a_hard_error(self):
        """Not a git repo at all is a different, harder failure than 'file is
        new' -- self-healing THAT would risk silently accepting anything."""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as not_a_repo:
            baseline = Path(not_a_repo) / "some_baseline.txt"
            baseline.write_text("a.py::foo::1\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(_MOD_PATH), str(baseline), "regen-cmd"],
                cwd=not_a_repo, capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_non_shrink_non_growth_drift_fails(self):
        """A header/comment-only edit is not shrinkage -- must not self-heal."""
        self._commit("# a header comment\na.py::foo::1\n")
        self.baseline.write_text("# a DIFFERENT header comment\na.py::foo::1\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("self-healing", result.stdout)

    def test_duplicate_helper_style_percentage_only_change_fails(self):
        """The recomputed clone-share percentage changing with no count change
        is real drift (S2): not shrinkage, must not silently self-heal."""
        self._commit("_account::3  # clone family, 33% of pairs near-identical\n")
        self.baseline.write_text(
            "_account::3  # clone family, 67% of pairs near-identical\n", encoding="utf-8"
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("self-healing", result.stdout)

    def test_totally_unparseable_baseline_on_both_sides_is_a_hard_error(self):
        """If neither side parses as <key>::<count> (e.g. the aggregate
        harness_logger_teardown shape, or any future format this gate is not
        wired for), classify() sees no changed keys at all. Caught by the
        non-shrink/non-growth drift guard (S2) either way, but this pins the
        specific "Cannot parse" message so the two failure reasons stay
        distinguishable to a reader.
        """
        self._commit("teardowns 11\ncalls 19\n")
        self.baseline.write_text("teardowns 99\ncalls 42\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Cannot parse", result.stdout)
        self.assertNotIn("self-healing", result.stdout)

    def test_partial_parse_does_not_mask_growth_behind_a_real_shrink(self):
        """C2's actual target: a real shrink in a parseable key alongside
        GROWTH hidden in a line that fails to parse. `classify()` alone would
        see only the shrink (the growth is invisible to it) and self-heal --
        the coverage guard must refuse before classify() is trusted at all.
        This is NOT redundant with the "totally unparseable" case above: there
        every dict is empty and the non-shrink/non-growth guard (S2) already
        catches it; here `shrunk` is genuinely non-empty, so S2 does not fire,
        and only the coverage guard stands between this and a false self-heal.
        """
        self._commit("a.py::foo::5\nteardowns 11\n")
        # foo genuinely shrank 5 -> 1; "teardowns" silently grew 11 -> 99,
        # invisible to parse_baseline because it never matches <key>::<count>.
        self.baseline.write_text("a.py::foo::1\nteardowns 99\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Cannot parse", result.stdout)
        self.assertNotIn("self-healing", result.stdout)


class TestRequireMarker(unittest.TestCase):
    """#769: duplicate_helper_baseline.txt mixes marked (`# clone family`,
    genuinely near-identical) and unmarked (name collision only, advisory)
    entries. Before `--require-marker`, this gate diffed the whole file, so an
    unmarked count going up looked exactly like a marked one and failed the
    build the same way -- forcing a rename to dodge the diff, even though the
    validator's own `--report` called the collision a coincidence. Every
    positive case here pairs with a control that a REAL clone-family growth
    still fails with the flag active, so a change that widened the exemption
    too far would be caught here too.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git("init", "-q", cwd=self.repo)
        _git("config", "user.email", "t@example.com", cwd=self.repo)
        _git("config", "user.name", "t", cwd=self.repo)
        self.baseline = self.repo / "some_baseline.txt"

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, text: str):
        self.baseline.write_text(text, encoding="utf-8")
        _git("add", "some_baseline.txt", cwd=self.repo)
        r = _git("commit", "-q", "-m", "baseline", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def _run_gate(self, *extra_args):
        return subprocess.run(
            [sys.executable, str(_MOD_PATH), str(self.baseline), "regen-cmd --update-baseline", *extra_args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_unmarked_count_growth_is_ignored(self):
        """The #769 shape exactly: `_row::6 -> _row::7`, no marker."""
        self._commit("_row::6\n_persist::2  # clone family, 100% of pairs near-identical\n")
        self.baseline.write_text(
            "_row::7\n_persist::2  # clone family, 100% of pairs near-identical\n",
            encoding="utf-8",
        )
        result = self._run_gate("--require-marker", "# clone family")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("matches the tree", result.stdout)

    def test_marked_count_growth_still_fails(self):
        """Control: a real clone-family copy landing alongside the unmarked
        growth above must still redden the build, and the message must name
        only the marked entry -- not the unmarked one riding along with it."""
        self._commit("_row::6\n_persist::2  # clone family, 100% of pairs near-identical\n")
        self.baseline.write_text(
            "_row::7\n_persist::3  # clone family, 100% of pairs near-identical\n",
            encoding="utf-8",
        )
        result = self._run_gate("--require-marker", "# clone family")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("_persist", result.stdout)
        self.assertNotIn("_row", result.stdout)

    def test_new_unmarked_key_is_ignored(self):
        self._commit("_persist::2  # clone family, 100% of pairs near-identical\n")
        self.baseline.write_text(
            "_persist::2  # clone family, 100% of pairs near-identical\n_new_collision::2\n",
            encoding="utf-8",
        )
        result = self._run_gate("--require-marker", "# clone family")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_marked_key_still_fails(self):
        """Control for the case above: a brand-new MARKED family must still fail."""
        self._commit("_persist::2  # clone family, 100% of pairs near-identical\n")
        self.baseline.write_text(
            "_persist::2  # clone family, 100% of pairs near-identical\n"
            "_new_clone::2  # clone family, 100% of pairs near-identical\n",
            encoding="utf-8",
        )
        result = self._run_gate("--require-marker", "# clone family")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("_new_clone", result.stdout)

    def test_percentage_only_change_on_a_marked_line_still_fails(self):
        """Drift WITHIN the marked subset (the existing S2 shape) must not be
        widened into a false pass just because scoping was added."""
        self._commit("_account::3  # clone family, 33% of pairs near-identical\n")
        self.baseline.write_text(
            "_account::3  # clone family, 67% of pairs near-identical\n", encoding="utf-8"
        )
        result = self._run_gate("--require-marker", "# clone family")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("self-healing", result.stdout)

    def test_marked_shrink_self_heals_while_unmarked_growth_is_ignored(self):
        """A mixed change: a clone family consolidated away (marked, shrunk),
        a DIFFERENT clone family untouched (marked, unchanged -- keeps the
        filtered census non-empty so this does not trip the separate "scan
        found nothing" guard tested elsewhere), and a coincidental name
        collision growing a lot (unmarked). Only the marked shrink may appear
        in the outcome."""
        self._commit(
            "_account::3  # clone family, 33% of pairs near-identical\n"
            "_other::2  # clone family, 100% of pairs near-identical\n"
            "_row::6\n"
        )
        self.baseline.write_text(
            "_other::2  # clone family, 100% of pairs near-identical\n_row::99\n",
            encoding="utf-8",
        )
        result = self._run_gate("--require-marker", "# clone family")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("self-healing", result.stdout)
        self.assertIn("_account", result.stdout)
        self.assertNotIn("_row", result.stdout)

    def test_fail_on_shrink_flag_still_applies_within_the_marked_scope(self):
        self._commit(
            "_account::3  # clone family, 33% of pairs near-identical\n"
            "_other::2  # clone family, 100% of pairs near-identical\n"
            "_row::6\n"
        )
        self.baseline.write_text(
            "_other::2  # clone family, 100% of pairs near-identical\n_row::99\n",
            encoding="utf-8",
        )
        result = self._run_gate("--require-marker", "# clone family", "--fail-on-shrink")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("self-healing", result.stdout)
        self.assertIn("_account", result.stdout)
        self.assertNotIn("_row", result.stdout)

    def test_without_the_flag_unmarked_growth_still_fails_as_before(self):
        """Confirms the flag is opt-in: the other three callers of this gate
        pass nothing for it, and must keep failing on ANY growth exactly as
        they did before this change."""
        self._commit("_row::6\n")
        self.baseline.write_text("_row::7\n", encoding="utf-8")
        result = self._run_gate()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("_row::6 -> _row::7", result.stdout)


if __name__ == "__main__":
    unittest.main()
