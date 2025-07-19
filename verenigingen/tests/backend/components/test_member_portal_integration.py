# -*- coding: utf-8 -*-
"""
Member portal integration tests covering status-dependent functionality and access controls
Tests how member status affects portal features, permissions, and user experience
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, add_to_date, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta


class TestMemberPortalIntegration(VereningingenTestCase):
    """Test member portal functionality with different member statuses and scenarios"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member_with_portal_setup()
        
    def create_test_member_with_portal_setup(self):
        """Create a test member with full portal setup"""
        member = frappe.new_doc("Member")
        member.first_name = "Portal"
        member.last_name = "TestUser"
        member.email = f"portal.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Portal Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.status = "Active"
        member.save()
        self.track_doc("Member", member.name)
        
        # Create customer for member
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        
        member.customer = customer.name
        member.save()
        
        # Create portal user
        user = frappe.new_doc("User")
        user.email = member.email
        user.first_name = member.first_name
        user.last_name = member.last_name
        user.enabled = 1
        user.user_type = "Website User"
        user.append("roles", {"role": "Verenigingen Member"})
        user.save()
        self.track_doc("User", user.name)
        
        return member
        
    # Portal Access Control Tests
    
    def test_portal_access_by_member_status(self):
        """Test portal access permissions based on different member statuses"""
        member = self.test_member
        
        # Test active member portal access
        portal_access_scenarios = [
            {"status": "Active", "should_have_access": True, "features": ["dashboard", "profile", "payments", "events"]},
            {"status": "Suspended", "should_have_access": True, "features": ["dashboard", "profile"], "restricted": ["payments", "events"]},
            {"status": "Terminated", "should_have_access": False, "features": [], "restricted": ["dashboard", "profile", "payments", "events"]},
            {"status": "Expired", "should_have_access": False, "features": [], "restricted": ["dashboard", "profile", "payments", "events"]},
            {"status": "Banned", "should_have_access": False, "features": [], "restricted": ["dashboard", "profile", "payments", "events"]},
            {"status": "Deceased", "should_have_access": False, "features": [], "restricted": ["dashboard", "profile", "payments", "events"]},
        ]
        
        for scenario in portal_access_scenarios:
            with self.subTest(status=scenario["status"]):
                member.status = scenario["status"]
                member.save()
                
                # Test basic portal access
                has_access = self.check_portal_access(member)
                self.assertEqual(has_access, scenario["should_have_access"])
                
                # Test feature access
                for feature in scenario.get("features", []):
                    feature_access = self.check_feature_access(member, feature)
                    self.assertTrue(feature_access, f"Member with {scenario['status']} should have {feature} access")
                
                # Test restricted features
                for feature in scenario.get("restricted", []):
                    feature_access = self.check_feature_access(member, feature)
                    self.assertFalse(feature_access, f"Member with {scenario['status']} should NOT have {feature} access")
                    
    def test_portal_dashboard_content_by_status(self):
        """Test dashboard content adaptation based on member status"""
        member = self.test_member
        
        # Test Active member dashboard
        member.status = "Active"
        member.save()
        
        dashboard_content = self.get_member_dashboard_content(member)
        self.assertIn("membership_status", dashboard_content)
        self.assertIn("payment_information", dashboard_content)
        self.assertIn("upcoming_events", dashboard_content)
        self.assertIn("volunteer_opportunities", dashboard_content)
        
        # Test Suspended member dashboard
        member.status = "Suspended"
        member.suspension_reason = "Payment overdue"
        member.save()
        
        dashboard_content = self.get_member_dashboard_content(member)
        self.assertIn("suspension_notice", dashboard_content)
        self.assertIn("payment_resolution_steps", dashboard_content)
        self.assertNotIn("upcoming_events", dashboard_content)
        self.assertNotIn("volunteer_opportunities", dashboard_content)
        
        # Test member with grace period (using membership grace period status)
        member.status = "Active"
        member.save()
        
        # Create membership with grace period status
        membership = self.create_test_membership_for_member(member)
        membership.grace_period_status = "Grace Period"
        membership.grace_period_expiry_date = add_days(today(), 7)
        membership.save()
        
        dashboard_content = self.get_member_dashboard_content(member)
        self.assertIn("grace_period_warning", dashboard_content)
        self.assertIn("payment_urgency", dashboard_content)
        self.assertIn("days_remaining", dashboard_content)
        
    def test_payment_portal_functionality_by_status(self):
        """Test payment portal features based on member status"""
        member = self.test_member
        
        # Create dues schedule for testing
        dues_schedule = self.create_test_dues_schedule_for_member(member)
        
        # Test Active member payment features
        member.status = "Active"
        member.save()
        
        payment_features = self.get_payment_portal_features(member)
        self.assertTrue(payment_features.get("can_view_invoices"))
        self.assertTrue(payment_features.get("can_make_payments"))
        self.assertTrue(payment_features.get("can_update_payment_method"))
        self.assertTrue(payment_features.get("can_view_payment_history"))
        
        # Test Suspended member payment features
        member.status = "Suspended"
        member.save()
        
        payment_features = self.get_payment_portal_features(member)
        self.assertTrue(payment_features.get("can_view_invoices"))
        self.assertTrue(payment_features.get("can_make_payments"))  # Can pay to resolve suspension
        self.assertFalse(payment_features.get("can_update_payment_method"))  # Restricted during suspension
        self.assertTrue(payment_features.get("can_view_payment_history"))
        
        # Test Terminated member payment features
        member.status = "Terminated"
        member.save()
        
        payment_features = self.get_payment_portal_features(member)
        self.assertFalse(payment_features.get("can_view_invoices"))
        self.assertFalse(payment_features.get("can_make_payments"))
        self.assertFalse(payment_features.get("can_update_payment_method"))
        self.assertFalse(payment_features.get("can_view_payment_history"))
        
    def test_member_profile_editing_restrictions(self):
        """Test profile editing restrictions based on member status"""
        member = self.test_member
        
        # Active member - full editing rights
        member.status = "Active"
        member.save()
        
        profile_permissions = self.get_profile_editing_permissions(member)
        self.assertTrue(profile_permissions.get("can_edit_contact_info"))
        self.assertTrue(profile_permissions.get("can_edit_address"))
        self.assertTrue(profile_permissions.get("can_edit_preferences"))
        self.assertTrue(profile_permissions.get("can_update_communication_preferences"))
        
        # Suspended member - limited editing
        member.status = "Suspended"
        member.save()
        
        profile_permissions = self.get_profile_editing_permissions(member)
        self.assertTrue(profile_permissions.get("can_edit_contact_info"))  # Can update contact for resolution
        self.assertFalse(profile_permissions.get("can_edit_address"))  # Restricted during suspension
        self.assertFalse(profile_permissions.get("can_edit_preferences"))
        self.assertTrue(profile_permissions.get("can_update_communication_preferences"))  # Can update for notifications
        
        # Terminated member - no editing
        member.status = "Terminated"
        member.save()
        
        profile_permissions = self.get_profile_editing_permissions(member)
        self.assertFalse(profile_permissions.get("can_edit_contact_info"))
        self.assertFalse(profile_permissions.get("can_edit_address"))
        self.assertFalse(profile_permissions.get("can_edit_preferences"))
        self.assertFalse(profile_permissions.get("can_update_communication_preferences"))
        
    # Event and Activity Access Tests
    
    def test_event_registration_by_member_status(self):
        """Test event registration capabilities based on member status"""
        member = self.test_member
        
        # Create test event
        event = self.create_test_event()
        
        # Active member - can register for events
        member.status = "Active"
        member.save()
        
        registration_result = self.attempt_event_registration(member, event)
        self.assertTrue(registration_result.get("success"))
        self.assertNotIn("status_restriction", registration_result.get("errors", []))
        
        # Suspended member - cannot register for events
        member.status = "Suspended"
        member.save()
        
        registration_result = self.attempt_event_registration(member, event)
        self.assertFalse(registration_result.get("success"))
        self.assertIn("status_restriction", registration_result.get("errors", []))
        
        # Member with grace period membership - can register with warning
        member.status = "Active"
        membership.grace_period_status = "Grace Period"
        membership.save()
        member.save()
        
        registration_result = self.attempt_event_registration(member, event)
        self.assertTrue(registration_result.get("success"))
        self.assertIn("grace_period_warning", registration_result.get("warnings", []))
        
    def test_volunteer_portal_access_by_status(self):
        """Test volunteer portal access based on member status"""
        member = self.test_member
        
        # Create volunteer record for member
        volunteer = self.create_test_volunteer_for_member(member)
        
        # Active member - full volunteer access
        member.status = "Active"
        member.save()
        
        volunteer_access = self.get_volunteer_portal_access(member)
        self.assertTrue(volunteer_access.get("can_view_assignments"))
        self.assertTrue(volunteer_access.get("can_accept_new_assignments"))
        self.assertTrue(volunteer_access.get("can_submit_expenses"))
        self.assertTrue(volunteer_access.get("can_access_volunteer_resources"))
        
        # Suspended member - limited volunteer access
        member.status = "Suspended"
        member.save()
        
        volunteer_access = self.get_volunteer_portal_access(member)
        self.assertTrue(volunteer_access.get("can_view_assignments"))  # Can view current assignments
        self.assertFalse(volunteer_access.get("can_accept_new_assignments"))  # Cannot take new work
        self.assertTrue(volunteer_access.get("can_submit_expenses"))  # Can submit for existing work
        self.assertFalse(volunteer_access.get("can_access_volunteer_resources"))
        
        # Terminated member - no volunteer access
        member.status = "Terminated"
        member.save()
        
        volunteer_access = self.get_volunteer_portal_access(member)
        self.assertFalse(volunteer_access.get("can_view_assignments"))
        self.assertFalse(volunteer_access.get("can_accept_new_assignments"))
        self.assertFalse(volunteer_access.get("can_submit_expenses"))
        self.assertFalse(volunteer_access.get("can_access_volunteer_resources"))
        
    # Communication and Notification Tests
    
    def test_communication_preferences_by_status(self):
        """Test communication preferences and restrictions by member status"""
        member = self.test_member
        
        # Active member - all communication types available
        member.status = "Active"
        member.save()
        
        comm_options = self.get_communication_options(member)
        self.assertIn("newsletter", comm_options.get("available_types", []))
        self.assertIn("event_notifications", comm_options.get("available_types", []))
        self.assertIn("volunteer_opportunities", comm_options.get("available_types", []))
        self.assertIn("administrative_updates", comm_options.get("available_types", []))
        
        # Suspended member - administrative only
        member.status = "Suspended"
        member.save()
        
        comm_options = self.get_communication_options(member)
        self.assertNotIn("newsletter", comm_options.get("available_types", []))
        self.assertNotIn("event_notifications", comm_options.get("available_types", []))
        self.assertNotIn("volunteer_opportunities", comm_options.get("available_types", []))
        self.assertIn("administrative_updates", comm_options.get("available_types", []))  # Required for resolution
        self.assertIn("payment_reminders", comm_options.get("forced_types", []))
        
        # Terminated member - minimal communication
        member.status = "Terminated"
        member.save()
        
        comm_options = self.get_communication_options(member)
        self.assertEqual(len(comm_options.get("available_types", [])), 0)
        self.assertIn("termination_updates", comm_options.get("forced_types", []))
        
    def test_notification_delivery_by_status(self):
        """Test notification delivery based on member status"""
        member = self.test_member
        
        # Test different notification types and member statuses
        notification_scenarios = [
            {"status": "Active", "type": "newsletter", "should_deliver": True},
            {"status": "Active", "type": "payment_reminder", "should_deliver": True},
            {"status": "Active", "type": "event_invitation", "should_deliver": True},
            {"status": "Suspended", "type": "newsletter", "should_deliver": False},
            {"status": "Suspended", "type": "payment_reminder", "should_deliver": True},
            {"status": "Suspended", "type": "event_invitation", "should_deliver": False},
            {"status": "Terminated", "type": "newsletter", "should_deliver": False},
            {"status": "Terminated", "type": "payment_reminder", "should_deliver": False},
            {"status": "Terminated", "type": "event_invitation", "should_deliver": False},
            {"status": "Terminated", "type": "administrative_notice", "should_deliver": True},
        ]
        
        for scenario in notification_scenarios:
            with self.subTest(status=scenario["status"], type=scenario["type"]):
                member.status = scenario["status"]
                member.save()
                
                delivery_allowed = self.check_notification_delivery(member, scenario["type"])
                self.assertEqual(delivery_allowed, scenario["should_deliver"])
                
    # Status Transition Portal Tests
    
    def test_status_change_portal_experience(self):
        """Test portal experience during status transitions"""
        member = self.test_member
        
        # Scenario 1: Active to Suspended transition
        member.status = "Active"
        member.save()
        
        # Simulate real-time status change
        member.status = "Suspended"
        member.suspension_reason = "Payment overdue"
        member.suspension_date = today()
        member.save()
        
        # Portal should immediately reflect new restrictions
        portal_state = self.get_portal_state_after_status_change(member)
        self.assertIn("suspension_banner", portal_state.get("ui_elements", []))
        self.assertIn("payment_resolution_cta", portal_state.get("ui_elements", []))
        self.assertEqual(portal_state.get("navigation_restrictions"), ["events", "volunteer_signup"])
        
        # Scenario 2: Suspended to Active transition
        member.status = "Active"
        member.suspension_reason = None
        member.suspension_date = None
        member.reactivation_date = today()
        member.save()
        
        portal_state = self.get_portal_state_after_status_change(member)
        self.assertIn("reactivation_welcome", portal_state.get("ui_elements", []))
        self.assertEqual(len(portal_state.get("navigation_restrictions", [])), 0)
        
    def test_portal_session_handling_during_status_change(self):
        """Test portal session behavior when member status changes during active session"""
        member = self.test_member
        
        # Start with active member session
        member.status = "Active"
        member.save()
        
        session_data = self.simulate_portal_session_start(member)
        self.assertTrue(session_data.get("valid_session"))
        self.assertIn("full_access", session_data.get("permissions", []))
        
        # Change status to suspended during session
        member.status = "Suspended"
        member.save()
        
        # Next portal request should reflect new restrictions
        updated_session = self.simulate_portal_request_after_status_change(member, session_data)
        self.assertTrue(updated_session.get("valid_session"))  # Session still valid
        self.assertNotIn("full_access", updated_session.get("permissions", []))
        self.assertIn("restricted_access", updated_session.get("permissions", []))
        
        # Change status to terminated
        member.status = "Terminated"
        member.save()
        
        # Session should be invalidated
        terminated_session = self.simulate_portal_request_after_status_change(member, session_data)
        self.assertFalse(terminated_session.get("valid_session"))
        self.assertIn("status_termination", terminated_session.get("termination_reason", []))
        
    # Data Access and Privacy Tests
    
    def test_data_access_restrictions_by_status(self):
        """Test data access restrictions based on member status"""
        member = self.test_member
        
        # Create various data types for member
        invoice_data = self.create_test_invoice_data_for_member(member)
        volunteer_data = self.create_test_volunteer_data_for_member(member)
        communication_data = self.create_test_communication_data_for_member(member)
        
        # Active member - full data access
        member.status = "Active"
        member.save()
        
        data_access = self.get_member_data_access_permissions(member)
        self.assertTrue(data_access.get("can_view_invoices"))
        self.assertTrue(data_access.get("can_view_volunteer_history"))
        self.assertTrue(data_access.get("can_view_communication_history"))
        self.assertTrue(data_access.get("can_export_data"))
        
        # Suspended member - limited data access
        member.status = "Suspended"
        member.save()
        
        data_access = self.get_member_data_access_permissions(member)
        self.assertTrue(data_access.get("can_view_invoices"))  # Need for payment resolution
        self.assertFalse(data_access.get("can_view_volunteer_history"))
        self.assertFalse(data_access.get("can_view_communication_history"))
        self.assertFalse(data_access.get("can_export_data"))
        
        # Terminated member - no data access via portal
        member.status = "Terminated"
        member.save()
        
        data_access = self.get_member_data_access_permissions(member)
        self.assertFalse(data_access.get("can_view_invoices"))
        self.assertFalse(data_access.get("can_view_volunteer_history"))
        self.assertFalse(data_access.get("can_view_communication_history"))
        self.assertFalse(data_access.get("can_export_data"))
        
    # Helper Methods
    
    def check_portal_access(self, member):
        """Check if member has basic portal access"""
        if member.status in ["Terminated", "Quit", "Expelled", "Deceased"]:
            return False
        return True
        
    def check_feature_access(self, member, feature):
        """Check if member has access to specific portal feature"""
        access_matrix = {
            "dashboard": ["Active", "Suspended"],
            "profile": ["Active", "Suspended"],
            "payments": ["Active"],
            "events": ["Active"],
        }
        
        allowed_statuses = access_matrix.get(feature, [])
        return member.status in allowed_statuses
        
    def get_member_dashboard_content(self, member):
        """Get dashboard content based on member status"""
        content = {
            "membership_status": member.status,
        }
        
        if member.status == "Active":
            content.update({
                "payment_information": True,
                "upcoming_events": True,
                "volunteer_opportunities": True
            })
        elif member.status == "Suspended":
            content.update({
                "suspension_notice": True,
                "payment_resolution_steps": True
            })
        
        # Check if member has grace period membership
        membership = self.get_current_membership(member)
        if membership and membership.grace_period_status == "Grace Period":
            content.update({
                "grace_period_warning": True,
                "payment_urgency": True,
                "days_remaining": (getdate(membership.grace_period_expiry_date) - getdate(today())).days if membership.grace_period_expiry_date else 0
            })
            
        return content
        
    def get_payment_portal_features(self, member):
        """Get payment portal features available to member"""
        features = {
            "can_view_invoices": False,
            "can_make_payments": False,
            "can_update_payment_method": False,
            "can_view_payment_history": False
        }
        
        if member.status == "Active":
            features = {k: True for k in features}
        elif member.status == "Suspended":
            features.update({
                "can_view_invoices": True,
                "can_make_payments": True,
                "can_view_payment_history": True
            })
            
        return features
        
    def get_profile_editing_permissions(self, member):
        """Get profile editing permissions for member"""
        permissions = {
            "can_edit_contact_info": False,
            "can_edit_address": False,
            "can_edit_preferences": False,
            "can_update_communication_preferences": False
        }
        
        if member.status in ["Active", "Current"]:
            permissions = {k: True for k in permissions}
        elif member.status == "Suspended":
            permissions.update({
                "can_edit_contact_info": True,
                "can_update_communication_preferences": True
            })
            
        return permissions
        
    def create_test_event(self):
        """Create a test event for registration testing"""
        event = frappe.new_doc("Event")
        event.subject = "Test Member Event"
        event.event_type = "Public"
        event.starts_on = add_days(today(), 30)
        event.ends_on = add_days(today(), 30)
        event.save()
        self.track_doc("Event", event.name)
        return event
        
    def attempt_event_registration(self, member, event):
        """Attempt to register member for event"""
        result = {"success": False, "errors": [], "warnings": []}
        
        if member.status == "Active":
            # Check if member has grace period membership
            membership = self.get_current_membership(member)
            if membership and membership.grace_period_status == "Grace Period":
                result["success"] = True
                result["warnings"].append("grace_period_warning")
            else:
                result["success"] = True
        else:
            result["errors"].append("status_restriction")
            
        return result
        
    def create_test_volunteer_for_member(self, member):
        """Create volunteer record for member"""
        volunteer = frappe.new_doc("Volunteer")
        volunteer.volunteer_name = f"{member.first_name} {member.last_name}"
        volunteer.email = member.email
        volunteer.member = member.name
        volunteer.save()
        self.track_doc("Volunteer", volunteer.name)
        return volunteer
        
    def get_volunteer_portal_access(self, member):
        """Get volunteer portal access permissions"""
        access = {
            "can_view_assignments": False,
            "can_accept_new_assignments": False,
            "can_submit_expenses": False,
            "can_access_volunteer_resources": False
        }
        
        if member.status in ["Active", "Current"]:
            access = {k: True for k in access}
        elif member.status == "Suspended":
            access.update({
                "can_view_assignments": True,
                "can_submit_expenses": True
            })
            
        return access
        
    def get_communication_options(self, member):
        """Get communication options for member"""
        options = {"available_types": [], "forced_types": []}
        
        if member.status in ["Active", "Current"]:
            options["available_types"] = [
                "newsletter", "event_notifications", 
                "volunteer_opportunities", "administrative_updates"
            ]
        elif member.status == "Suspended":
            options["available_types"] = ["administrative_updates"]
            options["forced_types"] = ["payment_reminders"]
        elif member.status == "Terminated":
            options["forced_types"] = ["termination_updates"]
            
        return options
        
    def check_notification_delivery(self, member, notification_type):
        """Check if notification should be delivered to member"""
        delivery_rules = {
            "Active": ["newsletter", "payment_reminder", "event_invitation", "administrative_notice"],
            "Suspended": ["payment_reminder", "administrative_notice"],
            "Terminated": ["administrative_notice"],
            "Expired": ["administrative_notice"],
            "Banned": ["administrative_notice"],
            "Deceased": []
        }
        
        allowed_types = delivery_rules.get(member.status, [])
        return notification_type in allowed_types
        
    def get_portal_state_after_status_change(self, member):
        """Get portal UI state after status change"""
        state = {"ui_elements": [], "navigation_restrictions": []}
        
        if member.status == "Suspended":
            state["ui_elements"] = ["suspension_banner", "payment_resolution_cta"]
            state["navigation_restrictions"] = ["events", "volunteer_signup"]
        elif member.status == "Active" and hasattr(member, 'reactivation_date') and member.reactivation_date:
            state["ui_elements"] = ["reactivation_welcome"]
            
        return state
        
    def simulate_portal_session_start(self, member):
        """Simulate starting a portal session"""
        session = {"valid_session": True, "permissions": []}
        
        if member.status == "Active":
            session["permissions"] = ["full_access"]
        elif member.status == "Suspended":
            session["permissions"] = ["restricted_access"]
        else:
            session["valid_session"] = False
            
        return session
        
    def simulate_portal_request_after_status_change(self, member, original_session):
        """Simulate portal request after status change"""
        if member.status in ["Terminated", "Quit", "Expelled", "Deceased"]:
            return {
                "valid_session": False,
                "termination_reason": ["status_termination"]
            }
            
        # Update permissions based on new status
        return self.simulate_portal_session_start(member)
        
    def create_test_dues_schedule_for_member(self, member):
        """Create test dues schedule for member"""
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.amount = 25.0
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_test_invoice_data_for_member(self, member):
        """Create test invoice data for member"""
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member.customer
        invoice.member = member.name
        invoice.posting_date = today()
        invoice.is_membership_invoice = 1
        invoice.append("items", {
            "item_code": "MEMBERSHIP-MONTHLY",
            "qty": 1,
            "rate": 25.0,
            "income_account": "Sales - TC"
        })
        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice
        
    def create_test_volunteer_data_for_member(self, member):
        """Create test volunteer data for member"""
        # Volunteer data would include assignments, expenses, etc.
        return {"volunteer_assignments": 3, "total_hours": 45}
        
    def create_test_communication_data_for_member(self, member):
        """Create test communication data for member"""
        # Communication data would include emails, newsletters, etc.
        return {"emails_sent": 15, "newsletters_received": 8}
        
    def get_member_data_access_permissions(self, member):
        """Get data access permissions for member"""
        permissions = {
            "can_view_invoices": False,
            "can_view_volunteer_history": False,
            "can_view_communication_history": False,
            "can_export_data": False
        }
        
        if member.status == "Active":
            permissions = {k: True for k in permissions}
        elif member.status == "Suspended":
            permissions["can_view_invoices"] = True
            
        return permissions
    
    def get_current_membership(self, member):
        """Get current membership for member"""
        memberships = frappe.get_all("Membership", filters={
            "member": member.name,
            "status": "Active"
        }, order_by="start_date desc", limit=1)
        
        if memberships:
            return frappe.get_doc("Membership", memberships[0].name)
        return None
    
    def create_test_membership_for_member(self, member):
        """Create test membership for member"""
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = "Monthly Membership"
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        return membership