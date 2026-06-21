"""
Coverage tests for two admin www/ portal pages.

Pages covered:
  * verenigingen/www/batch_optimizer.py     (route: /batch-optimizer)
  * verenigingen/www/email_group_admin.py   (route: /email-group-admin)

Both controllers were previously shipped with HYPHENATED filenames
(batch-optimizer.py / email-group-admin.py). Frappe's TemplatePage resolves a
www template's controller by converting hyphens in the template basename to
underscores, so the hyphenated controller files were never imported and the
permission gate / context never ran. The fix renamed them to the underscored
module names; these tests assert the now-LIVE behaviour by importing the
controllers as normal modules and driving get_context with real users/roles.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.www import batch_optimizer, email_group_admin


class TestBatchOptimizerPage(VereningingenTestCase):
    """www/batch_optimizer.py - LIVE SEPA batch optimizer page."""

    def setUp(self):
        super().setUp()
        self.admin_user = self.create_test_user("batchopt-admin@example.com", roles=["System Manager"])
        self.plain_user = self.create_test_user("batchopt-plain@example.com", roles=["Verenigingen Member"])

    def test_get_context_populates_config_and_chrome_for_admin(self):
        """get_context populates the real batch-optimization config + page chrome.

        current_config must be a populated dict so the template's
        {{ current_config.* }} references resolve (the old orphaned controller
        left it unset -> Jinja UndefinedError on the live page).
        """
        with self.set_user(self.admin_user.name):
            context = frappe._dict()
            with self.assertNoErrorLog():
                batch_optimizer.get_context(context)

        self.assertEqual(context.title, "SEPA Direct Debit Batch Optimizer")
        self.assertEqual(context.parents[0]["name"], "financial-management")

        # current_config is the real default config carrying the batch-sizing
        # knobs the template renders -- it must NOT be empty/None.
        self.assertIsInstance(context.current_config, dict)
        self.assertTrue(context.current_config, "current_config must be populated")
        self.assertIn("max_amount_per_batch", context.current_config)
        self.assertIn("max_invoices_per_batch", context.current_config)
        # Real numeric defaults (not blanks).
        self.assertGreater(context.current_config["max_amount_per_batch"], 0)
        self.assertGreater(context.current_config["max_invoices_per_batch"], 0)

        # System Manager => can_approve.
        self.assertIn("System Manager", context.user_roles)
        self.assertTrue(context.can_approve)

    def test_get_context_denies_user_without_dd_permission(self):
        """A member without Direct Debit Batch create permission is thrown out.

        The gate now actually runs (it never did while the controller was
        orphaned). The controller uses a bare frappe.throw() -> ValidationError.
        """
        with self.set_user(self.plain_user.name):
            context = frappe._dict()
            with self.assertRaises(frappe.ValidationError) as cm:
                batch_optimizer.get_context(context)
            self.assertIn("permission", str(cm.exception).lower())


class TestEmailGroupAdminPage(VereningingenTestCase):
    """www/email_group_admin.py - LIVE page with a now-enforced permission gate."""

    def setUp(self):
        super().setUp()
        self.staff_user = self.create_test_user("egadmin-staff@example.com", roles=["Verenigingen Staff"])
        self.plain_user = self.create_test_user("egadmin-plain@example.com", roles=["Verenigingen Member"])

    def test_gate_allows_staff_and_sets_chrome(self):
        """The gate now runs and permits Verenigingen Staff, setting page chrome."""
        with self.set_user(self.staff_user.name):
            context = frappe._dict()
            with self.assertNoErrorLog():
                email_group_admin.get_context(context)

        self.assertEqual(context.no_cache, 1)
        self.assertFalse(context.show_sidebar)
        self.assertEqual(context.parents[0]["name"], "Home")

    def test_gate_allows_system_manager(self):
        """System Manager is the other permitted role."""
        admin = self.create_test_user("egadmin-sysmgr@example.com", roles=["System Manager"])
        with self.set_user(admin.name):
            context = frappe._dict()
            with self.assertNoErrorLog():
                email_group_admin.get_context(context)
        self.assertEqual(context.no_cache, 1)

    def test_gate_denies_plain_member(self):
        """The gate now ACTUALLY enforces: a non-staff member is denied.

        Previously the orphaned controller never ran, so the page shell was
        served ungated. With the rename the PermissionError gate is live.
        """
        with self.set_user(self.plain_user.name):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                email_group_admin.get_context(context)
