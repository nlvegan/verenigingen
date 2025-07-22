import frappe
import unittest
from verenigingen.tests.utils.base import VereningingenTestCase


class TestTemplateValidationSimple(VereningingenTestCase):
    """Simple tests for template assignment validation"""

    def test_new_membership_types_require_template(self):
        """Test that new Membership Types require dues_schedule_template"""
        
        with self.assertRaises((frappe.ValidationError, frappe.MandatoryError)) as context:
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "TEST-Type-No-Template",
                "amount": 10.0,
                "billing_period": "Monthly",
                # Intentionally omitting dues_schedule_template (now required)
            })
            membership_type.insert()
        
        # The error should mention the missing required field
        error_message = str(context.exception)
        self.assertTrue("dues_schedule_template" in error_message.lower() or 
                       "default dues schedule template" in error_message.lower())

    def test_explicit_template_lookup_only(self):
        """Test that only explicit template assignments are used"""
        
        # Create a membership type first (bypass validation to create the base)
        frappe.flags.ignore_validate = True
        try:
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "TEST-Explicit-Only",
                "amount": 10.0,
                "billing_period": "Monthly"
            })
            membership_type.insert()
            self.track_doc("Membership Type", membership_type.name)
        finally:
            frappe.flags.ignore_validate = False

        # Create a template that would match by implicit lookup (old behavior)
        implicit_template = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": "TEST-Implicit-Template",
            "is_template": 1,
            "membership_type": "TEST-Explicit-Only",
            "minimum_amount": 99.0,  # Wrong value to detect if this gets used
            "suggested_amount": 99.0,
            "dues_rate": 99.0,
            "billing_frequency": "Monthly",
            "contribution_mode": "Calculator"
        })
        implicit_template.insert()
        self.track_doc("Membership Dues Schedule", implicit_template.name)

        # Create the CORRECT template for explicit assignment
        explicit_template = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": "TEST-Explicit-Template",
            "is_template": 1,
            "membership_type": "TEST-Explicit-Only",
            "minimum_amount": 5.0,  # Correct value
            "suggested_amount": 10.0,
            "dues_rate": 10.0,
            "billing_frequency": "Monthly",
            "contribution_mode": "Calculator"
        })
        explicit_template.insert()
        self.track_doc("Membership Dues Schedule", explicit_template.name)

        # Now update the membership type to explicitly point to the correct template
        frappe.db.set_value(
            "Membership Type",
            "TEST-Explicit-Only",
            "dues_schedule_template",
            explicit_template.name
        )
        frappe.db.commit()

        # Create test member
        member = self.create_test_member(
            name="TEST-Member-Explicit",
            first_name="Explicit",
            last_name="Template",
            email="explicit.template@example.com"
        )

        # Test that the system uses the EXPLICIT template, not implicit lookup
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
        
        schedule_name = MembershipDuesSchedule.create_from_template(
            member.name,
            membership_type="TEST-Explicit-Only"
        )
        
        self.track_doc("Membership Dues Schedule", schedule_name)
        
        # Verify it used the EXPLICIT template (10.0 values), not implicit (99.0 values)
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(schedule.template_reference, explicit_template.name)
        self.assertEqual(schedule.dues_rate, 10.0)  # Should be from explicit template
        self.assertNotEqual(schedule.dues_rate, 99.0)  # Should NOT be from implicit template

    def test_membership_type_without_template_fails_creation(self):
        """Test that membership type without template fails dues schedule creation"""
        
        # Create membership type without template assignment (bypassing validation)
        frappe.flags.ignore_validate = True
        try:
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "TEST-Type-No-Template-2",
                "amount": 10.0,
                "billing_period": "Monthly"
            })
            membership_type.insert()
            self.track_doc("Membership Type", membership_type.name)
        finally:
            frappe.flags.ignore_validate = False
        
        # Ensure no template assignment
        frappe.db.set_value("Membership Type", "TEST-Type-No-Template-2", "dues_schedule_template", "")
        frappe.db.commit()
        
        # Create test member
        member = self.create_test_member(
            name="TEST-Member-No-Template",
            first_name="No",
            last_name="Template",
            email="no.template@example.com"
        )
        
        # This should FAIL because membership type has no template assigned
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
        
        with self.assertRaises(frappe.ValidationError) as context:
            MembershipDuesSchedule.create_from_template(
                member.name,
                membership_type="TEST-Type-No-Template-2"
            )
        
        error_message = str(context.exception)
        self.assertIn("has no dues schedule template assigned", error_message)
        self.assertIn("TEST-Type-No-Template-2", error_message)


if __name__ == "__main__":
    unittest.main()