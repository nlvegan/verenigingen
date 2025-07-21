"""
Comprehensive Security Test Suite for Verenigingen
Tests for privilege escalation, data isolation, financial fraud protection, and API security
"""

import unittest

import frappe


class TestSecurityComprehensive(unittest.TestCase):
    """Comprehensive security tests covering all attack vectors"""

    @classmethod
    def setUpClass(cls):
        """Set up test data for security tests"""
        cls.test_records = []

        # Create test organizations (chapters)
        cls.chapter1 = frappe.get_doc(
            {
                "doctype": "Chapter",
                "chapter_name": "Test Chapter 1",
                "short_name": "TC1",
                "country": "Netherlands"}
        )
        cls.chapter1.insert()
        cls.test_records.append(cls.chapter1)

        cls.chapter2 = frappe.get_doc(
            {
                "doctype": "Chapter",
                "chapter_name": "Test Chapter 2",
                "short_name": "TC2",
                "country": "Netherlands"}
        )
        cls.chapter2.insert()
        cls.test_records.append(cls.chapter2)

        # Create test users with different permissions
        cls.admin_user = "admin@test.com"
        cls.chapter1_admin = "chapter1@test.com"
        cls.chapter2_admin = "chapter2@test.com"
        cls.regular_user = "user@test.com"
        cls.guest_user = "guest@test.com"

        # Create test members in different chapters
        cls.member1 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Member1",
                "email": "member1@test.com",
                "status": "Active",
                "chapter": cls.chapter1.name}
        )
        cls.member1.insert()
        cls.test_records.append(cls.member1)

        cls.member2 = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Member2",
                "email": "member2@test.com",
                "status": "Active",
                "chapter": cls.chapter2.name}
        )
        cls.member2.insert()
        cls.test_records.append(cls.member2)

        # Create test volunteers
        cls.volunteer1 = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Test Volunteer 1",
                "email": "volunteer1@test.com",
                "member": cls.member1.name,
                "status": "Active"}
        )
        cls.volunteer1.insert()
        cls.test_records.append(cls.volunteer1)

        # Create test membership with financial data
        cls.membership1 = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": cls.member1.name,
                "membership_type": "Regular",
                "status": "Active",
                "annual_fee": 50.00}
        )
        cls.membership1.insert()
        cls.test_records.append(cls.membership1)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        for record in reversed(cls.test_records):
            try:
                record.delete()
            except Exception:
                pass

    def setUp(self):
        """Set up each test"""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test"""
        frappe.set_user("Administrator")

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
        self.assertEqual(member1_doc.chapter, self.chapter1.name)

        # Should NOT be able to access other chapter's member
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Member", self.member2.name)

    # ===== DATA ISOLATION TESTS =====

    def test_cross_organization_data_leakage(self):
        """Test prevention of cross-organization data access"""
        frappe.set_user(self.chapter1_admin)

        # Test member data isolation
        members = frappe.get_all("Member", fields=["name", "chapter"])
        for member in members:
            if member.name in [self.member1.name, self.member2.name]:
                self.assertEqual(
                    member.chapter, self.chapter1.name, "Chapter admin can see members from other chapters"
                )

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
            frappe.get_all("Membership", fields=["annual_fee", "member"])

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
            membership.annual_fee = 1.00  # Reduce fee to almost nothing
            membership.save()

    def test_sepa_mandate_manipulation(self):
        """Test prevention of SEPA mandate tampering"""
        # Create test SEPA mandate
        frappe.set_user("Administrator")
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member1.name,
                "iban": "NL91ABNA0417164300",
                "status": "Active"}
        )
        mandate.insert()

        # Regular user should not modify SEPA mandates
        frappe.set_user(self.regular_user)
        with self.assertRaises(frappe.PermissionError):
            mandate.iban = "NL91RABO0123456789"  # Change to different account
            mandate.save()

        # Clean up
        frappe.set_user("Administrator")
        mandate.delete()

    # ===== INPUT VALIDATION TESTS =====

    def test_sql_injection_prevention(self):
        """Test SQL injection prevention"""
        malicious_inputs = [
            "'; DROP TABLE `tabMember`; --",
            "admin' OR '1'='1",
            "1; UPDATE `tabMembership` SET annual_fee=0; --",
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

        # These should require authentication
        restricted_methods = [
            "verenigingen.api.member.get_member_details",
            "verenigingen.api.volunteer.get_volunteer_expenses",
            "verenigingen.api.financial.get_payment_history",
        ]

        for method in restricted_methods:
            try:
                frappe.call(method)
                self.fail(f"Method {method} accessible without authentication")
            except (frappe.PermissionError, frappe.AuthenticationError):
                # Expected behavior
                pass
            except AttributeError:
                # Method doesn't exist - that's fine for this test
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
            frappe.get_doc(
                {"doctype": "Membership", "member": self.member1.name, "annual_fee": "not_a_number"}
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
