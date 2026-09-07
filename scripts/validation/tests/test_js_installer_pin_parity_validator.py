#!/usr/bin/env python3
"""Unit tests for scripts/validation/js_installer_pin_parity_validator.py (#272).

Stdlib-only, no bench or site needed -- same shape as its siblings in this
directory (test_baseline_shrink_gate.py, test_bench_resolution.py).

These are deliberately synthetic: they construct minimal action.yml/
package.json fragments so the pass/fail boundary is exercised directly,
independent of whatever state the real repo files happen to be in. The
real-file integration check runs separately via the validator's own CLI
(`python scripts/validation/js_installer_pin_parity_validator.py`, wired
into pre-commit as `js-installer-pin-parity`).
"""

import importlib.util
import sys
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "js_installer_pin_parity_validator.py"
_spec = importlib.util.spec_from_file_location("js_installer_pin_parity_validator", _MOD_PATH)
validator = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = validator
_spec.loader.exec_module(validator)

UNGATED_STEP = """\
    - name: Install JS Dependencies
      if: ${{ inputs.build-assets == 'true' }}
      shell: bash
      run: |
        for app in ${GITHUB_WORKSPACE}/apps/*/; do
          if [ -f "${app}package.json" ]; then
            pushd "$app"
            yarn --check-files || npm install
            popd
          fi
        done
    - name: Next Step
      run: echo done
"""

GATED_STEP = """\
    - name: Install JS Dependencies
      if: ${{ inputs.build-assets == 'true' }}
      shell: bash
      run: |
        for app in ${GITHUB_WORKSPACE}/apps/*/; do
          if [ -f "${app}package.json" ]; then
            pushd "$app"
            if [ -f "yarn.lock" ]; then
              yarn --check-files || npm install
            else
              npm install
            fi
            popd
          fi
        done
    - name: Next Step
      run: echo done
"""

COMMENT_ONLY_MENTION_STEP = """\
    - name: Install JS Dependencies
      run: |
        for app in ${GITHUB_WORKSPACE}/apps/*/; do
          if [ -f "${app}package.json" ]; then
            pushd "$app"
            # an unconditional `yarn --check-files` here used to run real yarn
            if [ -f "yarn.lock" ]; then
              yarn --check-files || npm install
            else
              npm install
            fi
            popd
          fi
        done
    - name: Next Step
      run: echo done
"""


class TestCheckInstallerGatesOnLockfile(unittest.TestCase):
    def test_unconditional_yarn_invocation_is_flagged(self):
        problems = validator.check_installer_gates_on_lockfile(UNGATED_STEP)
        self.assertTrue(problems, "an unconditional `yarn --check-files || npm install` must be flagged")
        self.assertTrue(any("without first testing" in p for p in problems))

    def test_lockfile_gated_invocation_passes(self):
        self.assertEqual(validator.check_installer_gates_on_lockfile(GATED_STEP), [])

    def test_comment_mentioning_yarn_check_files_is_not_flagged(self):
        # A comment line that merely *mentions* the invocation (e.g. explaining
        # why the code below is guarded) must not itself be treated as an
        # unguarded invocation.
        self.assertEqual(validator.check_installer_gates_on_lockfile(COMMENT_ONLY_MENTION_STEP), [])

    def test_missing_step_is_flagged(self):
        problems = validator.check_installer_gates_on_lockfile("- name: Something Else\n  run: echo hi\n")
        self.assertTrue(problems)
        self.assertIn("could not find", problems[0])


class TestCheckNoDeadResolutionsBlock(unittest.TestCase):
    def test_resolutions_block_present_is_flagged(self):
        problems = validator.check_no_dead_resolutions_block(
            {"resolutions": {"lodash": "^4.17.23"}, "overrides": {}}
        )
        self.assertTrue(problems, "a package.json with 'resolutions' must be flagged")

    def test_resolutions_block_absent_passes(self):
        problems = validator.check_no_dead_resolutions_block({"overrides": {"lodash": "^4.17.23"}})
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
