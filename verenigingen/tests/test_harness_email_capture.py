"""The harness's email capture must actually be installed.

Three of the five patches in `EnhancedTestCase._setup_email_mocking` targeted
modules that no longer exist — `frappe.utils.email_lib` (twice) and
`email_queue.send_one`. They failed to start on every test, and the loop logged
"some methods may not exist" and continued, through a `frappe.logger()` sitting
at level ERROR that discarded the message (#311). So `captured_emails == []`
meant **"nothing was watching"**, not "no mail was sent" (#312).

Starting a patch is fatal now, which makes a dead target impossible to miss.
These tests pin the pathways that remain, including the one whose patch was
deleted rather than retargeted — that deletion rests on an argument
(`sendmail_to_system_managers` is a one-line wrapper around `frappe.sendmail`,
so patch 1 already covers it) and an argument is worth making only if it is
checked.

The case is driven through `unittest` rather than by calling
`_setup_email_mocking` directly, because what is under test is what `setUp`
installs.
"""

import unittest
from unittest.mock import MagicMock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestHarnessEmailCapture(unittest.TestCase):
    def _run_capturing_case(self):
        observed = {}

        class _CapturingCase(EnhancedTestCase):
            def test_capture(inner):
                from frappe.email import sendmail_to_system_managers
                from frappe.email.doctype.email_queue.email_queue import EmailQueue

                frappe.sendmail(recipients=["nobody@example.invalid"], subject="probe", message="x")
                sendmail_to_system_managers("probe-via-wrapper", "x")
                observed["captured"] = list(inner.captured_emails)
                observed["queue_send_patched"] = isinstance(EmailQueue.send, MagicMock)

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_CapturingCase).run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        return observed

    def test_sendmail_is_captured(self):
        observed = self._run_capturing_case()

        subjects = [e["subject"] for e in observed["captured"]]
        self.assertIn("probe", subjects, "frappe.sendmail was not captured")

    def test_the_deleted_wrapper_patch_is_genuinely_covered(self):
        """`sendmail_to_system_managers` reaches `frappe.sendmail` at call time.

        `frappe/email/__init__.py` calls `frappe.sendmail(...)` as a module
        attribute lookup, so patching `frappe.sendmail` intercepts it. That is
        why its own patch was deleted rather than retargeted; if this ever
        stops holding, a whole notification pathway goes uncaptured silently.
        """
        observed = self._run_capturing_case()

        subjects = [e["subject"] for e in observed["captured"]]
        self.assertIn(
            "probe-via-wrapper",
            subjects,
            "sendmail_to_system_managers escaped capture -- it needs its own patch again",
        )

    def test_the_queue_send_path_is_patched(self):
        """Was `email_queue.send_one`, which no longer exists.

        This is the path that would open a real SMTP connection for an Email
        Queue row created without going through `frappe.sendmail`.
        """
        observed = self._run_capturing_case()

        self.assertTrue(observed["queue_send_patched"], "EmailQueue.send was left unpatched")

    def test_a_failure_after_some_patches_started_does_not_leak_them(self):
        """unittest skips tearDown when setUp raises.

        The harness stops its email patches in `tearDown`, so without an
        `addCleanup` registered BEFORE the start loop, the patches that started
        before a failing one stay started for the rest of the process, bound to
        a dead test case's `captured_emails` list. Every later test in that
        process then sends mail into a list nobody reads.

        This drives the real path: `super()._setup_email_mocking()` starts the
        genuine patches, then a dead target raises out of setUp. What the
        assertion checks is whether the harness's own cleanup put them back.
        """

        class _FailingSetUpCase(EnhancedTestCase):
            def _setup_email_mocking(inner):
                from unittest.mock import patch

                super()._setup_email_mocking()  # starts the real patches
                try:
                    patch("frappe.utils.email_lib.send").start()
                except Exception as e:
                    raise RuntimeError(f"Email capture could not be installed: {e}") from e

            def test_never_runs(inner):
                raise AssertionError("setUp should have raised before the test body")

        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(_FailingSetUpCase).run(result)

        self.assertEqual(len(result.errors), 1, "the dead patch target did not fail the test")
        self.assertIn("Email capture could not be installed", result.errors[0][1])
        self.assertFalse(
            isinstance(frappe.sendmail, MagicMock),
            "frappe.sendmail is STILL patched after a setUp that raised -- the patches leaked "
            "into the rest of the process",
        )
