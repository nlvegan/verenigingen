"""The scripts/ duplicate-helper population must be enforced in CI (#1429).

``duplicate_helper_scripts_baseline.txt`` (#1044/#1100) was committed with no caller at all,
so scripts/ drifted past it unseen. The ``duplicate-helper-ratchet`` job must run the
validator with ``--root scripts`` against that baseline, and must run the baseline sync gate
for it too. The verenigingen-root steps are the control: they must still be there.
"""

import unittest
from pathlib import Path

import yaml

try:
    from test_workflow_field_validator_exit_code import steps_running
except ImportError:  # dotted-module run
    from .test_workflow_field_validator_exit_code import steps_running

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "code-validation.yml"
_JOB = "duplicate-helper-ratchet"
_BASELINE = "duplicate_helper_scripts_baseline.txt"


class ScriptsDuplicateHelperRatchetIsWiredTests(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW.read_text()

    def _steps(self, needle):
        return [block for job, block in steps_running(self.text, needle) if job == _JOB]

    def test_control_the_verenigingen_root_baseline_gate_is_still_wired(self):
        blocks = self._steps("duplicate_helper_baseline.txt")
        self.assertTrue(any("baseline_shrink_gate.py" in b for b in blocks), blocks)

    def test_a_step_ratchets_the_scripts_root_against_its_own_baseline(self):
        blocks = [
            b
            for b in self._steps("--root scripts")
            if _BASELINE in b and "--update-baseline" not in b
        ]
        self.assertEqual(len(blocks), 1, blocks)

    def test_a_step_gates_the_scripts_baseline_sync_on_clone_family_lines(self):
        blocks = [
            b
            for b in self._steps(_BASELINE)
            if "baseline_shrink_gate.py" in b and "--root scripts" in b
        ]
        self.assertEqual(len(blocks), 1, blocks)
        self.assertIn('--require-marker "# clone family"', blocks[0])
        self.assertIn("--already-regenerated", blocks[0])

    def test_a_step_fails_when_scripts_clone_family_copies_grow(self):
        blocks = [b for b in self._steps(_BASELINE) if "exit 1" in b and "clone-family" in b]
        self.assertEqual(len(blocks), 1, blocks)

    def test_the_scripts_sync_gate_passes_fail_on_shrink(self):
        """Parse the step: without $FAIL_ON_SHRINK the push-side shrink gate is
        silently off, and a whole-file substring would still find it elsewhere."""
        steps = yaml.safe_load(self.text)["jobs"][_JOB]["steps"]
        sync = [
            st
            for st in steps
            if "baseline_shrink_gate.py" in st.get("run", "") and "--root scripts" in st.get("run", "")
        ]
        self.assertEqual(len(sync), 1, sync)
        self.assertIn("$FAIL_ON_SHRINK", sync[0]["run"])
        self.assertIn("--fail-on-shrink", sync[0]["env"]["FAIL_ON_SHRINK"])


if __name__ == "__main__":
    unittest.main()
