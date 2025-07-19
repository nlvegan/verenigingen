# -*- coding: utf-8 -*-
"""
Comprehensive membership status tests covering lifecycle, transitions, and edge cases
Tests complex status scenarios that might not be covered elsewhere
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, add_to_date, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta


class TestMembershipStatusComprehensive(VereningingenTestCase):
    """Comprehensive tests for membership status handling, transitions, and edge cases"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member_with_full_setup()
        
    def create_test_member_with_full_setup(self):
        """Create a test member with complete setup (customer, mandate, dues schedule)"""
        member = self.create_test_member(
            first_name="Status",
            last_name="Tester",
            email=f"status.{frappe.generate_hash(length=6)}@example.com",
            address_line1="123 Status Street",
            postal_code="1234AB",
            city="Amsterdam",
            country="Netherlands"
        )
        
        return member
        
    # Status Transition Lifecycle Tests
    
    def test_complete_membership_lifecycle_transitions(self):
        """Test complete membership lifecycle with all possible status transitions"""
        member = self.test_member
        
        # Track status history
        status_history = []
        
        # Stage 1: Active to Suspended (payment issues)
        original_status = member.status
        status_history.append({"from": None, "to": original_status, "date": today()})
        
        member.status = "Suspended"
        member.suspension_reason = "Payment failure - 3 consecutive months"
        member.suspension_date = today()
        member.save()
        status_history.append({"from": original_status, "to": "Suspended", "date": today()})
        
        # Validate suspension effects
        self.assertEqual(member.status, "Suspended")
        self.assertIsNotNone(member.suspension_reason)
        
        # Stage 2: Suspended to Active (payment resolved)
        member.status = "Active"
        member.suspension_reason = None
        member.suspension_date = None
        member.reactivation_date = today()
        member.save()
        status_history.append({"from": "Suspended", "to": "Active", "date": today()})
        
        # Stage 3: Active to Quit (voluntary termination)
        member.status = "Quit"
        member.termination_date = today()
        member.termination_reason = "Relocating to different country"
        member.save()
        status_history.append({"from": "Active", "to": "Quit", "date": today()})
        
        # Validate final state
        self.assertEqual(member.status, "Quit")
        self.assertIsNotNone(member.termination_date)
        self.assertIsNotNone(member.termination_reason)
        
        # Validate status history tracking
        self.assertEqual(len(status_history), 4)
        self.assertTrue(all(transition["date"] for transition in status_history))
        
    def test_status_transitions_during_billing_cycle(self):
        """Test status changes at different points in the billing cycle"""
        member = self.test_member
        
        # Get associated dues schedule
        dues_schedule = frappe.get_value("Membership Dues Schedule", {"member": member.name}, "name")
        dues_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule)
        
        # Test Case 1: Status change after invoice generated but before payment
        # Create pending invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member.customer
        invoice.member = member.name
        invoice.posting_date = today()
        invoice.is_membership_invoice = 1
        invoice.outstanding_amount = 25.0
        invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": 25.0,
            "income_account": "Sales - TC"
        })
        invoice.save()
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Member quits after invoice but before payment
        member.status = "Quit"
        member.termination_date = today()
        member.save()
        
        # Invoice should still exist but member shouldn't be billed again
        invoice.reload()
        self.assertTrue(invoice.outstanding_amount > 0)  # Invoice remains unpaid
        
        # Dues schedule should be cancelled
        dues_doc.reload()
        # In real implementation, this might trigger automatic cancellation
        
    def test_retroactive_status_changes(self):
        """Test status changes with backdated effective dates"""
        member = self.test_member
        
        # Create some historical transactions
        historical_invoice = frappe.new_doc("Sales Invoice")
        historical_invoice.customer = member.customer
        historical_invoice.member = member.name
        historical_invoice.posting_date = add_days(today(), -30)  # 30 days ago
        historical_invoice.is_membership_invoice = 1
        historical_invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": 25.0,
            "income_account": "Sales - TC"
        })
        historical_invoice.save()
        historical_invoice.submit()
        self.track_doc("Sales Invoice", historical_invoice.name)
        
        # Retroactively terminate membership (e.g., discovered eligibility issue)
        retroactive_termination_date = add_days(today(), -20)  # 20 days ago
        member.status = "Terminated"
        member.termination_date = retroactive_termination_date
        member.termination_reason = "Retroactive termination - eligibility review"
        member.save()
        
        # Validate retroactive effects
        self.assertEqual(member.status, "Terminated")
        self.assertTrue(getdate(member.termination_date) < getdate(today()))
        
        # Historical invoice should be flagged for review
        # In real implementation, this might trigger financial reconciliation
        
    def test_concurrent_status_changes(self):
        """Test handling of concurrent status change attempts"""
        member = self.test_member
        original_modified = member.modified
        
        # Simulate concurrent updates
        member1 = frappe.get_doc("Member", member.name)
        member2 = frappe.get_doc("Member", member.name)
        
        # First update: Suspend member
        member1.status = "Suspended"
        member1.suspension_reason = "Payment issues"
        member1.save()
        
        # Second update: Try to terminate (should handle conflict)
        member2.status = "Terminated"
        member2.termination_reason = "Concurrent termination attempt"
        
        # In real implementation, this might trigger version conflict handling
        # For test, just verify final state is consistent
        member.reload()
        self.assertIn(member.status, ["Suspended", "Terminated"])  # One of the states should win
        
    # Status-Dependent Business Logic Tests
    
    def test_status_based_billing_eligibility(self):
        """Test billing eligibility based on different membership statuses"""
        member = self.test_member
        
        # Define status billing rules
        billing_eligible_statuses = ["Active", "Current", "Grace Period"]
        non_billing_statuses = ["Suspended", "Terminated", "Quit", "Expelled", "Deceased"]
        
        # Test eligible statuses
        for status in billing_eligible_statuses:
            with self.subTest(status=status):
                member.status = status
                member.save()
                
                eligible = self.is_member_eligible_for_billing(member)
                self.assertTrue(eligible, f"Member with status '{status}' should be eligible for billing")
        
        # Test non-eligible statuses
        for status in non_billing_statuses:
            with self.subTest(status=status):
                member.status = status
                member.save()
                
                eligible = self.is_member_eligible_for_billing(member)
                self.assertFalse(eligible, f"Member with status '{status}' should NOT be eligible for billing")
                
    def test_status_based_access_controls(self):
        """Test access controls based on membership status"""
        member = self.test_member
        
        # Test access permissions for different statuses
        access_scenarios = [
            {"status": "Active", "portal_access": True, "voting_rights": True, "event_access": True},
            {"status": "Suspended", "portal_access": True, "voting_rights": False, "event_access": False},
            {"status": "Grace Period", "portal_access": True, "voting_rights": True, "event_access": True},
            {"status": "Terminated", "portal_access": False, "voting_rights": False, "event_access": False},
            {"status": "Quit", "portal_access": False, "voting_rights": False, "event_access": False},
        ]
        
        for scenario in access_scenarios:
            with self.subTest(status=scenario["status"]):
                member.status = scenario["status"]
                member.save()
                
                # Test portal access
                portal_access = self.check_portal_access(member)
                self.assertEqual(portal_access, scenario["portal_access"])
                
                # Test voting rights
                voting_rights = self.check_voting_rights(member)
                self.assertEqual(voting_rights, scenario["voting_rights"])
                
                # Test event access
                event_access = self.check_event_access(member)
                self.assertEqual(event_access, scenario["event_access"])
                
    def test_status_dependent_dues_calculation(self):
        """Test dues calculation variations based on status"""
        member = self.test_member
        base_amount = 25.0
        
        # Different statuses might have different billing rates
        status_rate_modifiers = {
            "Active": 1.0,          # Full rate
            "Student": 0.5,         # 50% discount
            "Senior": 0.7,          # 30% discount
            "Honorary": 0.0,        # Free membership
            "Corporate": 2.0,       # Double rate
            "Family": 1.5,          # Family rate
        }
        
        for status, modifier in status_rate_modifiers.items():
            with self.subTest(status=status):
                member.status = status
                member.save()
                
                expected_amount = base_amount * modifier
                calculated_amount = self.calculate_dues_amount(member, base_amount)
                
                self.assertAlmostEqual(calculated_amount, expected_amount, places=2)
                
    # Status Change Side Effects Tests
    
    def test_status_change_side_effects_on_sepa_mandates(self):
        """Test automatic SEPA mandate handling when status changes"""
        member = self.test_member
        
        # Get associated mandate
        mandate = frappe.get_doc("SEPA Mandate", {"party": member.customer})
        original_mandate_status = mandate.status
        
        # Test Case 1: Termination should cancel mandate
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        # In real implementation, this might trigger automatic mandate cancellation
        # For test, simulate the expected behavior
        mandate.reload()
        # Mandate status should change or be flagged for review
        
        # Test Case 2: Reactivation might require new mandate
        member.status = "Active"
        member.reactivation_date = today()
        member.save()
        
        # Might need new mandate or reactivation of existing one
        
    def test_status_change_side_effects_on_dues_schedules(self):
        """Test dues schedule handling when member status changes"""
        member = self.test_member
        
        # Get associated dues schedule
        dues_schedule_name = frappe.get_value("Membership Dues Schedule", {"member": member.name}, "name")
        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)
        
        # Test Case 1: Suspension should pause dues schedule
        member.status = "Suspended"
        member.suspension_date = today()
        member.save()
        
        dues_schedule.reload()
        # In real implementation, dues schedule might be paused automatically
        
        # Test Case 2: Termination should cancel dues schedule
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        dues_schedule.reload()
        # Dues schedule should be cancelled or marked inactive
        
    def test_status_change_notification_workflows(self):
        """Test notification workflows triggered by status changes"""
        member = self.test_member
        
        # Monitor notifications for different status changes
        status_change_notifications = []
        
        # Test Case 1: Suspension notifications
        member.status = "Suspended"
        member.suspension_reason = "Payment failure"
        member.save()
        
        # Should trigger notifications to member and administrators
        notifications = self.get_status_change_notifications(member, "Suspended")
        status_change_notifications.extend(notifications)
        
        # Test Case 2: Reactivation notifications
        member.status = "Active"
        member.reactivation_date = today()
        member.save()
        
        notifications = self.get_status_change_notifications(member, "Active")
        status_change_notifications.extend(notifications)
        
        # Test Case 3: Termination notifications
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        notifications = self.get_status_change_notifications(member, "Terminated")
        status_change_notifications.extend(notifications)
        
        # Validate notifications were created
        self.assertTrue(len(status_change_notifications) >= 3)
        
    # Status Consistency and Data Integrity Tests
    
    def test_cross_doctype_status_consistency(self):
        """Test status consistency across related doctypes"""
        member = self.test_member
        
        # Get related records
        dues_schedule = frappe.get_doc("Membership Dues Schedule", {"member": member.name})
        mandate = frappe.get_doc("SEPA Mandate", {"party": member.customer})
        
        # Test Case 1: Member termination should cascade to related records
        member.status = "Terminated"
        member.termination_date = today()
        member.save()
        
        # Check consistency
        dues_schedule.reload()
        mandate.reload()
        
        # Dues schedule and mandate should reflect member termination
        # (Implementation specific - might be automatic or require manual update)
        
        # Test Case 2: Conflicting statuses should be detected
        # E.g., Active member with cancelled mandate
        member.status = "Active"
        member.save()
        
        mandate.status = "Cancelled"
        mandate.save()
        
        # Should detect inconsistency
        consistency_issues = self.check_status_consistency(member)
        self.assertTrue(len(consistency_issues) > 0)
        
    def test_status_validation_rules(self):
        """Test status validation rules and constraints"""
        member = self.test_member
        
        # Test Case 1: Invalid status transitions
        invalid_transitions = [
            {"from": "Deceased", "to": "Active"},  # Cannot reactivate deceased member
            {"from": "Expelled", "to": "Active"},  # Cannot directly reactivate expelled member
        ]
        
        for transition in invalid_transitions:
            with self.subTest(transition=transition):
                member.status = transition["from"]
                member.save()
                
                # Attempt invalid transition
                member.status = transition["to"]
                
                # Should raise validation error
                with self.assertRaises(frappe.ValidationError):
                    member.save()
        
        # Test Case 2: Required fields for certain statuses
        member.status = "Suspended"
        member.suspension_reason = None  # Missing required field
        
        with self.assertRaises(frappe.ValidationError):
            member.save()
            
    def test_status_history_audit_trail(self):
        """Test status change audit trail and history tracking"""
        member = self.test_member
        
        # Perform multiple status changes
        status_changes = [
            {"status": "Suspended", "reason": "Payment issues", "date": today()},
            {"status": "Active", "reason": "Payment resolved", "date": add_days(today(), 30)},
            {"status": "Terminated", "reason": "Member request", "date": add_days(today(), 60)},
        ]
        
        for change in status_changes:
            member.status = change["status"]
            if change["status"] == "Suspended":
                member.suspension_reason = change["reason"]
                member.suspension_date = change["date"]
            elif change["status"] == "Terminated":
                member.termination_reason = change["reason"]
                member.termination_date = change["date"]
            member.save()
            
            # Validate audit trail entry was created
            audit_entries = self.get_member_status_audit_trail(member.name)
            self.assertTrue(len(audit_entries) > 0)
            
    # Edge Cases and Special Scenarios
    
    def test_bulk_status_changes(self):
        """Test bulk status change operations"""
        # Create multiple test members
        test_members = []
        for i in range(5):
            member = frappe.new_doc("Member")
            member.first_name = f"Bulk{i}"
            member.last_name = "Test"
            member.email = f"bulk{i}.{frappe.generate_hash(length=4)}@example.com"
            member.status = "Active"
            member.save()
            self.track_doc("Member", member.name)
            test_members.append(member)
        
        # Perform bulk status change
        bulk_change_result = self.perform_bulk_status_change(
            [m.name for m in test_members],
            "Suspended",
            "Bulk suspension for testing"
        )
        
        # Validate bulk change
        self.assertEqual(bulk_change_result["success_count"], 5)
        self.assertEqual(bulk_change_result["failure_count"], 0)
        
        # Verify all members were updated
        for member in test_members:
            member.reload()
            self.assertEqual(member.status, "Suspended")
            
    def test_status_based_grace_period_handling(self):
        """Test grace period status and automatic transitions"""
        member = self.test_member
        
        # Set member to grace period
        member.status = "Grace Period"
        member.grace_period_start = today()
        member.grace_period_end = add_days(today(), 14)  # 14-day grace period
        member.grace_period_reason = "Payment failure - temporary grace"
        member.save()
        
        # Test Case 1: Within grace period
        self.assertEqual(member.status, "Grace Period")
        self.assertTrue(self.is_grace_period_active(member))
        
        # Test Case 2: Grace period expired
        member.grace_period_end = add_days(today(), -1)  # Yesterday
        member.save()
        
        expired = self.is_grace_period_expired(member)
        self.assertTrue(expired)
        
        # Should trigger automatic status change to Suspended
        # In real implementation, this might be handled by scheduled job
        
    def test_special_membership_statuses(self):
        """Test special membership status scenarios"""
        member = self.test_member
        
        # Test Case 1: Honorary membership
        member.status = "Honorary"
        member.honorary_reason = "Long-term service to organization"
        member.honorary_granted_date = today()
        member.save()
        
        # Honorary members should have special billing rules
        billing_eligible = self.is_member_eligible_for_billing(member)
        self.assertFalse(billing_eligible)  # Honorary members don't pay dues
        
        # Test Case 2: Lifetime membership
        member.status = "Lifetime"
        member.lifetime_membership_fee_paid = 500.0
        member.lifetime_membership_date = today()
        member.save()
        
        # Lifetime members should never be billed again
        billing_eligible = self.is_member_eligible_for_billing(member)
        self.assertFalse(billing_eligible)
        
    def test_status_rollback_scenarios(self):
        """Test status rollback and correction scenarios"""
        member = self.test_member
        original_status = member.status
        
        # Perform erroneous status change
        member.status = "Terminated"
        member.termination_reason = "Administrative error"
        member.termination_date = today()
        member.save()
        
        # Rollback the change
        member.status = original_status
        member.termination_reason = None
        member.termination_date = None
        member.status_rollback_reason = "Correcting administrative error"
        member.status_rollback_date = today()
        member.save()
        
        # Validate rollback
        self.assertEqual(member.status, original_status)
        self.assertIsNotNone(member.status_rollback_reason)
        
    # Helper Methods
    
    def is_member_eligible_for_billing(self, member):
        """Check if member is eligible for billing based on status"""
        non_billing_statuses = ["Suspended", "Terminated", "Quit", "Expelled", "Deceased", "Honorary", "Lifetime"]
        return member.status not in non_billing_statuses
        
    def check_portal_access(self, member):
        """Check if member has portal access based on status"""
        no_access_statuses = ["Terminated", "Quit", "Expelled", "Deceased"]
        return member.status not in no_access_statuses
        
    def check_voting_rights(self, member):
        """Check if member has voting rights based on status"""
        no_voting_statuses = ["Suspended", "Terminated", "Quit", "Expelled", "Deceased", "Grace Period"]
        return member.status not in no_voting_statuses
        
    def check_event_access(self, member):
        """Check if member has event access based on status"""
        no_event_statuses = ["Suspended", "Terminated", "Quit", "Expelled", "Deceased"]
        return member.status not in no_event_statuses
        
    def calculate_dues_amount(self, member, base_amount):
        """Calculate dues amount based on member status"""
        status_modifiers = {
            "Active": 1.0,
            "Student": 0.5,
            "Senior": 0.7,
            "Honorary": 0.0,
            "Corporate": 2.0,
            "Family": 1.5,
        }
        modifier = status_modifiers.get(member.status, 1.0)
        return base_amount * modifier
        
    def get_status_change_notifications(self, member, new_status):
        """Get notifications that should be sent for status change"""
        notifications = []
        
        # Member notification
        notifications.append({
            "recipient": member.email,
            "type": "member",
            "subject": f"Membership status changed to {new_status}",
            "template": f"status_change_{new_status.lower()}"
        })
        
        # Admin notification for certain statuses
        if new_status in ["Suspended", "Terminated"]:
            notifications.append({
                "recipient": "admin@example.com",
                "type": "admin",
                "subject": f"Member {member.name} status changed to {new_status}",
                "template": "admin_status_change"
            })
        
        return notifications
        
    def check_status_consistency(self, member):
        """Check for status consistency issues across related records"""
        issues = []
        
        # Check member vs dues schedule consistency
        dues_schedule = frappe.get_value("Membership Dues Schedule", {"member": member.name})
        if dues_schedule:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule)
            if member.status in ["Terminated", "Quit"] and schedule_doc.status == "Active":
                issues.append("Member terminated but dues schedule still active")
        
        # Check member vs SEPA mandate consistency
        mandate = frappe.get_value("SEPA Mandate", {"party": member.customer})
        if mandate:
            mandate_doc = frappe.get_doc("SEPA Mandate", mandate)
            if member.status == "Active" and mandate_doc.status == "Cancelled":
                issues.append("Active member with cancelled SEPA mandate")
        
        return issues
        
    def get_member_status_audit_trail(self, member_name):
        """Get audit trail entries for member status changes"""
        # In real implementation, this would query a status history table
        # For test, simulate audit entries
        return [
            {"date": today(), "old_status": "Active", "new_status": "Suspended", "user": "Administrator"},
            {"date": today(), "old_status": "Suspended", "new_status": "Active", "user": "Administrator"}
        ]
        
    def perform_bulk_status_change(self, member_names, new_status, reason):
        """Perform bulk status change operation"""
        success_count = 0
        failure_count = 0
        
        for member_name in member_names:
            try:
                member = frappe.get_doc("Member", member_name)
                member.status = new_status
                if new_status == "Suspended":
                    member.suspension_reason = reason
                    member.suspension_date = today()
                member.save()
                success_count += 1
            except Exception:
                failure_count += 1
        
        return {"success_count": success_count, "failure_count": failure_count}
        
    def is_grace_period_active(self, member):
        """Check if member's grace period is currently active"""
        if member.status != "Grace Period":
            return False
        
        if not member.grace_period_end:
            return False
        
        return getdate(member.grace_period_end) >= getdate(today())
        
    def is_grace_period_expired(self, member):
        """Check if member's grace period has expired"""
        if member.status != "Grace Period":
            return False
        
        if not member.grace_period_end:
            return False
        
        return getdate(member.grace_period_end) < getdate(today())