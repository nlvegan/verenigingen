"""A test class that seeds notification state must leave the site as it found it (#2053).

``allow_reminder_sends`` used to seed the registry, switch the master switch on and zero the
cooldowns with no cleanup. Every later class in a CI shard then ran on state it never asked for.
The leak is only visible from OUTSIDE the class that caused it, so each real caller is run here
in a nested unittest run and the notification state is read in this same process afterwards.
"""

import io
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.utils.notification_state import snapshot_notification_rows

DOCTYPE = "Verenigingen Email Configuration"

# (module, class, method or None): every class that used to call ``allow_reminder_sends`` or hand-roll
# the restore. ``None`` runs the class's first two tests (its setUp seeds). ``send_renewal_reminders``
# COMMITS mid-test (api/periodic_donation_operations.py), which made that test's seed permanent, so
# that caller is pinned to the test that reaches it.
CALLERS = [
    ("verenigingen.tests.test_operationresult_callers_2177", "TestOperationResultCallers2177", None),
    ("verenigingen.tests.chapter.test_chapter_join_request_second_profile_2286", "TestChapterJoinRequestSecondProfile2286", None),
    ("verenigingen.tests.backend.components.test_payment_processing_api", "TestPaymentProcessingAPI", None),
    ("verenigingen.tests.backend.components.test_payment_processing_api_real", "TestPaymentProcessingAPIReal", None),
    ("verenigingen.tests.integration.test_payment_processing_api_integration", "TestPaymentProcessingAPIIntegration", None),
    (
        "verenigingen.tests.api.test_periodic_donation_operations",
        "TestPeriodicDonationOperations",
        "test_send_renewal_reminders_query_selects_only_expiring_active_agreements",
    ),
    (
        "verenigingen.tests.backend.components.test_payment_processing_real_template_handling",
        "TestPaymentProcessingRealTemplateHandling",
        None,
    ),
    ("verenigingen.tests.payment.test_payment_reminder_outcomes", "TestPaymentReminderOutcomes", None),
]


def notification_state():
    """Master switch plus the raw rows (names, flags, cooldowns, stamps), read from the database."""
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
    master = frappe.db.get_single_value(DOCTYPE, "master_email_enabled")
    return master, snapshot_notification_rows()


def _row_summary(rows):
    return {r["notification_key"]: (r["enabled"], r["cooldown_minutes"]) for r in rows}


def run_two_tests(module, class_name, method=None):
    """Run two test methods of a real caller back to back; returns (ran, problems) of that nested run.

    Two, because the harness commits between tests: a restore that put back a state already
    polluted by an earlier setUp is only made permanent by the NEXT test's commit, so a single
    test cannot show it.
    """
    cls = getattr(__import__(module, fromlist=[class_name]), class_name)
    names = unittest.TestLoader().getTestCaseNames(cls)
    first = method or names[0]
    second = next(n for n in names if n != first)
    suite = unittest.TestSuite([cls(first), cls(second)])
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return result.testsRun, result.errors + result.failures


class TestNotificationSeedLeak2053(FrappeTestCase):
    def test_no_caller_leaves_notification_state_behind(self):
        for module, class_name, method in CALLERS:
            with self.subTest(caller=class_name):
                before = notification_state()
                ran, problems = run_two_tests(module, class_name, method)
                self.assertEqual(ran, 2, f"control: {class_name} must really run")
                self.assertEqual(problems, [], f"control: {class_name} must pass on its own")
                after = notification_state()
                self.assertEqual(after[0], before[0], f"{class_name} left the master switch changed")
                self.assertEqual(
                    _row_summary(after[1]),
                    _row_summary(before[1]),
                    f"{class_name} changed registry rows or cooldowns",
                )
                self.assertEqual(after, before, f"{class_name} replaced rows (names or stamps differ)")
