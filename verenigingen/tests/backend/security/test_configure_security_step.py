# Tests for the security-configuration onboarding step's whitelisted endpoints.
#
# Both endpoints in this module used to raise AttributeError on every call:
#
#   * get_security_configuration_guide() did frappe.get_doc("Onboarding Step", ...)
#     and called get_security_checklist() on it. That method lived on a
#     VereningingenConfigureSecurity(Document) class in the module's *fixture*
#     directory, which Frappe never binds as a controller -- "Onboarding Step" is
#     a Frappe doctype and is not in override_doctype_class. The doc that came
#     back was a plain frappe OnboardingStep with no such method.
#   * validate_security_configuration() read SystemSettings.enable_version_control,
#     a field that does not exist in Frappe v16.
#
# The guide endpoint and its checklist were deleted rather than repaired: every
# issue they described had already been fixed, and two of the doctypes they told
# administrators to reconfigure do not exist. validate_security_configuration()
# was kept because it inspects live permission state and is a real regression
# detector, so these tests pin that it runs and what it reports on.

import frappe
from frappe.tests.utils import FrappeTestCase

import verenigingen.verenigingen.onboarding_step.verenigingen_configure_security.verenigingen_configure_security as mod


class TestValidateSecurityConfiguration(FrappeTestCase):
    """validate_security_configuration() — inspects live permission state."""

    def test_returns_envelope_without_raising(self):
        # The regression: this raised AttributeError on every call.
        result = mod.validate_security_configuration()
        self.assertIsInstance(result, dict)
        self.assertEqual(
            set(result), {"configuration_complete", "issues_remaining", "next_steps"}
        )
        self.assertIsInstance(result["issues_remaining"], list)
        self.assertIsInstance(result["configuration_complete"], bool)

    def test_does_not_report_the_removed_global_setting(self):
        """The dead check must not come back.

        System Settings has no version-tracking field in v16, so a check against
        one can only ever fire spuriously. Per-doctype track_changes is the real
        mechanism and is asserted separately below.
        """
        issues = mod.validate_security_configuration()["issues_remaining"]
        self.assertNotIn(
            "Version tracking is disabled",
            [i["issue"] for i in issues],
            "the global System Settings check was removed and must not return",
        )

    def test_reports_guest_read_access_to_member(self):
        """Positive control: the guest-access check must actually be able to fire.

        Without this, a permanently-empty issues list would pass every other
        assertion here.
        """
        baseline = [
            i["issue"] for i in mod.validate_security_configuration()["issues_remaining"]
        ]
        self.assertNotIn(
            "Guest users still have read access to Member records",
            baseline,
            "precondition: Guest must not already hold read on Member",
        )

        # Insert the DocPerm row directly rather than saving the Member DocType:
        # that document carries a permission row pointing at "Volunteer Expense",
        # which is not installed, so a full save dies on an unrelated broken link.
        frappe.get_doc(
            {
                "doctype": "DocPerm",
                "parent": "Member",
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": "Guest",
                "permlevel": 0,
                "read": 1,
            }
        ).insert()
        try:
            issues = [
                i["issue"] for i in mod.validate_security_configuration()["issues_remaining"]
            ]
            self.assertIn(
                "Guest users still have read access to Member records",
                issues,
                "granting Guest read on Member must be detected",
            )
        finally:
            frappe.db.rollback()

    def test_reports_doctype_without_change_tracking(self):
        """Positive control for the per-doctype track_changes check."""
        self.assertTrue(
            frappe.get_meta("Member").track_changes,
            "precondition: Member should track changes",
        )

        # Written straight to the row for the same reason as above: saving the
        # Member DocType trips a broken link unrelated to this test.
        frappe.db.set_value("DocType", "Member", "track_changes", 0, update_modified=False)
        frappe.clear_cache(doctype="Member")
        try:
            issues = [
                i["issue"] for i in mod.validate_security_configuration()["issues_remaining"]
            ]
            self.assertIn(
                "Member DocType does not have change tracking enabled",
                issues,
                "disabling track_changes on Member must be detected",
            )
        finally:
            frappe.db.rollback()
            frappe.clear_cache(doctype="Member")


class TestDeletedGuideEndpoint(FrappeTestCase):
    """The stale checklist and its unreachable controller are gone for good."""

    def test_guide_endpoint_and_dead_controller_are_removed(self):
        # Both named a security posture that no longer exists and instructed
        # admins to reconfigure doctypes ("Volunteer Expense", "Verenigingen
        # Volunteer") that are not installed. Re-adding either should be a
        # deliberate act, not an accident.
        self.assertFalse(hasattr(mod, "get_security_configuration_guide"))
        self.assertFalse(hasattr(mod, "VereningingenConfigureSecurity"))
