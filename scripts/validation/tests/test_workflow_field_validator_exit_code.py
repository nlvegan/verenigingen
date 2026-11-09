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
    """Return (job, step_text) for every step whose block mentions ``needle``."""
    out, job, step = [], None, []
    lines = text.splitlines() + ["  __end__:"]
    for line in lines:
        boundary = _STEP_START.match(line) or _JOB_START.match(line)
        if boundary and step:
            block = "\n".join(step)
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


if __name__ == "__main__":
    unittest.main()
