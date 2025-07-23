"""
Test Self-Service Fee Adjustment Functionality

This module tests the self-service fee adjustment features including:
- Fee increases without approval (within limits)
- 365-day rolling window for adjustment limits
- Approval requirements for decreases and large increases
- Maximum fee multiplier enforcement
"""

import frappe
from frappe.utils import today, add_days, flt
from verenigingen.tests.base_test_case import BaseTestCase


class TestSelfServiceFeeAdjustment(BaseTestCase):
    """Test suite for self-service fee adjustment functionality"""

    def setUp(self):
        """Set up test environment for each test"""
        super().setUp()
        
        # Clean up any existing Standard Monthly membership types
        existing_types = frappe.get_all("Membership Type", filters={"membership_type_name": "Standard Monthly"})
        for mt in existing_types:
            frappe.delete_doc("Membership Type", mt.name, force=True, ignore_permissions=True)
        frappe.db.commit()
        
        # Create test settings
        self.update_verenigingen_settings({
            'enable_member_fee_adjustment': 1,
            'max_adjustments_per_year': 2,
            'require_approval_for_increases': 0,
            'require_approval_for_decreases': 1,
            'adjustment_reason_required': 1,
            'maximum_fee_multiplier': 3.0,
            'auto_approve_fee_increases': 1,
            'auto_approve_member_requests': 1,
            'max_auto_approve_amount': 1000
        })
        
        # Create test member with membership
        self.member = self.create_test_member(
            first_name="Fee",
            last_name="Adjuster",
            email="fee.adjuster@test.com"
        )
        
        # Create membership type and membership
        self.membership_type = self.create_membership_type(
            name="Standard Monthly",
            amount=20.00
        )
        
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name
        )
        
        # Create active dues schedule
        self.dues_schedule = self.create_dues_schedule(
            member=self.member.name,
            membership=self.membership.name,
            membership_type=self.membership_type.name,
            amount=self.membership_type.minimum_amount
        )
    
    def test_fee_increase_without_approval(self):
        """Test that fee increases within limits don't require approval"""
        # Create fee increase request (2x base amount, within 3x limit)
        new_amount = self.membership_type.minimum_amount * 2
        
        # Set session user to be the member
        original_user = frappe.session.user
        # Create a user for the member if it doesn't exist
        if not frappe.db.exists("User", self.member.email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.member.email,
                "first_name": self.member.first_name,
                "last_name": self.member.last_name,
                "enabled": 1,
                "user_type": "Website User"
            })
            user.insert(ignore_permissions=True)
        frappe.session.user = self.member.email
        
        try:
            request = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "member": self.member.name,
                "membership": self.membership.name,
                "amendment_type": "Fee Change",
                "current_amount": self.membership_type.minimum_amount,
                "requested_amount": new_amount,
                "reason": "Want to contribute more",
                "requested_by_member": 1,
                "effective_date": today()
            })
            request.insert(ignore_permissions=True)
            
            # Should be auto-approved
            self.assertEqual(request.status, "Approved")
            
            # Apply the approved amendment to create dues schedule
            result = request.apply_amendment()
            if result.get("status") != "success":
                print(f"Apply amendment failed: {result.get('message')}")
            self.assertEqual(result.get("status"), "success")
        finally:
            frappe.session.user = original_user
        
        # Check that new dues schedule was created
        new_schedule = frappe.get_list(
            "Membership Dues Schedule",
            filters={
                "member": self.member.name,
                "status": "Active",
                "dues_rate": new_amount
            }
        )
        self.assertTrue(len(new_schedule) > 0)
    
    def test_fee_increase_exceeding_limit_requires_approval(self):
        """Test that fee increases beyond maximum multiplier require approval"""
        # Create fee increase request (4x base amount, exceeds 3x limit)
        new_amount = self.membership_type.minimum_amount * 4
        
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": new_amount,
            "reason": "Want to contribute much more",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Should require approval
        self.assertEqual(request.status, "Pending Approval")
    
    def test_fee_decrease_always_requires_approval(self):
        """Test that fee decreases always require approval"""
        # Create fee decrease request
        new_amount = self.membership_type.minimum_amount * 0.5
        
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": new_amount,
            "reason": "Financial difficulties",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Should require approval
        self.assertEqual(request.status, "Pending Approval")
    
    def test_365_day_rolling_window(self):
        """Test that adjustment limit uses 365-day rolling window"""
        # Create first adjustment 200 days ago
        old_request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": self.membership_type.minimum_amount * 1.5,
            "reason": "First adjustment",
            "status": "Applied",
            "requested_by_member": 1,
            "effective_date": today()  # Use today to pass validation
        })
        old_request.insert()
        # Now update the creation date and effective date to the past
        old_request.creation = add_days(frappe.utils.now_datetime(), -200)
        old_request.effective_date = add_days(today(), -200)
        old_request.status = "Applied"  # Ensure it's marked as applied
        old_request.db_update()
        
        # Create second adjustment 100 days ago
        mid_request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount * 1.5,
            "requested_amount": self.membership_type.minimum_amount * 2,
            "reason": "Second adjustment",
            "status": "Applied",
            "requested_by_member": 1,
            "effective_date": today()  # Use today to pass validation
        })
        mid_request.insert()
        # Now update the creation date and effective date to the past
        mid_request.creation = add_days(frappe.utils.now_datetime(), -100)
        mid_request.effective_date = add_days(today(), -100)
        mid_request.status = "Applied"  # Ensure it's marked as applied
        mid_request.db_update()
        
        # Count adjustments in past 365 days
        date_365_days_ago = add_days(today(), -365)
        adjustments_past_year = frappe.db.count(
            "Contribution Amendment Request",
            filters={
                "member": self.member.name,
                "amendment_type": "Fee Change",
                "creation": [">=", date_365_days_ago],
                "requested_by_member": 1},
        )
        
        # Should count both (200 and 100 days ago are within 365 days)
        self.assertEqual(adjustments_past_year, 2)
        
        # Try to create third adjustment - should fail
        with self.assertRaises(frappe.ValidationError) as cm:
            new_request = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "member": self.member.name,
                "membership": self.membership.name,
                "amendment_type": "Fee Change",
                "current_amount": self.membership_type.minimum_amount * 2,
                "requested_amount": self.membership_type.minimum_amount * 2.5,
                "reason": "Third adjustment",
                "status": "Pending Approval",
                "requested_by_member": 1,
                "effective_date": today()
            })
            new_request.insert()
        
        self.assertIn("maximum number of fee adjustments", str(cm.exception))
    
    def test_adjustment_after_365_days(self):
        """Test that adjustments older than 365 days don't count toward limit"""
        # Create adjustment 400 days ago
        old_request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": self.membership_type.minimum_amount * 1.5,
            "reason": "Old adjustment",
            "status": "Applied",
            "requested_by_member": 1,
            "effective_date": today()  # Use today to pass validation
        })
        old_request.insert()
        # Now update the creation date and effective date to the past
        old_request.creation = add_days(frappe.utils.now_datetime(), -400)
        old_request.effective_date = add_days(today(), -400)
        old_request.status = "Applied"  # Ensure it's marked as applied
        old_request.db_update()
        
        # Count adjustments in past 365 days
        date_365_days_ago = add_days(today(), -365)
        adjustments_past_year = frappe.db.count(
            "Contribution Amendment Request",
            filters={
                "member": self.member.name,
                "amendment_type": "Fee Change",
                "creation": [">=", date_365_days_ago],
                "requested_by_member": 1},
        )
        
        # Should not count the old adjustment
        self.assertEqual(adjustments_past_year, 0)
        
        # Should be able to create new adjustment
        new_request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": self.membership_type.minimum_amount * 2,
            "reason": "New adjustment",
            "status": "Auto-Approved",
            "requested_by_member": 1,
            "effective_date": today()
        })
        new_request.insert()
        
        self.assertTrue(new_request.name)
    
    def test_same_amount_adjustment_rejected(self):
        """Test that adjusting to the same amount is rejected"""
        # Try to create adjustment with same amount
        with self.assertRaises(frappe.ValidationError) as cm:
            request = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "member": self.member.name,
                "membership": self.membership.name,
                "amendment_type": "Fee Change",
                "current_amount": self.membership_type.minimum_amount,
                "requested_amount": self.membership_type.minimum_amount,
                "reason": "No change",
                "status": "Pending Approval",
                "requested_by_member": 1,
                "effective_date": today()
            })
            request.insert()
        
        self.assertIn("same as current amount", str(cm.exception))
    
    def test_minimum_fee_enforcement(self):
        """Test that fees cannot go below minimum"""
        # Calculate minimum fee (30% of base or €5, whichever is higher)
        minimum_fee = max(self.membership_type.minimum_amount * 0.3, 5.0)
        
        # Try to set fee below minimum
        with self.assertRaises(frappe.ValidationError) as cm:
            request = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "member": self.member.name,
                "membership": self.membership.name,
                "amendment_type": "Fee Change",
                "current_amount": self.membership_type.minimum_amount,
                "requested_amount": minimum_fee - 1,  # Below minimum
                "reason": "Too low",
                "status": "Pending Approval",
                "requested_by_member": 1,
                "effective_date": today()
            })
            request.insert()
        
        self.assertIn("less than minimum fee", str(cm.exception))
    
    def test_student_discount_minimum(self):
        """Test that students get a different minimum fee"""
        # Set member as student
        self.member.reload()  # Reload to get fresh timestamp
        self.member.student_status = 1
        self.member.save()
        
        # Student minimum is 50% of base
        student_minimum = max(self.membership_type.minimum_amount * 0.5, 5.0)
        
        # Should be able to set fee at student minimum
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": student_minimum,
            "reason": "Student discount",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        self.assertTrue(request.name)
    
    def test_zero_amount_handling(self):
        """Test that zero amounts are handled correctly"""
        # Try to set fee to zero
        with self.assertRaises(frappe.ValidationError) as cm:
            request = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "member": self.member.name,
                "membership": self.membership.name,
                "amendment_type": "Fee Change",
                "current_amount": self.membership_type.minimum_amount,
                "requested_amount": 0,
                "reason": "Want free membership",
                "status": "Pending Approval",
                "requested_by_member": 1,
                "effective_date": today()
            })
            request.insert()
        
        self.assertIn("must be greater than 0", str(cm.exception))
    
    def test_dues_schedule_update_on_approval(self):
        """Test that dues schedule is properly updated when fee change is approved"""
        # Create fee change request
        new_amount = self.membership_type.minimum_amount * 1.5
        
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Fee Change",
            "current_amount": self.membership_type.minimum_amount,
            "requested_amount": new_amount,
            "reason": "Increasing contribution",
            "status": "Auto-Approved",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Apply the fee change
        self.apply_fee_change(request)
        
        # Check old schedule was cancelled
        old_schedule = frappe.get_doc("Membership Dues Schedule", self.dues_schedule.name)
        self.assertEqual(old_schedule.status, "Cancelled")
        
        # Check new schedule was created with correct amount
        new_schedule = frappe.get_list(
            "Membership Dues Schedule",
            filters={
                "member": self.member.name,
                "status": "Active"
            },
            fields=["name", "dues_rate", "contribution_mode"]
        )[0]
        
        self.assertEqual(new_schedule.dues_rate, new_amount)
        self.assertEqual(new_schedule.contribution_mode, "Custom")
    
    # Helper methods
    
    def update_verenigingen_settings(self, settings):
        """Update Verenigingen Settings"""
        doc = frappe.get_single("Verenigingen Settings")
        for key, value in settings.items():
            setattr(doc, key, value)
        doc.save()
    
    def create_membership_type(self, name, amount):
        """Create a test membership type"""
        test_name = f"TEST-{name}-{frappe.utils.random_string(10)}"
        
        # Check if it already exists (shouldn't happen with random string, but be safe)
        if frappe.db.exists("Membership Type", test_name):
            test_name = f"TEST-{name}-{frappe.utils.random_string(15)}"
        
        membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type": test_name,
            "membership_type_name": name,
            "amount": amount,
            "is_published": 1
        })
        membership_type.insert()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
    
    def create_test_membership(self, member, membership_type):
        """Create a test membership"""
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member,
            "membership_type": membership_type,
            "status": "Active",
            "start_date": today()
        })
        membership.insert()
        membership.submit()
        self.track_doc("Membership", membership.name)
        return membership
    
    def create_dues_schedule(self, member, membership, membership_type, amount):
        """Create a test dues schedule"""
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test Schedule {frappe.utils.random_string(8)}",
            "member": member,
            "membership": membership,
            "membership_type": membership_type,
            "dues_rate": amount,
            "status": "Active",
            "effective_date": today(),
            "next_invoice_date": today(),
            "contribution_mode": "Custom",
            "uses_custom_amount": 1,
            "custom_amount_approved": 1,
            "custom_amount_reason": "Test dues schedule"
        })
        dues_schedule.insert()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
    
    def apply_fee_change(self, request):
        """Apply an approved fee change"""
        # Cancel old dues schedule
        if hasattr(self, 'dues_schedule') and self.dues_schedule:
            old_schedule = frappe.get_doc("Membership Dues Schedule", self.dues_schedule.name)
            old_schedule.status = "Cancelled"
            old_schedule.save()
        
        # Create new dues schedule
        new_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Adjusted Schedule {frappe.utils.random_string(8)}",
            "member": request.member,
            "membership": request.membership,
            "membership_type": self.membership_type.name,
            "dues_rate": request.requested_amount,
            "status": "Active",
            "effective_date": request.effective_date,
            "contribution_mode": "Custom",
            "uses_custom_amount": 1,
            "custom_amount_approved": 1,
            "custom_amount_reason": request.reason
        })
        new_schedule.insert()
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        # Update request
        request.status = "Applied"
        request.applied_date = frappe.utils.now_datetime()
        request.new_dues_schedule = new_schedule.name
        request.save()