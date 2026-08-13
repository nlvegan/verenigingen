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

import importlib
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
                # Drive the queue path for real rather than inspecting the mock.
                EmailQueue({"doctype": "Email Queue"}).send()
                observed["captured"] = list(inner.captured_emails)

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

    def test_the_queue_send_path_is_captured(self):
        """Was `email_queue.send_one`, which no longer exists.

        This is the path that would open a real SMTP connection for an Email
        Queue row created without going through `frappe.sendmail`.

        Asserting `isinstance(EmailQueue.send, MagicMock)` was not enough: it
        proves something replaced the attribute, so a patch that intercepts and
        records nothing passes. Measured — that mutant survived. Drive a send.
        """
        observed = self._run_capturing_case()

        methods = [e["method"] for e in observed["captured"]]
        self.assertIn(
            "EmailQueue.send",
            methods,
            "a real EmailQueue.send() was not captured; the queue path is unwatched",
        )

    def test_a_dead_target_fails_loudly_and_leaks_nothing(self):
        """The two behaviours this PR is actually about, in one path.

        A dead patch target must (a) raise out of `setUp` rather than be logged
        and continued, and (b) not leave the patches that started BEFORE it live
        for the rest of the process -- unittest skips `tearDown` when `setUp`
        raises, and `tearDown` is where the harness stops them.

        The failure is induced INSIDE the production start loop, by removing the
        third patch's target, so ordering of `addCleanup` relative to that loop
        is what decides the outcome. An earlier version of this test raised its
        own RuntimeError from a subclass after `super()` had already completed:
        it asserted on a message the test itself produced, so reverting the
        production `raise` to a warning, and moving the `addCleanup` after the
        loop, BOTH still passed. Measured.
        """
        comm_email = importlib.import_module("frappe.core.doctype.communication.email")
        original_make = comm_email.make

        class _DeadTargetCase(EnhancedTestCase):
            def test_never_runs(inner):
                raise AssertionError("setUp should have raised before the test body")

        result = unittest.TestResult()
        del comm_email.make
        try:
            unittest.TestLoader().loadTestsFromTestCase(_DeadTargetCase).run(result)
        finally:
            comm_email.make = original_make

        self.assertEqual(len(result.errors), 1, "a dead patch target did not fail the test")
        traceback_text = result.errors[0][1]
        # Wording only the PRODUCTION handler emits, so a revert to log-and-continue
        # cannot pass this.
        self.assertIn("Tests would silently see zero emails", traceback_text)
        self.assertIn("frappe.core.doctype.communication.email.make", traceback_text)

        self.assertFalse(
            isinstance(frappe.sendmail, MagicMock),
            "frappe.sendmail is STILL patched after a setUp that raised -- the patches that "
            "started before the failing one leaked into the rest of the process",
        )
