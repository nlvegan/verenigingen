"""
Comprehensive integration tests for Member Contact Request workflow
Tests the complete flow from portal submission to CRM integration
"""

import frappe
from frappe.utils import add_days, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberContactRequestIntegration(EnhancedTestCase):
    """Test Member Contact Request integration end-to-end"""

    def setUp(self):
        """Set up test data for each test using factory methods"""
        super().setUp()
        
        # Create test member using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="John",
            last_name="Doe",
            email_address="john.doe.test@example.com",
            contact_number="+31612345678",
            status="Active"
        )

        # Clean up any existing contact requests for this member
        frappe.db.delete("Member Contact Request", {"member": self.test_member.name})
        frappe.db.commit()
        # Base class will handle member cleanup automatically

    def test_contact_request_creation_basic(self):
        """Test basic contact request creation"""
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            create_contact_request,
        )

        # Create contact request
        result = create_contact_request(
            member=self.test_member.name,
            subject="Test Integration Request",
            message="This is a test message for integration testing",
            request_type="General Inquiry",
            preferred_contact_method="Email",
            urgency="Normal",
        )

        # Verify result
        self.assertTrue(result["success"])
        self.assertIn("contact_request", result)

        # Verify contact request was created
        contact_request = frappe.get_doc("Member Contact Request", result["contact_request"])
        self.assertEqual(contact_request.member, self.test_member.name)
        self.assertEqual(contact_request.subject, "Test Integration Request")
        self.assertEqual(contact_request.status, "Open")
        self.assertEqual(contact_request.member_name, self.test_member.full_name)
        self.assertEqual(contact_request.email, self.test_member.email)
        self.assertTrue(contact_request.created_by_portal)

    def test_contact_request_integration_workflow(self):
        """Test the complete contact request workflow without inappropriate mocking"""
        # Create contact request using real database operations
        contact_request = frappe.get_doc({
            "doctype": "Member Contact Request",
            "member": self.test_member.name,
            "subject": "Integration Test Request",
            "message": "Testing complete workflow",
            "request_type": "Volunteer Opportunity",
            "preferred_contact_method": "Email",
            "urgency": "Medium",
            "created_by_portal": 1
        })
        contact_request.insert()

        # Verify the contact request was created properly
        self.assertEqual(contact_request.member, self.test_member.name)
        self.assertEqual(contact_request.subject, "Integration Test Request")
        self.assertEqual(contact_request.status, "Open")
        self.assertTrue(contact_request.created_by_portal)

        # Test status progression
        contact_request.status = "In Progress"
        contact_request.save()
        self.assertEqual(contact_request.status, "In Progress")
        
        # Test completion
        contact_request.status = "Resolved"
        contact_request.resolution_notes = "Request handled successfully"
        contact_request.save()
        self.assertEqual(contact_request.status, "Resolved")
        self.assertIsNotNone(contact_request.resolution_notes)

    def test_contact_request_status_transitions(self):
        """Test contact request status transitions and automation"""
        # Create contact request
        contact_request = frappe.get_doc(
            {
                "doctype": "Member Contact Request",
                "member": self.test_member.name,
                "subject": "Status Transition Test",
                "message": "Testing status transitions",
                "request_type": "Technical Support",
                "status": "Open"}
        )
        contact_request.insert()
        self.track_doc("Member Contact Request", contact_request.name)

        # Test status change to In Progress
        contact_request.status = "In Progress"
        contact_request.save()

        # Verify response date was set
        self.assertIsNotNone(contact_request.response_date)

        # Test status change to Resolved
        contact_request.status = "Resolved"
        contact_request.save()

        # Verify closed date was set
        self.assertIsNotNone(contact_request.closed_date)

    def test_assignment_workflow(self):
        """Test assignment workflow and notifications"""
        # Create a test user for assignment

        # Create contact request
        contact_request = frappe.get_doc(
            {
                "doctype": "Member Contact Request",
                "member": self.test_member.name,
                "subject": "Assignment Test",
                "message": "Testing assignment workflow",
                "request_type": "Complaint",
                "urgency": "High"}
        )
        contact_request.insert()
        self.track_doc("Member Contact Request", contact_request.name)

        # Mock sendmail to prevent actual email sending during tests
        with patch("frappe.sendmail") as mock_sendmail:
            # Assign to user
            contact_request.assigned_to = "Administrator"
            contact_request.save()

            # Verify follow-up date was set
            self.assertIsNotNone(contact_request.follow_up_date)

    def test_get_member_contact_requests_api(self):
        """Test API for retrieving member contact requests"""
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            get_member_contact_requests,
        )

        # Create multiple contact requests
        for i in range(3):
            contact_request = frappe.get_doc(
                {
                    "doctype": "Member Contact Request",
                    "member": self.test_member.name,
                    "subject": f"Test Request {i + 1}",
                    "message": f"Test message {i + 1}",
                    "request_type": "General Inquiry",
                    "status": "Open" if i % 2 == 0 else "Resolved"}
            )
            contact_request.insert()

        # Test API call
        requests = get_member_contact_requests(self.test_member.name, limit=5)

        # Verify results
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(req["member"] == self.test_member.name for req in requests))

    def test_portal_form_submission(self):
        """Test contact request submission through portal form"""
        # Simulate portal form submission
        form_data = {
            "subject": "Portal Form Test",
            "message": "Testing portal form submission",
            "request_type": "Event Information",
            "preferred_contact_method": "Phone",
            "urgency": "Normal",
            "preferred_time": "Weekdays 9-17"}

        # Mock session user as the test member
        with patch("frappe.session.user", self.test_member.email):
            # Mock member lookup to return our test member
            with patch("frappe.db.get_value") as mock_get_value:
                mock_get_value.return_value = self.test_member.name

                # Mock member permission check
                with patch.object(self.test_member, "has_permission", return_value=True):
                    from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
                        create_contact_request,
                    )

                    result = create_contact_request(
                        member=self.test_member.name,
                        subject=form_data["subject"],
                        message=form_data["message"],
                        request_type=form_data["request_type"],
                        preferred_contact_method=form_data["preferred_contact_method"],
                        urgency=form_data["urgency"],
                        preferred_time=form_data["preferred_time"],
                    )

                    # Verify submission success
                    self.assertTrue(result["success"])

                    # Verify contact request was created with portal flag
                    contact_request = frappe.get_doc("Member Contact Request", result["contact_request"])
                    self.assertTrue(contact_request.created_by_portal)
                    self.assertEqual(contact_request.preferred_time, form_data["preferred_time"])

    @patch("frappe.sendmail")  # Mock external email service (appropriate for automation testing)
    def test_automation_workflows(self, mock_sendmail):
        """Test automated workflows like follow-ups and escalations"""
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            auto_close_resolved_requests,
            send_follow_up_reminders,
        )

        # Create overdue contact request
        overdue_request = frappe.get_doc(
            {
                "doctype": "Member Contact Request",
                "member": self.test_member.name,
                "subject": "Overdue Test Request",
                "message": "Testing overdue automation",
                "request_type": "Urgent",
                "urgency": "Urgent",
                "status": "Open",
                "request_date": add_days(today(), -2),  # 2 days ago
                "follow_up_date": today(),  # Due today
                "assigned_to": "Administrator"}
        )
        overdue_request.insert()

        # Test follow-up reminders
        send_follow_up_reminders()

        # Verify follow-up date was updated
        overdue_request.reload()
        self.assertNotEqual(overdue_request.follow_up_date, today())

        # Test auto-close for resolved requests
        resolved_request = frappe.get_doc(
            {
                "doctype": "Member Contact Request",
                "member": self.test_member.name,
                "subject": "Auto-close Test",
                "message": "Testing auto-close",
                "status": "Resolved",
                "response_date": add_days(today(), -8),  # 8 days ago
            }
        )
        resolved_request.insert()
        self.track_doc("Member Contact Request", resolved_request.name)

        auto_close_resolved_requests()

        # Verify request was auto-closed
        resolved_request.reload()
        self.assertEqual(resolved_request.status, "Closed")
        self.assertIsNotNone(resolved_request.closed_date)

    def test_permission_validation(self):
        """Test permission validation for contact requests"""
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            create_contact_request,
        )

        # Test guest user access (should fail)
        original_user = frappe.session.user
        try:
            frappe.session.user = "Guest"
            with self.assertRaises(frappe.exceptions.PermissionError):
                create_contact_request(
                    member=self.test_member.name, subject="Unauthorized Test", message="This should fail"
                )
        finally:
            frappe.session.user = original_user

        # Test user without member record (should fail)
        try:
            frappe.session.user = "no.member@example.com"
            with patch("frappe.db.get_value", return_value=None):
                with self.assertRaises(frappe.exceptions.DoesNotExistError):
                    create_contact_request(
                        member=self.test_member.name, subject="No Member Test", message="This should fail"
                    )
        finally:
            frappe.session.user = original_user

    def test_analytics_and_reporting(self):
        """Test analytics and reporting functionality"""
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            get_contact_request_analytics,
        )

        # Create test contact requests with different statuses and types
        test_requests = [
            {"status": "Open", "request_type": "General Inquiry"},
            {"status": "In Progress", "request_type": "Technical Support"},
            {"status": "Resolved", "request_type": "General Inquiry"},
            {"status": "Closed", "request_type": "Complaint"},
        ]

        for req_data in test_requests:
            contact_request = frappe.get_doc(
                {
                    "doctype": "Member Contact Request",
                    "member": self.test_member.name,
                    "subject": f"Analytics Test - {req_data['request_type']}",
                    "message": "Test for analytics",
                    "request_type": req_data["request_type"],
                    "status": req_data["status"],
                    "response_date": today() if req_data["status"] != "Open" else None}
            )
            contact_request.insert()
            self.track_doc("Member Contact Request", contact_request.name)

        # Test analytics
        analytics = get_contact_request_analytics()

        # Verify analytics structure
        self.assertIn("status_distribution", analytics)
        self.assertIn("request_types", analytics)
        self.assertIn("avg_response_time_days", analytics)
        self.assertIn("monthly_volume", analytics)


if __name__ == "__main__":
    # Can be run via:
    # bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.integration.test_member_contact_request_integration
    import unittest
    unittest.main()
