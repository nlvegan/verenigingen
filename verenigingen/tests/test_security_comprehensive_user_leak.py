"""#2561: test_security_comprehensive must not leave its four fixed-email Users behind.

Its `setUpClass` builds `sec_admin@`, `sec_chapter1@`, `sec_chapter2@` and `sec_user@test.com`
through a raw `User.insert` and commits. Nothing tracked them, so the first run on a site left four
Users (the later runs reuse them, which is why a re-run shows +0) and a CI shard carried them into
every later module.

The class is driven through a manually-built suite (the same device as
`test_harness_drains_survive_setup_failure`) so its class-level cleanups have run by the time
we look. The Users are deleted first, so a run that merely reuses them cannot hide a leak.
"""

import io
import unittest

import frappe

from verenigingen.tests.backend.security import test_security_comprehensive
from verenigingen.tests.utils.base import VereningingenTestCase

SECURITY_USERS = test_security_comprehensive.TestSecurityComprehensive.SECURITY_USERS


class TestSecurityComprehensiveLeavesNoUsers(VereningingenTestCase):
    def test_class_run_leaves_none_of_its_users_behind_2561(self):
        test_security_comprehensive.TestSecurityComprehensive._cleanup_security_users()
        self.addCleanup(test_security_comprehensive.TestSecurityComprehensive._cleanup_security_users)

        suite = unittest.TestSuite()
        suite.addTest(test_security_comprehensive.TestSecurityComprehensive("test_privilege_escalation_role_manipulation"))
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), f"control: the driven class must pass: {result.errors}")

        klass = test_security_comprehensive.TestSecurityComprehensive
        self.assertEqual(
            {klass.admin_user, klass.chapter1_admin, klass.chapter2_admin, klass.regular_user},
            set(SECURITY_USERS),
            "control: the users setUpClass created are exactly the ones the cleanup deletes",
        )
        # Read from a fresh transaction view: the class cleanup commits its delete.
        frappe.db.rollback()
        leaked = [email for email in SECURITY_USERS if frappe.db.exists("User", email)]
        self.assertEqual(leaked, [], "the class left its fixed-email Users behind")
