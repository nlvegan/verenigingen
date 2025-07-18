# -*- coding: utf-8 -*-
"""
Comprehensive workflow tests for the enhanced membership lifecycle
Tests complete end-to-end workflows with the new membership dues system
"""

import frappe
from frappe.utils import today, add_months, add_days, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestEnhancedMembershipLifecycle(VereningingenTestCase):
    """Test complete enhanced membership lifecycle workflows"""

    def setUp(self):
        super().setUp()
        # Create test data for workflows
        self.tier_membership_type = self.create_tier_based_membership_type()
        self.calculator_membership_type = self.create_calculator_based_membership_type()
        
    def test_tier_based_membership_complete_workflow(self):
        """Test complete workflow for tier-based membership"""
        
        # 1. Create membership application with tier selection
        application_data = {
            "first_name": "Jane",
            "last_name": "Tier",
            "email": "jane.tier@example.com",
            "address_line1": "123 Tier Street",
            "postal_code": "1234AB",
            "city": "Amsterdam",
            "country": "Netherlands",
            "membership_type": self.tier_membership_type.name,
            "contribution_mode": "Tier",
            "selected_tier": self.tier_membership_type.predefined_tiers[1].name,  # Standard tier
            "contribution_amount": self.tier_membership_type.predefined_tiers[1].amount,
            "payment_method": "SEPA Direct Debit",
            "iban": "NL13TEST0123456789",
            "account_holder_name": "Jane Tier"
        }
        
        # Process application
        from verenigingen.api.enhanced_membership_application import process_enhanced_application
        result = process_enhanced_application(application_data)
        
        self.assertTrue(result.get("success"))
        application_id = result.get("application_id")
        self.assertIsNotNone(application_id)
        
        # Track created documents - this should be a Member with pending status
        application = frappe.get_doc("Member", application_id)
        self.track_doc("Member", application.name)
        
        # 2. Validate application details
        self.assertEqual(application.application_status, "Pending")
        self.assertEqual(application.selected_membership_type, self.tier_membership_type.name)
        # Note: contribution details might be stored differently in Member vs separate Application
        
        # 3. Approve application and create member
        member = self.approve_application_and_create_member(application)
        
        # 4. Create membership dues schedule
        dues_schedule = self.create_dues_schedule_from_application(member, application)
        
        # 5. Test dues collection process
        self.test_dues_collection_for_schedule(dues_schedule)
        
        # 6. Test contribution adjustment
        self.test_contribution_adjustment(dues_schedule, "Supporter")
        
    def test_calculator_based_membership_complete_workflow(self):
        """Test complete workflow for calculator-based membership"""
        
        # 1. Create membership application with calculator
        application_data = {
            "first_name": "John",
            "last_name": "Calculator",
            "email": "john.calculator@example.com",
            "address_line1": "456 Calculator Avenue",
            "postal_code": "5678CD",
            "city": "Rotterdam",
            "country": "Netherlands",
            "membership_type": self.calculator_membership_type.name,
            "contribution_mode": "Calculator",
            "base_multiplier": 1.5,  # 150% of suggested amount
            "contribution_amount": self.calculator_membership_type.suggested_contribution * 1.5,
            "payment_method": "Bank Transfer"
        }
        
        # Process application
        from verenigingen.api.enhanced_membership_application import process_enhanced_application
        result = process_enhanced_application(application_data)
        
        self.assertTrue(result.get("success"))
        application_id = result.get("application_id")
        
        application = frappe.get_doc("Membership Application", application_id)
        self.track_doc("Membership Application", application.name)
        
        # 2. Validate calculator configuration
        self.assertEqual(application.contribution_mode, "Calculator")
        self.assertEqual(application.base_multiplier, 1.5)
        expected_amount = self.calculator_membership_type.suggested_contribution * 1.5
        self.assertEqual(application.contribution_amount, expected_amount)
        
        # 3. Complete workflow
        member = self.approve_application_and_create_member(application)
        dues_schedule = self.create_dues_schedule_from_application(member, application)
        
        # 4. Test payment plan request for calculator-based member
        self.test_payment_plan_request_workflow(member, dues_schedule)
        
    def test_contribution_adjustment_workflow(self):
        """Test workflow for adjusting contribution amounts"""
        
        # Start with tier-based member
        member = self.create_test_member()
        dues_schedule = self.create_tier_based_dues_schedule(member)
        
        original_amount = dues_schedule.amount
        original_tier = dues_schedule.selected_tier
        
        # Request adjustment to different tier
        new_tier = self.get_different_tier(original_tier)
        if new_tier:
            # Update dues schedule
            dues_schedule.selected_tier = new_tier.name
            dues_schedule.amount = new_tier.amount
            dues_schedule.add_comment(
                text=f"Contribution adjusted from {original_tier} to {new_tier.display_name}"
            )
            dues_schedule.save()
            
            # Validate adjustment
            self.assertEqual(dues_schedule.amount, new_tier.amount)
            self.assertNotEqual(dues_schedule.amount, original_amount)
            
    def test_payment_failure_recovery_workflow(self):
        """Test complete payment failure and recovery workflow"""
        
        # 1. Create member with SEPA dues schedule
        member = self.create_test_member()
        dues_schedule = self.create_sepa_dues_schedule(member)
        
        # 2. Simulate first payment failure
        dues_schedule.consecutive_failures = 1
        dues_schedule.status = "Grace Period" 
        dues_schedule.grace_period_until = add_days(today(), 14)
        dues_schedule.save()
        
        # Validate grace period
        self.assertEqual(dues_schedule.status, "Grace Period")
        self.assertIsNotNone(dues_schedule.grace_period_until)
        
        # 3. Simulate second failure
        dues_schedule.consecutive_failures = 2
        dues_schedule.save()
        
        # 4. Simulate third failure -> suspension
        dues_schedule.consecutive_failures = 3
        dues_schedule.status = "Suspended"
        dues_schedule.save()
        
        # Validate suspension
        self.assertEqual(dues_schedule.status, "Suspended")
        self.assertEqual(dues_schedule.consecutive_failures, 3)
        
        # 5. Recovery: Create payment plan
        payment_plan_data = {
            "member": member.name,
            "total_amount": dues_schedule.amount * 3,  # 3 months arrears
            "preferred_installments": 3,
            "preferred_frequency": "Monthly",
            "reason": "Payment failure recovery plan"
        }
        
        from verenigingen.api.payment_plan_management import request_payment_plan
        plan_result = request_payment_plan(**payment_plan_data)
        
        self.assertTrue(plan_result.get("success"))
        
        # 6. Approve payment plan
        plan_id = plan_result.get("payment_plan_id")
        payment_plan = frappe.get_doc("Payment Plan", plan_id)
        self.track_doc("Payment Plan", payment_plan.name)
        
        payment_plan.approved_by = frappe.session.user
        payment_plan.approval_date = frappe.utils.now()
        payment_plan.status = "Active"
        payment_plan.save()
        payment_plan.submit()
        
        # 7. Verify dues schedule is paused
        dues_schedule.reload()
        self.assertEqual(dues_schedule.status, "Payment Plan Active")
        
    def test_membership_type_migration_workflow(self):
        """Test workflow for migrating between membership types"""
        
        # 1. Start with calculator-based membership
        member = self.create_test_member()
        old_dues_schedule = self.create_calculator_dues_schedule(member)
        
        # 2. Create new dues schedule with tier-based type
        new_dues_schedule = frappe.new_doc("Membership Dues Schedule")
        new_dues_schedule.member = member.name
        new_dues_schedule.membership_type = self.tier_membership_type.name
        new_dues_schedule.contribution_mode = "Tier"
        new_dues_schedule.selected_tier = self.tier_membership_type.predefined_tiers[0].name
        new_dues_schedule.amount = self.tier_membership_type.predefined_tiers[0].amount
        new_dues_schedule.billing_frequency = "Monthly"
        new_dues_schedule.payment_method = "SEPA Direct Debit"
        new_dues_schedule.status = "Active"
        new_dues_schedule.auto_generate = 1
        
        new_dues_schedule.save()
        self.track_doc("Membership Dues Schedule", new_dues_schedule.name)
        
        # 3. Deactivate old schedule
        old_dues_schedule.status = "Inactive"
        old_dues_schedule.add_comment(
            text=f"Replaced by new schedule {new_dues_schedule.name}"
        )
        old_dues_schedule.save()
        
        # 4. Validate migration
        self.assertEqual(old_dues_schedule.status, "Inactive")
        self.assertEqual(new_dues_schedule.status, "Active")
        self.assertNotEqual(old_dues_schedule.membership_type, new_dues_schedule.membership_type)
        
    def test_seasonal_membership_workflow(self):
        """Test workflow for seasonal/temporary membership adjustments"""
        
        member = self.create_test_member()
        dues_schedule = self.create_calculator_dues_schedule(member)
        
        original_amount = dues_schedule.amount
        
        # 1. Temporary reduction (e.g., student discount period)
        dues_schedule.contribution_mode = "Custom"
        dues_schedule.amount = original_amount * 0.5  # 50% discount
        dues_schedule.uses_custom_amount = 1
        dues_schedule.custom_amount_reason = "Student discount - summer period"
        dues_schedule.save()
        
        # Validate temporary adjustment
        self.assertEqual(dues_schedule.contribution_mode, "Custom")
        self.assertEqual(dues_schedule.amount, original_amount * 0.5)
        self.assertTrue(dues_schedule.uses_custom_amount)
        
        # 2. Revert to normal rate
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.amount = original_amount
        dues_schedule.uses_custom_amount = 0
        dues_schedule.custom_amount_reason = ""
        dues_schedule.save()
        
        # Validate reversion
        self.assertEqual(dues_schedule.contribution_mode, "Calculator")
        self.assertEqual(dues_schedule.amount, original_amount)
        self.assertFalse(dues_schedule.uses_custom_amount)
        
    def test_bulk_contribution_adjustment_workflow(self):
        """Test workflow for bulk contribution adjustments"""
        
        # Create multiple members with dues schedules
        members_and_schedules = []
        for i in range(3):
            member = self.create_test_member(f"bulk{i}@example.com")
            schedule = self.create_calculator_dues_schedule(member)
            members_and_schedules.append((member, schedule))
            
        # Simulate bulk adjustment (e.g., inflation adjustment)
        adjustment_factor = 1.05  # 5% increase
        
        for member, schedule in members_and_schedules:
            original_amount = schedule.amount
            new_amount = original_amount * adjustment_factor
            
            schedule.amount = new_amount
            schedule.add_comment(
                text=f"Annual adjustment: {original_amount} -> {new_amount} (+5%)"
            )
            schedule.save()
            
            # Validate adjustment
            self.assertAlmostEqual(schedule.amount, original_amount * adjustment_factor, places=2)
            
    def test_enhanced_application_api_workflow(self):
        """Test the enhanced application API workflow"""
        
        # 1. Get membership types for application
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application
        types = get_membership_types_for_application()
        
        self.assertIsInstance(types, list)
        self.assertGreater(len(types), 0)
        
        # 2. Find our test types
        tier_type = next((t for t in types if t["name"] == self.tier_membership_type.name), None)
        calc_type = next((t for t in types if t["name"] == self.calculator_membership_type.name), None)
        
        self.assertIsNotNone(tier_type)
        self.assertIsNotNone(calc_type)
        
        # 3. Validate contribution options
        self.assertEqual(tier_type["contribution_options"]["mode"], "Tiers")
        self.assertEqual(calc_type["contribution_options"]["mode"], "Calculator")
        
        # 4. Test contribution validation
        from verenigingen.api.enhanced_membership_application import validate_contribution_amount
        
        valid_result = validate_contribution_amount(
            self.calculator_membership_type.name,
            self.calculator_membership_type.suggested_contribution,
            "Calculator",
            None,
            1.0
        )
        self.assertTrue(valid_result["valid"])
        
        invalid_result = validate_contribution_amount(
            self.calculator_membership_type.name,
            1.0,  # Below minimum
            "Calculator",
            None,
            0.1
        )
        self.assertFalse(invalid_result["valid"])
        
    # Helper methods for workflow testing
    
    def approve_application_and_create_member(self, application):
        """Approve application and create member"""
        # Create member
        member = frappe.new_doc("Member")
        member.first_name = application.first_name
        member.last_name = application.last_name
        member.email = application.email
        member.member_since = today()
        member.address_line1 = application.address_line1
        member.postal_code = application.postal_code
        member.city = application.city
        member.country = application.country
        
        member.save()
        self.track_doc("Member", member.name)
        
        # Update application
        application.status = "Approved"
        application.member = member.name
        application.save()
        
        return member
        
    def create_dues_schedule_from_application(self, member, application):
        """Create dues schedule from approved application"""
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership_type = application.membership_type
        dues_schedule.contribution_mode = application.contribution_mode
        dues_schedule.amount = application.contribution_amount
        
        if hasattr(application, 'selected_tier') and application.selected_tier:
            dues_schedule.selected_tier = application.selected_tier
        if hasattr(application, 'base_multiplier') and application.base_multiplier:
            dues_schedule.base_multiplier = application.base_multiplier
            
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.payment_method = application.payment_method
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 1
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def test_dues_collection_for_schedule(self, dues_schedule):
        """Test dues collection for a schedule"""
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import EnhancedSEPAProcessor
        
        # Make schedule eligible for collection
        dues_schedule.next_invoice_date = today()
        dues_schedule.test_mode = 0
        dues_schedule.save()
        
        processor = EnhancedSEPAProcessor()
        eligible = processor.get_eligible_dues_schedules(today())
        
        # Should find our schedule
        schedule_names = [s.name for s in eligible]
        self.assertIn(dues_schedule.name, schedule_names)
        
    def test_contribution_adjustment(self, dues_schedule, target_tier_name):
        """Test adjusting contribution to different tier"""
        if dues_schedule.contribution_mode == "Tier":
            membership_type = frappe.get_doc("Membership Type", dues_schedule.membership_type)
            
            # Find target tier
            target_tier = None
            for tier in membership_type.predefined_tiers:
                if tier.tier_name == target_tier_name:
                    target_tier = tier
                    break
                    
            if target_tier:
                original_amount = dues_schedule.amount
                dues_schedule.selected_tier = target_tier.name
                dues_schedule.amount = target_tier.amount
                dues_schedule.save()
                
                # Validate adjustment
                self.assertEqual(dues_schedule.amount, target_tier.amount)
                self.assertNotEqual(dues_schedule.amount, original_amount)
                
    def test_payment_plan_request_workflow(self, member, dues_schedule):
        """Test payment plan request for member"""
        from verenigingen.api.payment_plan_management import request_payment_plan
        
        # Set up member email for permission test
        member.email = "payment.plan@example.com"
        member.save()
        
        with self.set_user(member.email):
            result = request_payment_plan(
                member=member.name,
                total_amount=dues_schedule.amount * 2,  # 2 months
                preferred_installments=2,
                preferred_frequency="Monthly",
                reason="Testing payment plan workflow"
            )
            
            self.assertTrue(result.get("success"))
            
            # Track created payment plan
            plan_id = result.get("payment_plan_id")
            self.track_doc("Payment Plan", plan_id)
            
    def get_different_tier(self, current_tier_name):
        """Get a different tier for testing adjustments"""
        for tier in self.tier_membership_type.predefined_tiers:
            if tier.name != current_tier_name:
                return tier
        return None
        
    # Test data creation helpers
    
    def create_tier_based_membership_type(self):
        """Create tier-based membership type for testing"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Workflow Tier Type {frappe.generate_hash(length=6)}"
        membership_type.description = "Tier-based membership for workflow testing"
        membership_type.amount = 25.0
        membership_type.subscription_period = "Monthly"
        membership_type.is_active = 1
        membership_type.contribution_mode = "Tiers"
        membership_type.minimum_contribution = 10.0
        membership_type.suggested_contribution = 25.0
        membership_type.maximum_contribution = 100.0
        
        # Add tiers
        tiers_data = [
            {"name": "Student", "display": "Student Membership", "amount": 15.0, "order": 1},
            {"name": "Standard", "display": "Standard Membership", "amount": 25.0, "order": 2, "default": True},
            {"name": "Supporter", "display": "Supporter Membership", "amount": 50.0, "order": 3}
        ]
        
        for tier_data in tiers_data:
            tier = membership_type.append("predefined_tiers", {})
            tier.tier_name = tier_data["name"]
            tier.display_name = tier_data["display"]
            tier.amount = tier_data["amount"]
            tier.display_order = tier_data["order"]
            tier.is_default = tier_data.get("default", False)
            
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_calculator_based_membership_type(self):
        """Create calculator-based membership type for testing"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Workflow Calculator Type {frappe.generate_hash(length=6)}"
        membership_type.description = "Calculator-based membership for workflow testing"
        membership_type.amount = 20.0
        membership_type.subscription_period = "Monthly"
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.minimum_contribution = 8.0
        membership_type.suggested_contribution = 20.0
        membership_type.maximum_contribution = 200.0
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.6
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_tier_based_dues_schedule(self, member):
        """Create tier-based dues schedule"""
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership_type = self.tier_membership_type.name
        dues_schedule.contribution_mode = "Tier"
        dues_schedule.selected_tier = self.tier_membership_type.predefined_tiers[1].name  # Standard
        dues_schedule.amount = self.tier_membership_type.predefined_tiers[1].amount
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_calculator_dues_schedule(self, member):
        """Create calculator-based dues schedule"""
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership_type = self.calculator_membership_type.name
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.base_multiplier = 1.0
        dues_schedule.amount = self.calculator_membership_type.suggested_contribution
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_sepa_dues_schedule(self, member):
        """Create SEPA-enabled dues schedule"""
        dues_schedule = self.create_calculator_dues_schedule(member)
        dues_schedule.payment_method = "SEPA Direct Debit"
        dues_schedule.save()
        return dues_schedule