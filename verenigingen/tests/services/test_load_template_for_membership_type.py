# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for load_template_for_membership_type() helper function.

Covers:
- Happy path: string name and document inputs
- Error path: required=True with no template throws
- Graceful path: required=False with no template returns None
- Return value: correct template document returned
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.billing.template_configuration_service import (
    load_template_for_membership_type,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestLoadTemplateForMembershipType(EnhancedTestCase):
    """Tests for the centralized template loading helper."""

    def setUp(self):
        super().setUp()
        # Create a membership type WITH a template (the default)
        self.membership_type_with_template = self.create_test_membership_type(
            membership_type_name="WithTemplate", amount=50.0
        )

    def _create_membership_type_without_template(self):
        """Create a bare Membership Type with no dues_schedule_template."""
        import time

        unique_name = f"NoTemplate-{int(time.time() * 1000)}"

        role_profile = frappe.db.get_value("Role Profile", {"name": "Verenigingen Member"})
        if not role_profile:
            test_profile = frappe.new_doc("Role Profile")
            test_profile.role_profile = "Test Member Profile"
            if frappe.db.exists("Role", "Verenigingen Member"):
                test_profile.append("roles", {"role": "Verenigingen Member"})
            test_profile.insert(ignore_permissions=True)
            role_profile = test_profile.name
            self.factory.track_document("Role Profile", role_profile, priority=0)

        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = unique_name
        mt.is_active = 1
        mt.minimum_amount = 10.0
        mt.role_profile = role_profile
        mt.contribution_mode = "Fixed Amount"
        mt.flags.ignore_after_insert_template_creation = True
        mt.insert(ignore_permissions=True)
        self.factory.track_document("Membership Type", mt.name, priority=1)

        # Force-clear the template link in case after_insert set one
        if mt.dues_schedule_template:
            mt.db_set("dues_schedule_template", None)
            mt.reload()

        return mt

    # --- Happy path ---

    def test_returns_template_document_from_doc_input(self):
        """Passing a Membership Type document returns the linked template."""
        template = load_template_for_membership_type(self.membership_type_with_template)

        self.assertIsNotNone(template)
        self.assertEqual(template.doctype, "Membership Dues Schedule")
        self.assertEqual(template.name, self.membership_type_with_template.dues_schedule_template)

    def test_returns_template_document_from_string_input(self):
        """Passing a Membership Type name string returns the linked template."""
        template = load_template_for_membership_type(self.membership_type_with_template.name)

        self.assertIsNotNone(template)
        self.assertEqual(template.doctype, "Membership Dues Schedule")
        self.assertEqual(template.name, self.membership_type_with_template.dues_schedule_template)

    def test_template_has_expected_fields(self):
        """Returned template document has the key billing fields."""
        template = load_template_for_membership_type(self.membership_type_with_template)

        self.assertTrue(hasattr(template, "suggested_amount"))
        self.assertTrue(hasattr(template, "dues_rate"))
        self.assertTrue(hasattr(template, "billing_frequency"))
        self.assertTrue(hasattr(template, "minimum_amount"))

    # --- Error path: required=True (default) ---

    def test_required_true_throws_when_no_template(self):
        """Default required=True throws ValidationError when no template assigned."""
        mt = self._create_membership_type_without_template()

        with self.assertRaises(frappe.ValidationError) as ctx:
            load_template_for_membership_type(mt)

        self.assertIn("has no dues schedule template assigned", str(ctx.exception))
        self.assertIn(mt.name, str(ctx.exception))

    def test_required_true_throws_from_string_input(self):
        """required=True throws even when given a string name."""
        mt = self._create_membership_type_without_template()

        with self.assertRaises(frappe.ValidationError):
            load_template_for_membership_type(mt.name)

    # --- Graceful path: required=False ---

    def test_required_false_returns_none_when_no_template(self):
        """required=False returns None instead of throwing."""
        mt = self._create_membership_type_without_template()

        result = load_template_for_membership_type(mt, required=False)

        self.assertIsNone(result)

    def test_required_false_still_returns_template_when_present(self):
        """required=False still returns the template when one exists."""
        template = load_template_for_membership_type(
            self.membership_type_with_template, required=False
        )

        self.assertIsNotNone(template)
        self.assertEqual(template.name, self.membership_type_with_template.dues_schedule_template)

    # --- Edge cases ---

    def test_nonexistent_membership_type_string_throws(self):
        """Passing a nonexistent Membership Type name throws DoesNotExistError."""
        with self.assertRaises(frappe.DoesNotExistError):
            load_template_for_membership_type("Nonexistent-Type-999999")
