"""#2592: test_membership_analytics_permissions must not leave its five fixed-email Users behind.

Its `setUpClass` builds `admin@`, `manager@`, `board@`, `member@` and `norole@test.com` and commits.
Nothing removed them, so the first run on a site left five Users (later runs reuse them, which is
why a re-run shows +0) and a CI shard carried them into every later module.

The class is driven through a manually-built suite (the device used by the #2561 sibling test) so
its class-level cleanups have run by the time we look. The Users are deleted first, so a run that
merely reuses them cannot hide a leak.
"""

import io
import unittest

import frappe

from verenigingen.tests.backend.components import test_membership_analytics_permissions as analytics
from verenigingen.tests.utils.base import VereningingenTestCase


class TestAnalyticsPermissionsLeavesNoUsers(VereningingenTestCase):
    def test_class_run_leaves_none_of_its_users_behind_2592(self):
        klass = analytics.TestMembershipAnalyticsPermissions
        klass._cleanup_analytics_users()
        self.addCleanup(klass._cleanup_analytics_users)

        suite = unittest.TestSuite()
        suite.addTest(klass("test_analytics_page_access"))
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), f"control: the driven class must pass: {result.errors}")

        self.assertEqual(
            {
                klass.admin_user,
                klass.manager_user,
                klass.board_member_user,
                klass.regular_member_user,
                klass.no_role_user,
            },
            set(klass.ANALYTICS_USERS),
            "control: the users setUpClass created are exactly the ones the cleanup deletes",
        )
        # Read from a fresh transaction view: the class cleanup commits its delete.
        frappe.db.rollback()
        leaked = [email for email in klass.ANALYTICS_USERS if frappe.db.exists("User", email)]
        self.assertEqual(leaked, [], "the class left its fixed-email Users behind")
