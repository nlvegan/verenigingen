"""The field-reference validator must be able to fail CI (#2190).

``enhanced_field_reference_validator.py`` ran twice in ``code-validation.yml`` and
both runs ended in ``|| echo "Field validation completed with issues"``, which turns
any exit code into 0. One run is the REQUIRED check ``fast-validation``, so a
finding could never turn it red and its PR comment always said "all valid".

Stdlib-only, line-based (no YAML parser), like its siblings.
"""

import re
import unittest
from pathlib import Path

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "code-validation.yml"
_VALIDATOR = "enhanced_field_reference_validator.py"
_SWALLOW = re.compile(
    r"\|\|\s*(echo\b|(/bin/)?true\b|:|exit\s+0\b|\(\s*exit\s+0\s*\))"
    r"|;\s*(true|exit\s+0)\b|\bset \+e\b"
)
_STEP_START = re.compile(r"^\s*-\s+name:")
_JOB_START = re.compile(r"^  [A-Za-z0-9_-]+:\s*(#.*)?$")


def steps_running(text: str, needle: str) -> list[tuple[str, str]]:
    """Return (job, step_text) for every step whose block mentions ``needle``.

    Comment-only lines are dropped from a block before matching (#2400); a ``#`` inside
    a code line (a quoted argument, a trailing comment) is left alone.
    """
    out, job, step = [], None, []
    lines = text.splitlines() + ["  __end__:"]
    for line in lines:
        boundary = _STEP_START.match(line) or _JOB_START.match(line)
        if boundary and step:
            # A comment-only line is prose, and one above the next `- name:` would otherwise
            # land in THIS step's block (#2400). Trailing comments on a code line are kept.
            block = "\n".join(ln for ln in step if not ln.lstrip().startswith("#"))
            if needle in block:
                out.append((job, block))
            step = []
        if _JOB_START.match(line):
            job = line.strip().rstrip(":")
        elif _STEP_START.match(line) or step:
            step.append(line)
    return out


class FieldValidatorCanFailCITests(unittest.TestCase):
    def setUp(self):
        self.steps = steps_running(_WORKFLOW.read_text(), _VALIDATOR)

    def test_the_scan_finds_both_runs(self):
        # Control: a scan that finds nothing would pass every test below.
        self.assertEqual(
            sorted(job for job, _ in self.steps), sorted(["validation", "fast-validation"]),
            self.steps,
        )

    def test_no_run_swallows_the_exit_code(self):
        for job, block in self.steps:
            with self.subTest(job=job):
                self.assertIsNone(_SWALLOW.search(block), block)

    def test_the_required_fast_validation_step_is_not_continue_on_error(self):
        (block,) = [b for j, b in self.steps if j == "fast-validation"]
        self.assertNotIn("continue-on-error", block)

    def test_the_pr_comment_reads_the_real_step_outcome(self):
        text = _WORKFLOW.read_text()
        (block,) = [b for j, b in self.steps if j == "fast-validation"]
        step_id = re.search(r"^\s*id:\s*(\S+)", block, re.M).group(1)
        job_text = text[text.index("  fast-validation:"):]
        self.assertIn("steps.%s.outcome" % step_id, job_text)

    def test_the_swallow_detector_can_fire(self):
        # Control for the regex itself.
        self.assertTrue(_SWALLOW.search('python x.py || echo "completed with issues"'))
        for swallow in ("|| true", "|| :", "|| exit 0", "|| (exit 0)", "|| /bin/true", "; exit 0"):
            with self.subTest(swallow=swallow):
                self.assertTrue(_SWALLOW.search("python x.py " + swallow))
        self.assertFalse(_SWALLOW.search("python x.py --pre-commit"))


class StepsRunningCommentAttributionTests(unittest.TestCase):
    """#2400: a comment above a step belongs to no step, least of all the one before it."""

    _WORKFLOW = (
        "jobs:\n"
        "  validation:\n"
        "    steps:\n"
        "    - name: Earlier\n"
        "      run: python earlier.py\n"
        "      continue-on-error: true\n"
        "\n"
        "    # note: never add `|| echo` here, it hides the exit code\n"
        "    - name: Later\n"
        "      run: python later.py\n"
    )

    def test_a_comment_above_a_step_is_not_attributed_to_the_previous_step(self):
        (job, block), = steps_running(self._WORKFLOW, "python earlier.py")
        self.assertEqual(job, "validation")
        self.assertIsNone(_SWALLOW.search(block), block)

    def test_a_comment_naming_the_needle_does_not_make_a_step_match(self):
        self.assertEqual(steps_running(self._WORKFLOW, "never add"), [])

    def test_a_real_swallow_inside_the_step_is_still_found(self):
        # Control: stripping comments must not blind the scan to a real `|| echo`.
        text = self._WORKFLOW.replace(
            "python earlier.py\n", 'python earlier.py || echo "done"  # tolerated\n'
        )
        (_, block), = steps_running(text, "python earlier.py")
        self.assertIsNotNone(_SWALLOW.search(block), block)

    def test_a_swallow_on_a_line_after_a_comment_inside_the_step_is_still_found(self):
        text = self._WORKFLOW.replace(
            "      run: python earlier.py\n",
            "      run: |\n        # explain\n        python earlier.py || true\n",
        )
        (_, block), = steps_running(text, "python earlier.py")
        self.assertIsNotNone(_SWALLOW.search(block), block)

    def test_a_hash_inside_a_quoted_argument_does_not_hide_a_later_swallow(self):
        # Control against a "strip # to end of line" fix, which would eat the swallow.
        text = self._WORKFLOW.replace(
            "      run: python earlier.py\n", '      run: python earlier.py "a#b" || true\n'
        )
        (_, block), = steps_running(text, "python earlier.py")
        self.assertIsNotNone(_SWALLOW.search(block), block)


if __name__ == "__main__":
    unittest.main()
