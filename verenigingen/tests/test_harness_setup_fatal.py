"""Harness setup that fails must say so, not log and continue.

The failure mode these guard against is not a crash. It is a setup step that
did not happen, whose consequence arrives much later as a storm of failures in
unrelated tests -- the #291 shape. `disable_workflow_action_emails()` is the
clearest case: if it does not take, Frappe renders a PDF synchronously inside
every Member insert and can raise `OSError: ... HostNotFoundError` in every test
that touches a Member, none of which names this cause (#314).

Two kinds of assertion here, because neither kind alone is enough:

* Behavioural -- the patch is actually on, an import failure propagates instead
  of being logged, and the postcondition fires when the assignment does not take.
* A source guard -- re-wrapping any of these call sites in a `try`/`except`
  restores the old behaviour without changing any observable result on a healthy
  box, so no behavioural test can catch it.
"""

import ast
import sys
import unittest
from pathlib import Path

import frappe  # noqa: F401  (import side effects the harness modules rely on)

from verenigingen.tests.setup import (
    disable_workflow_action_emails,
    workflow_action_emails_disabled,
)

_WORKFLOW_ACTION_PKG = "frappe.workflow.doctype.workflow_action"

# Call sites that must not be wrapped in a swallow, and the file each lives in.
# Keyed by the called function's name because that is what survives a refactor
# of the surrounding code; the line number does not.
UNGUARDED_CALLS = {
    "verenigingen/tests/utils/__init__.py": {"disable_workflow_action_emails"},
    "verenigingen/tests/fixtures/enhanced_test_factory.py": {"disable_workflow_action_emails"},
    "verenigingen/tests/setup/__init__.py": {
        "_seed_default_team_roles",
        "set_defaults_for_tests",
        "enable_all_roles_and_domains",
    },
}


def _app_root() -> Path:
    """The verenigingen app root, from this file rather than from the cwd."""
    return Path(__file__).resolve().parents[2]


class _WritesAreDropped:
    """Stands in for the workflow_action module and ignores attribute writes.

    Used to prove the postcondition check does real work: with this in place the
    assignment inside `disable_workflow_action_emails()` silently does nothing,
    which is exactly the situation "it did not raise" cannot distinguish from
    success.
    """

    send_workflow_action_email = staticmethod(lambda *a, **k: None)

    def __setattr__(self, name, value):
        pass


class _FakePackage:
    def __init__(self, workflow_action):
        self.workflow_action = workflow_action


class WorkflowActionEmailPatchTest(unittest.TestCase):
    """The patch must be on, and must be verified rather than assumed."""

    def tearDown(self):
        # Whatever a test did to sys.modules, leave the real patch in place: the
        # rest of the suite depends on it, and a test that quietly turns it off
        # would slow every later Member insert to a PDF render.
        sys.modules.pop("_never", None)
        disable_workflow_action_emails()

    def test_the_patch_is_on_during_a_test_run(self):
        """The real postcondition, against the real module."""
        self.assertTrue(
            workflow_action_emails_disabled(),
            "workflow-action emails are not disabled; every Member insert renders a PDF",
        )

    def test_calling_it_again_is_idempotent(self):
        disable_workflow_action_emails()
        disable_workflow_action_emails()
        self.assertTrue(workflow_action_emails_disabled())

    def test_an_import_failure_propagates_instead_of_being_logged(self):
        """A `None` in sys.modules makes the import raise. It must not be caught."""
        original = sys.modules.get(_WORKFLOW_ACTION_PKG)
        sys.modules[_WORKFLOW_ACTION_PKG] = None
        try:
            with self.assertRaises(ImportError):
                disable_workflow_action_emails()
        finally:
            if original is None:
                sys.modules.pop(_WORKFLOW_ACTION_PKG, None)
            else:
                sys.modules[_WORKFLOW_ACTION_PKG] = original

    def test_an_assignment_that_does_not_take_is_caught(self):
        """"It did not raise" is not evidence the side effect happened."""
        original = sys.modules.get(_WORKFLOW_ACTION_PKG)
        sys.modules[_WORKFLOW_ACTION_PKG] = _FakePackage(_WritesAreDropped())
        try:
            with self.assertRaises(RuntimeError) as caught:
                disable_workflow_action_emails()
            self.assertIn("send_workflow_action_email", str(caught.exception))
        finally:
            if original is None:
                sys.modules.pop(_WORKFLOW_ACTION_PKG, None)
            else:
                sys.modules[_WORKFLOW_ACTION_PKG] = original


class SetupCallsAreNotSwallowedTest(unittest.TestCase):
    """No behavioural test can see a swallow that never fires. This can."""

    def test_named_setup_calls_are_not_inside_a_try_except(self):
        offenders = []
        for rel_path, names in UNGUARDED_CALLS.items():
            path = _app_root() / rel_path
            self.assertTrue(path.exists(), f"{rel_path} moved; update this test")
            for name, lineno in _calls_guarded_by_except(path, names):
                offenders.append(f"{rel_path}:{lineno} {name}()")

        self.assertEqual(
            [],
            offenders,
            "These setup calls are wrapped in an except handler again. A failure "
            "there is not survivable in a useful way -- it resurfaces as unrelated "
            "failures elsewhere. See #309/#314.",
        )


def _calls_guarded_by_except(path: Path, names: set[str]):
    """Yield (name, lineno) for calls to `names` inside a try that has handlers.

    A bare `try`/`finally` is not a swallow, so only handler-bearing Try nodes
    count. Nested functions defined inside the try are not walked around -- a
    call is reported wherever it textually sits, which is what the guard is about.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not node.handlers:
            continue
        for statement in node.body:
            for inner in ast.walk(statement):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name in names:
                    yield name, inner.lineno


if __name__ == "__main__":
    unittest.main()
