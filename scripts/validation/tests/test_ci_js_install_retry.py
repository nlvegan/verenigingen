"""The CI JS install must say when a failure is infrastructure (#853).

Drives the real ``.github/actions/setup/retry-js-install.sh`` through bash with a fake installer
whose behaviour is scripted per attempt, and checks the action actually uses it.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LIB = _ROOT / ".github" / "actions" / "setup" / "retry-js-install.sh"
_ACTION = _ROOT / ".github" / "actions" / "setup" / "action.yml"
_INFRA = "This is an infrastructure failure, not a code failure - no test has run at this point. Re-run the job."


def _run(outputs, rc_after=None, attempts=3, fn="ci_retry_js_install"):
    """Run ci_retry_js_install with a fake installer. ``outputs`` is one (exit, text) per attempt."""
    with tempfile.TemporaryDirectory() as d:
        for i, (_, text) in enumerate(outputs, 1):
            Path(d, f"out{i}").write_text(text)
        codes = " ".join(str(c) for c, _ in outputs)
        script = f"""
        source "{_LIB}"
        sleeps=(); sleep() {{ sleeps+=("$1"); }}
        codes=({codes}); calls=0
        fake() {{ calls=$((calls+1)); cat "{d}/out$calls"; return "${{codes[$((calls-1))]}}"; }}
        CI_JS_INSTALL_ATTEMPTS={attempts} CI_JS_INSTALL_BACKOFF=15 {fn} demo fake
        rc=$?; echo "ATTEMPTS=$calls SLEEPS=${{sleeps[*]}} GAVE_UP=$CI_RETRY_GAVE_UP_ON_NETWORK"; exit $rc
        """
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={**os.environ})
        return p.returncode, p.stdout + p.stderr


class JsInstallRetryTests(unittest.TestCase):
    def test_success_runs_once(self):
        rc, out = _run([(0, "ok\n")])
        self.assertEqual(rc, 0)
        self.assertIn("ATTEMPTS=1", out)
        self.assertNotIn("::error::", out)

    def test_transient_failure_then_success(self):
        rc, out = _run([(1, "npm error code E404\nnpm error 404 Not Found - GET https://registry.npmjs.org/playwright/-/playwright-1.63.0.tgz\n"), (0, "ok\n")])
        self.assertEqual(rc, 0)
        self.assertIn("ATTEMPTS=2", out)
        self.assertNotIn("::error::", out)

    def test_permanent_network_failure_emits_infra_error_and_fails(self):
        rc, out = _run([(1, "npm error code ECONNRESET\n")] * 3)
        self.assertNotEqual(rc, 0)
        self.assertIn("ATTEMPTS=3", out)
        self.assertIn("::error::", out)
        self.assertIn(_INFRA, out)

    def test_real_dependency_error_is_not_retried_nor_called_infra(self):
        rc, out = _run([(1, "npm error code ERESOLVE\nnpm error unable to resolve dependency tree\n")] * 3)
        self.assertEqual(rc, 1)
        self.assertIn("ATTEMPTS=1", out)
        self.assertNotIn("infrastructure failure", out)
        self.assertNotIn("::error::", out)

    def test_packument_404_is_a_real_pin_error_not_retried(self):
        rc, out = _run([(1, "npm error code E404\nnpm error 404 Not Found - GET https://registry.npmjs.org/no-such-pkg\n")] * 3)
        self.assertEqual(rc, 1)
        self.assertIn("ATTEMPTS=1", out)
        self.assertNotIn("infrastructure failure", out)

    def test_missing_version_etarget_is_not_retried(self):
        rc, out = _run([(1, "npm error code ETARGET\nnpm error notarget No matching version found for x@9.\n")] * 3)
        self.assertIn("ATTEMPTS=1", out)
        self.assertNotIn("infrastructure failure", out)

    def test_backoff_sleeps_double_between_attempts(self):
        _, out = _run([(1, "npm error code ECONNRESET\n")] * 4, attempts=4)
        self.assertIn("SLEEPS=15 30 60", out)

    def test_original_exit_code_is_preserved(self):
        rc, _ = _run([(7, "ERESOLVE\n")])
        self.assertEqual(rc, 7)


def _pip(outputs, attempts=3):
    return _run(outputs, attempts=attempts, fn="ci_retry_pip_install")


_PIP_RESET = (
    "WARNING: Retrying (Retry(total=0, connect=None, read=None, redirect=None, status=None)) after "
    "connection broken by 'ReadTimeoutError(\"HTTPSConnectionPool(host='pypi.org', port=443): Read timed out.\")'\n"
    "ERROR: Could not find a version that satisfies the requirement frappe-bench (from versions: none)\n"
    "ERROR: No matching distribution found for frappe-bench\n"
)


class PipInstallRetryTests(unittest.TestCase):
    """#2910: pip/git network failures get the same retry + infrastructure verdict as npm/yarn."""

    def test_transient_pip_failure_then_success(self):
        rc, out = _pip([(1, _PIP_RESET), (0, "ok\n")])
        self.assertEqual(rc, 0)
        self.assertIn("ATTEMPTS=2", out)
        self.assertNotIn("::error::", out)

    def test_permanent_pip_network_failure_emits_infra_error(self):
        rc, out = _pip([(1, _PIP_RESET)] * 3)
        self.assertNotEqual(rc, 0)
        self.assertIn("ATTEMPTS=3", out)
        self.assertIn("::error::Python dependency install", out)
        self.assertIn(_INFRA, out)
        self.assertIn("GAVE_UP=1", out)

    def test_git_clone_failure_is_transient(self):
        rc, out = _pip([(128, "fatal: unable to access 'https://github.com/x/y/': Could not resolve host: github.com\n"), (0, "")])
        self.assertEqual(rc, 0)
        self.assertIn("ATTEMPTS=2", out)

    def test_missing_distribution_is_a_real_pin_error_not_retried(self):
        rc, out = _pip([(1, "ERROR: Could not find a version that satisfies the requirement nosuch==9\nERROR: No matching distribution found for nosuch==9\n")] * 3)
        self.assertEqual(rc, 1)
        self.assertIn("ATTEMPTS=1", out)
        self.assertIn("GAVE_UP=0", out)
        self.assertNotIn("infrastructure failure", out)

    def test_resolution_conflict_is_not_retried(self):
        rc, out = _pip([(1, "ERROR: Cannot install a and b because these package versions have conflicting dependencies.\n")] * 3)
        self.assertIn("ATTEMPTS=1", out)
        self.assertNotIn("infrastructure failure", out)

    def test_npm_signature_is_not_a_pip_network_error(self):
        # each manager has its own pattern; npm's must not leak into pip's classification
        _, out = _pip([(1, "npm error code ECONNRESET\n")] * 3)
        self.assertIn("ATTEMPTS=1", out)

    def test_original_exit_code_is_preserved(self):
        rc, _ = _pip([(5, "ERROR: boom\n")])
        self.assertEqual(rc, 5)


