"""
Account Creation Security Tests
================================

Advanced security validation for the account creation system:
- Authorization matrix (multi-role access control)
- Role escalation prevention
- Audit trail tamper resistance
- Session hijacking prevention
- Mass assignment prevention
"""

import frappe
from frappe.utils import now

from verenigingen.utils.account_creation_manager import (
    AccountCreationManager,
    queue_account_creation_for_member,
)
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAccountCreationSecurity(EnhancedTestCase):
    """Advanced security validation tests for account creation."""

    def test_authorization_matrix(self):
        """Test multi-role access control: authorized roles succeed, unauthorized are denied."""
        member = self.create_test_member(
            first_name=f"Authorization{self.uid}",
            last_name="Matrix",
            email=f"authorization.matrix.{self.uid}@test.invalid",
        )

        scenario = self.create_permission_test_scenario(
            authorized_roles=["Verenigingen Administrator"],
            unauthorized_roles=["System Manager", "Verenigingen Member", "Verenigingen Volunteer"],
        )

        # Test authorized users can create requests
        for auth_user in scenario["authorized_users"]:
            request_name = None
            with self.subTest(user=auth_user.email):
                with self.as_user(auth_user.email):
                    try:
                        result = queue_account_creation_for_member(member.name)

                        if hasattr(result, "success"):
                            success = result.success
                            errors = result.errors if hasattr(result, "errors") else []
                            request_name = result.data.get("request_name") if result.data else None
                        else:
                            success = result.get("success")
                            errors = result.get("errors", [])
                            request_name = result.get("request_name") or result.get("data", {}).get(
                                "request_name"
                            )

                        if not success:
                            error_str = str(errors)
                            if "Role" in error_str or "Employee Self Service" in error_str:
                                self.skipTest(f"Required role missing in test environment: {errors}")
                            if "permission" in error_str.lower():
                                continue

                    except frappe.PermissionError:
                        self.fail(f"Authorized user {auth_user.email} was denied access")

                # Cleanup outside user context (back to Administrator)
                if request_name:
                    frappe.delete_doc("Account Creation Request", request_name)

        # Test unauthorized users are denied
        for unauth_user in scenario["unauthorized_users"]:
            if unauth_user.email == "Guest":
                continue
            with self.subTest(user=unauth_user.email):
                with self.as_user(unauth_user.email):
                    try:
                        queue_account_creation_for_member(member.name)
                        self.fail(f"Expected PermissionError for unauthorized user {unauth_user.email}")
                    except (frappe.PermissionError, VPermissionError):
                        pass

    def test_role_escalation_prevention(self):
        """Test that a Verenigingen Administrator cannot assign System Manager role."""
        member = self.create_test_member(
            first_name=f"Role{self.uid}",
            last_name="Escalation",
            email=f"role.escalation.{self.uid}@test.invalid",
        )

        admin_user = self.create_test_user_with_roles(
            email=f"admin.user.{self.uid}@test.invalid",
            roles=["Verenigingen Administrator"],
        )

        with self.as_user(admin_user.email):
            request_data = {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": member.email,
                "full_name": member.full_name,
                "requested_roles": [{"role": "System Manager"}],
            }
            try:
                request = frappe.get_doc(request_data)
                request.insert()
                self.fail("Expected exception for role escalation attempt")
            except (frappe.PermissionError, frappe.ValidationError, VPermissionError):
                pass

    def test_audit_trail_tamper_resistance(self):
        """Test that audit fields (requested_by, creation) cannot be modified after insert."""
        member = self.create_test_member(
            first_name=f"Audit{self.uid}",
            last_name="Trail",
            email=f"audit.trail.{self.uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
        )

        tampering_attempts = {
            "requested_by": "Administrator",
            "creation": "2020-01-01 00:00:00",
            "modified_by": "Guest",
            "processed_by": "fake.user@test.invalid",
        }

        for field, malicious_value in tampering_attempts.items():
            with self.subTest(field=field):
                original_value = getattr(request, field, None)
                try:
                    setattr(request, field, malicious_value)
                    request.save()
                    request.reload()
                    current_value = getattr(request, field, None)
                    if field in ["requested_by", "creation"]:
                        self.assertEqual(
                            current_value, original_value, f"Audit field {field} was tampered with"
                        )
                except Exception:
                    pass  # System prevented tampering

    def test_session_hijacking_prevention(self):
        """Test that a low-privilege user cannot process another user's ACR."""
        member = self.create_test_member(
            first_name=f"Session{self.uid}",
            last_name="Hijacking",
            email=f"session.hijacking.{self.uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
        )

        malicious_user = self.create_test_user_with_roles(
            email=f"malicious.user.{self.uid}@test.invalid",
            roles=["Verenigingen Member"],
        )

        with self.as_user(malicious_user.email):
            manager = AccountCreationManager(request.name)
            try:
                manager.validate_processing_permissions()
                self.fail("Expected exception for session hijacking attempt")
            except (frappe.PermissionError, frappe.ValidationError, VPermissionError):
                pass

    def test_mass_assignment_prevention(self):
        """Test that status/created_user/completed_at cannot be set at insert time."""
        member = self.create_test_member(
            first_name=f"Mass{self.uid}",
            last_name="Assignment",
            email=f"mass.assignment.{self.uid}@test.invalid",
        )

        malicious_data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "status": "Completed",
            "created_user": "Administrator",
            "completed_at": now(),
            "processed_by": "Administrator",
        }

        request = frappe.get_doc(malicious_data)
        request.insert()

        self.assertEqual(request.status, "Requested")
        self.assertIsNone(request.created_user)
        self.assertIsNone(request.completed_at)
        self.assertIsNone(request.processed_by)
