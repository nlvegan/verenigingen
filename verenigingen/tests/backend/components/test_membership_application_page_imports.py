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
    def setUp(self):
        super().setUp()
        # Seed at least one active Membership Type. Without this, both tests below
        # would have vacuous-pass paths on a bare site: an empty list satisfies
        # `isinstance(..., list)` and skips the `contribution_options` for-loop.
        self.test_membership_type = self.create_test_membership_type()

    def test_apply_for_membership_get_context_resolves_imports(self):
        """`/apply_for_membership` page load must not raise ImportError and must
        reach the service path (not silently fall back to an empty list)."""
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
        # setUp seeded a Membership Type — service path must surface it.
        self.assertGreater(
            len(result.enhanced_membership_types),
            0,
            "Expected at least the setUp-seeded membership type in service output",
        )
        # Service path enriches each entry with contribution_options; the gone
        # module-level function would have raised ImportError before reaching here.
        for mt in result.enhanced_membership_types:
            self.assertIn("contribution_options", mt)

    def test_get_form_data_uses_service_path(self):
        """`get_form_data` must reach the service accessor, not the fallback.

        Service path enriches each membership type with `contribution_options`;
        the bare-except fallback only adds `billing_frequency`. Asserting on
        `contribution_options` confirms the import resolved.
        """
        from verenigingen.services.member.approval.application_helpers import get_form_data

        result = get_form_data()

        self.assertTrue(result["success"], f"get_form_data failed: {result}")
        # setUp seeded a Membership Type — a vacuous-pass guard would hide a
        # regression of the service import back to the silent fallback (the
        # fallback returns success=True with the same shape).
        self.assertGreater(
            len(result["membership_types"]),
            0,
            "Expected at least the setUp-seeded membership type in form data",
        )
        for mt in result["membership_types"]:
            self.assertIn(
                "contribution_options",
                mt,
                "Fallback path ran — service import is broken again",
            )
