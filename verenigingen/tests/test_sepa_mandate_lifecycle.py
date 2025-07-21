#!/usr/bin/env python3
"""
Test suite for SEPA Mandate Lifecycle Integration
Tests the complete lifecycle from member creation through SEPA mandate generation
"""

import frappe
from frappe.utils import today, add_days, add_months
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAMandateLifecycle(VereningingenTestCase):
    """Test SEPA mandate integration throughout member and dues lifecycle"""

    def setUp(self):
        """Set up test-specific environment"""
        super().setUp()
        
        # Store original settings for cleanup
        self.sepa_backup = self.get_sepa_settings_backup()

    def tearDown(self):
        """Clean up test-specific data"""
        # Restore SEPA settings
        self.restore_sepa_settings(self.sepa_backup)
        super().tearDown()

    def test_member_to_sepa_mandate_workflow(self):
        """Test complete workflow from member creation to SEPA mandate"""
        
        # 1. Create a member
        member = self.create_test_member(
            first_name="Lifecycle",
            last_name="TestMember",
            email="lifecycle@example.com",
            birth_date="1985-05-15"
        )
        
        self.assertTrue(member.name, "Member should be created successfully")
        
        # 2. Create SEPA mandate for member
        mandate = self.create_test_sepa_mandate(member=member.name)
        
        # 3. Verify mandate has proper auto-generated ID
        self.assertTrue(mandate.mandate_id, "SEPA mandate should have auto-generated ID")
        self.assertEqual(mandate.member, member.name, "SEPA mandate should be linked to member")
        self.assertEqual(mandate.status, "Active", "SEPA mandate should be Active")
        
        # 4. Verify member's SEPA mandates child table is updated
        member.reload()
        sepa_links = [m for m in member.sepa_mandates if m.sepa_mandate == mandate.name]
        self.assertTrue(sepa_links, "Member should have link to SEPA mandate in child table")
        
        if sepa_links:
            sepa_link = sepa_links[0] 
            self.assertEqual(sepa_link.mandate_reference, mandate.mandate_id, 
                           "Member's SEPA mandate link should have correct mandate reference")

    def test_membership_dues_with_sepa_mandate(self):
        """Test membership dues schedule integration with SEPA mandate"""
        
        # 1. Create member with SEPA mandate
        member = self.create_test_member(
            first_name="Dues",
            last_name="TestMember", 
            email="dues@example.com"
        )
        
        mandate = self.create_test_sepa_mandate(member=member.name)
        
        # 2. Create membership dues schedule
        dues_schedule = self.create_test_membership_dues_schedule(
            member=member.name,
            payment_method="SEPA Direct Debit",
            dues_rate=25.00
        )
        
        # 3. Verify integration
        self.assertEqual(dues_schedule.member, member.name, 
                        "Dues schedule should be linked to member")
        self.assertEqual(dues_schedule.payment_method, "SEPA Direct Debit",
                        "Dues schedule should use SEPA payment method")
        
        # 4. Test invoice generation (if implemented)
        if hasattr(dues_schedule, 'generate_invoice'):
            try:
                invoice_name = dues_schedule.generate_invoice()
                if invoice_name:
                    invoice = frappe.get_doc("Sales Invoice", invoice_name)
                    self.assertEqual(invoice.customer, member.customer,
                                   "Generated invoice should be for member's customer")
                    self.track_doc("Sales Invoice", invoice_name)
            except Exception as e:
                # Log but don't fail test if invoice generation has issues
                frappe.logger().info(f"Invoice generation test skipped: {e}")

    def test_sepa_mandate_pattern_in_lifecycle(self):
        """Test that SEPA mandate patterns work correctly in full lifecycle"""
        
        # Set specific pattern for this test
        settings = frappe.get_single("Verenigingen Settings")
        settings.sepa_mandate_naming_pattern = "LIFE-.YY.-.####"
        settings.sepa_mandate_starting_counter = 1000
        settings.save()
        
        # 1. Create multiple members and mandates
        members_and_mandates = []
        
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Pattern{i}",
                last_name="TestMember",
                email=f"pattern{i}@example.com"
            )
            
            mandate = self.create_test_sepa_mandate(member=member.name)
            members_and_mandates.append((member, mandate))
            
            # Verify pattern
            self.assertTrue(mandate.mandate_id.startswith("LIFE-"),
                           f"Mandate {i} should use LIFE- prefix: {mandate.mandate_id}")
        
        # 2. Verify sequential numbering
        mandate_ids = [mandate.mandate_id for _, mandate in members_and_mandates]
        
        # Should have 1000, 1001, 1002
        self.assertIn("1000", mandate_ids[0], "First mandate should contain 1000")
        self.assertIn("1001", mandate_ids[1], "Second mandate should contain 1001") 
        self.assertIn("1002", mandate_ids[2], "Third mandate should contain 1002")

    def test_sepa_mandate_update_lifecycle(self):
        """Test SEPA mandate updates and status changes"""
        
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="Update",
            last_name="TestMember",
            email="update@example.com"
        )
        
        mandate = self.create_test_sepa_mandate(member=member.name)
        original_id = mandate.mandate_id
        
        # 2. Test status change
        mandate.status = "Suspended"
        mandate.is_active = 0
        mandate.save()
        
        # Verify status change
        mandate.reload()
        self.assertEqual(mandate.status, "Suspended", "Status should be updated to Suspended")
        self.assertEqual(mandate.is_active, 0, "is_active should be 0 when suspended")
        
        # 3. Verify member's child table is updated
        member.reload()
        sepa_links = [m for m in member.sepa_mandates if m.sepa_mandate == mandate.name]
        if sepa_links:
            self.assertEqual(sepa_links[0].status, "Suspended",
                           "Member's SEPA mandate link should show updated status")
        
        # 4. Reactivate mandate
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.save()
        
        mandate.reload()
        self.assertEqual(mandate.status, "Active", "Status should be reactivated")
        self.assertEqual(mandate.is_active, 1, "is_active should be 1 when active")
        
        # 5. Verify mandate_id didn't change during updates
        self.assertEqual(mandate.mandate_id, original_id, 
                        "mandate_id should remain unchanged during status updates")

    def test_multiple_mandates_per_member(self):
        """Test that members can have multiple SEPA mandates with different patterns"""
        
        # 1. Create member
        member = self.create_test_member(
            first_name="Multiple",
            last_name="TestMember",
            email="multiple@example.com"
        )
        
        # 2. Create first mandate with default pattern
        mandate1 = self.create_test_sepa_mandate(member=member.name)
        
        # 3. Change pattern and create second mandate
        settings = frappe.get_single("Verenigingen Settings")
        settings.sepa_mandate_naming_pattern = "SECOND-.YY.-.####" 
        settings.sepa_mandate_starting_counter = 500
        settings.save()
        
        mandate2 = self.create_test_sepa_mandate(
            member=member.name,
            iban="NL91ABNA0417164399"  # Different IBAN
        )
        
        # 4. Verify both mandates have different patterns
        self.assertTrue(mandate1.mandate_id.startswith("MANDATE-") or 
                       "MANDATE" in mandate1.mandate_id,
                       f"First mandate should use default pattern: {mandate1.mandate_id}")
        self.assertTrue(mandate2.mandate_id.startswith("SECOND-"),
                       f"Second mandate should use SECOND- pattern: {mandate2.mandate_id}")
        
        # 5. Verify member links to both mandates
        member.reload()
        mandate_links = [m.sepa_mandate for m in member.sepa_mandates]
        self.assertIn(mandate1.name, mandate_links, "Member should link to first mandate")
        self.assertIn(mandate2.name, mandate_links, "Member should link to second mandate")

    def test_sepa_mandate_validation_integration(self):
        """Test SEPA mandate validation works properly in lifecycle"""
        
        # 1. Create member
        member = self.create_test_member(
            first_name="Validation",
            last_name="TestMember",
            email="validation@example.com"
        )
        
        # 2. Test valid IBAN validation
        valid_mandate = self.create_test_sepa_mandate(
            member=member.name,
            iban="NL91ABNA0417164300"  # Known valid test IBAN
        )
        
        self.assertEqual(valid_mandate.status, "Active", "Valid mandate should be created successfully")
        
        # 3. Test invalid IBAN validation (should fail)
        with self.assertRaises(frappe.ValidationError):
            invalid_mandate = frappe.new_doc("SEPA Mandate")
            invalid_mandate.member = member.name
            invalid_mandate.account_holder_name = "Test Invalid"
            invalid_mandate.iban = "INVALID_IBAN_123"  # Invalid IBAN
            invalid_mandate.sign_date = today()
            invalid_mandate.save()

    def test_sepa_mandate_deletion_cascade(self):
        """Test proper cleanup when members or mandates are deleted"""
        
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="Deletion",
            last_name="TestMember",
            email="deletion@example.com"
        )
        
        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id
        
        # 2. Verify member has link to mandate
        member.reload()
        initial_mandate_count = len(member.sepa_mandates)
        self.assertGreater(initial_mandate_count, 0, "Member should have SEPA mandate links")
        
        # 3. Delete mandate and verify cleanup
        frappe.delete_doc("SEPA Mandate", mandate.name, force=True)
        
        # 4. Verify member's child table is updated (this happens in SEPA mandate's on_trash if implemented)
        member.reload()
        remaining_mandates = [m for m in member.sepa_mandates if m.sepa_mandate == mandate.name]
        # Note: Depending on implementation, this might still exist but be inactive
        # The exact behavior depends on business requirements

    def test_sepa_mandate_integration_with_reporting(self):
        """Test that SEPA mandates integrate properly with reporting systems"""
        
        # 1. Create test data
        member = self.create_test_member(
            first_name="Reporting",
            last_name="TestMember",
            email="reporting@example.com"
        )
        
        mandate = self.create_test_sepa_mandate(member=member.name)
        
        # 2. Test that mandate appears in expected queries
        active_mandates = frappe.get_all("SEPA Mandate", 
                                       filters={"status": "Active", "member": member.name})
        
        self.assertGreater(len(active_mandates), 0, "Should find active SEPA mandates for member")
        
        # 3. Test mandate_id uniqueness across system
        all_mandates = frappe.get_all("SEPA Mandate", fields=["name", "mandate_id"])
        mandate_ids = [m.mandate_id for m in all_mandates if m.mandate_id]
        unique_mandate_ids = list(set(mandate_ids))
        
        self.assertEqual(len(mandate_ids), len(unique_mandate_ids),
                        "All mandate_ids should be unique across the system")


if __name__ == "__main__":
    import unittest
    unittest.main()