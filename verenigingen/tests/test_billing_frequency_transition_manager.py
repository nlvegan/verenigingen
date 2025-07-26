"""
Test Billing Frequency Transition Manager

Tests complex billing frequency transitions with proper validation,
prorated calculations, and audit trails.
"""

import frappe
from frappe.utils import today, add_days, add_months
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.billing_frequency_transition_manager import BillingFrequencyTransitionManager


class TestBillingFrequencyTransitionManager(VereningingenTestCase):
    """Test billing frequency transition functionality"""

    def setUp(self):
        super().setUp()
        self.manager = BillingFrequencyTransitionManager()
        
        # Create test member with active monthly schedule
        self.member = self.create_test_member(
            first_name="TransitionTest",
            email="transition@example.com"
        )
        
        # Create membership first (required for dues schedule)
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type="Monthly Standard"
        )
        
        # Create active monthly schedule using factory method
        self.monthly_schedule = self.create_test_dues_schedule(
            member=self.member.name,
            billing_frequency="Monthly",
            dues_rate=25.0,
            start_date=add_days(today(), -30),
            end_date=add_days(today(), 30),
            next_due_date=add_days(today(), 7),
            status="Active"
        )

    def test_validate_transition_success(self):
        """Test successful transition validation"""
        
        result = self.manager.validate_transition(
            self.member.name,
            "Monthly",
            "Annual", 
            add_days(today(), 7)
        )
        
        # Should be valid
        self.assertTrue(result["valid"], f"Validation failed: {result.get('issues', [])}")
        self.assertIn("calculations", result)
        
        # Should have calculated prorated amounts
        calculations = result["calculations"]
        self.assertIn("old_monthly_rate", calculations)
        self.assertIn("new_monthly_rate", calculations)
        self.assertEqual(calculations["old_monthly_rate"], 25.0)  # 25/1 month

    def test_validate_transition_invalid_frequency(self):
        """Test validation with invalid frequency"""
        
        result = self.manager.validate_transition(
            self.member.name,
            "Invalid",
            "Annual",
            add_days(today(), 7)
        )
        
        self.assertFalse(result["valid"])
        self.assertIn("Unsupported old frequency: Invalid", result["issues"])

    def test_validate_transition_past_date(self):
        """Test validation with past effective date"""
        
        result = self.manager.validate_transition(
            self.member.name,
            "Monthly",
            "Annual",
            add_days(today(), -1)  # Yesterday
        )
        
        self.assertFalse(result["valid"])
        self.assertIn("Effective date cannot be in the past", result["issues"])

    def test_validate_transition_nonexistent_member(self):
        """Test validation with non-existent member"""
        
        result = self.manager.validate_transition(
            "NONEXISTENT-MEMBER",
            "Monthly", 
            "Annual",
            add_days(today(), 7)
        )
        
        self.assertFalse(result["valid"])
        self.assertIn("Member not found: NONEXISTENT-MEMBER", result["issues"])

    def test_prorated_calculation_monthly_to_annual(self):
        """Test prorated amount calculation for monthly to annual transition"""
        
        effective_date = add_days(today(), 7)
        
        result = self.manager.validate_transition(
            self.member.name,
            "Monthly",
            "Annual",
            effective_date
        )
        
        self.assertTrue(result["valid"])
        
        calculations = result["calculations"]
        
        # Verify monthly rates
        self.assertEqual(calculations["old_monthly_rate"], 25.0)
        self.assertEqual(calculations["new_monthly_rate"], 25.0)  # Should stay the same
        
        # Should have some unused time in current period
        self.assertGreater(calculations["unused_period_months"], 0)
        
        # Should have a net adjustment (likely additional charge for annual)
        self.assertIsInstance(calculations["net_adjustment"], (int, float))

    def test_execute_transition_success(self):
        """Test successful transition execution"""
        
        effective_date = add_days(today(), 7)
        
        transition_params = {
            "old_frequency": "Monthly",
            "new_frequency": "Annual", 
            "effective_date": effective_date,
            "reason": "Test transition"
        }
        
        result = self.manager.execute_transition(self.member.name, transition_params)
        
        self.assertTrue(result["success"], f"Transition failed: {result.get('message')}")
        
        # Verify schedules were modified
        self.assertEqual(len(result["cancelled_schedules"]), 1)
        self.assertEqual(len(result["created_schedules"]), 1)
        
        # Verify old schedule was cancelled
        old_schedule = frappe.get_doc("Membership Dues Schedule", self.monthly_schedule.name)
        self.assertEqual(old_schedule.status, "Cancelled")
        self.assertEqual(str(old_schedule.end_date), str(effective_date))
        
        # Verify new schedule was created
        new_schedule_name = result["created_schedules"][0]
        new_schedule = frappe.get_doc("Membership Dues Schedule", new_schedule_name)
        self.track_doc("Membership Dues Schedule", new_schedule_name)
        
        self.assertEqual(new_schedule.billing_frequency, "Annual")
        self.assertEqual(new_schedule.member, self.member.name)
        self.assertEqual(new_schedule.status, "Active")
        self.assertEqual(str(new_schedule.start_date), str(effective_date))
        
        # Verify audit trail was created
        self.assertGreater(len(result["audit_trail"]), 0)
        
        # Check audit record was created
        audit_records = frappe.get_all(
            "Billing Frequency Transition Audit",
            filters={"member": self.member.name},
            fields=["name", "transition_status", "old_frequency", "new_frequency"]
        )
        
        self.assertEqual(len(audit_records), 1)
        audit_record = audit_records[0]
        self.assertEqual(audit_record.old_frequency, "Monthly")
        self.assertEqual(audit_record.new_frequency, "Annual")
        self.assertEqual(audit_record.transition_status, "Completed")
        
        # Track audit record for cleanup
        self.track_doc("Billing Frequency Transition Audit", audit_record.name)

    def test_execute_transition_validation_failure(self):
        """Test transition execution with validation failure"""
        
        transition_params = {
            "old_frequency": "Invalid",
            "new_frequency": "Annual",
            "effective_date": add_days(today(), 7),
            "reason": "Test invalid transition"
        }
        
        result = self.manager.execute_transition(self.member.name, transition_params)
        
        self.assertFalse(result["success"])
        self.assertIn("Validation failed", result["message"])
        
        # Verify no changes were made
        self.assertEqual(len(result["cancelled_schedules"]), 0)
        self.assertEqual(len(result["created_schedules"]), 0)

    def test_get_transition_preview(self):
        """Test transition preview functionality"""
        
        effective_date = add_days(today(), 7)
        
        preview = self.manager.get_transition_preview(
            self.member.name,
            "Monthly",
            "Annual",
            effective_date
        )
        
        self.assertTrue(preview["valid"])
        
        # Verify member info
        self.assertEqual(preview["member_info"]["name"], self.member.name)
        self.assertEqual(preview["member_info"]["full_name"], self.member.full_name)
        
        # Verify current schedules
        self.assertEqual(len(preview["current_schedules"]), 1)
        self.assertEqual(preview["current_schedules"][0]["billing_frequency"], "Monthly")
        
        # Verify proposed changes
        proposed = preview["proposed_changes"]
        self.assertEqual(proposed["schedules_to_cancel"], 1)
        self.assertEqual(proposed["new_schedule_frequency"], "Annual")
        self.assertEqual(str(proposed["effective_date"]), str(effective_date))
        
        # Verify financial impact
        self.assertIn("financial_impact", preview)
        financial = preview["financial_impact"]
        self.assertIn("old_monthly_rate", financial)
        self.assertIn("new_monthly_rate", financial)
        
        # Verify next steps
        self.assertIn("next_steps", preview)
        self.assertIsInstance(preview["next_steps"], list)
        self.assertGreater(len(preview["next_steps"]), 0)

    def test_quarterly_to_monthly_transition(self):
        """Test transition from quarterly to monthly billing"""
        
        # Create quarterly schedule using factory method
        quarterly_schedule = self.create_test_dues_schedule(
            member=self.member.name,
            billing_frequency="Quarterly",
            dues_rate=75.0,  # 25/month * 3 months
            start_date=add_days(today(), -60),
            end_date=add_days(today(), 30),
            next_due_date=add_days(today(), 14),
            status="Active"
        )
        
        # Cancel the monthly schedule to avoid conflicts
        self.monthly_schedule.status = "Cancelled"
        self.monthly_schedule.save()
        
        effective_date = add_days(today(), 7)
        
        # Test validation
        result = self.manager.validate_transition(
            self.member.name,
            "Quarterly",
            "Monthly",
            effective_date
        )
        
        self.assertTrue(result["valid"])
        
        # Verify calculations
        calculations = result["calculations"]
        self.assertEqual(calculations["old_monthly_rate"], 25.0)  # 75/3 months
        self.assertEqual(calculations["new_monthly_rate"], 25.0)

    def test_overlapping_schedule_detection(self):
        """Test detection of overlapping schedules"""
        
        effective_date = add_days(today(), 7)
        
        # Create overlapping annual schedule using factory method
        overlapping_schedule = self.create_test_dues_schedule(
            member=self.member.name,
            billing_frequency="Annual",
            dues_rate=300.0,
            start_date=add_days(today(), -10),
            end_date=add_days(today(), 355),
            status="Active"
        )
        
        # Test validation - should detect overlap
        result = self.manager.validate_transition(
            self.member.name,
            "Monthly",
            "Annual",
            effective_date
        )
        
        self.assertFalse(result["valid"])
        self.assertTrue(any("Overlapping Annual schedules found" in issue for issue in result["issues"]))

    def test_api_endpoints(self):
        """Test API endpoint functionality"""
        
        effective_date = add_days(today(), 7)
        
        # Test validation endpoint
        validation_result = frappe.call(
            "verenigingen.utils.billing_frequency_transition_manager.validate_billing_frequency_transition",
            member=self.member.name,
            old_frequency="Monthly",
            new_frequency="Annual", 
            effective_date=effective_date
        )
        
        self.assertTrue(validation_result["valid"])
        
        # Test preview endpoint
        preview_result = frappe.call(
            "verenigingen.utils.billing_frequency_transition_manager.get_billing_transition_preview",
            member=self.member.name,
            old_frequency="Monthly",
            new_frequency="Annual",
            effective_date=effective_date
        )
        
        self.assertTrue(preview_result["valid"])
        self.assertEqual(preview_result["member_info"]["name"], self.member.name)

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()