class PipFinalFailureClassificationTests(unittest.TestCase):
    """#2910 review: the FINAL failure decides; a bare retry line / fetch error is not a transport cause."""

    _BLIP = "WARNING: Retrying (Retry(total=4)) after connection broken by 'ReadTimeoutError(Read timed out.)'\n"

    def _assert_real(self, text):
        rc, out = _pip([(1, text)] * 3)
        self.assertIn("ATTEMPTS=1", out)
        self.assertIn("GAVE_UP=0", out)
        self.assertNotIn("infrastructure failure", out)
        self.assertEqual(rc, 1)

    def test_blip_then_real_conflict_is_not_infra(self):
        self._assert_real(self._BLIP + "ERROR: Cannot install a and b because these package versions have conflicting dependencies.\n")

    def test_git_404_is_not_infra(self):
        self._assert_real("fatal: unable to access 'https://github.com/x/y/': The requested URL returned error: 404\n")

    def test_git_403_is_not_infra(self):
        self._assert_real("fatal: unable to access 'https://github.com/x/y/': The requested URL returned error: 403\n")

    def test_pypi_404_then_no_matching_distribution_is_not_infra(self):
        self._assert_real(
            "WARNING: Retrying (Retry(total=4)) after connection broken\n"
            "ERROR: HTTP error 404 while getting https://pypi.org/simple/nosuch/\n"
            "ERROR: Could not install requirement nosuch because of HTTP error 404 Client Error: Not Found for url\n"
            "WARNING: Could not fetch URL https://pypi.org/simple/nosuch/: 404 Client Error\n"
            "ERROR: No matching distribution found for nosuch\n"
        )

    def test_bare_retry_line_without_a_cause_is_not_infra(self):
        self._assert_real("WARNING: Retrying (Retry(total=4)) after something\nERROR: No matching distribution found for x\n")


