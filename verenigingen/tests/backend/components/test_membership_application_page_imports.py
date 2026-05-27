"""
Regression tests for membership application page imports.

Background: `get_membership_types_with_contributions` was promoted from a
module-level helper in `templates.pages.membership_application` to an instance
method on `MembershipApplicationService`. Two callers continued to import the
module-level symbol — one silently degraded to a fallback, the other hard-failed
on page load.

These tests pin the canonical service-accessor pattern at both call sites so a
future regression surfaces immediately.
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipApplicationPageImports(EnhancedTestCase):
    def test_apply_for_membership_get_context_resolves_imports(self):
        """`/apply_for_membership` page load must not raise ImportError."""
        from verenigingen.templates.pages.apply_for_membership import get_context

        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            context = frappe._dict()
            result = get_context(context)
        finally:
            frappe.set_user(original_user)

        self.assertIn("enhanced_membership_types", result)
        self.assertIsInstance(result.enhanced_membership_types, list)

    def test_get_form_data_uses_service_path(self):
        """`get_form_data` must reach the service accessor, not the fallback.

        The service path enriches each membership type with `contribution_options`;
        the bare-except fallback only adds `billing_frequency`. Asserting on
        `contribution_options` confirms the import resolved.
        """
        from verenigingen.services.member.approval.application_helpers import get_form_data

        result = get_form_data()

        self.assertTrue(result["success"], f"get_form_data failed: {result}")
        if result["membership_types"]:
            for mt in result["membership_types"]:
                self.assertIn(
                    "contribution_options",
                    mt,
                    "Fallback path ran — service import is broken again",
                )
