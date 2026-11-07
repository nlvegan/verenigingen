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

# The PR- and ref-dependent context these workflows read: expressions, the runner's env
# vars, and actions/github-script's `context`. Each is empty, absent or different on a
# merge_group run (whose ref is gh-readonly-queue/...). NOT exhaustive: expressions split
# across lines, toJSON(github.event) and github['head_ref'] are not matched.
_EVENT_CONDITIONAL = re.compile(
    r"github\.(event_name|head_ref|base_ref|event\.(number|pull_request|issue))"
    r"|github\.ref(_name)?\b"
    r"|GITHUB_(BASE_REF|HEAD_REF|EVENT_NAME|REF)\b"
    r"|context\.(issue|payload)"
)
_DECISION = "# merge_group:"
# A step starts at a list item opening with a step key; a job starts at a two-space
# key (a trailing comment allowed). The decision comment must sit inside the same
# step or job as the conditional line. A bare `- ` is NOT a boundary: Markdown
# bullets inside a run/script block would otherwise end the step early.
_SCOPE_START = re.compile(r"^\s*-\s+[A-Za-z_][A-Za-z0-9_-]*:|^  [A-Za-z0-9_-]+:\s*(#.*)?$")


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


def queue_trigger_is_unfiltered(text: str) -> bool:
    """True when the merge_group trigger block has no paths/branches filter of any kind."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if re.match(r"^  merge_group:", line))
    except StopIteration:
        return False
    if not re.match(r"^  merge_group:\s*(#.*)?$", lines[start]):
        return False  # flow mapping or inline value: not inspected, so not accepted
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^\S|^  \S", line):  # next trigger or top-level key ends the block
            break
        if re.match(r"^\s+(paths|paths-ignore|branches|branches-ignore):", line):
            return False
    return True


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

    def test_every_form_of_pr_context_is_flagged(self):
        # Each of these is PR-only context that is empty or absent on a merge_group run.
        forms = [
            "github.event_name == 'pull_request'",
            "github.event.pull_request.base.sha",
            "github.base_ref",
            "github.head_ref",
            "github.event.number",
            "github.event.issue.number",
            "$GITHUB_BASE_REF",
            "$GITHUB_HEAD_REF",
            "$GITHUB_EVENT_NAME",
            "context.issue.number",
            "context.payload.pull_request",
        ]
        for form in forms:
            with self.subTest(form=form):
                self.assertEqual(undecided_lines(f"    - name: Step\n      run: echo {form}\n"), [2])

    def test_a_queue_trigger_with_a_path_filter_is_not_ready(self):
        # A path-skipped workflow reports nothing, and the queue waits on every required check.
        text = "on:\n  merge_group:\n    types: [checks_requested]\n    paths:\n      - 'x/**'\n  push:\n"
        self.assertFalse(queue_trigger_is_unfiltered(text))
        self.assertTrue(queue_trigger_is_unfiltered("on:\n  merge_group:\n    types: [checks_requested]\n  push:\n"))

    def test_a_markdown_bullet_inside_a_script_does_not_end_the_step(self):
        # quality-assurance.yml's PR comment builds a Markdown list inside github-script.
        text = (
            "      - name: Comment\n"
            "        # merge_group: skipped, it only comments on the PR\n"
            "        with:\n"
            "          script: |\n"
            "            - **Coverage**: done\n"
            "              issue_number: context.issue.number,\n"
        )
        self.assertEqual(undecided_lines(text), [])

    def test_ref_based_conditions_are_flagged(self):
        # A queue run's ref is gh-readonly-queue/..., so `github.ref == 'refs/heads/develop'` is false.
        for form in ("github.ref == 'refs/heads/develop'", "github.ref_name", "$GITHUB_REF"):
            with self.subTest(form=form):
                self.assertEqual(undecided_lines(f"    - name: Step\n      run: echo {form}\n"), [2])

    def test_a_decision_in_one_job_does_not_cover_the_next_job(self):
        text = (
            "  first:\n"
            "    steps:\n"
            "      - name: Step\n"
            "        # merge_group: decided for this step only\n"
            "        run: true\n"
            "  second:\n"
            "    if: github.event_name == 'push'\n"
        )
        self.assertEqual(undecided_lines(text), [7])

    def test_a_step_starting_with_any_key_ends_the_previous_step(self):
        for key in ("uses", "run", "python"):
            with self.subTest(key=key):
                text = (
                    "      - name: Earlier\n"
                    "        # merge_group: decided for THIS step only\n"
                    f"      - {key}: x\n"
                    "        if: github.event_name == 'pull_request'\n"
                )
                self.assertEqual(undecided_lines(text), [4])

    def test_a_comment_that_mentions_pr_context_is_not_a_conditional(self):
        self.assertEqual(undecided_lines("      # compares github.event_name with push\n"), [])

    def test_prose_mentioning_merge_group_is_not_a_decision(self):
        text = (
            "    - name: Step\n"
            "      # this predates merge_group support\n"
            "      if: github.event_name == 'pull_request'\n"
        )
        self.assertEqual(undecided_lines(text), [3])

    def test_every_filter_kind_under_the_queue_trigger_is_caught(self):
        for key in ("paths", "paths-ignore", "branches", "branches-ignore"):
            with self.subTest(key=key):
                text = f"on:\n  merge_group:\n    types: [checks_requested]\n    {key}:\n      - x\n"
                self.assertFalse(queue_trigger_is_unfiltered(text))

    def test_a_comment_inside_the_trigger_block_does_not_hide_a_filter(self):
        text = "on:\n  merge_group:\n    types: [checks_requested]\n  # why\n    paths: [x]\n  push:\n"
        self.assertFalse(queue_trigger_is_unfiltered(text))

    def test_a_flow_mapping_trigger_is_not_accepted_as_unfiltered(self):
        text = "on:\n  merge_group: {types: [checks_requested], paths: ['x']}\n"
        self.assertFalse(queue_trigger_is_unfiltered(text))

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

    def test_no_queue_trigger_carries_a_path_or_branch_filter(self):
        filtered = [w for w in QUEUE_WORKFLOWS if not queue_trigger_is_unfiltered((_WORKFLOWS / w).read_text())]
        self.assertEqual(filtered, [], "a filtered merge_group trigger can leave a required check unreported")

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



def _on_block(text: str) -> list[str]:
    """The lines of the top-level `on:` block (comments dropped)."""
    lines = text.splitlines()
    start = lines.index("on:")
    block = []
    for line in lines[start + 1 :]:
        if re.match(r"^\S", line):
            break
        if line.strip() and not line.lstrip().startswith("#"):
            block.append(line)
    return block


def _job_field(text: str, job: str, field: str) -> str:
    """A scalar field (`if`, `name`, `needs`, ...) of a top-level job, or "" if absent."""
    lines = text.splitlines()
    i = lines.index(f"  {job}:")
    for line in lines[i + 1 :]:
        if re.match(r"^  \S", line):
            break
        m = re.match(rf"^    {re.escape(field)}:\s*(.*)$", line)
        if m:
            return m.group(1).strip()
    return ""


def _job_if(text: str, job: str) -> str:
    """The `if:` expression of a top-level job, or "" if it has none."""
    return _job_field(text, job, "if")


class TestServerTestsRunsTheSuiteOnlyInTheQueue(unittest.TestCase):
    """#2184's flip: the 12-shard suite (~300 job-min) runs once per queue batch, not per push.

    Safe only while develop's merge queue requires `Test Summary` (set 2026-11-07): the PR
    must still REPORT it, the queue must run the suite, and nothing may skip the workflow.
    """

    def setUp(self):
        self.text = (_WORKFLOWS / "server-tests.yml").read_text()

    def test_no_trigger_carries_a_path_filter(self):
        # A path-skipped workflow reports nothing, and Test Summary is required on the PR.
        self.assertEqual([l for l in _on_block(self.text) if re.match(r"^\s+paths(-ignore)?:", l)], [])

    def test_it_still_triggers_on_pull_request_and_merge_group(self):
        triggers = {l.strip().rstrip(":") for l in _on_block(self.text) if re.match(r"^  \S", l)}
        self.assertLessEqual({"pull_request", "merge_group"}, triggers)

    def test_a_develop_push_does_not_rerun_the_suite(self):
        # The queue already ran it on the exact tree that lands.
        triggers = {l.strip().rstrip(":") for l in _on_block(self.text) if re.match(r"^  \S", l)}
        self.assertNotIn("push", triggers)

    def test_the_suite_job_skips_pull_request_and_runs_otherwise(self):
        self.assertEqual(_job_if(self.text, "tests"), "github.event_name != 'pull_request'")

    def test_the_summary_still_reports_when_the_suite_is_skipped(self):
        self.assertEqual(_job_if(self.text, "summary"), "always()")

    def test_the_required_check_keeps_its_exact_name(self):
        # Ruleset "Merge gates for default branch" requires the context "Test Summary": a renamed
        # job never reports it, so every PR and every queue entry would wait until timeout.
        self.assertEqual(_job_field(self.text, "summary", "name"), "Test Summary")

    def test_the_summary_reads_the_suite_result(self):
        # Without `needs: tests`, needs.tests.result is empty and the gate no longer reflects shards.
        self.assertEqual(_job_field(self.text, "summary", "needs"), "tests")

if __name__ == "__main__":
    unittest.main()
