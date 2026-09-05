"""
Core Security Tests for Donor Permissions System

Focuses on validating the critical security fixes:
1. SQL injection prevention in permission queries
2. Proper access control enforcement
3. Error handling robustness

Uses realistic test data generation without complex mocking frameworks.
"""

import frappe
from frappe.utils import random_string

from verenigingen.permissions import get_donor_permission_query, has_donor_permission
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorSecurityCore(VereningingenTestCase):
    """Core security validation tests for donor permission system"""

    def setUp(self):
        """Set up realistic test data"""
        super().setUp()

        # Start from a known Administrator context. These are access-control tests
        # that switch users in their bodies; if a prior test in the shard leaked a
        # non-Administrator session (intermittent, ordering-dependent), the setup
        # below would run as that user and the assertions would see spurious
        # "Access denied ... roles: Guest". Mirrors TestDonorPermissionsSecurity.setUp.
        frappe.set_user("Administrator")

        # Create test users and members
        self.member_user_email = f"security_member_{random_string(5)}@example.com"

        # Create test member
        self.test_member = self.factory.create_test_member(
            first_name="Security", last_name="Member", email=self.member_user_email, birth_date="1990-01-01"
        )

        # Create donor linked to member
        self.linked_donor = self._create_local_test_donor(
            donor_name="Linked Security Donor",
            donor_type="Individual",
            donor_email="linked_donor@example.com",
            member=self.test_member.name,
        )

        # Create orphaned donor (no member link)
        self.orphaned_donor = self._create_local_test_donor(
            donor_name="Orphaned Security Donor",
            donor_type="Individual",
            donor_email="orphaned@example.com",
            # No member field
        )

    def _create_local_test_donor(self, **kwargs):
        """Create test donor with required fields.

        Renamed from `create_test_donor` (#496): that name shadows
        `VereningingenTestCase.create_test_donor(**kwargs)`, which
        `create_test_donation()`/`create_test_periodic_donation_agreement()`
        call internally for a caller that omits `donor=`. Same arity so no
        crash, but this override skips the harness's `is_anbi_eligible`
        default -- latent because this class never calls those methods
        without an explicit `donor=` today.
        """
        defaults = {
            "donor_name": f"Security Test Donor {random_string(5)}",
            "donor_type": "Individual",
            "donor_email": f"security_donor_{random_string(5)}@example.com",
        }
        defaults.update(kwargs)

        donor = frappe.new_doc("Donor")
        for key, value in defaults.items():
            setattr(donor, key, value)

        donor.save()
        self.track_doc("Donor", donor.name)
        return donor

    def test_sql_injection_prevention_core(self):
        """Test SQL injection prevention in permission query generation"""

        # Test the core SQL injection scenarios
        injection_payloads = ["'; DROP TABLE tabDonor; --", "' OR 1=1 --", "'; DELETE FROM tabMember --"]

        for payload in injection_payloads:
            with self.subTest(payload=payload):
                # get_member_name_for_user() (called from get_donor_permission_query)
                # is only reached for a user holding the Verenigingen Member /
                # Chapter Board Member role - self.member_user_email has no real
                # User account, so without mock_roles the code short-circuits to
                # "1=0" before ever calling frappe.db.get_value("Member", ...) and
                # this patch would never fire. Grant the role so the malicious
                # "member name" actually flows into the generated query.
                original_get_value = frappe.db.get_value
                original_get_roles = frappe.get_roles

                def dangerous_get_value(doctype, filters, fieldname=None):
                    if doctype == "Member" and isinstance(filters, dict) and "user" in filters:
                        return payload  # Simulate a corrupted member docname
                    return original_get_value(doctype, filters, fieldname)

                def member_role_get_roles(user=None, with_standard=True):
                    return ["Verenigingen Member", "All"]

                frappe.db.get_value = dangerous_get_value
                frappe.get_roles = member_role_get_roles

                try:
                    result = get_donor_permission_query(self.member_user_email)

                    # frappe.db.escape() must wrap the malicious payload as a single
                    # quoted string literal (quotes backslash-escaped) - not leave
                    # it interpolated raw, which would let it break out of the
                    # literal and execute as SQL.
                    expected = f"(`tabDonor`.member = {frappe.db.escape(payload)})"
                    self.assertEqual(result, expected)

                    # Executing the generated condition must not raise/execute the
                    # injected statement - it should behave as a literal comparison.
                    count = frappe.db.sql(f"SELECT COUNT(*) FROM `tabDonor` WHERE {result}")[0][0]
                    self.assertEqual(count, 0, "Escaped payload should not match any real donor row")

                finally:
                    frappe.db.get_value = original_get_value
                    frappe.get_roles = original_get_roles

    def test_admin_access_validation(self):
        """Test admin role access validation"""

        # Test with Administrator (system built-in admin).
        # get_donor_permission_query returns "" for admins ("No filter needed");
        # in Frappe an empty-string permission query and None BOTH mean
        # "no restriction / unrestricted", so accept either.
        admin_query = get_donor_permission_query("Administrator")
        self.assertIn(admin_query, (None, ""), "Administrator should get unrestricted access")

        admin_permission = has_donor_permission(self.linked_donor.name, "Administrator")
        self.assertTrue(admin_permission, "Administrator should have donor access")

    def test_unauthorized_user_access_denial(self):
        """Test that unauthorized users are properly denied access"""

        fake_user = f"unauthorized_{random_string(5)}@example.com"

        # User without proper roles should be denied
        query = get_donor_permission_query(fake_user)
        self.assertEqual(query, "1=0", "Unauthorized user should get restrictive query")

        permission = has_donor_permission(self.linked_donor.name, fake_user)
        self.assertFalse(permission, "Unauthorized user should be denied access")

    def test_member_isolation_security(self):
        """Test that members can only access their own linked donors"""

        # Create second member
        other_member = self.factory.create_test_member(
            first_name="Other",
            last_name="Member",
            email=f"other_member_{random_string(5)}@example.com",
            birth_date="1985-01-01",
        )

        other_donor = self._create_local_test_donor(
            donor_name="Other Member Donor",
            donor_type="Individual",
            donor_email="other_donor@example.com",
            member=other_member.name,
        )

        # First member should NOT have access to second member's donor
        cross_access = has_donor_permission(other_donor.name, self.member_user_email)
        self.assertFalse(cross_access, "Member should NOT access other member's donor")

    def test_nonexistent_donor_handling(self):
        """Test handling of requests for non-existent donors"""

        fake_donor_id = f"FAKE-DONOR-{random_string(10)}"

        # Should handle non-existent donor gracefully
        permission = has_donor_permission(fake_donor_id, self.member_user_email)
        self.assertFalse(permission, "Should deny access to non-existent donor")

    def test_orphaned_donor_access_denial(self):
        """Test that orphaned donors (no member link) deny access"""

        # Member should not have access to orphaned donor
        orphan_access = has_donor_permission(self.orphaned_donor.name, self.member_user_email)
        self.assertFalse(orphan_access, "Should deny access to orphaned donor")

    def test_malformed_input_robustness(self):
        """Test system robustness with malformed inputs"""

        malformed_inputs = [
            None,
            "",
            "   ",  # Whitespace
            "' OR 1=1 --",  # SQL injection
            "<script>alert('xss')</script>",  # XSS
            "A" * 500,  # Very long string
        ]

        for malformed_input in malformed_inputs:
            with self.subTest(input=repr(malformed_input)):
                try:
                    result = has_donor_permission(malformed_input, self.member_user_email)
                    # Should always deny access for malformed input
                    self.assertFalse(result, f"Should reject malformed input: {malformed_input}")
                except Exception as e:
                    # If exceptions occur, they should be controlled
                    expected_exceptions = (ValueError, TypeError, frappe.ValidationError, AttributeError)
                    self.assertIsInstance(
                        e, expected_exceptions, f"Unexpected exception for input {malformed_input}: {type(e)}"
                    )

    def test_performance_under_load(self):
        """Test permission system performance under repeated requests"""

        import time

        start_time = time.time()

        # Perform many permission checks
        for i in range(100):
            get_donor_permission_query(self.member_user_email)
            has_donor_permission(self.linked_donor.name, self.member_user_email)

            # Mix in some invalid requests
            if i % 10 == 0:
                has_donor_permission(f"FAKE-{i}", self.member_user_email)

        end_time = time.time()
        execution_time = end_time - start_time

        # Should complete reasonably fast
        self.assertLess(execution_time, 3.0, "Permission checks taking too long")

    def test_error_recovery(self):
        """Test system error recovery capabilities"""

        # Test with problematic member link
        problematic_donor = frappe.new_doc("Donor")
        problematic_donor.donor_name = "Problematic Donor"
        problematic_donor.donor_type = "Individual"
        problematic_donor.donor_email = "problematic@example.com"
        # Don't save - this creates a transient object for testing

        # Should handle problematic document object gracefully
        try:
            result = has_donor_permission(problematic_donor, self.member_user_email)
            self.assertFalse(result, "Should deny access to problematic donor")
        except Exception as e:
            # Should not crash the system
            self.assertIsInstance(e, (frappe.ValidationError, AttributeError, TypeError))

    def test_address_permission_sql_injection(self):
        """Test SQL injection prevention in address permissions"""
        from verenigingen.permissions import get_address_permission_query

        injection_payload = "'; DROP TABLE tabAddress; --"

        # Mock member name with injection payload
        original_get_value = frappe.db.get_value

        def malicious_get_value(doctype, filters, fieldname=None):
            if doctype == "Member":
                return injection_payload
            return original_get_value(doctype, filters, fieldname)

        frappe.db.get_value = malicious_get_value

        try:
            query = get_address_permission_query(self.member_user_email)

            # Should handle malicious input safely
            self.assertIsNotNone(query)

            # If not restrictive "1=0", should be properly escaped.
            # The payload's own text ("DROP TABLE ...") legitimately appears inside
            # an escaped SQL string literal — that is harmless. The security
            # property is that the injection cannot BREAK OUT of that literal, i.e.
            # the payload's leading single quote is escaped (as \' or '') by
            # frappe.db.escape and never appears as a bare, unescaped quote that
            # would terminate the literal early. Assert the escaped form is present.
            if query != "1=0":
                self.assertIn("'", query, "Should contain escaped quotes")
                # The injection payload begins with a single quote intended to
                # terminate the SQL string literal early. frappe.db.escape neutralises
                # it by emitting the payload wrapped in quotes with the internal quote
                # escaped as \' (MariaDB driver) or doubled as ''. Assert that the
                # payload's quote appears only in escaped form — i.e. the escaped
                # token is present in the query.
                self.assertTrue(
                    "\\'; DROP TABLE tabAddress; --" in query or "''; DROP TABLE tabAddress; --" in query,
                    f"Injection payload's quote must be escaped (got {query!r})",
                )

        finally:
            frappe.db.get_value = original_get_value

    def test_document_vs_string_consistency(self):
        """Test consistent behavior between document objects and string IDs"""

        # Get permission with string ID
        string_permission = has_donor_permission(self.linked_donor.name, self.member_user_email)

        # Get permission with document object
        donor_doc = frappe.get_doc("Donor", self.linked_donor.name)
        doc_permission = has_donor_permission(donor_doc, self.member_user_email)

        # Should return consistent results
        self.assertEqual(
            string_permission, doc_permission, "String and document permission checks should be consistent"
        )

    def test_escape_function_validation(self):
        """Test that frappe.db.escape function works correctly"""

        # Test basic escape functionality
        dangerous_input = "'; DROP TABLE tabDonor; --"
        escaped = frappe.db.escape(dangerous_input)

        # Should wrap in quotes and escape dangerous content.
        self.assertTrue(
            escaped.startswith("'") and escaped.endswith("'"), "Should wrap escaped content in quotes"
        )
        # The MariaDB driver used by Frappe v16 escapes an internal single quote
        # with a backslash ("\\'") rather than by doubling it ("''"). Both are
        # injection-safe; assert the internal quote is escaped by either style.
        self.assertTrue(
            "''" in escaped or "\\'" in escaped,
            f"Internal quote should be escaped (got {escaped!r})",
        )

        # Test the escape is actually used in permission query. Without the
        # Verenigingen Member role, get_donor_permission_query never reaches the
        # member lookup (it short-circuits to "1=0" first) - grant the role so
        # the dangerous value returned below actually flows into the query.
        original_get_value = frappe.db.get_value
        original_get_roles = frappe.get_roles

        def return_dangerous(*args, **kwargs):
            return dangerous_input

        def member_role_get_roles(user=None, with_standard=True):
            return ["Verenigingen Member", "All"]

        frappe.db.get_value = return_dangerous
        frappe.get_roles = member_role_get_roles

        try:
            query = get_donor_permission_query(self.member_user_email)
            # The dangerous value must reach the query only via frappe.db.escape()
            # (quoted, internal quote backslash-escaped) - never interpolated raw.
            self.assertEqual(query, f"(`tabDonor`.member = {frappe.db.escape(dangerous_input)})")

        finally:
            frappe.db.get_value = original_get_value
            frappe.get_roles = original_get_roles
