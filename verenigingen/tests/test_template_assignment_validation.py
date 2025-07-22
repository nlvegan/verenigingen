import frappe
import unittest
from verenigingen.tests.utils.base import VereningingenTestCase


class TestTemplateAssignmentValidation(VereningingenTestCase):
    """Tests that enforce proper template assignment and fail when fields aren't populated correctly"""

    def setUp(self):
        super().setUp()
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Clean up any existing test data"""
        test_names = [
            "TEST-Template-Validation",
            "TEST-Type-No-Template",
            "TEST-Type-With-Template",
            "TEST-Member-Template-Val"
        ]
        
        for name in test_names:
            frappe.db.delete("Membership Dues Schedule", {"name": name})
            frappe.db.delete("Membership Type", {"name": name})
            frappe.db.delete("Member", {"name": name})
            frappe.db.delete("Membership", {"member": name})
        
        frappe.db.commit()

    def test_membership_type_requires_template(self):
        """Test that Membership Type creation fails without dues_schedule_template"""
        
        with self.assertRaises(frappe.MandatoryError) as context:
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "TEST-Type-No-Template",
                "minimum_amount": 10.0,
                "billing_period": "Monthly",
                # Intentionally omitting dues_schedule_template (now required)
            })
            membership_type.insert()
        
        # Verify the error mentions the required field
        error_message = str(context.exception)
        self.assertIn("dues_schedule_template", error_message)
        
    def test_membership_type_with_invalid_template_fails(self):
        """Test that Membership Type creation fails with non-existent template"""
        
        with self.assertRaises(frappe.LinkValidationError):
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "TEST-Type-Invalid-Template",
                "minimum_amount": 10.0,
                "billing_period": "Monthly",
                "dues_schedule_template": "NON-EXISTENT-TEMPLATE"
            })
            membership_type.insert()

    def test_create_from_template_fails_without_template_assignment(self):
        """Test that create_from_template fails when membership type has no template"""
        
        # Create membership type WITHOUT template assignment (simulating old data)
        # We need to bypass the new validation temporarily for this test
        membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type_name": "TEST-Type-No-Template", 
            "minimum_amount": 10.0,
            "billing_period": "Monthly",
            # Intentionally NOT setting dues_schedule_template
        })
        membership_type.flags.ignore_mandatory = True
        membership_type.insert()
        self.track_doc("Membership Type", membership_type.name)
        
        # Manually clear the template field to simulate problematic data
        frappe.db.set_value("Membership Type", "TEST-Type-No-Template", "dues_schedule_template", "")
        frappe.db.commit()
        
        # Create a template (for testing - but membership type won't reference it)
        template = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": "TEST-Template-Validation",
            "is_template": 1,
            "membership_type": "TEST-Type-No-Template",
            "minimum_amount": 5.0,
            "suggested_amount": 10.0,
            "dues_rate": 10.0,
            "billing_frequency": "Monthly",
            "contribution_mode": "Calculator"
        })
        template.insert()
        self.track_doc("Membership Dues Schedule", template.name)
        
        # Create test member
        member = self.create_test_member(
            name="TEST-Member-Template-Val",
            first_name="Template",
            last_name="Validation",
            email="template.validation@example.com"
        )
        
        # This should FAIL because membership type has no template assigned
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
        
        with self.assertRaises(frappe.ValidationError) as context:
            MembershipDuesSchedule.create_from_template(
                member.name, 
                membership_type="TEST-Type-No-Template"
            )
        
        error_message = str(context.exception)
        self.assertIn("has no dues schedule template assigned", error_message)
        self.assertIn("TEST-Type-No-Template", error_message)

    def test_create_from_template_succeeds_with_proper_template(self):
        """Test that create_from_template works when membership type has proper template"""
        
        # Create membership type first (without template reference)
        membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type_name": "TEST-Type-With-Template",
            "minimum_amount": 10.0,
            "billing_period": "Monthly",
        })
        membership_type.flags.ignore_mandatory = True
        membership_type.insert()
        self.track_doc("Membership Type", membership_type.name)
        
        # Create a proper template
        template = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": "TEST-Template-Validation",
            "is_template": 1,
            "membership_type": "TEST-Type-With-Template",
            "minimum_amount": 5.0,
            "suggested_amount": 10.0,
            "dues_rate": 10.0,
            "billing_frequency": "Monthly",
            "contribution_mode": "Calculator"
        })
        template.insert()
        self.track_doc("Membership Dues Schedule", template.name)
        
        # Update membership type with template reference
        membership_type.dues_schedule_template = template.name
        membership_type.save()
        
        # Create test member
        member = self.create_test_member(
            name="TEST-Member-Template-Val",
            first_name="Template",
            last_name="Validation",
            email="template.validation@example.com"
        )
        
        # This should SUCCEED because membership type has proper template
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
        
        schedule_name = MembershipDuesSchedule.create_from_template(
            member.name,
            membership_type="TEST-Type-With-Template"
        )
        
        self.assertIsNotNone(schedule_name)
        self.track_doc("Membership Dues Schedule", schedule_name)
        
        # Verify the schedule was created with correct template reference
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(schedule.template_reference, template.name)
        self.assertEqual(schedule.membership_type, "TEST-Type-With-Template")
        self.assertEqual(schedule.member, member.name)

    def test_membership_creation_fails_without_proper_template(self):
        """Test that membership submission fails if membership type lacks template"""
        
        # Create membership type without template (bypassing validation)
        membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type_name": "TEST-Type-No-Template",
            "minimum_amount": 10.0,
            "billing_period": "Monthly",
        })
        membership_type.flags.ignore_mandatory = True
        membership_type.insert()
        self.track_doc("Membership Type", membership_type.name)
        
        # Manually clear the template field
        frappe.db.set_value("Membership Type", "TEST-Type-No-Template", "dues_schedule_template", "")
        frappe.db.commit()
        
        # Create test member
        member = self.create_test_member(
            name="TEST-Member-Template-Val",
            first_name="Template", 
            last_name="Validation",
            email="template.validation@example.com"
        )
        
        # Create membership
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member.name,
            "membership_type": "TEST-Type-No-Template",
            "start_date": frappe.utils.today(),
            "status": "Active"
        })
        membership.insert()
        self.track_doc("Membership", membership.name)
        
        # Submission should FAIL because it tries to create dues schedule
        # but membership type has no template assigned
        with self.assertRaises(frappe.ValidationError) as context:
            membership.submit()
        
        error_message = str(context.exception)
        self.assertIn("has no dues schedule template assigned", error_message)

    def test_no_implicit_template_lookup(self):
        """Test that the system no longer does implicit template lookup by membership type"""
        
        # Create membership type first
        membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type_name": "TEST-Type-Implicit",
            "minimum_amount": 10.0,
            "billing_period": "Monthly", 
        })
        membership_type.flags.ignore_mandatory = True
        membership_type.insert()
        self.track_doc("Membership Type", membership_type.name)
        
        # Create a template with matching membership_type field (old implicit lookup style)
        implicit_template = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": "TEST-Implicit-Template",
            "is_template": 1,
            "membership_type": "TEST-Type-Implicit", 
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
            "membership_type": "TEST-Type-Implicit",
            "minimum_amount": 5.0,  # Correct value
            "suggested_amount": 10.0,
            "dues_rate": 10.0,
            "billing_frequency": "Monthly",
            "contribution_mode": "Calculator"
        })
        explicit_template.insert()
        self.track_doc("Membership Dues Schedule", explicit_template.name)
        
        # Update membership type that explicitly points to the correct template
        membership_type.dues_schedule_template = explicit_template.name  # Explicit assignment
        membership_type.save()
        
        # Create test member
        member = self.create_test_member(
            name="TEST-Member-Template-Val",
            first_name="Template",
            last_name="Validation", 
            email="template.validation@example.com"
        )
        
        # Create schedule - should use EXPLICIT template, not implicit lookup
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import MembershipDuesSchedule
        
        schedule_name = MembershipDuesSchedule.create_from_template(
            member.name,
            membership_type="TEST-Type-Implicit"
        )
        
        self.track_doc("Membership Dues Schedule", schedule_name)
        
        # Verify it used the EXPLICIT template (10.0 values), not implicit (99.0 values)
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(schedule.template_reference, explicit_template.name)
        self.assertEqual(schedule.dues_rate, 10.0)  # Should be from explicit template
        self.assertNotEqual(schedule.dues_rate, 99.0)  # Should NOT be from implicit template
        
    def tearDown(self):
        """Clean up test data"""
        super().tearDown()
        self.cleanup_test_data()


if __name__ == "__main__":
    unittest.main()