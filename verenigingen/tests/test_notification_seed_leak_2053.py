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

from verenigingen.tests.utils.notification_state import restore_notification_rows, snapshot_notification_rows

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
    # Commits by design (the finalizer rolls back fully), so it declares ``commits=True``.
    ("verenigingen.tests.payment.test_payment_plan_pe_failure_alert_1330", "TestRepeatedPaymentEntryFailureAlert", None),
    # #2541: found by measuring every other notification-state writer (the test sites carry a master
    # switch of 1 and no canary, so run this module on a site where it is 0 to see these go red).
    (
        "verenigingen.tests.api.test_skipped_mail_not_counted_sent",
        "TestSkippedMailNotCountedSent",
        "test_renewal_reminder_inside_cooldown_is_not_logged_or_counted_as_sent",
    ),
    ("verenigingen.tests.test_mail_body_escaping_2307", "TestRenewalReminder", None),
    ("verenigingen.tests.test_mail_body_escaping_2307", "TestExpulsionMails", None),
    ("verenigingen.tests.test_mail_body_escaping_2307", "TestSepaValidationAlert", None),
    ("verenigingen.tests.test_mail_body_escaping_2307", "TestPaymentAlertMails", None),
]


def notification_state():
    """Master switch plus the raw rows (names, flags, cooldowns, stamps), read from the database."""
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
    master = frappe.db.get_single_value(DOCTYPE, "master_email_enabled")
    return master, snapshot_notification_rows()


def _row_summary(rows):
    return {r["notification_key"]: (r["enabled"], r["cooldown_minutes"]) for r in rows}


def run_two_tests(module, class_name, method=None):
    """Run two test methods of a real caller back to back; returns (ran, problems, expected) of that nested run.

    Two, because the harness commits between tests: a restore that put back a state already
    polluted by an earlier setUp is only made permanent by the NEXT test's commit, so a single
    test cannot show it.
    """
    cls = getattr(__import__(module, fromlist=[class_name]), class_name)
    names = unittest.TestLoader().getTestCaseNames(cls)
    first = method or names[0]
    chosen = [first] + [n for n in names if n != first][:1]  # a one-test class runs its one test
    suite = unittest.TestSuite([cls(n) for n in chosen])
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return result.testsRun, result.errors + result.failures, len(chosen)


def _create_canary_state():
    """Master switch 0 and every row at (enabled, cooldown 7777), committed: values no caller writes.

    A site that already holds the value a caller writes (CI's master switch is 1 out of the box, a
    used local site often holds a seeded cooldown of 0) cannot show that write leaking (#2541).
    """
    frappe.db.set_single_value(DOCTYPE, "master_email_enabled", 0)
    frappe.db.sql(
        "update `tabEmail Notification Type` set enabled = 1, cooldown_minutes = 7777 where parent = %s",
        DOCTYPE,
    )
    frappe.db.commit()
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)


def _cleanup_site_state(master, rows):
    restore_notification_rows(rows)
    frappe.db.set_single_value(DOCTYPE, "master_email_enabled", master)
    frappe.db.commit()


class TestNotificationSeedLeak2053(FrappeTestCase):
    def test_no_caller_leaves_notification_state_behind(self):
        master, rows = notification_state()
        self.addCleanup(_cleanup_site_state, master, rows)
        for module, class_name, method in CALLERS:
            with self.subTest(caller=class_name):
                _create_canary_state()  # per caller: an earlier leak must not blind the later ones
                before = notification_state()
                ran, problems, expected = run_two_tests(module, class_name, method)
                self.assertEqual(ran, expected, f"control: {class_name} must really run")
                self.assertEqual(problems, [], f"control: {class_name} must pass on its own")
                after = notification_state()
                self.assertEqual(after[0], before[0], f"{class_name} left the master switch changed")
                self.assertEqual(
                    _row_summary(after[1]),
                    _row_summary(before[1]),
                    f"{class_name} changed registry rows or cooldowns",
                )
                self.assertEqual(after, before, f"{class_name} replaced rows (names or stamps differ)")
