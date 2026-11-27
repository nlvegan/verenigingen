#!/usr/bin/env python3
"""#950: the order-dependence growth gate must not switch itself off when a PR edits the scanner.

Stdlib-only, real git, throwaway repos, and the REAL workflow step: the step's `run:` text is
extracted from code-validation.yml and executed, so a revert of the wiring reddens these tests
(the develop step `exit 0`s at "Scanner changed in this PR"). Each red case pairs with a control
that must stay green (a scanner edit that adds nothing; a line shift of an existing finding).
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "code-validation.yml"
SCANNER_REL = "scripts/testing/scan_order_dependence.py"
GATE_REL = "scripts/validation/order_dependence_scanner_edit_gate.py"
BASELINE_REL = "scripts/validation/order_dependence_baseline.txt"

CLEAN = "import frappe\n\n\nclass T:\n    def test_x(self):\n        pass\n"
BARE_COMMIT = "import frappe\n\n\nclass T:\n    def setUp(self):\n        frappe.db.\x63ommit()\n\n    def test_x(self):\n        pass\n"


def step_script():
    """The `run:` body of the 'Baseline did not grow' step, dedented."""
    # Scoped to the job: other ratchet jobs carry a step with the same name.
    text = WORKFLOW.read_text().split("  order-dependence-ratchet:", 1)[1]
    block = text.split("- name: Baseline did not grow", 1)[1].split("\n  fast-validation:", 1)[0]
    body = block.split("run: |\n", 1)[1]
    lines = body.splitlines()
    indent = len(lines[0]) - len(lines[0].lstrip())
    return "\n".join(line[indent:] for line in lines)


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Repo:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q")
        git(self.dir, "config", "user.email", "t@example.com")
        git(self.dir, "config", "user.name", "t")
        (self.dir / "scripts/testing").mkdir(parents=True)
        (self.dir / "scripts/validation").mkdir(parents=True)
        (self.dir / "verenigingen/tests").mkdir(parents=True)
        shutil.copy(ROOT / SCANNER_REL, self.dir / SCANNER_REL)
        shutil.copy(ROOT / GATE_REL, self.dir / GATE_REL)

    def write(self, rel, text):
        (self.dir / rel).write_text(text)

    def regen_baseline(self):
        subprocess.run(
            [sys.executable, SCANNER_REL, "--update-baseline", BASELINE_REL],
            cwd=str(self.dir), capture_output=True, text=True, check=True,
        )

    def commit(self, msg):
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", msg)
        return git(self.dir, "rev-parse", "HEAD")

    def run_step(self, base_sha):
        env = {"BASE_SHA": base_sha, "PATH": "/usr/bin:/bin:/usr/local/bin"}
        # the workflow calls bare `python`; make it this interpreter
        shim = self.dir / ".shim"
        shim.mkdir(exist_ok=True)
        (shim / "python").symlink_to(sys.executable) if not (shim / "python").exists() else None
        env["PATH"] = f"{shim}:{env['PATH']}"
        return subprocess.run(
            ["bash", "-e", "-c", step_script()], cwd=str(self.dir), env=env,
            capture_output=True, text=True, timeout=300,
        )

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class ScannerEditGateTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.cleanup)
        self.repo.write("verenigingen/tests/test_a.py", CLEAN)
        self.repo.regen_baseline()
        self.base = self.repo.commit("base")
        (self.repo.dir / ".gitignore").write_text(".shim\n")

    def _edit_scanner(self, extra=""):
        p = self.repo.dir / SCANNER_REL
        p.write_text(p.read_text() + "\n# scanner edited in this PR\n" + extra)

    def _commit_and_gate(self):
        self.repo.commit("head")
        return self.repo.run_step(self.base)

    def test_new_finding_plus_regenerated_baseline_in_a_scanner_editing_pr_fails(self):
        self._edit_scanner()
        self.repo.write("verenigingen/tests/test_b.py", BARE_COMMIT)
        self.repo.regen_baseline()
        r = self._commit_and_gate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("test_b.py", r.stdout)

    def test_control_scanner_edit_adding_nothing_passes(self):
        self._edit_scanner()
        r = self._commit_and_gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("No order-dependence growth", r.stdout)

    def test_control_an_existing_finding_shifting_lines_is_not_growth(self):
        self.repo.write("verenigingen/tests/test_b.py", BARE_COMMIT)
        self.repo.regen_baseline()
        self.base = self.repo.commit("base with one finding")
        self._edit_scanner()
        self.repo.write("verenigingen/tests/test_b.py", "# shift\n# shift\n" + BARE_COMMIT)
        self.repo.regen_baseline()
        r = self._commit_and_gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_pr_that_blinds_the_scanner_to_a_file_while_adding_a_finding_there_fails(self):
        """Under the PR's scanner alone both censuses lose the file and show zero delta;
        only the BASE scanner on the head tree sees the new finding."""
        self._edit_scanner()
        p = self.repo.dir / SCANNER_REL
        text = p.read_text()
        marker = "def _is_scannable(dirpath, root, fn):\n"
        self.assertIn(marker, text)
        p.write_text(text.replace(marker, marker + "    if fn == 'test_blind.py':\n        return False\n", 1))
        self.repo.write("verenigingen/tests/test_blind.py", BARE_COMMIT)
        self.repo.regen_baseline()
        r = self._commit_and_gate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("[base scanner]", r.stdout)

    def test_a_scanner_that_crashes_fails_closed(self):
        (self.repo.dir / SCANNER_REL).write_text("this is not python (\n")
        r = self._commit_and_gate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("failed closed", r.stdout)

    def test_control_scanner_unchanged_growth_still_fails(self):
        self.repo.write("verenigingen/tests/test_b.py", BARE_COMMIT)
        self.repo.regen_baseline()
        r = self._commit_and_gate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("grew from", r.stdout + r.stderr)


class WiringTests(unittest.TestCase):
    def test_the_step_no_longer_exits_zero_on_a_scanner_change(self):
        script = step_script()
        guard = re.search(r'git diff --quiet "\$BASE_SHA" HEAD -- "\$SCANNER"; then\n(.*?)\n\s*fi', script, re.S)
        self.assertIsNotNone(guard, script)
        self.assertNotRegex(guard.group(1), r"exit 0")
        self.assertIn("order_dependence_scanner_edit_gate.py", guard.group(1))


if __name__ == "__main__":
    unittest.main()
