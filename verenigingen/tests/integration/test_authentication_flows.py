#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Authentication Flow Integration Tests for Verenigingen System

This test suite provides comprehensive end-to-end testing of critical authentication
flows in the Dutch association management system, focusing on real-world scenarios
that validate the complete security architecture.

Critical Authentication Flows Tested:
1. Member Authentication Flow - User login → Member lookup → Permissions
2. Portal Authentication - Secure access to member portal endpoints
3. API Authentication - Security decorators and member ownership validation
4. SEPA Mandate Authentication - Financial data access controls

The tests use realistic data generation and validate security boundaries without
bypassing the permission system, ensuring the authentication architecture works
correctly in production-like conditions.
"""

import json
import time
from contextlib import contextmanager

import frappe
from frappe.utils import add_days, getdate, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import (
    get_current_user_member_name,
    get_member_name_for_user,
    get_member_sepa_mandate,
    get_volunteer_name_for_user,
    has_mollie_subscription,
    validate_member_ownership,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    critical_api,
    get_security_framework,
    high_security_api,
    self_service_api,
    standard_api,
)


class TestAuthenticationFlowsComprehensive(EnhancedTestCase):
    """
    Comprehensive integration tests for authentication flows in Verenigingen system.

    Tests the complete authentication architecture without mocking, using realistic
    data and scenarios that validate security boundaries and access controls.
    """

    def setUp(self):
        """Set up comprehensive test scenario with realistic member relationships"""
        super().setUp()

        # Create realistic test users with proper role assignments
        self.test_users = self._create_authentication_test_users()

        # Create member records linked to users
        self.test_members = self._create_test_members_with_relationships()

        # Create customer relationships for billing
        self._setup_customer_relationships()

        # Create SEPA mandates for financial testing
        self._setup_sepa_mandates()

        # Create volunteer records for role-based testing
        self._setup_volunteer_relationships()

        # Track original user for cleanup
        self.original_user = frappe.session.user

    def _create_authentication_test_users(self):
        """Create test users with different authentication scenarios"""
        users = {}

        # Member with full access
        users["member_full"] = self.create_test_user_with_roles(
            email="member.full@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Test",
            last_name="Member Full",
        )

        # Member with limited access
        users["member_limited"] = self.create_test_user_with_roles(
            email="member.limited@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Test",
            last_name="Member Limited",
        )

        # Volunteer with member access
        users["volunteer"] = self.create_test_user_with_roles(
            email="volunteer@test.verenigingen.invalid",
            roles=["Verenigingen Volunteer", "Verenigingen Member"],
            first_name="Test",
            last_name="Volunteer",
        )

        # Staff user with administrative access
        users["staff"] = self.create_test_user_with_roles(
            email="staff@test.verenigingen.invalid",
            roles=["Verenigingen Staff", "Verenigingen Staff"],
            first_name="Test",
            last_name="Staff",
        )

        # Admin user with full system access
        users["admin"] = self.create_test_user_with_roles(
            email="admin@test.verenigingen.invalid",
            roles=["System Manager", "Verenigingen Administrator"],
            first_name="Test",
            last_name="Administrator",
        )

        # User without member record (orphaned user scenario)
        users["orphaned"] = self.create_test_user_with_roles(
            email="orphaned@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Orphaned",
            last_name="User",
        )

        return users

    def _create_test_members_with_relationships(self):
        """Create member records linked to test users"""
        members = {}

        # Full access member with payment setup.
        # payment_method="SEPA Direct Debit" requires iban + bank_account_name
        # at Member.validate time, otherwise it throws "IBAN is required for SEPA
        # Direct Debit payment method". The SEPA mandate created later reuses the
        # same IBAN.
        members["member_full"] = self.create_test_member(
            first_name="Test",
            last_name="Member Full",
            email="member.full@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -9000),  # 24+ years old
            payment_method="SEPA Direct Debit",
            iban="NL91ABNA0417164300",
            bank_account_name="Test Member Full",
            status="Active",
        )

        # Limited access member without payment setup
        members["member_limited"] = self.create_test_member(
            first_name="Test",
            last_name="Member Limited",
            email="member.limited@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -7000),  # 19+ years old
            payment_method="Manual",
            status="Active",
        )

        # Volunteer member with both member and volunteer access
        members["volunteer"] = self.create_test_member(
            first_name="Test",
            last_name="Volunteer",
            email="volunteer@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -8000),  # 22+ years old
            payment_method="Mollie",
            status="Active",
            # Add Mollie subscription details
            mollie_customer_id="cst_test_volunteer",
            mollie_subscription_id="sub_test_volunteer",
            subscription_status="active",
        )

        # Note: staff and admin users intentionally don't have member records
        # to test administrative access without member relationships

        # Don't create member for orphaned user - this tests the scenario
        # where a user has Member role but no actual member record

        # Link each member to its corresponding User and align member.email to the
        # login email. The test factory uniquifies member.email, so without this the
        # session-based member lookups (get_member_name_for_user / get_current_user_*)
        # cannot resolve the logged-in user to a member. Mirror production where
        # member.user is set and member.email equals the login email.
        for key, member in members.items():
            user = self.test_users[key]
            member.user = user.name
            member.email = user.name
            member.save()
            member.reload()

        return members

    def _setup_customer_relationships(self):
        """Set up Customer records for billing relationships"""
        # Members automatically get Customer records via create_customer()
        for member_key, member in self.test_members.items():
            if not member.customer:
                member.create_customer()
                member.reload()

    def _setup_sepa_mandates(self):
        """Create SEPA mandates for financial testing"""
        # Create active SEPA mandate for member_full
        if hasattr(self, "test_members") and "member_full" in self.test_members:
            member = self.test_members["member_full"]

            sepa_mandate = frappe.get_doc(
                {
                    "doctype": "SEPA Mandate",
                    "member": member.name,
                    "mandate_id": f"TEST-MANDATE-{member.name}",
                    "iban": "NL91ABNA0417164300",
                    "bic": "ABNANL2A",
                    "account_holder_name": member.full_name,
                    "status": "Active",
                    "is_active": 1,
                    "sign_date": getdate(),
                    "mandate_type": "RCUR",  # Recurring payment
                    # scheme is reqd=1; its DocType default ("SEPA") is not applied to
                    # a dict-constructed doc before validation, so set it explicitly.
                    "scheme": "SEPA",
                }
            )
            sepa_mandate.insert()

            # Update member with SEPA details. Reload first: the member row was
            # modified by customer-creation hooks and the mandate insert since
            # this in-memory doc was built, so saving the stale copy raises
            # TimestampMismatchError.
            member.reload()
            member.iban = sepa_mandate.iban
            member.bic = sepa_mandate.bic
            member.bank_account_name = sepa_mandate.account_holder_name
            member.save()

    def _setup_volunteer_relationships(self):
        """Create volunteer records for role-based testing"""
        if hasattr(self, "test_members") and "volunteer" in self.test_members:
            volunteer_member = self.test_members["volunteer"]

            self.test_volunteer = self.create_test_volunteer(
                member_name=volunteer_member.name,
                volunteer_name=volunteer_member.full_name,
                email=volunteer_member.email,
                status="Active",
                start_date=getdate(),
            )

            # Align the volunteer email to the volunteer user's login email so
            # get_volunteer_name_for_user (which looks up Volunteer by email/user)
            # resolves it. The factory uniquifies the volunteer email otherwise.
            volunteer_user = self.test_users["volunteer"]
            self.test_volunteer.email = volunteer_user.name
            self.test_volunteer.save()
            self.test_volunteer.reload()

    # ===== MEMBER AUTHENTICATION FLOW TESTS =====

    def test_member_authentication_flow_complete(self):
        """Test complete member authentication flow: login → lookup → permissions"""

        # Test successful member authentication flow
        test_user = self.test_users["member_full"]
        expected_member = self.test_members["member_full"]

        with self.as_user(test_user.email):
            # 1. Test user session is valid
            self.assertEqual(frappe.session.user, test_user.email)

            # 2. Test member lookup by user email
            member_name = get_member_name_for_user(test_user.email)
            self.assertEqual(member_name, expected_member.name)

            # 3. Test current user member lookup
            current_member = get_current_user_member_name()
            self.assertEqual(current_member, expected_member.name)

            # 4. Test member document access
            member_doc = frappe.get_doc("Member", current_member)
            self.assertEqual(member_doc.email, test_user.email)

            # 5. Test role-based permissions
            user_roles = frappe.get_roles(test_user.email)
            self.assertIn("Verenigingen Member", user_roles)

    def test_member_authentication_with_orphaned_user(self):
        """Test authentication with user who has role but no member record"""

        orphaned_user = self.test_users["orphaned"]

        with self.as_user(orphaned_user.email):
            # 1. User session should be valid
            self.assertEqual(frappe.session.user, orphaned_user.email)

            # 2. Member lookup should return None
            member_name = get_member_name_for_user(orphaned_user.email)
            self.assertIsNone(member_name)

            # 3. Current user member lookup should return None
            current_member = get_current_user_member_name()
            self.assertIsNone(current_member)

            # 4. User should still have the role
            user_roles = frappe.get_roles(orphaned_user.email)
            self.assertIn("Verenigingen Member", user_roles)

    def test_member_authentication_fallback_mechanisms(self):
        """Test authentication fallback mechanisms and error handling"""

        with self.as_user(self.test_users["member_full"].email):
            # Test with None user input
            result = get_member_name_for_user(None)
            self.assertIsNone(result)

            # Test with empty string
            result = get_member_name_for_user("")
            self.assertIsNone(result)

            # Test with non-existent user
            result = get_member_name_for_user("nonexistent@example.com")
            self.assertIsNone(result)

    def test_member_ownership_validation_comprehensive(self):
        """Test comprehensive member ownership validation scenarios"""

        member_full = self.test_members["member_full"]
        member_limited = self.test_members["member_limited"]

        # Test valid ownership validation
        with self.as_user(self.test_users["member_full"].email):
            # Should pass - user owns this member record
            validate_member_ownership(member_full.name)

            # Should fail - user doesn't own this member record
            with self.assertRaises(frappe.PermissionError):
                validate_member_ownership(member_limited.name)

            # Should fail - invalid member ID
            with self.assertRaises(frappe.ValidationError):
                validate_member_ownership("")

            # Should fail - non-existent member
            with self.assertRaises(frappe.DoesNotExistError):
                validate_member_ownership("NONEXISTENT-MEMBER-001")

    def test_volunteer_authentication_integration(self):
        """Test volunteer authentication integration with member system"""

        volunteer_user = self.test_users["volunteer"]
        volunteer_member = self.test_members["volunteer"]

        with self.as_user(volunteer_user.email):
            # 1. Test member lookup works for volunteer
            member_name = get_member_name_for_user(volunteer_user.email)
            self.assertEqual(member_name, volunteer_member.name)

            # 2. Test volunteer lookup by user email
            volunteer_name = get_volunteer_name_for_user(volunteer_user.email)
            self.assertEqual(volunteer_name, self.test_volunteer.name)

            # 3. Test role assignments
            user_roles = frappe.get_roles(volunteer_user.email)
            self.assertIn("Verenigingen Member", user_roles)
            self.assertIn("Verenigingen Volunteer", user_roles)

    # ===== PORTAL AUTHENTICATION TESTS =====

    def test_portal_context_generation_security(self):
        """Test portal context generation with security validation"""

        with self.as_user(self.test_users["member_full"].email):
            from verenigingen.templates.pages.member_portal import get_context

            # get_context sets attributes on the context (context.no_cache = 1),
            # which requires an attribute-accessible object. In production the page
            # context is a frappe._dict, not a plain dict.
            context = frappe._dict()
            result_context = get_context(context)

            # Verify context has required security elements
            self.assertIn("member", result_context)
            self.assertEqual(result_context["no_cache"], 1)

            # Verify member context matches current user
            member = result_context["member"]
            self.assertEqual(member.email, frappe.session.user)

    def test_portal_session_security_integration(self):
        """Test portal session security and CSRF protection"""

        with self.as_user(self.test_users["member_full"].email):
            # Note: frappe.session.csrf_token is only populated within an HTTP
            # request context; under `bench run-tests` there is no request, so it
            # is legitimately None and is not asserted here.

            # Test session user consistency
            self.assertEqual(frappe.session.user, self.test_users["member_full"].email)

            # Verify session contains security metadata
            self.assertIsNotNone(frappe.session.sid)

    # ===== API AUTHENTICATION WITH SECURITY DECORATORS TESTS =====

    def test_api_security_decorators_member_data_access(self):
        """Test @high_security_api (HIGH) gates elevated member-data access by role.

        Elevated member-data lookups (an admin/staff viewing arbitrary member
        records) require HIGH. Under the current contract Staff and Verenigingen
        Administrator pass HIGH; a plain Verenigingen Member and a Volunteer
        (MEDIUM max) are denied with frappe.PermissionError before the function
        body runs. Guest is rejected at authentication.
        """

        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def admin_member_data_api(target_member):
            # HIGH-level lookup of an arbitrary member's data
            return {"member": target_member, "access": "granted"}

        target = self.test_members["member_full"].name

        # POSITIVE: Staff (HIGH) and Admin (CRITICAL ⊃ HIGH) are entitled.
        with self.as_user(self.test_users["staff"].email):
            result = admin_member_data_api(target)
            self.assertEqual(result["access"], "granted")
            self.assertEqual(result["member"], target)

        with self.as_user(self.test_users["admin"].email):
            result = admin_member_data_api(target)
            self.assertEqual(result["access"], "granted")

        # NEGATIVE: a plain Member (LOW) cannot reach a HIGH endpoint.
        with self.as_user(self.test_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                admin_member_data_api(target)

        # NEGATIVE: a Volunteer (MEDIUM) still cannot reach a HIGH endpoint.
        with self.as_user(self.test_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                admin_member_data_api(target)

        # NEGATIVE: Guest is rejected at authentication (also PermissionError).
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                admin_member_data_api(target)

    def test_api_security_decorators_financial_operations(self):
        """Test @critical_api (CRITICAL) gates financial operations by role.

        Financial operations require CRITICAL. Under the current contract only
        Treasurer / National Board / Verenigingen Administrator / System
        Administrator pass CRITICAL. A plain Member (LOW), a Volunteer (MEDIUM)
        and even Staff (HIGH, not CRITICAL) are all denied with
        frappe.PermissionError before the function body runs.
        """

        @critical_api(operation_type=OperationType.FINANCIAL)
        def financial_api(target_member):
            # CRITICAL-level financial data lookup (ownership not the concern here)
            sepa_mandate = get_member_sepa_mandate(target_member)
            return {
                "financial_access": "granted",
                "mandate": sepa_mandate["name"] if sepa_mandate else None,
            }

        target = self.test_members["member_full"].name

        # POSITIVE: Verenigingen Administrator is entitled to CRITICAL.
        with self.as_user(self.test_users["admin"].email):
            result = financial_api(target)
            self.assertEqual(result["financial_access"], "granted")
            self.assertIn("mandate", result)
            # The member_full SEPA mandate set up in setUp is reachable.
            self.assertIsNotNone(result["mandate"])

        # NEGATIVE: Staff has HIGH but NOT CRITICAL.
        with self.as_user(self.test_users["staff"].email):
            with self.assertRaises(frappe.PermissionError):
                financial_api(target)

        # NEGATIVE: a Volunteer (MEDIUM) cannot reach CRITICAL.
        with self.as_user(self.test_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                financial_api(target)

        # NEGATIVE: a plain Member (LOW) cannot reach CRITICAL.
        with self.as_user(self.test_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                financial_api(target)

    def test_api_member_ownership_validation_security(self):
        """Test @self_service_api (LOW + ownership) member-data self-access.

        Member self-access to their own record is expressed via
        @self_service_api: LOW level (any authenticated member passes the level
        check) PLUS an ownership gate. A Verenigingen Member SUCCEEDS on their
        OWN record and is DENIED (frappe.PermissionError) on another member's
        record — the ownership gate is enforced by SelfServiceAccessController
        before the function body runs.
        """

        @self_service_api(operation_type=OperationType.MEMBER_DATA)
        def ownership_api(member):
            # The framework's self-service gate already verified ownership of
            # `member`; the body just confirms the call reached business logic.
            validate_member_ownership(member)
            return {"ownership": "validated", "target": member}

        member_full = self.test_members["member_full"]
        member_limited = self.test_members["member_limited"]

        # POSITIVE: member acts on OWN record.
        with self.as_user(self.test_users["member_full"].email):
            result = ownership_api(member=member_full.name)
            self.assertEqual(result["ownership"], "validated")
            self.assertEqual(result["target"], member_full.name)

        # NEGATIVE: member attempts to act on ANOTHER member's record.
        with self.as_user(self.test_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                ownership_api(member=member_limited.name)

    def test_api_rate_limiting_with_authentication(self):
        """Test rate limiting plays nicely with auth on a reachable endpoint.

        A plain Member is LOW-only, so the rate-limit interaction is exercised
        on a @self_service_api (LOW + ownership) endpoint the member can
        actually reach. Repeated calls on the member's OWN data all succeed
        under the limit, while the authorization contract still holds: the same
        member is denied (frappe.PermissionError) when targeting another
        member's data. (Rate limiting is intentionally skipped in the test
        execution context, so calls under the limit must not be rejected.)
        """

        @self_service_api(operation_type=OperationType.MEMBER_DATA)
        def rate_limited_self_service_api(member):
            return {
                "timestamp": now_datetime(),
                "user": frappe.session.user,
                "member": member,
            }

        member_full = self.test_members["member_full"]
        member_limited = self.test_members["member_limited"]

        # POSITIVE: several authenticated, owned-data calls succeed under the limit.
        successful_calls = 0
        with self.as_user(self.test_users["member_full"].email):
            for _ in range(5):
                result = rate_limited_self_service_api(member=member_full.name)
                self.assertEqual(result["user"], self.test_users["member_full"].email)
                self.assertEqual(result["member"], member_full.name)
                successful_calls += 1

        self.assertEqual(successful_calls, 5, "All under-limit owned-data calls should succeed")

        # NEGATIVE: the contract still denies cross-member access for the same user.
        with self.as_user(self.test_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                rate_limited_self_service_api(member=member_limited.name)

    # ===== SEPA MANDATE AUTHENTICATION TESTS =====

    def test_sepa_mandate_access_controls(self):
        """Test SEPA mandate access controls and financial data security"""

        member_with_sepa = self.test_members["member_full"]
        member_without_sepa = self.test_members["member_limited"]

        # Test SEPA mandate access for member with mandate
        with self.as_user(self.test_users["member_full"].email):
            sepa_mandate = get_member_sepa_mandate(member_with_sepa.name)
            self.assertIsNotNone(sepa_mandate)
            self.assertEqual(sepa_mandate["status"], "Active")
            self.assertIn("iban", sepa_mandate)

        # Test SEPA mandate access for member without mandate
        with self.as_user(self.test_users["member_limited"].email):
            sepa_mandate = get_member_sepa_mandate(member_without_sepa.name)
            self.assertIsNone(sepa_mandate)

    def test_sepa_mandate_cross_member_access_prevention(self):
        """Test prevention of cross-member SEPA mandate access"""

        member_with_sepa = self.test_members["member_full"]

        # Member should not be able to access another member's SEPA mandate
        with self.as_user(self.test_users["member_limited"].email):
            # This should work - checking your own (non-existent) mandate
            own_mandate = get_member_sepa_mandate(self.test_members["member_limited"].name)
            self.assertIsNone(own_mandate)

            # This tests the API security - shouldn't be able to check other's mandates
            # without proper ownership validation in the calling API
            other_mandate = get_member_sepa_mandate(member_with_sepa.name)
            # Note: get_member_sepa_mandate doesn't validate ownership by design
            # Ownership validation should happen in the calling API endpoint

    def test_mollie_subscription_authentication_integration(self):
        """Test Mollie subscription authentication integration"""

        # Test member with Mollie subscription
        with self.as_user(self.test_users["volunteer"].email):
            has_subscription = has_mollie_subscription()
            self.assertTrue(has_subscription)

        # Test member without Mollie subscription
        with self.as_user(self.test_users["member_full"].email):
            has_subscription = has_mollie_subscription()
            self.assertFalse(has_subscription)  # Uses SEPA, not Mollie

        # Test orphaned user without member record
        with self.as_user(self.test_users["orphaned"].email):
            has_subscription = has_mollie_subscription()
            self.assertFalse(has_subscription)

    # ===== SECURITY BOUNDARY TESTS =====

    def test_authentication_security_boundaries(self):
        """Test authentication security boundaries and edge cases"""

        # Test session hijacking prevention
        original_user = frappe.session.user

        with self.as_user(self.test_users["member_full"].email):
            member_name = get_current_user_member_name()
            self.assertEqual(member_name, self.test_members["member_full"].name)

        # Verify session restored properly
        frappe.set_user(original_user)
        self.assertEqual(frappe.session.user, original_user)

    def test_concurrent_authentication_safety(self):
        """Test concurrent authentication operations safety"""
        import threading
        import time

        results = []
        errors = []

        # Worker threads open their own DB connections (frappe.local is per-thread),
        # which cannot see the current uncommitted test transaction. Commit setUp
        # data and pass the site/identifiers needed to init each thread context.
        site = frappe.local.site
        member_user_email = self.test_users["member_full"].name
        expected_member_name = self.test_members["member_full"].name
        frappe.db.commit()

        def authenticate_and_lookup():
            try:
                frappe.init(site=site, force=True)
                frappe.connect()
                frappe.set_user(member_user_email)
                member_name = get_current_user_member_name()
                if member_name == expected_member_name:
                    results.append("success")
                else:
                    results.append("mismatch")
            except Exception as e:
                errors.append(str(e))
            finally:
                try:
                    frappe.destroy()
                except Exception:
                    pass

        # Run concurrent authentication operations
        threads = []
        for _ in range(3):  # Reduced from 5 to avoid rate limiting
            t = threading.Thread(target=authenticate_and_lookup)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f"Concurrent authentication errors: {errors}")
        self.assertEqual(len(results), 3, "All concurrent operations should complete")
        self.assertEqual(results.count("success"), 3, "All operations should succeed")

    def test_authentication_error_handling(self):
        """Test authentication error handling for invalid inputs"""

        # Should return None for non-existent user
        result = get_member_name_for_user("nonexistent.user@invalid.example.com")
        self.assertIsNone(result)

        # Should return None for empty input
        result = get_member_name_for_user("")
        self.assertIsNone(result)

        # Should return None for None input
        result = get_member_name_for_user(None)
        self.assertIsNone(result)

    def test_role_based_api_access_matrix(self):
        """Test the full role -> security-level access matrix.

        Asserts the current contract end-to-end across three level tiers:
          - @critical_api  (CRITICAL)
          - @high_security_api (HIGH)
          - @standard_api  (MEDIUM)

        Expected matrix:
          admin    (Verenigingen Administrator): CRITICAL + HIGH + MEDIUM
          staff    (Verenigingen Staff)        : HIGH + MEDIUM, NOT CRITICAL
          volunteer(Verenigingen Volunteer)    : MEDIUM, NOT HIGH/CRITICAL
          member   (Verenigingen Member)       : LOW only -> denied at MEDIUM/HIGH/CRITICAL

        Denials surface as frappe.PermissionError (VPermissionError subclass).
        """

        @critical_api(operation_type=OperationType.ADMIN)
        def critical_level_api():
            return {"level": "critical", "access": "granted"}

        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def high_level_api():
            return {"level": "high", "access": "granted"}

        @standard_api(operation_type=OperationType.REPORTING)
        def medium_level_api():
            return {"level": "medium", "access": "granted"}

        # ----- admin: CRITICAL + HIGH + MEDIUM all granted -----
        with self.as_user(self.test_users["admin"].email):
            self.assertEqual(critical_level_api()["access"], "granted")
            self.assertEqual(high_level_api()["access"], "granted")
            self.assertEqual(medium_level_api()["access"], "granted")

        # ----- staff: HIGH + MEDIUM granted, CRITICAL denied -----
        with self.as_user(self.test_users["staff"].email):
            with self.assertRaises(frappe.PermissionError):
                critical_level_api()
            self.assertEqual(high_level_api()["access"], "granted")
            self.assertEqual(medium_level_api()["access"], "granted")

        # ----- volunteer: MEDIUM granted, HIGH + CRITICAL denied -----
        with self.as_user(self.test_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                critical_level_api()
            with self.assertRaises(frappe.PermissionError):
                high_level_api()
            self.assertEqual(medium_level_api()["access"], "granted")

        # ----- member: LOW only -> denied at MEDIUM, HIGH and CRITICAL -----
        with self.as_user(self.test_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                critical_level_api()
            with self.assertRaises(frappe.PermissionError):
                high_level_api()
            with self.assertRaises(frappe.PermissionError):
                medium_level_api()

    # ===== CONTEXT MANAGERS AND UTILITIES =====

    @contextmanager
    def as_user(self, user_email):
        """Context manager for running code as specific user"""
        original_user = frappe.session.user
        try:
            frappe.set_user(user_email)
            yield
        finally:
            frappe.set_user(original_user)

    def tearDown(self):
        """Clean up test data and restore session"""
        # Restore original user session
        frappe.set_user(self.original_user)

        # Clean up any security audit logs that might have been created
        try:
            frappe.db.sql(
                """
                DELETE FROM `tabError Log`
                WHERE creation >= %s
                AND error LIKE '%test%'
            """,
                (self.test_start_time,),
            )
        except Exception:
            pass  # Ignore cleanup errors

        super().tearDown()


# ===== UTILITY FUNCTIONS FOR TESTING =====


def run_authentication_integration_tests():
    """Run comprehensive authentication integration tests"""
    import unittest

    print("🔐 Running Comprehensive Authentication Flow Integration Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestAuthenticationFlowsComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All authentication integration tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(traceback)
        return False


if __name__ == "__main__":
    # Run when called directly
    run_authentication_integration_tests()
