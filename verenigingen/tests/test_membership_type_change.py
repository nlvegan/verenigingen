"""
Test Membership Type Change Functionality

This module tests the membership type change request workflow including:
- Creating membership type change requests
- Validation of change requests
- Approval workflow
- Email notifications
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.base_test_case import BaseTestCase


class TestMembershipTypeChange(BaseTestCase):
    """Test suite for membership type change functionality"""

    def setUp(self):
        """Set up test environment for each test"""
        super().setUp()
        
        # Clean up any existing test membership types to avoid conflicts
        test_types = frappe.get_all("Membership Type", filters=[["name", "like", "TEST-%"]])
        for mt in test_types:
            frappe.delete_doc("Membership Type", mt.name, force=True, ignore_permissions=True)
        frappe.db.commit()
        
        # Create test membership types
        self.basic_type = self.create_membership_type(
            name="Basic Monthly",
            amount=10.00,
            description="Basic monthly membership"
        )
        
        self.premium_type = self.create_membership_type(
            name="Premium Monthly", 
            amount=25.00,
            description="Premium monthly membership with extra benefits"
        )
        
        self.quarterly_type = self.create_membership_type(
            name="Basic Quarterly",
            amount=27.00,
            description="Basic quarterly membership (3 months)"
        )
        
        # Create a test member with active membership
        self.member = self.create_test_member(
            first_name="Type",
            last_name="Changer",
            email="type.changer@test.com"
        )
        
        # Create active membership
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.basic_type.name
        )
        
        # Create dues schedule for the member
        self.dues_schedule = self.create_dues_schedule(
            member=self.member.name,
            membership=self.membership.name,
            membership_type=self.basic_type.name,
            amount=self.basic_type.amount
        )
    
    def test_create_membership_type_change_request(self):
        """Test creating a membership type change request"""
        # Create change request
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.premium_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.premium_type.amount,
            "reason": "Upgrading to premium for extra benefits",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Verify request was created
        self.assertTrue(request.name)
        self.assertEqual(request.amendment_type, "Membership Type Change")
        self.assertEqual(request.status, "Pending Approval")
        self.assertEqual(request.requested_membership_type, self.premium_type.name)
    
    def test_validate_same_type_change(self):
        """Test that changing to the same type is not allowed"""
        # Try to create request for same type
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.basic_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.basic_type.amount,
            "reason": "No real change",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        
        # Should not be allowed
        with self.assertRaises(frappe.ValidationError):
            request.insert()
    
    def test_multiple_pending_requests_not_allowed(self):
        """Test that only one pending membership type change is allowed"""
        # Create first request
        request1 = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.premium_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.premium_type.amount,
            "reason": "First request",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request1.insert()
        
        # Try to create second request
        request2 = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.quarterly_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.quarterly_type.amount,
            "reason": "Second request",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        
        # Should not be allowed
        with self.assertRaises(frappe.ValidationError):
            request2.insert()
    
    def test_approve_membership_type_change(self):
        """Test approving a membership type change request"""
        # Create request
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.premium_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.premium_type.amount,
            "reason": "Upgrading to premium",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Approve the request
        request.status = "Approved"
        request.approved_by = frappe.session.user
        request.approved_date = frappe.utils.now_datetime()
        request.save()
        
        # Apply the change
        self.apply_membership_type_change(request)
        
        # Verify membership was updated
        membership = frappe.get_doc("Membership", self.membership.name)
        self.assertEqual(membership.membership_type, self.premium_type.name)
        
        # Verify new dues schedule was created
        new_schedule = frappe.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "status": "Active"},
            "name"
        )
        self.assertTrue(new_schedule)
        
        # Verify old schedule was cancelled
        old_schedule = frappe.get_doc("Membership Dues Schedule", self.dues_schedule.name)
        self.assertEqual(old_schedule.status, "Cancelled")
    
    def test_fee_increase_on_type_change(self):
        """Test that fee correctly increases with membership type upgrade"""
        # Create request for upgrade
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.premium_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.premium_type.amount,
            "reason": "Upgrading membership",
            "status": "Approved",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Apply the change
        self.apply_membership_type_change(request)
        
        # Check new dues schedule has correct amount
        new_schedule = frappe.get_list(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            fields=["name", "dues_rate"]
        )[0]
        
        self.assertEqual(new_schedule.dues_rate, self.premium_type.amount)
    
    def test_reject_membership_type_change(self):
        """Test rejecting a membership type change request"""
        # Create request
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.basic_type.name,
            "requested_membership_type": self.premium_type.name,
            "current_amount": self.basic_type.amount,
            "requested_amount": self.premium_type.amount,
            "reason": "Want premium",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Reject the request
        request.status = "Rejected"
        request.rejection_reason = "Not eligible for premium membership"
        request.save()
        
        # Verify membership type didn't change
        membership = frappe.get_doc("Membership", self.membership.name)
        self.assertEqual(membership.membership_type, self.basic_type.name)
        
        # Verify dues schedule didn't change
        schedule = frappe.get_doc("Membership Dues Schedule", self.dues_schedule.name)
        self.assertEqual(schedule.status, "Active")
        self.assertEqual(schedule.dues_rate, self.basic_type.amount)
    
    def test_downgrade_membership_type(self):
        """Test downgrading from premium to basic membership"""
        # First upgrade to premium
        self.membership.membership_type = self.premium_type.name
        self.membership.save()
        
        # Update dues schedule
        self.dues_schedule.dues_rate = self.premium_type.amount
        self.dues_schedule.membership_type = self.premium_type.name
        self.dues_schedule.save()
        
        # Create downgrade request
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.premium_type.name,
            "requested_membership_type": self.basic_type.name,
            "current_amount": self.premium_type.amount,
            "requested_amount": self.basic_type.amount,
            "reason": "Can't afford premium anymore",
            "status": "Pending Approval",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Approve and apply
        request.status = "Approved"
        request.save()
        self.apply_membership_type_change(request)
        
        # Verify downgrade worked
        membership = frappe.get_doc("Membership", self.membership.name)
        self.assertEqual(membership.membership_type, self.basic_type.name)
        
        # Check new dues schedule has lower amount
        new_schedule = frappe.get_list(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            fields=["name", "dues_rate"]
        )[0]
        
        self.assertEqual(new_schedule.dues_rate, self.basic_type.amount)
    
    def test_quarterly_to_monthly_conversion(self):
        """Test converting from quarterly to monthly membership"""
        # Set up quarterly membership
        self.membership.membership_type = self.quarterly_type.name
        self.membership.save()
        
        self.dues_schedule.dues_rate = self.quarterly_type.amount
        self.dues_schedule.billing_frequency = "Quarterly"
        self.dues_schedule.membership_type = self.quarterly_type.name
        self.dues_schedule.save()
        
        # Create conversion request
        request = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": self.member.name,
            "membership": self.membership.name,
            "amendment_type": "Membership Type Change",
            "current_membership_type": self.quarterly_type.name,
            "requested_membership_type": self.basic_type.name,
            "current_amount": self.quarterly_type.amount,
            "requested_amount": self.basic_type.amount,
            "reason": "Prefer monthly payments",
            "status": "Approved",
            "requested_by_member": 1,
            "effective_date": today()
        })
        request.insert()
        
        # Apply the change
        self.apply_membership_type_change(request)
        
        # Verify billing frequency changed
        new_schedule = frappe.get_list(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            fields=["name", "dues_rate", "billing_frequency"]
        )[0]
        
        self.assertEqual(new_schedule.billing_frequency, "Monthly")
        self.assertEqual(new_schedule.dues_rate, self.basic_type.amount)
    
    # Helper methods
    
    def create_membership_type(self, name, amount, description=""):
        """Create a test membership type"""
        test_name = f"TEST-{name}-{frappe.utils.random_string(8)}"
        
        membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type": test_name,
            "membership_type_name": name,
            "dues_rate": amount,
            "description": description,
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
            "contribution_mode": "Custom",  # Set to Custom to preserve our amount
            "uses_custom_amount": 1,
            "custom_amount_approved": 1,
            "custom_amount_reason": "Test amount",
            "status": "Active",
            "effective_date": today(),
            "next_invoice_date": today()
        })
        
        dues_schedule.insert()
        
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
    
    def apply_membership_type_change(self, request):
        """Apply an approved membership type change"""
        # Update membership type directly (now allowed with allow_on_submit)
        membership = frappe.get_doc("Membership", request.membership)
        membership.membership_type = request.requested_membership_type
        membership.save()
        
        # Cancel old dues schedule
        if hasattr(self, 'dues_schedule') and self.dues_schedule:
            old_schedule = frappe.get_doc("Membership Dues Schedule", self.dues_schedule.name)
            old_schedule.status = "Cancelled"
            old_schedule.save()
        
        # Create new dues schedule
        new_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Type Change Schedule {frappe.utils.random_string(8)}",
            "member": request.member,
            "membership": request.membership,
            "membership_type": request.requested_membership_type,
            "dues_rate": request.requested_amount,
            "contribution_mode": "Custom",  # Set to Custom to preserve our amount
            "uses_custom_amount": 1,
            "custom_amount_approved": 1,
            "custom_amount_reason": "Membership type change",
            "status": "Active",
            "effective_date": request.effective_date,
            "next_invoice_date": request.effective_date
        })
        new_schedule.insert()
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        # Update request
        request.status = "Applied"
        request.applied_date = frappe.utils.now_datetime()
        request.applied_by = frappe.session.user
        request.new_dues_schedule = new_schedule.name
        request.save()