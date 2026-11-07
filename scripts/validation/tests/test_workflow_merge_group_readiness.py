"""Merge-queue readiness of the workflows that own required checks (#2184).

Two things break silently when a merge queue is enabled on develop:

1. A workflow that owns a REQUIRED check but has no ``merge_group`` trigger
   never reports on a queue run, so every queued PR waits until it times out.
2. Every ``github.event_name`` / ``github.event.pull_request`` condition was
   written for a world with two events. A ``merge_group`` run is "not a
   pull_request", so ``!= 'pull_request'`` silently gives it push behaviour,
   ``== 'pull_request'`` silently skips the step, and
   ``github.event.pull_request.base.sha`` is silently empty.

So each such line in a queue workflow must either mention ``merge_group``
itself, or sit in a step/job that carries a ``# merge_group: <decision>``
comment saying what a queue run does there and why. A new event conditional
without a decision fails here instead of misbehaving on the first queue run.

Stdlib-only, like its siblings: line-based, no YAML parser needed.
"""

import re
import unittest
from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"

# Workflows owning a check in develop's required set ("Merge gates for default
# branch" ruleset, read 2026-11-07), plus server-tests.yml, whose Test Summary
# becomes required when the queue is enabled (#2184).
QUEUE_WORKFLOWS = ("ci.yml", "code-validation.yml", "quality-assurance.yml", "server-tests.yml")

_EVENT_CONDITIONAL = re.compile(r"github\.event_name|github\.event\.pull_request|github\.base_ref")
_DECISION = "# merge_group:"
# A step starts at a list item; a job starts at a two-space key. The decision
# comment must sit inside the same step or job as the conditional line.
_SCOPE_START = re.compile(r"^\s*- |^  [A-Za-z0-9_-]+:\s*$")


def undecided_lines(text: str) -> list[int]:
    """1-based line numbers of event conditionals with no merge_group decision."""
    lines = text.splitlines()
    missing = []
    for i, line in enumerate(lines):
        if not _EVENT_CONDITIONAL.search(line) or line.lstrip().startswith("#"):
            continue
        if "merge_group" in line:
            continue
        j = i - 1
        decided = False
        while j >= 0:
            if _DECISION in lines[j]:
                decided = True
                break
            if _SCOPE_START.match(lines[j]):
                break
            j -= 1
        if not decided:
            missing.append(i + 1)
    return missing


def triggers_on_merge_group(text: str) -> bool:
    return re.search(r"^  merge_group:", text, re.MULTILINE) is not None


class TestScannerControls(unittest.TestCase):
    """The scanner must be able to fail, or the real test below proves nothing."""

    def test_an_undecided_conditional_is_flagged(self):
        text = "    - name: Step\n      if: github.event_name == 'pull_request'\n"
        self.assertEqual(undecided_lines(text), [2])

    def test_a_decision_comment_in_the_same_step_clears_it(self):
        text = (
            "    - name: Step\n"
            "      # merge_group: skipped, it only comments on the PR\n"
            "      if: github.event_name == 'pull_request'\n"
        )
        self.assertEqual(undecided_lines(text), [])

    def test_a_decision_comment_in_the_previous_step_does_not_count(self):
        text = (
            "    - name: Earlier\n"
            "      # merge_group: decided for THIS step only\n"
            "      run: true\n"
            "    - name: Later\n"
            "      if: github.event_name == 'pull_request'\n"
        )
        self.assertEqual(undecided_lines(text), [5])

    def test_a_line_naming_merge_group_is_decided(self):
        text = "      BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}\n"
        self.assertEqual(undecided_lines(text), [])

    def test_trigger_detection_needs_a_top_level_on_key(self):
        self.assertTrue(triggers_on_merge_group("on:\n  merge_group:\n    types: [checks_requested]\n"))
        self.assertFalse(triggers_on_merge_group("on:\n  push:\n# merge_group: later\n"))


class TestQueueWorkflowsAreReady(unittest.TestCase):
    def test_every_queue_workflow_triggers_on_merge_group(self):
        missing = [w for w in QUEUE_WORKFLOWS if not triggers_on_merge_group((_WORKFLOWS / w).read_text())]
        self.assertEqual(missing, [], "these own required checks but would never report on a queue run")

    def test_every_event_conditional_has_a_merge_group_decision(self):
        report = {}
        for name in QUEUE_WORKFLOWS:
            found = undecided_lines((_WORKFLOWS / name).read_text())
            if found:
                report[name] = found
        self.assertEqual(
            report,
            {},
            "event conditionals with no merge_group decision (handle merge_group in the line, "
            f"or add a '{_DECISION} <what a queue run does here>' comment in the same step/job)",
        )


if __name__ == "__main__":
    unittest.main()
