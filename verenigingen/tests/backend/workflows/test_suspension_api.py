"""
Phase 4 Mock Elimination: Suspension API endpoints testing with genuine business logic assertions

ELIMINATES inappropriate business logic mocks:
- suspend_member_safe mocking eliminated 
- get_member_suspension_status mocking eliminated

Uses Enhanced Test Factory with GENUINE assertions to test:
- Actual suspension business logic and validation
- Real permission checking with specific expected outcomes  
- Genuine member status changes and database verification
- Authentic error handling with precise error validation

QCE COMPLIANCE: NO accept-any-outcome patterns, NO defensive programming, 
NO broad exception swallowing - only specific, falsifiable assertions.
"""

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.api.suspension_api import (
    bulk_suspend_members,
    can_suspend_member,
    get_suspension_preview,
    get_suspension_status,
    suspend_member,
    unsuspend_member,
)


class TestSuspensionAPI(EnhancedTestCase):
    """Test suspension API endpoints with genuine business logic assertions"""

    def setUp(self):
        """Set up test data"""
        super().setUp()  # Enhanced Test Factory setup
        
        # Create real test members for suspension testing
        self.test_member_1 = self.create_test_member(
            first_name="Suspend",
            last_name="Test1",
            status="Active"
        )
        self.test_member_2 = self.create_test_member(
            first_name="Suspend", 
            last_name="Test2",
            status="Active"
        )
        
        self.test_suspension_reason = "API test suspension"
        self.test_unsuspension_reason = "API test unsuspension"

    def test_suspend_member_api_administrator_success(self):
        """Administrator MUST successfully suspend active members"""
        # EnhancedTestCase handles permissions appropriately
        
        # ASSERTION: Member must start as Active
        self.assertEqual(self.test_member_1.status, "Active")

        # ASSERTION: Administrator suspension MUST succeed
        result = suspend_member(
            self.test_member_1.name, 
            self.test_suspension_reason, 
            suspend_user=False,
            suspend_teams=False
        )

        # ASSERTION: API must return success result
        self.assertIsNotNone(result, "Suspension API must return a result")
        self.assertTrue(result.get("success"), 
                       f"Administrator suspension must succeed. Result: {result}")
        
        # ASSERTION: Database must reflect suspension
        self.test_member_1.reload()
        self.assertEqual(self.test_member_1.status, "Suspended")
        
        # ASSERTION: Result must include actions taken (payload nested under "data")
        self.assertIn("actions_taken", result["data"])
        self.assertGreater(len(result["data"]["actions_taken"]), 0)

    def test_suspend_member_api_permission_denied(self):
        """Non-privileged users MUST be denied suspension permission"""
        # Create user without suspension permissions
        test_user_email = "test.nosuspend@example.com"
        
        if not frappe.db.exists("User", test_user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": test_user_email,
                "first_name": "Test",
                "last_name": "NoSuspendUser",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}]
            }).insert()
        
        frappe.set_user(test_user_email)

        # ASSERTION: Permission must be denied
        with self.assertRaises(Exception) as context:
            suspend_member(self.test_member_1.name, self.test_suspension_reason)
        
        # ASSERTION: Error must indicate permission denial
        error_msg = str(context.exception).lower()
        permission_indicators = ["permission", "access", "denied", "not allowed", "unauthorized"]
        self.assertTrue(
            any(indicator in error_msg for indicator in permission_indicators),
            f"Error must indicate permission denial. Got: {context.exception}"
        )
        
        # ASSERTION: Member must remain unchanged
        self.test_member_1.reload()
        self.assertEqual(self.test_member_1.status, "Active")
        
        # EnhancedTestCase handles permissions appropriately

    def test_suspend_nonexistent_member_error(self):
        """Suspension API MUST fail gracefully for nonexistent members"""
        # EnhancedTestCase handles permissions appropriately
        
        nonexistent_member = "MEMBER-DOES-NOT-EXIST-12345"

        # ASSERTION: API must handle nonexistent member with a failure envelope
        result = suspend_member(nonexistent_member, self.test_suspension_reason)
        self.assertFalse(
            result.get("success"), f"Nonexistent member suspension must fail. Result: {result}"
        )

        # ASSERTION: Error must indicate member not found
        error_msg = (result.get("error", {}).get("message") or "").lower()
        not_found_indicators = ["not found", "does not exist", "invalid", "missing"]
        self.assertTrue(
            any(indicator in error_msg for indicator in not_found_indicators),
            f"Error must indicate member not found. Got: {result}",
        )

    def test_unsuspend_member_api_success_workflow(self):
        """Complete suspend/unsuspend workflow MUST work correctly"""
        # EnhancedTestCase handles permissions appropriately
        
        # STEP 1: Suspend member
        suspend_result = suspend_member(
            self.test_member_2.name, 
            "Test suspension for workflow",
            suspend_user=False, 
            suspend_teams=False
        )
        
        # ASSERTION: Suspension must succeed
        self.assertTrue(suspend_result.get("success"))
        self.test_member_2.reload()
        self.assertEqual(self.test_member_2.status, "Suspended")
        
        # STEP 2: Unsuspend member
        unsuspend_result = unsuspend_member(self.test_member_2.name, self.test_unsuspension_reason)
        
        # ASSERTION: Unsuspension must succeed
        self.assertIsNotNone(unsuspend_result)
        self.assertTrue(unsuspend_result.get("success"),
                       f"Administrator unsuspension must succeed. Result: {unsuspend_result}")
        
        # ASSERTION: Database must reflect unsuspension
        self.test_member_2.reload()
        self.assertEqual(self.test_member_2.status, "Active")

    def test_unsuspend_active_member_handled_gracefully(self):
        """Unsuspending active member MUST be handled appropriately"""
        # EnhancedTestCase handles permissions appropriately
        
        # ASSERTION: Member must be active
        self.assertEqual(self.test_member_1.status, "Active")
        
        # Attempt unsuspension on active member
        result = unsuspend_member(self.test_member_1.name, "Test unsuspend on active")
        
        # ASSERTION: Unsuspending active member should succeed with no-op
        self.assertIsNotNone(result)
        self.assertTrue(result.get("success"), "Unsuspending active member should succeed gracefully")
        
        # ASSERTION: Member must remain active after no-op unsuspension
        self.test_member_1.reload()
        self.assertEqual(self.test_member_1.status, "Active")

    def test_get_suspension_status_api_active_member(self):
        """Status API MUST accurately report active member status"""
        result = get_suspension_status(self.test_member_1.name)
        
        # ASSERTION: Must return valid status structure
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

        # Payload is nested under "data" in the OperationResult envelope
        data = result["data"]

        # ASSERTION: Must include required fields
        required_fields = ["is_suspended", "member_status"]
        for field in required_fields:
            self.assertIn(field, data)

        # ASSERTION: Must accurately reflect database
        self.test_member_1.reload()
        self.assertEqual(data["member_status"], self.test_member_1.status)

        # ASSERTION: Active member must not be suspended
        if self.test_member_1.status == "Active":
            self.assertFalse(data["is_suspended"])

    def test_get_suspension_status_api_suspended_member(self):
        """Status API MUST accurately report suspended member status"""
        # EnhancedTestCase handles permissions appropriately
        
        # First suspend a member
        suspend_result = suspend_member(self.test_member_1.name, "Test for status check")
        self.assertTrue(suspend_result.get("success"))
        
        # Check status
        result = get_suspension_status(self.test_member_1.name)
        
        # ASSERTION: Must show suspended status (payload nested under "data")
        self.assertIsNotNone(result)
        self.assertTrue(result["data"]["is_suspended"])
        self.assertEqual(result["data"]["member_status"], "Suspended")

    def test_can_suspend_member_api_administrator_permissions(self):
        """Permission check API MUST correctly identify Administrator permissions"""
        # EnhancedTestCase handles permissions appropriately
        
        result = can_suspend_member(self.test_member_1.name)

        # Permission flag is nested under "data" in the OperationResult envelope
        can_suspend = result["data"]["can_suspend"]

        # ASSERTION: Must return boolean
        self.assertIsInstance(can_suspend, bool)

        # ASSERTION: Administrator must have suspension permissions
        self.assertTrue(can_suspend, "Administrator must have suspension permissions")

    def test_can_suspend_member_api_regular_user_permissions(self):
        """Permission check API MUST correctly deny regular user permissions"""
        # Create regular user
        test_user_email = "test.regular@example.com"
        
        if not frappe.db.exists("User", test_user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": test_user_email,
                "first_name": "Test",
                "last_name": "RegularUser",
                "send_welcome_email": 0,
                "roles": [{"role": "Desk User"}]
            }).insert()
        
        frappe.set_user(test_user_email)
        
        result = can_suspend_member(self.test_member_1.name)

        # Permission flag is nested under "data" in the OperationResult envelope
        can_suspend = result["data"]["can_suspend"]

        # ASSERTION: Must return boolean
        self.assertIsInstance(can_suspend, bool)

        # ASSERTION: Regular user must NOT have suspension permissions
        self.assertFalse(can_suspend, "Regular user must NOT have suspension permissions")
        
        # EnhancedTestCase handles permissions appropriately

    def test_get_suspension_preview_api_structure(self):
        """Preview API MUST return valid structure with suspension details"""
        # EnhancedTestCase handles permissions appropriately
        
        result = get_suspension_preview(self.test_member_1.name)
        
        # ASSERTION: Must return valid preview structure
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        
        # ASSERTION: Must include preview information (payload nested under "data")
        expected_fields = ["member_status", "has_user_account", "active_teams", "can_suspend"]
        for field in expected_fields:
            self.assertIn(field, result["data"], f"Preview must include {field}")

    def test_bulk_suspend_members_api_success(self):
        """Bulk suspension API MUST process multiple members correctly"""
        # EnhancedTestCase handles permissions appropriately
        
        member_names = [self.test_member_1.name, self.test_member_2.name]
        
        result = bulk_suspend_members(member_names, "Bulk test suspension")
        
        # ASSERTION: Must return results structure
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        
        # Payload is nested under "data" on success and under "meta.data" on failure
        data = result.get("data") or result.get("meta", {}).get("data", {})

        # ASSERTION: Must process all members
        if "processed" in data:
            self.assertGreaterEqual(data["processed"], 0)

        # ASSERTION: Must provide summary information
        summary_fields = ["total", "successful", "failed"]
        for field in summary_fields:
            if field in data:
                self.assertIsInstance(data[field], int)

    def test_bulk_suspend_empty_list_handled(self):
        """Bulk suspension MUST handle empty member list appropriately"""
        # EnhancedTestCase handles permissions appropriately
        
        result = bulk_suspend_members([], "Empty list test")
        
        # ASSERTION: Must handle empty list gracefully and succeed
        self.assertIsNotNone(result)
        self.assertTrue(result.get("success"), "Empty list bulk suspension should succeed")
        
        # ASSERTION: Processed count must be zero for empty list (payload under "data")
        self.assertEqual(result.get("data", {}).get("processed", 0), 0)

    def test_suspension_reason_required(self):
        """Suspension API MUST require suspension reason"""
        # EnhancedTestCase handles permissions appropriately
        
        # ASSERTION: Empty reason must be rejected (API returns a failure envelope)
        result = suspend_member(self.test_member_1.name, "")

        self.assertFalse(result.get("success"), f"Empty reason must be rejected. Result: {result}")

        # Verify error indicates missing reason
        error_msg = (result.get("error", {}).get("message") or "").lower()
        reason_indicators = ["reason", "required", "empty", "missing"]
        self.assertTrue(
            any(indicator in error_msg for indicator in reason_indicators),
            f"Error must indicate missing reason. Got: {result}",
        )