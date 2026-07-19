#!/usr/bin/env python3

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

# -*- coding: utf-8 -*-
"""
API Authentication with Security Decorators Integration Tests

This test suite provides comprehensive integration testing of the API security
framework decorators in realistic authentication scenarios. It validates that
the security decorators properly integrate with the member authentication system
and enforce security boundaries correctly.

Key API Authentication Patterns Tested:
1. Security decorator integration with member lookup utilities
2. Role-based access control enforcement through decorators
3. Member ownership validation in decorated API endpoints
4. Financial operation security with SEPA mandate validation
5. Multi-layer security validation (authentication + authorization + ownership)

Security Focus:
- End-to-end API security validation
- Realistic attack scenario prevention
- Performance impact of layered security
- Error handling and audit trail generation
"""

import time
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime, add_days, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.member_utils import (
    get_current_user_member_name,
    get_current_user_member_doc,
    get_member_sepa_mandate,
)
from verenigingen.utils.security.api_security_framework import (
    SecurityLevel,
    OperationType,
    api_security_framework,
    critical_api,
    high_security_api,
    standard_api,
    self_service_api,
    utility_api,
    public_api,
)


class TestAPIAuthenticationDecoratorsIntegration(EnhancedTestCase):
    """
    Integration tests for API security decorators with authentication system.

    Tests the complete integration of security decorators with the member
    authentication system, validating that all security layers work together.
    """

    def setUp(self):
        """Set up API authentication integration test scenario"""
        super().setUp()

        # Create comprehensive user-member relationships for API testing
        self.api_users = self._create_api_test_users()
        self.api_members = self._create_api_test_members()
        self._setup_api_test_data()

        # Store original session
        self.original_user = frappe.session.user

    def _create_api_test_users(self):
        """Create test users for API authentication scenarios.

        Each user is granted the Role Profile(s) matching its roles. The custom
        APISecurityFramework authorizes on Role Profiles, not bare roles, so a
        user with roles but no profile is capped at MEDIUM and denied
        HIGH/CRITICAL endpoints. Matching-name profiles restore the tier the
        role name implies while low-tier roles stay correctly denied, preserving
        both the allow and deny assertions in this suite.
        """
        # (key, email, roles) -- role names map 1:1 to Role Profile names.
        specs = [
            ("admin", "admin.api@test.verenigingen.invalid",
             ["System Manager", "Verenigingen Administrator"], "Administrator"),
            ("manager", "manager.api@test.verenigingen.invalid",
             ["Verenigingen Staff"], "Manager"),
            ("staff", "staff.api@test.verenigingen.invalid",
             ["Verenigingen Staff"], "Staff"),
            ("member_full", "member.full.api@test.verenigingen.invalid",
             ["Verenigingen Member"], "Member Full"),
            ("member_financial", "member.financial.api@test.verenigingen.invalid",
             ["Verenigingen Member"], "Member Financial"),
            ("member_basic", "member.basic.api@test.verenigingen.invalid",
             ["Verenigingen Member"], "Member Basic"),
            ("volunteer", "volunteer.api@test.verenigingen.invalid",
             ["Verenigingen Volunteer", "Verenigingen Member"], "Volunteer"),
        ]

        users = {}
        for key, email, roles, last_name in specs:
            users[key] = self.create_test_user_with_roles(
                email=email, roles=roles, first_name="API", last_name=last_name,
            )
            grant_matching_role_profiles(email, roles)

        return users

    def _create_api_test_members(self):
        """Create member records for API testing"""
        members = {}

        # Full profile member
        members["member_full"] = self.create_test_member(
            first_name="API",
            last_name="Member Full",
            email="member.full.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -9000),  # Adult
            status="Active",
            payment_method="Manual",
        )

        # Financial member with SEPA setup
        members["member_financial"] = self.create_test_member(
            first_name="API",
            last_name="Member Financial",
            email="member.financial.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -8000),
            status="Active",
            payment_method="SEPA Direct Debit",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            bank_account_name="API Financial Test",
        )

        # Basic member
        members["member_basic"] = self.create_test_member(
            first_name="API",
            last_name="Member Basic",
            email="member.basic.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -7000),
            status="Active",
            payment_method="Manual",
        )

        # Volunteer member
        members["volunteer"] = self.create_test_member(
            first_name="API",
            last_name="Volunteer",
            email="volunteer.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -8500),
            status="Active",
            payment_method="Mollie",
            mollie_customer_id="cst_api_volunteer",
            mollie_subscription_id="sub_api_volunteer",
            subscription_status="active",
        )

        # Link each member to its corresponding User and align the member email to
        # the login email. The test factory uniquifies member.email, so without this
        # the session-based member lookups (get_current_user_member_*) cannot resolve
        # the logged-in user to a member. Mirror production where member.user is set
        # and member.email equals the login email.
        for key, member in members.items():
            user = self.api_users[key]
            member.user = user.name
            member.email = user.name
            member.save()
            member.reload()

        return members

    def _setup_api_test_data(self):
        """Set up additional test data for API testing"""
        # Create SEPA mandate for financial member
        financial_member = self.api_members["member_financial"]

        sepa_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": financial_member.name,
                "mandate_id": f"API-TEST-{financial_member.name}",
                "iban": financial_member.iban,
                "bic": financial_member.bic,
                "account_holder_name": financial_member.bank_account_name,
                "status": "Active",
                "is_active": 1,
                "sign_date": getdate(),
                "mandate_type": "RCUR",
            }
        )
        sepa_mandate.insert()

        # Create volunteer record
        volunteer_member = self.api_members["volunteer"]
        self.api_volunteer = self.create_test_volunteer(
            member_name=volunteer_member.name,
            volunteer_name=volunteer_member.full_name,
            email=volunteer_member.email,
            status="Active",
        )

        # Set up customer relationships for billing
        for member in self.api_members.values():
            if not member.customer:
                member.create_customer()
                member.reload()

    # ===== BASIC SECURITY DECORATOR INTEGRATION TESTS =====

    def test_public_api_decorator_integration(self):
        """Test public API decorator integration with authentication system"""

        @public_api(operation_type=OperationType.PUBLIC)
        def test_public_endpoint():
            return {
                "public": "access_granted",
                "user": frappe.session.user,
                "authenticated": frappe.session.user != "Guest",
            }

        # Test guest access (should work)
        with self.as_user("Guest"):
            result = test_public_endpoint()
            self.assertEqual(result["public"], "access_granted")
            self.assertEqual(result["user"], "Guest")
            self.assertFalse(result["authenticated"])

        # Test authenticated user access (should also work)
        with self.as_user(self.api_users["member_full"].email):
            result = test_public_endpoint()
            self.assertEqual(result["public"], "access_granted")
            self.assertEqual(result["user"], self.api_users["member_full"].email)
            self.assertTrue(result["authenticated"])

    def test_utility_api_decorator_integration(self):
        """Test utility API decorator integration"""

        @utility_api(operation_type=OperationType.UTILITY)
        def test_utility_endpoint():
            # Even utility APIs can access authentication context
            current_user = frappe.session.user
            member_name = None

            if current_user != "Guest":
                member_name = get_current_user_member_name()

            return {
                "utility": "access_granted",
                "user": current_user,
                "has_member": bool(member_name),
                "member": member_name,
            }

        # Test with authenticated member
        with self.as_user(self.api_users["member_full"].email):
            result = test_utility_endpoint()
            self.assertEqual(result["utility"], "access_granted")
            self.assertTrue(result["has_member"])
            self.assertEqual(result["member"], self.api_members["member_full"].name)

        # Test with authenticated user without member record
        with self.as_user(self.api_users["admin"].email):
            result = test_utility_endpoint()
            self.assertEqual(result["utility"], "access_granted")
            self.assertFalse(result["has_member"])
            self.assertIsNone(result["member"])

    # ===== MEMBER DATA ACCESS SECURITY TESTS =====

    def test_standard_api_member_data_integration(self):
        """Test standard API decorator (MEDIUM) role enforcement.

        Contract: @standard_api requires MEDIUM. Volunteer/Staff/Admin reach
        MEDIUM and succeed; a plain Verenigingen Member is LOW-only and is denied.
        """

        @standard_api(operation_type=OperationType.REPORTING)
        def medium_level_operation():
            return {"level": "medium", "user": frappe.session.user}

        # POSITIVE: Staff reaches MEDIUM (Staff -> HIGH/MEDIUM/LOW)
        with self.as_user(self.api_users["staff"].email):
            result = medium_level_operation()
            self.assertEqual(result["level"], "medium")
            self.assertEqual(result["user"], self.api_users["staff"].email)

        # POSITIVE: Volunteer reaches MEDIUM (Volunteer -> MEDIUM/LOW)
        with self.as_user(self.api_users["volunteer"].email):
            result = medium_level_operation()
            self.assertEqual(result["level"], "medium")

        # POSITIVE: Admin reaches MEDIUM
        with self.as_user(self.api_users["admin"].email):
            result = medium_level_operation()
            self.assertEqual(result["level"], "medium")

        # NEGATIVE: plain Member is LOW-only -> denied at MEDIUM
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                medium_level_operation()

    def test_self_service_api_member_ownership_validation(self):
        """Test self-service API ownership enforcement for member self-access.

        Intent: a member acting on their OWN record. Under the current contract
        this is expressed with @self_service_api (LOW + ownership), NOT
        @high_security_api. A plain Member passes LOW, then the ownership gate
        allows acting only on their own record and denies another member's record.
        """

        @self_service_api(operation_type=OperationType.MEMBER_DATA)
        def update_member_data(member_id, new_notes):
            member = frappe.get_doc("Member", member_id)
            old_notes = member.notes
            member.notes = new_notes
            member.save()

            return {
                "updated": True,
                "member": member_id,
                "old_notes": old_notes,
                "new_notes": new_notes,
            }

        member_full = self.api_members["member_full"]
        member_basic = self.api_members["member_basic"]

        # POSITIVE: member updates their OWN record (LOW passes, ownership matches)
        with self.as_user(self.api_users["member_full"].email):
            result = update_member_data(member_id=member_full.name, new_notes="Updated by owner 456")
            self.assertTrue(result["updated"])
            self.assertEqual(result["member"], member_full.name)
            self.assertEqual(result["new_notes"], "Updated by owner 456")

        # NEGATIVE: member denied on ANOTHER member's record (ownership gate)
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                update_member_data(member_id=member_basic.name, new_notes="Unauthorized note")

    # ===== FINANCIAL OPERATION SECURITY TESTS =====

    def test_critical_api_financial_operations(self):
        """Test critical API decorator with financial operations"""

        @critical_api(operation_type=OperationType.FINANCIAL)
        def process_sepa_payment(member_id, amount):
            # Validate admin access and member ownership
            current_user = frappe.session.user
            user_roles = frappe.get_roles(current_user)

            if "System Manager" not in user_roles and "Verenigingen Administrator" not in user_roles:
                frappe.throw("Administrative access required", frappe.PermissionError)

            # Validate member exists and has SEPA mandate
            if not DocumentExistenceValidator.check_document_exists("Member", member_id):
                frappe.throw("Member not found", frappe.DoesNotExistError)

            sepa_mandate = get_member_sepa_mandate(member_id)
            if not sepa_mandate:
                frappe.throw("No active SEPA mandate found", frappe.ValidationError)

            return {
                "payment_processed": True,
                "member": member_id,
                "amount": amount,
                "mandate_id": sepa_mandate["mandate_id"],
                "processor": current_user,
            }

        financial_member = self.api_members["member_financial"]

        # Test successful financial operation with admin user
        with self.as_user(self.api_users["admin"].email):
            result = process_sepa_payment(financial_member.name, 50.0)
            self.assertTrue(result["payment_processed"])
            self.assertEqual(result["member"], financial_member.name)
            self.assertEqual(result["amount"], 50.0)
            self.assertEqual(result["processor"], self.api_users["admin"].email)

        # Test access denied for non-admin user
        with self.as_user(self.api_users["staff"].email):
            with self.assertRaises(Exception):  # Should be denied by decorator
                process_sepa_payment(financial_member.name, 50.0)

    def test_financial_api_mollie_integration(self):
        """Test financial API (HIGH) integration with Mollie subscriptions.

        Contract: @high_security_api requires HIGH. Staff/Admin reach HIGH and
        succeed; a plain Member AND a Volunteer (MEDIUM) are denied. Because a
        staff operator (not the subscriber) runs this, the target member is
        passed explicitly. The ValidationError-on-missing-subscription behaviour
        is preserved and asserted on the HIGH-authorized path.
        """

        @high_security_api(operation_type=OperationType.FINANCIAL)
        def manage_mollie_subscription(action, member_id):
            member_doc = frappe.get_doc("Member", member_id)

            if not member_doc.get("mollie_subscription_id"):
                frappe.throw("No active Mollie subscription found", frappe.ValidationError)

            return {
                "action": action,
                "member": member_doc.name,
                "customer_id": member_doc.mollie_customer_id,
                "subscription_id": member_doc.mollie_subscription_id,
                "status": member_doc.subscription_status,
            }

        volunteer_member = self.api_members["volunteer"]
        financial_member = self.api_members["member_financial"]

        # POSITIVE: Staff reaches HIGH and processes the subscriber's record
        with self.as_user(self.api_users["staff"].email):
            result = manage_mollie_subscription("status_check", member_id=volunteer_member.name)
            self.assertEqual(result["action"], "status_check")
            self.assertEqual(result["member"], volunteer_member.name)
            self.assertIsNotNone(result["customer_id"])

        # POSITIVE: Admin reaches HIGH too
        with self.as_user(self.api_users["admin"].email):
            result = manage_mollie_subscription("status_check", member_id=volunteer_member.name)
            self.assertEqual(result["member"], volunteer_member.name)

        # Preserved non-authz behaviour: ValidationError when no subscription,
        # asserted on a HIGH-authorized caller so it is the business rule firing.
        with self.as_user(self.api_users["staff"].email):
            with self.assertRaises(frappe.ValidationError):
                manage_mollie_subscription("status_check", member_id=financial_member.name)

        # NEGATIVE: Volunteer is MEDIUM-only -> denied at HIGH
        with self.as_user(self.api_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                manage_mollie_subscription("status_check", member_id=volunteer_member.name)

        # NEGATIVE: plain Member is LOW-only -> denied at HIGH
        with self.as_user(self.api_users["member_financial"].email):
            with self.assertRaises(frappe.PermissionError):
                manage_mollie_subscription("status_check", member_id=financial_member.name)

    # ===== ROLE-BASED ACCESS CONTROL INTEGRATION TESTS =====

    def test_api_role_matrix_integration(self):
        """Test comprehensive role-based access control matrix.

        Contract boundaries:
          - Admin (Verenigingen Administrator): CRITICAL + HIGH + MEDIUM
          - Staff (Verenigingen Staff): HIGH + MEDIUM, NOT CRITICAL
          - Volunteer (Verenigingen Volunteer): MEDIUM, NOT HIGH/CRITICAL
          - Member (Verenigingen Member): LOW only -> NONE of CRITICAL/HIGH/MEDIUM
        """

        # CRITICAL level API
        @critical_api(operation_type=OperationType.ADMIN)
        def critical_operation():
            return {"level": "critical", "user": frappe.session.user}

        # HIGH level API
        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def high_operation():
            return {"level": "high", "user": frappe.session.user}

        # MEDIUM level API
        @standard_api(operation_type=OperationType.REPORTING)
        def medium_operation():
            return {"level": "medium", "user": frappe.session.user}

        # Admin: reaches CRITICAL + HIGH + MEDIUM
        with self.as_user(self.api_users["admin"].email):
            self.assertEqual(critical_operation()["level"], "critical")
            self.assertEqual(high_operation()["level"], "high")
            self.assertEqual(medium_operation()["level"], "medium")

        # Staff: reaches HIGH + MEDIUM, NOT CRITICAL
        with self.as_user(self.api_users["staff"].email):
            with self.assertRaises(frappe.PermissionError):
                critical_operation()
            self.assertEqual(high_operation()["level"], "high")
            self.assertEqual(medium_operation()["level"], "medium")

        # Volunteer: reaches MEDIUM, NOT HIGH/CRITICAL
        with self.as_user(self.api_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                critical_operation()
            with self.assertRaises(frappe.PermissionError):
                high_operation()
            self.assertEqual(medium_operation()["level"], "medium")

        # Member: LOW only -> denied at MEDIUM/HIGH/CRITICAL
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                critical_operation()
            with self.assertRaises(frappe.PermissionError):
                high_operation()
            with self.assertRaises(frappe.PermissionError):
                medium_operation()

    def test_volunteer_role_integration(self):
        """Test volunteer role integration with API security.

        Intent: a volunteer accessing combined member + volunteer data. The right
        level for that is MEDIUM (@standard_api), which a Volunteer legitimately
        reaches under the current contract. POSITIVE: volunteer succeeds and the
        member/volunteer linkage assertions hold. NEGATIVE: a plain Member is
        LOW-only and is denied at MEDIUM.
        """

        @standard_api(operation_type=OperationType.MEMBER_DATA)
        def volunteer_profile_access():
            member_doc = get_current_user_member_doc()

            # Check if user is also a volunteer
            from verenigingen.utils.member_utils import get_volunteer_for_current_user

            volunteer_name = get_volunteer_for_current_user()

            return {
                "member": member_doc.name,
                "is_volunteer": bool(volunteer_name),
                "volunteer_name": volunteer_name,
                "roles": frappe.get_roles(frappe.session.user),
            }

        # POSITIVE: volunteer reaches MEDIUM; member+volunteer linkage preserved
        with self.as_user(self.api_users["volunteer"].email):
            result = volunteer_profile_access()
            self.assertEqual(result["member"], self.api_members["volunteer"].name)
            self.assertTrue(result["is_volunteer"])
            self.assertEqual(result["volunteer_name"], self.api_volunteer.name)
            self.assertIn("Verenigingen Volunteer", result["roles"])
            self.assertIn("Verenigingen Member", result["roles"])

        # NEGATIVE: plain Member is LOW-only -> denied at MEDIUM
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                volunteer_profile_access()

    # ===== SECURITY BOUNDARY AND ATTACK PREVENTION TESTS =====

    def test_api_session_hijacking_prevention(self):
        """Test API session hijacking prevention via self-service ownership.

        Intent: a session can only resolve/act on its own member. Modelled with
        @self_service_api (LOW + ownership): each member resolves to its OWN
        record (session isolation), and a member supplying ANOTHER member's id is
        denied (the anti-hijacking guarantee) with frappe.PermissionError.
        """

        @self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
        def session_sensitive_operation(member_id=None):
            member_doc = get_current_user_member_doc()
            return {
                "session_user": frappe.session.user,
                "member_name": member_doc.name,
                "member_email": member_doc.email,
            }

        # POSITIVE: session isolation — each user resolves to its own member
        with self.as_user(self.api_users["member_full"].email):
            result1 = session_sensitive_operation()
            self.assertEqual(result1["session_user"], self.api_users["member_full"].email)
            self.assertEqual(result1["member_name"], self.api_members["member_full"].name)

        with self.as_user(self.api_users["member_basic"].email):
            result2 = session_sensitive_operation()
            self.assertEqual(result2["session_user"], self.api_users["member_basic"].email)
            self.assertEqual(result2["member_name"], self.api_members["member_basic"].name)

        # Sessions are properly isolated
        self.assertNotEqual(result1["session_user"], result2["session_user"])
        self.assertNotEqual(result1["member_name"], result2["member_name"])

        # NEGATIVE: a member cannot target another member's record (hijack attempt)
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                session_sensitive_operation(member_id=self.api_members["member_basic"].name)

    def test_api_parameter_injection_prevention(self):
        """Test API parameter injection, validation and ownership.

        Intent: defend against parameter tampering on a member-self endpoint.
        Modelled with @self_service_api (LOW + ownership): a member looks up its
        OWN record successfully; empty/None member ids raise ValidationError
        (input validation preserved); supplying another member's id is denied
        with frappe.PermissionError (injection/ownership defense).
        """

        @self_service_api(operation_type=OperationType.MEMBER_DATA, implicit_allowed=True)
        def secure_member_lookup(member_id):
            # Security: validate member_id format
            if not member_id or not isinstance(member_id, str):
                frappe.throw("Invalid member ID format", frappe.ValidationError)

            member = frappe.get_doc("Member", member_id)
            return {"member": member.name, "validated": True}

        member_full = self.api_members["member_full"]
        member_basic = self.api_members["member_basic"]

        # POSITIVE: valid parameter, own record
        with self.as_user(self.api_users["member_full"].email):
            result = secure_member_lookup(member_id=member_full.name)
            self.assertTrue(result["validated"])
            self.assertEqual(result["member"], member_full.name)

        # NEGATIVE (input validation): empty / None are rejected
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.ValidationError):
                secure_member_lookup(member_id="")  # Empty string

            with self.assertRaises(frappe.ValidationError):
                secure_member_lookup(member_id=None)  # None value

        # NEGATIVE (ownership/injection): another member's id is denied
        with self.as_user(self.api_users["member_full"].email):
            with self.assertRaises(frappe.PermissionError):
                secure_member_lookup(member_id=member_basic.name)

    def test_api_concurrent_access_safety(self):
        """Test API concurrent access safety with decorators.

        Contract: @standard_api requires MEDIUM. POSITIVE: a Volunteer (MEDIUM)
        runs the operation concurrently and every call succeeds with the correct
        session. NEGATIVE: a plain Member (LOW only) is denied at MEDIUM even
        under the same concurrent invocation, proving the level check is enforced
        per-session and is not weakened by concurrency.
        """
        import threading

        # NOTE: the operation intentionally does NOT read the Member record. Each
        # worker thread opens its OWN DB connection (see thread_session) which does
        # not see the test's uncommitted member rows. The authorization decision
        # (MEDIUM level enforced via committed User roles) is what this test asserts
        # under concurrency, so the body only reports the resolved session user.
        @standard_api(operation_type=OperationType.REPORTING)
        def concurrent_safe_operation():
            return {
                "user": frappe.session.user,
                "timestamp": now_datetime(),
            }

        volunteer_email = self.api_users["volunteer"].email
        member_email = self.api_users["member_full"].email
        site = frappe.local.site

        results = []
        errors = []
        denials = []

        @contextmanager
        def thread_session(user_email):
            # Worker threads do not inherit the parent's DB connection ("object is
            # not bound"), so each thread initialises and connects its own Frappe
            # context, then sets the target user for the duration of the call.
            frappe.init(site=site)
            frappe.connect()
            try:
                frappe.set_user(user_email)
                yield
            finally:
                frappe.destroy()

        def authorized_call():
            try:
                with thread_session(volunteer_email):
                    result = concurrent_safe_operation()
                    if result["user"] == volunteer_email:
                        results.append("success")
                    else:
                        results.append("session_mismatch")
            except Exception as e:  # noqa: BLE001 - record unexpected errors
                errors.append(str(e))

        def denied_call():
            try:
                with thread_session(member_email):
                    concurrent_safe_operation()
                    denials.append("unexpected_success")
            except frappe.PermissionError:
                denials.append("denied")
            except Exception as e:  # noqa: BLE001 - record unexpected errors
                errors.append(str(e))

        # Commit so the worker threads' fresh DB connections can see the test
        # users' Has Role rows (authorization resolves roles via frappe.get_roles);
        # without this the role lookup in a new connection may miss the uncommitted
        # rows and spuriously deny the authorized calls. Mirrors the SEPA concurrent test.
        frappe.db.commit()

        # POSITIVE: 3 concurrent authorized (MEDIUM) calls
        threads = [threading.Thread(target=authorized_call) for _ in range(3)]
        # NEGATIVE: 2 concurrent under-privileged (LOW) calls
        threads += [threading.Thread(target=denied_call) for _ in range(2)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"No unexpected errors should occur: {errors}")
        self.assertEqual(results.count("success"), 3, "All authorized concurrent calls should succeed")
        self.assertEqual(denials.count("denied"), 2, "All under-privileged concurrent calls should be denied")

    # ===== PERFORMANCE AND MONITORING TESTS =====

    def test_security_decorator_performance_impact(self):
        """Test performance impact of security decorators"""

        # Baseline function without decorator
        def baseline_function():
            return {"baseline": "response"}

        # Function with security decorator
        @standard_api(operation_type=OperationType.REPORTING)
        def secured_function():
            return {"secured": "response"}

        # Measure performance with authenticated user
        with self.as_user(self.api_users["staff"].email):
            # Warm up
            baseline_function()
            secured_function()

            # Time baseline
            start_time = time.time()
            for _ in range(10):
                baseline_function()
            baseline_time = time.time() - start_time

            # Time secured function
            start_time = time.time()
            for _ in range(10):
                secured_function()
            secured_time = time.time() - start_time

            # Security overhead should be reasonable. A ratio is meaningless here
            # because the baseline (a trivial dict return) is effectively 0s, so a
            # tiny absolute overhead produces a huge ratio. Assert on absolute
            # per-call time instead: each secured call should stay well under 100ms.
            per_call_secured = secured_time / 10
            self.assertLess(per_call_secured, 0.1, "Per-call security overhead should be reasonable (<100ms)")

    # ===== UTILITY METHODS =====

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
        """Clean up API test data"""
        frappe.set_user(self.original_user)
        super().tearDown()


# ===== TEST EXECUTION FUNCTIONS =====


def run_api_authentication_decorator_tests():
    """Run API authentication decorator integration tests"""
    import unittest

    print("🔒 Running API Authentication Decorator Integration Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestAPIAuthenticationDecoratorsIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All API authentication decorator tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(traceback)
        return False


if __name__ == "__main__":
    run_api_authentication_decorator_tests()
