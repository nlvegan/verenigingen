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


def _run(outputs, rc_after=None):
    """Run ci_retry_js_install with a fake installer. ``outputs`` is one (exit, text) per attempt."""
    with tempfile.TemporaryDirectory() as d:
        for i, (_, text) in enumerate(outputs, 1):
            Path(d, f"out{i}").write_text(text)
        codes = " ".join(str(c) for c, _ in outputs)
        script = f"""
        source "{_LIB}"
        codes=({codes}); calls=0
        fake() {{ calls=$((calls+1)); cat "{d}/out$calls"; return "${{codes[$((calls-1))]}}"; }}
        CI_JS_INSTALL_ATTEMPTS=3 CI_JS_INSTALL_BACKOFF=0 ci_retry_js_install demo fake
        rc=$?; echo "ATTEMPTS=$calls"; exit $rc
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
        rc, out = _run([(1, "npm error code E404\nnpm error 404 Not Found - GET .../playwright-1.63.0.tgz\n"), (0, "ok\n")])
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

    def test_original_exit_code_is_preserved(self):
        rc, _ = _run([(7, "ERESOLVE\n")])
        self.assertEqual(rc, 7)


class ActionUsesTheGuardTests(unittest.TestCase):
    def test_action_wraps_the_install_and_keeps_the_yarn_npm_fallback(self):
        text = _ACTION.read_text()
        self.assertIn("retry-js-install.sh", text)
        self.assertIn("ci_retry_js_install", text)
        self.assertIn("yarn --check-files || npm install", text)

    def test_the_lib_exists(self):
        self.assertTrue(_LIB.exists())


if __name__ == "__main__":
    unittest.main()