def _extract_pip_step_script():
    text = _ACTION.read_text()
    start = text.index("    - name: Install Python Dependencies")
    body = text[start:].split("      run: |\n", 1)[1].split("\n    - name:", 1)[0]
    lines = [ln[8:] if ln.startswith("        ") else ln for ln in body.splitlines()]
    return "\n".join(lines)


class PipStepFailsClosedTests(unittest.TestCase):
    """Run the REAL "Install Python Dependencies" step body under `bash -eo pipefail` with a fake pip."""

    def _run_step(self, pip_output):
        script = _extract_pip_step_script()
        script = script.replace("${{ github.action_path }}", str(_LIB.parent))
        script = script.replace("${{ inputs.enable-coverage }}", "false")
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "env" / "bin").mkdir(parents=True)
            (ws / "env" / "bin" / "activate").write_text("")
            (ws / "sites").mkdir()
            (ws / "apps" / "demo").mkdir(parents=True)
            (ws / "apps" / "demo" / "pyproject.toml").write_text("")
            fake = ws / "bin"
            fake.mkdir()
            (fake / "pip").write_text(f"#!/bin/bash\ncat <<'EOF'\n{pip_output}EOF\nexit 1\n")
            (fake / "pip").chmod(0o755)
            (fake / "sleep").write_text("#!/bin/bash\nexit 0\n")
            (fake / "sleep").chmod(0o755)
            env = {**os.environ, "GITHUB_WORKSPACE": str(ws), "PATH": f"{fake}:{os.environ['PATH']}",
                   "CI_JS_INSTALL_ATTEMPTS": "2", "CI_JS_INSTALL_BACKOFF": "0"}
            p = subprocess.run(["bash", "-eo", "pipefail", "-c", script + "\necho STEP_CONTINUED"],
                               capture_output=True, text=True, env=env, cwd=ws)
            return p.returncode, p.stdout + p.stderr

    def test_step_stops_after_a_network_give_up(self):
        rc, out = self._run_step("WARNING: ReadTimeoutError: Read timed out.\n")
        self.assertNotIn("STEP_CONTINUED", out)
        self.assertNotEqual(rc, 0)
        self.assertIn("infrastructure failure", out)

    def test_step_stops_after_a_real_failure_of_both_installs(self):
        rc, out = self._run_step("ERROR: Cannot install a and b because these package versions have conflicting dependencies.\n")
        self.assertNotIn("STEP_CONTINUED", out)
        self.assertNotEqual(rc, 0)


class ActionUsesTheGuardTests(unittest.TestCase):
    def test_action_wraps_the_install_and_keeps_the_yarn_npm_fallback(self):
        text = _ACTION.read_text()
        self.assertIn("retry-js-install.sh", text)
        self.assertIn("ci_retry_js_install", text)
        self.assertIn("yarn --check-files || npm install", text)

    def test_install_js_deps_keeps_the_yarn_lock_branch(self):
        text = _ACTION.read_text()
        body = text[text.index("install_js_deps() {") :].split("\n        }\n", 1)[0]
        self.assertIn('if [ -f "yarn.lock" ]; then', body)
        self.assertIn("yarn --check-files || npm install", body)
        self.assertIn("npm install", body.split("else", 1)[1])

    def test_every_pip_install_in_the_action_goes_through_the_guard(self):
        import re

        text = _ACTION.read_text()
        bare = [
            ln.strip()
            for ln in text.splitlines()
            if re.match(r"\s*pip install ", ln) and not ln.strip().startswith("#")
        ]
        self.assertEqual(bare, [], "a bare `pip install` bypasses the #2910 guard")
        self.assertEqual(text.count("ci_retry_pip_install "), 5)

    def test_extras_fallback_is_skipped_after_a_network_give_up(self):
        text = _ACTION.read_text()
        self.assertIn('[ "$CI_RETRY_GAVE_UP_ON_NETWORK" != 1 ]', text)

    def test_the_lib_exists(self):
        self.assertTrue(_LIB.exists())


if __name__ == "__main__":
    unittest.main()
