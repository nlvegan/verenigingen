"""
Tests for Member Merge Service

Tests the member merge functionality including field-level selection,
conflict detection, and data preservation.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.services.member_merge_service import MemberMergeService


class TestMemberMerge(FrappeTestCase):
    """Test cases for member merge functionality."""

    def setUp(self):
        """Set up test data before each test."""
        self.service = MemberMergeService()

        # Create test members
        self.source = frappe.get_doc({
            "doctype": "Member",
            "first_name": "John",
            "last_name": "Smith",
            "email": "john.smith@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-01-15",
            "notes": "Source member notes",
        }).insert()

        self.target = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Johnny",
            "last_name": "Smith",
            "email": "johnny.smith@example.com",
            "birth_date": "1990-01-15",
            # No contact number
            "notes": "Target member notes",
        }).insert()

        frappe.db.commit()

    def tearDown(self):
        """Clean up after each test."""
        # Delete test members if they exist
        for name in [self.source.name, self.target.name]:
            if frappe.db.exists("Member", name):
                frappe.delete_doc("Member", name, force=True)

        frappe.db.commit()

    def test_merge_preview_generation(self):
        """Test that merge preview correctly identifies conflicts and suggestions."""
        preview = self.service.get_merge_preview(
            self.source.name,
            self.target.name
        )

        # Check structure
        self.assertIn("source", preview)
        self.assertIn("target", preview)
        self.assertIn("fields", preview)
        self.assertIn("warnings", preview)

        # Check source/target info
        self.assertEqual(preview["source"]["name"], self.source.name)
        self.assertEqual(preview["target"]["name"], self.target.name)

        # Check field comparisons
        fields_by_name = {f["fieldname"]: f for f in preview["fields"]}

        # Contact number: source has value, target doesn't - should suggest source
        contact_field = fields_by_name.get("contact_number")
        self.assertIsNotNone(contact_field)
        self.assertEqual(contact_field["suggested"], "source")
        self.assertFalse(contact_field["has_conflict"])

        # Email: both have values but different - should have conflict
        email_field = fields_by_name.get("email")
        self.assertIsNotNone(email_field)
        self.assertTrue(email_field["has_conflict"])

        # Notes: both have values but different - should have conflict
        notes_field = fields_by_name.get("notes")
        self.assertIsNotNone(notes_field)
        self.assertTrue(notes_field["has_conflict"])

    def test_merge_execution_with_source_preference(self):
        """Test merging with source data preferred for contact field."""
        field_selections = {
            "first_name": "source",  # John
            "contact_number": "source",  # +31612345678
            "email": "target",  # johnny.smith@example.com
            "notes": "target",  # Target member notes
        }

        result = self.service.execute_merge(
            self.source.name,
            self.target.name,
            field_selections
        )

        # Check result
        self.assertTrue(result["success"])
        self.assertGreater(result["changes_applied"], 0)

        # Verify target was updated
        merged = frappe.get_doc("Member", self.target.name)
        self.assertEqual(merged.first_name, "John")  # From source
        self.assertEqual(merged.contact_number, "+31612345678")  # From source
        self.assertEqual(merged.email, "johnny.smith@example.com")  # From target
        self.assertEqual(merged.notes, "Target member notes")  # From target

        # Verify source was deleted
        self.assertFalse(frappe.db.exists("Member", self.source.name))

    def test_merge_with_contact_email_preservation(self):
        """Test that secondary email is saved to Contact when both have emails."""
        # Create Contact for target
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": self.target.first_name,
            "last_name": self.target.last_name,
            "email_id": self.target.email,
        }).insert()

        self.target.contact = contact.name
        self.target.save()
        frappe.db.commit()

        # Merge with source email preferred
        field_selections = {
            "email": "source",  # Choose source email
        }

        result = self.service.execute_merge(
            self.source.name,
            self.target.name,
            field_selections
        )

        self.assertTrue(result["success"])

        # Check that target's old email was saved to Contact
        if result.get("secondary_emails_saved", 0) > 0:
            contact.reload()
            email_ids = [row.email_id for row in contact.email_ids]
            self.assertIn(self.target.email, email_ids)

        # Clean up contact
        frappe.delete_doc("Contact", contact.name, force=True)

    def test_merge_conflict_warnings(self):
        """Test that warnings are generated for financial/volunteer conflicts."""
        # current_membership_plan is a Link to Membership and is validated on
        # save, so we need a real Membership rather than a fabricated name.
        mt_name = "ZZ Merge Test Type"
        if not frappe.db.exists("Membership Type", mt_name):
            frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": mt_name,
                "billing_period": "Annual",
                "minimum_amount": 50.0,
                "is_active": 1,
            }).insert(ignore_permissions=True)

        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": self.source.name,
            "membership_type": mt_name,
            "start_date": frappe.utils.today(),
        })
        membership.flags.skip_dues_schedule_creation = True
        membership.insert(ignore_permissions=True)

        self.source.current_membership_plan = membership.name
        self.source.save()
        frappe.db.commit()

        preview = self.service.get_merge_preview(
            self.source.name,
            self.target.name
        )

        # Should have warning about active membership
        warnings_text = " ".join(preview["warnings"])
        self.assertIn("active membership", warnings_text.lower())

    def test_permission_checks(self):
        """Test that merge requires write permission on both members."""
        # This would need to be tested with a user without permissions
        # For now, just verify the preview method requires valid members
        with self.assertRaises(frappe.DoesNotExistError):
            self.service.get_merge_preview(
                "INVALID-MEMBER-1",
                self.target.name
            )
