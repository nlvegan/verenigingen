#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contribution Amendment Request Integration Tests

Proper integration tests converted from debug functions that were previously
mixed into the production controller. These tests validate the entire
amendment workflow end-to-end.

Author: Verenigingen Development Team  
Created: 2025-09-11 (converted from debug functions)
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import ensure_sepa_payment_terms_template
import unittest


class TestContributionAmendmentIntegration(EnhancedTestCase):
    """Integration tests for Contribution Amendment Request workflows"""

    def setUp(self):
        super().setUp()
        # Dues schedules created during amendment apply set
        # payment_terms_template = "SEPA Direct Debit"; ensure that master exists.
        ensure_sepa_payment_terms_template()

    def _get_active_dues_schedule(self, member_name):
        """Return the member's auto-created active (instance) dues schedule."""
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertIsNotNone(
            name, f"Expected an auto-created active dues schedule for {member_name}"
        )
        return frappe.get_doc("Membership Dues Schedule", name)

    def test_amendment_controller_methods_exist(self):
        """Test that all required controller methods exist and are callable"""
        
        # Create a test amendment document
        test_amendment = frappe.new_doc("Contribution Amendment Request")
        
        # Check that all essential methods exist
        required_methods = [
            "validate",
            "create_dues_schedule_for_amendment", 
            "set_current_details",
            "apply_fee_change",
            "approve_amendment",
            "apply_amendment",
            "get_impact_preview"
        ]

        for method in required_methods:
            self.assertTrue(
                hasattr(test_amendment, method),
                f"Method '{method}' should exist on ContributionAmendmentRequest"
            )

        print("✅ All required controller methods exist")

    def test_amendment_document_creation_and_validation(self):
        """Test creating and validating amendment documents"""
        
        # Create test member with active membership
        member = self.create_test_member(
            first_name="Amendment",
            last_name="Test"
        )
        
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Create amendment request. The requested amount must respect the
        # membership type minimum (€100), otherwise validation/approval differs.
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Fee Change",
            "requested_amount": 150.0,
            "reason": "Integration test amendment",
            "effective_date": add_days(today(), 30)
        })

        # Should validate and insert successfully
        amendment.insert()

        # A Fee Change that respects the minimum is auto-approved in the current
        # business logic (set_auto_approval_status), so the persisted status is
        # "Approved" rather than the old "Draft".
        self.assertEqual(amendment.status, "Approved")
        self.assertEqual(amendment.requested_by, frappe.session.user)
        self.assertIsNotNone(amendment.effective_date)

        print(f"✅ Amendment {amendment.name} created and validated successfully")

    def test_amendment_approval_workflow(self):
        """Test the complete approval workflow"""
        
        # Create test data
        member = self.create_test_member(
            first_name="Approval",
            last_name="Workflow"
        )
        
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Create an amendment that requires manual approval. Auto-approval only
        # triggers when the requested amount respects the membership type minimum
        # (€100); a below-minimum amount lands in "Pending Approval" so we can
        # exercise the manual approval path.
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Fee Change",
            "requested_amount": 50.0,  # Below minimum -> requires approval
            "reason": "Below-minimum fee change requiring manual approval",
            "effective_date": add_days(today(), 30)
        })

        amendment.insert()

        # Below-minimum amounts require manual approval
        self.assertEqual(amendment.status, "Pending Approval")

        # Test approval process
        amendment.approve_amendment("Approved for integration test")

        self.assertEqual(amendment.status, "Approved")
        self.assertEqual(amendment.approved_by, frappe.session.user)
        self.assertIsNotNone(amendment.approved_date)

        print(f"✅ Amendment approval workflow completed for {amendment.name}")

    def test_dues_schedule_integration(self):
        """Test integration with Membership Dues Schedule"""
        
        # Create test member with dues schedule
        member = self.create_test_member(
            first_name="Dues",
            last_name="Integration"
        )
        
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Creating the membership auto-creates an Active dues schedule, and the
        # controller enforces one active schedule per member. Fetch that schedule
        # and set its rate rather than creating a second (which would fail).
        dues_schedule = self._get_active_dues_schedule(member.name)
        dues_schedule.dues_rate = 100.0  # respect membership type minimum
        dues_schedule.save()

        # Create amendment (>= minimum -> auto-approved on insert)
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Fee Change",
            "requested_amount": 150.0,
            "reason": "Dues schedule integration test",
            "effective_date": today()
        })

        amendment.insert()
        self.assertEqual(amendment.status, "Approved")

        # Force apply the amendment
        amendment._force_apply = True
        result = amendment.apply_amendment()

        self.assertEqual(result["status"], "success")
        self.assertEqual(amendment.status, "Applied")

        # Verify dues schedule was updated
        dues_schedule.reload()
        self.assertEqual(float(dues_schedule.dues_rate), 150.0)
        
        print(f"✅ Dues schedule integration successful for {amendment.name}")

    def test_amendment_field_configuration(self):
        """Test that amendment DocType has required fields properly configured"""
        
        doctype = frappe.get_doc("DocType", "Contribution Amendment Request")
        
        # Check for critical fields
        required_fields = [
            "member",
            "membership", 
            "amendment_type",
            "requested_amount",
            "reason",
            "status",
            "effective_date",
            "new_dues_schedule",
            "current_dues_schedule",
            "processing_notes"
        ]

        existing_fields = [field.fieldname for field in doctype.fields]

        for field in required_fields:
            self.assertIn(
                field, existing_fields,
                f"Required field '{field}' should exist in Contribution Amendment Request DocType"
            )

        # Check specific field configurations
        for field in doctype.fields:
            if field.fieldname == "new_dues_schedule":
                self.assertEqual(field.fieldtype, "Link")
                self.assertEqual(field.options, "Membership Dues Schedule")
            elif field.fieldname == "current_dues_schedule":
                self.assertEqual(field.fieldtype, "Link") 
                self.assertEqual(field.options, "Membership Dues Schedule")

        print("✅ Amendment DocType field configuration is correct")

    def test_auto_approval_logic(self):
        """Test automatic approval logic for small increases"""
        
        # Create member with existing dues
        member = self.create_test_member(
            first_name="Auto",
            last_name="Approval"
        )
        
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Use the membership's auto-created active dues schedule (one-active-per-
        # member rule) and set its base rate.
        dues_schedule = self._get_active_dues_schedule(member.name)
        dues_schedule.dues_rate = 100.0  # respect membership type minimum
        dues_schedule.save()

        # Fee change that respects the minimum (>= €100) should auto-approve
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Fee Change",
            "requested_amount": 105.0,
            "reason": "Small auto-approval test",
            "effective_date": add_days(today(), 30)
        })

        amendment.insert()

        # Should auto-approve changes that respect the minimum
        self.assertEqual(amendment.status, "Approved")
        self.assertIn("Auto-approved", amendment.internal_notes or "")
        
        print(f"✅ Auto-approval logic working for {amendment.name}")

    def test_impact_preview_generation(self):
        """Test that impact preview is generated correctly"""
        
        member = self.create_test_member(
            first_name="Impact",
            last_name="Preview"
        )
        
        membership = self.create_test_membership(
            member=member.name,
            status="Active"
        )

        # Create amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": member.name,
            "membership": membership.name,
            "amendment_type": "Fee Change",
            "requested_amount": 30.0,
            "reason": "Impact preview test",
        })
        
        amendment.insert()
        
        # Test impact preview generation
        preview = amendment.get_impact_preview()
        
        self.assertIsInstance(preview, dict)
        self.assertIn("html", preview)
        self.assertIn("Amendment Impact Preview", preview["html"])
        
        print(f"✅ Impact preview generated successfully for {amendment.name}")


if __name__ == "__main__":
    import unittest
    # Enable test mode
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    # Run the tests
    unittest.main()