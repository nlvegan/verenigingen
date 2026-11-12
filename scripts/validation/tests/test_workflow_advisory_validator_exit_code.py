"""The template and child-table validators must not swallow their exit code (#2329).

Sibling of ``test_workflow_field_validator_exit_code`` (#2190). In the advisory
``validation`` job of ``code-validation.yml`` these steps ended in ``|| echo ...``,
which turns any exit code into 0 and makes the Validation Summary's
``steps.template-validation.outcome`` read "success" over a finding. The steps stay
advisory via ``continue-on-error: true`` (job stays green, outcome stays real).

Stdlib-only, line-based (no YAML parser), reusing the sibling's scanner.
"""

import unittest
from pathlib import Path

try:
    from test_workflow_field_validator_exit_code import _SWALLOW, steps_running
except ImportError:  # dotted-module run: python -m unittest scripts.validation.tests.<name>
    from .test_workflow_field_validator_exit_code import _SWALLOW, steps_running

_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "code-validation.yml"
# "python " prefix: a comment elsewhere in the file may merely mention a validator by name.
_VALIDATORS = ("python template_variable_validator.py", "python child_table_creation_validator.py")


class AdvisoryValidatorsCanReportTests(unittest.TestCase):
    def setUp(self):
        self.text = _WORKFLOW.read_text()

    def test_the_scan_finds_each_validator_once_in_the_validation_job(self):
        # Control: a scan that finds nothing would pass every test below.
        for validator in _VALIDATORS:
            with self.subTest(validator=validator):
                steps = steps_running(self.text, validator)
                self.assertEqual([job for job, _ in steps], ["validation"], steps)

    def test_no_run_swallows_the_exit_code(self):
        for validator in _VALIDATORS:
            for job, block in steps_running(self.text, validator):
                with self.subTest(validator=validator, job=job):
                    self.assertIsNone(_SWALLOW.search(block), block)

    def test_each_step_stays_advisory(self):
        # Dropping `|| echo` without this would turn the advisory job red.
        for validator in _VALIDATORS:
            for job, block in steps_running(self.text, validator):
                with self.subTest(validator=validator, job=job):
                    self.assertIn("continue-on-error: true", block)


if __name__ == "__main__":
    unittest.main()
