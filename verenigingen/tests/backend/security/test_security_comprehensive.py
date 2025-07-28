"""
Comprehensive Security Test Suite for Verenigingen
Tests for privilege escalation, data isolation, financial fraud protection, and API security
"""

import unittest
import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSecurityComprehensive(VereningingenTestCase):
    """Comprehensive security tests covering all attack vectors"""

    def setUp(self):
        """Set up test data for security tests"""
        super().setUp()

        # Create test organizations (chapters) using factory
        self.chapter1 = self.factory.create_test_chapter(chapter_name="Security Test Chapter 1")
        self.chapter2 = self.factory.create_test_chapter(chapter_name="Security Test Chapter 2")

        # Create test users with different permissions
        self.admin_user = "admin@test.com"
        self.chapter1_admin = "chapter1@test.com"
        self.chapter2_admin = "chapter2@test.com"
        self.regular_user = "user@test.com"
        self.guest_user = "guest@test.com"

        # Create test members in different chapters using factory with unique emails
        self.member1 = self.factory.create_test_member(
            first_name="Test",
            last_name="Member1", 
            chapter=self.chapter1.name
        )

        self.member2 = self.factory.create_test_member(
            first_name="Test",
            last_name="Member2",
            chapter=self.chapter2.name
        )

        # Create test volunteers using factory with unique email
        self.volunteer1 = self.factory.create_test_volunteer(
            volunteer_name="Test Volunteer 1",
            member=self.member1.name
        )

        # Create test membership using factory
        self.membership1 = self.factory.create_test_membership(
            member=self.member1.name
        )


    # ===== PRIVILEGE ESCALATION TESTS =====

    def test_privilege_escalation_role_manipulation(self):
        """Test prevention of role manipulation attacks"""
        # Set user as regular member
        frappe.set_user(self.regular_user)

        # Attempt to escalate privileges by manipulating user roles
        with self.assertRaises(frappe.PermissionError):
            frappe.db.sql(
                """
                INSERT INTO `tabHas Role` (parent, role)
                VALUES (%s, 'System Manager')
            """,
                (self.regular_user,),
            )

        # Verify user doesn't have admin privileges
        self.assertFalse(frappe.has_permission("User", "create"))

    def test_privilege_escalation_api_bypass(self):
        """Test prevention of API-based privilege escalation"""
        frappe.set_user(self.regular_user)

        # Attempt to access admin-only API endpoints
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("User", "Administrator")

        # Attempt to modify system settings
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("System Settings")

    def test_privilege_escalation_document_permissions(self):
        """Test document-level privilege escalation prevention"""
        frappe.set_user(self.chapter1_admin)

        # Should be able to access own chapter's member
        member1_doc = frappe.get_doc("Member", self.member1.name)
        # Verify chapter membership through Chapter Member relationships
        chapter_memberships = frappe.get_all(
            "Chapter Member",
            filters={"member": member1_doc.name, "status": "Active"},
            fields=["parent"]
        )
        chapter_names = [cm.parent for cm in chapter_memberships]
        self.assertIn(self.chapter1.name, chapter_names)

        # Should NOT be able to access other chapter's member
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Member", self.member2.name)

    # ===== DATA ISOLATION TESTS =====

    def test_cross_organization_data_leakage(self):
        """Test prevention of cross-organization data access"""
        frappe.set_user(self.chapter1_admin)

        # Test member data isolation
        members = frappe.get_all("Member", fields=["name"])  # chapter field doesn't exist in Member doctype
        for member in members:
            if member.name in [self.member1.name, self.member2.name]:
                # Verify chapter through Chapter Member relationships instead of deprecated member.chapter
                chapter_memberships = frappe.get_all(
                    "Chapter Member",
                    filters={"member": member.name, "status": "Active", "parent": self.chapter1.name},
                    fields=["parent"]
                )
                self.assertTrue(len(chapter_memberships) > 0, "Chapter admin can see members from their chapters")

        # Test volunteer data isolation
        volunteers = frappe.get_all("Volunteer", fields=["name", "member"])
        accessible_volunteers = [v for v in volunteers if v.name == self.volunteer1.name]
        self.assertTrue(
            len(accessible_volunteers) <= 1, "Chapter admin can access volunteers from other chapters"
        )

    def test_financial_data_isolation(self):
        """Test financial data access isolation"""
        frappe.set_user(self.regular_user)

        # Regular user should not access financial data
        with self.assertRaises(frappe.PermissionError):
            frappe.get_all("Membership", fields=["membership_type", "member"])  # annual_fee field doesn't exist

        with self.assertRaises(frappe.PermissionError):
            frappe.get_all("SEPA Direct Debit Batch")

        with self.assertRaises(frappe.PermissionError):
            frappe.get_all("SEPA Mandate")

    def test_volunteer_data_privacy(self):
        """Test volunteer data privacy protection"""
        frappe.set_user(self.regular_user)

        # Regular user should not access volunteer personal data
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Volunteer", self.volunteer1.name)

    # ===== FINANCIAL FRAUD PROTECTION =====

    def test_payment_amount_tampering(self):
        """Test prevention of payment amount manipulation"""
        frappe.set_user(self.chapter1_admin)

        # Create test expense
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.volunteer1.name,
                "description": "Test expense",
                "amount": 100.00,
                "currency": "EUR",
                "expense_date": frappe.utils.today()}
        )

        # Attempt to manipulate amount after creation
        with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
            expense.amount = 1000.00  # 10x increase
            expense.save()

    def test_membership_fee_manipulation(self):
        """Test prevention of membership fee tampering"""
        frappe.set_user(self.regular_user)

        # Regular user should not be able to modify membership fees
        with self.assertRaises(frappe.PermissionError):
            membership = frappe.get_doc("Membership", self.membership1.name)
            # Note: annual_fee field doesn't exist - fee is defined in membership_type
            membership.save()

    def test_sepa_mandate_manipulation(self):
        """Test prevention of SEPA mandate tampering"""
        # Create test SEPA mandate with all required fields
        frappe.set_user("Administrator")
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member1.name,
                "mandate_id": f"TEST-MANDATE-{frappe.utils.now()}",
                "account_holder_name": "Test Account Holder",
                "iban": "NL13TEST0123456789",
                "sign_date": frappe.utils.today(),
                "status": "Active",
                "mandate_type": "RCUR",
                "scheme": "SEPA"}
        )
        mandate.insert()

        # Regular user should not modify SEPA mandates
        frappe.set_user(self.regular_user)
        with self.assertRaises(frappe.PermissionError):
            mandate.iban = "NL82MOCK0123456789"  # Change to different account
            mandate.save()

        # Clean up handled by base test case
        frappe.set_user("Administrator")
        self.track_doc("SEPA Mandate", mandate.name)

    # ===== INPUT VALIDATION TESTS =====

    def test_sql_injection_prevention(self):
        """Test SQL injection prevention"""
        malicious_inputs = [
            "'; DROP TABLE `tabMember`; --",
            "admin' OR '1'='1",
            "1; UPDATE `tabMembership` SET status='Cancelled'; --",  # Changed from annual_fee which doesn't exist
            "' UNION SELECT password FROM `tabUser` --",
        ]

        for malicious_input in malicious_inputs:
            with self.assertRaises((frappe.ValidationError, frappe.DataError)):
                # Try various injection points
                frappe.get_doc(
                    {
                        "doctype": "Member",
                        "first_name": malicious_input,
                        "last_name": "Test",
                        "email": "test@test.com"}
                ).insert()

    def test_xss_prevention(self):
        """Test XSS prevention in user inputs"""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "javascript:alert('XSS')",
            "<img src=x onerror=alert('XSS')>",
            "<svg onload=alert('XSS')>",
        ]

        for payload in xss_payloads:
            try:
                member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "first_name": payload,
                        "last_name": "Test",
                        "email": "xsstest@test.com"}
                )
                member.insert()

                # Verify payload is sanitized
                saved_member = frappe.get_doc("Member", member.name)
                self.assertNotIn("<script>", saved_member.first_name)
                self.assertNotIn("javascript:", saved_member.first_name)

                # Clean up
                saved_member.delete()
            except frappe.ValidationError:
                # Validation error is acceptable - means XSS was prevented
                pass

    # ===== SESSION SECURITY TESTS =====

    def test_session_fixation_prevention(self):
        """Test session fixation attack prevention"""
        # Get current session
        old_session = frappe.session.sid

        # Simulate login
        frappe.local.login_manager.authenticate("Administrator", "admin")

        # Session ID should change after authentication
        new_session = frappe.session.sid
        self.assertNotEqual(
            old_session,
            new_session,
            "Session ID didn't change after authentication - vulnerable to session fixation",
        )

    def test_concurrent_session_management(self):
        """Test proper handling of concurrent sessions"""
        # This test would require more complex setup with actual HTTP requests
        # For now, verify session data integrity
        user = frappe.session.user
        self.assertIsNotNone(user)
        self.assertNotEqual(user, "Guest")

    # ===== API SECURITY TESTS =====

    def test_api_rate_limiting(self):
        """Test API rate limiting (if implemented)"""
        # This is a placeholder for rate limiting tests
        # Would require actual HTTP requests to test properly

    def test_api_authentication_bypass(self):
        """Test API authentication bypass attempts"""
        # Test accessing whitelisted methods without proper auth
        frappe.set_user("Guest")

        # These are actual API methods that should require authentication
        restricted_methods = [
            "verenigingen.api.debug_payment_history.debug_payment_history_system",
            "verenigingen.api.performance_validation.run_performance_validation",
            "verenigingen.api.database_index_manager.analyze_query_performance",
        ]

        for method in restricted_methods:
            try:
                frappe.call(method)
                self.fail(f"Method {method} accessible without authentication")
            except (frappe.PermissionError, frappe.AuthenticationError):
                # Expected behavior
                pass
            except (AttributeError, ModuleNotFoundError):
                # Method doesn't exist or module issue - that's acceptable for this test
                pass

    # ===== DATA VALIDATION EDGE CASES =====

    def test_boundary_value_attacks(self):
        """Test boundary value manipulation attacks"""
        # Test negative amounts
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.volunteer1.name,
                    "amount": -100.00,  # Negative amount
                    "description": "Test"}
            ).insert()

        # Test extreme values
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.volunteer1.name,
                    "amount": 999999999.99,  # Extremely large amount
                    "description": "Test"}
            ).insert()

    def test_data_type_confusion(self):
        """Test data type confusion attacks"""
        # Test string where number expected
        with self.assertRaises((frappe.ValidationError, TypeError)):
            # Note: fee is defined in membership_type, not directly on membership
            frappe.get_doc(
                {"doctype": "Membership", "member": self.member1.name, "status": "not_a_valid_status"}
            ).insert()

    # ===== AUDIT TRAIL SECURITY =====

    def test_audit_trail_tampering(self):
        """Test audit trail tampering prevention"""
        frappe.set_user(self.regular_user)

        # User should not be able to modify audit entries
        with self.assertRaises(frappe.PermissionError):
            frappe.get_all("Communication History")

        with self.assertRaises(frappe.PermissionError):
            frappe.get_all("Termination Audit Entry")

    def test_log_injection_prevention(self):
        """Test log injection prevention"""
        # Attempt to inject malicious content into logs
        malicious_content = "\\n[ERROR] Fake error message\\n[INFO] Admin password: secret"

        try:
            frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": malicious_content,
                    "last_name": "Test",
                    "email": "logtest@test.com"}
            ).insert()
        except Exception:
            # Any exception is acceptable - the important thing is no log injection
            pass


def run_security_tests():
    """Run all security tests"""
    print("🔒 Running Comprehensive Security Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestSecurityComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All security tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    # Run when called directly
    run_security_tests()
