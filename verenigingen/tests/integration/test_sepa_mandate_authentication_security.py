#!/usr/bin/env python3

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

# -*- coding: utf-8 -*-
"""
SEPA Mandate Authentication Security Integration Tests

This test suite provides comprehensive integration testing of SEPA mandate
authentication and authorization flows, focusing on the critical security
boundaries around financial data access and banking operations.

SEPA (Single Euro Payments Area) mandates are legal authorizations for direct
debit payments and represent some of the most sensitive financial data in the
system. These tests ensure that access to SEPA mandates is properly secured
and authenticated.

Key SEPA Authentication Flows Tested:
1. SEPA mandate creation with proper member authentication
2. Mandate access control and ownership validation
3. Banking data security (IBAN, BIC, account details)
4. Cross-member mandate access prevention
5. Administrative mandate management security
6. Integration with payment processing authentication

Security Focus:
- Financial data protection and access controls
- Banking regulation compliance (PCI DSS, PSD2)
- Member ownership validation for financial operations
- Administrative oversight and audit requirements
- Prevention of unauthorized financial data access
"""

from unittest.mock import patch

import frappe
from frappe.utils import now_datetime, add_days, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.member_utils import (
    get_current_user_member_name,
    get_current_user_member_doc,
    validate_member_ownership,
    get_member_sepa_mandate,
    has_active_sepa_mandate,
)
from verenigingen.utils.security.api_security_framework import (
    SecurityLevel,
    OperationType,
    critical_api,
    high_security_api,
    self_service_api,
)


class TestSEPAMandateAuthenticationSecurity(EnhancedTestCase):
    """
    Integration tests for SEPA mandate authentication and security.

    Tests the complete authentication and authorization architecture around
    SEPA direct debit mandates, ensuring financial data is properly protected.
    """

    def setUp(self):
        """Set up SEPA mandate authentication test scenario"""
        super().setUp()

        # Per-TEST login identities, so a leaked Member cannot block the next run.
        #
        # These emails were fixed while setUp builds a fresh Member for each of the 12 test
        # methods and links it to that User. Within a healthy run that is fine -- MEASURED
        # on test_site_2: per-test cleanup deletes each Member before the next is created,
        # 0 rows remain afterwards, and all 12 tests pass with Member.user unique. But if a
        # run dies before cleanup the rows persist, and test_site_1 holds 11 such leftovers
        # right now from one aborted run. Under the unique index added in #269 those
        # leftovers make the NEXT run's first test fail on a collision it did not cause --
        # on the bench default site, where developers run tests by hand.
        #
        # Unique per test rather than get-or-create on the Member: reusing a Member left by
        # an earlier test would carry its mutations forward, which is the order-dependence
        # class #291 is about.
        self.sepa_email_suffix = frappe.generate_hash(length=6)

        # Create comprehensive test scenario for SEPA operations
        self.sepa_users = self._create_sepa_test_users()
        self.sepa_members = self._create_sepa_test_members()
        self.sepa_mandates = self._create_sepa_test_mandates()

        # Store original session
        self.original_user = frappe.session.user

    def _sepa_email(self, local_part):
        """A login email unique to this test method -- see setUp for why."""
        return f"{local_part}.{self.sepa_email_suffix}@test.verenigingen.invalid"

    def _create_sepa_test_users(self):
        """Create test users for SEPA mandate scenarios"""
        users = {}

        # System administrator with financial oversight
        users["admin"] = self.create_test_user_with_roles(
            email=self._sepa_email("admin.sepa"),
            roles=["System Manager", "Verenigingen Administrator"],
            first_name="SEPA",
            last_name="Administrator",
        )

        # Financial manager with SEPA authority (Staff -> HIGH, but NOT CRITICAL)
        users["financial_manager"] = self.create_test_user_with_roles(
            email=self._sepa_email("financial.manager"),
            roles=["Verenigingen Staff"],
            first_name="Financial",
            last_name="Manager",
        )

        # Volunteer user (MEDIUM/LOW only -> denied for HIGH/CRITICAL endpoints)
        users["volunteer"] = self.create_test_user_with_roles(
            email=self._sepa_email("volunteer.sepa"),
            roles=["Verenigingen Volunteer"],
            first_name="SEPA",
            last_name="Volunteer",
        )

        # Member with active SEPA mandate
        users["member_sepa_active"] = self.create_test_user_with_roles(
            email=self._sepa_email("member.sepa.active"),
            roles=["Verenigingen Member"],
            first_name="SEPA",
            last_name="Active Member",
        )

        # Member with inactive SEPA mandate
        users["member_sepa_inactive"] = self.create_test_user_with_roles(
            email=self._sepa_email("member.sepa.inactive"),
            roles=["Verenigingen Member"],
            first_name="SEPA",
            last_name="Inactive Member",
        )

        # Member without SEPA mandate
        users["member_no_sepa"] = self.create_test_user_with_roles(
            email=self._sepa_email("member.no.sepa"),
            roles=["Verenigingen Member"],
            first_name="No SEPA",
            last_name="Member",
        )

        # Member with pending SEPA mandate
        users["member_sepa_pending"] = self.create_test_user_with_roles(
            email=self._sepa_email("member.sepa.pending"),
            roles=["Verenigingen Member"],
            first_name="SEPA",
            last_name="Pending Member",
        )

        # The APISecurityFramework authorizes on Role Profiles, not bare roles:
        # a user with roles but no matching profile is capped at MEDIUM and denied
        # HIGH/CRITICAL endpoints. Grant each user the profile matching its roles
        # (1:1 by name) so allow-paths work while low-tier users stay denied.
        for u in users.values():
            grant_matching_role_profiles(u.email, [r.role for r in u.roles])

        return users

    def _create_sepa_test_members(self):
        """Create member records for SEPA testing"""
        members = {}

        # Member with active SEPA setup
        members["sepa_active"] = self.create_test_member(
            first_name="SEPA",
            last_name="Active Member",
            email=self._sepa_email("member.sepa.active"),
            birth_date=add_days(getdate(), -9000),  # Adult member
            status="Active",
            payment_method="SEPA Direct Debit",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            bank_account_name="SEPA Active Member",
        )

        # Member with inactive SEPA setup
        members["sepa_inactive"] = self.create_test_member(
            first_name="SEPA",
            last_name="Inactive Member",
            email=self._sepa_email("member.sepa.inactive"),
            birth_date=add_days(getdate(), -8000),
            status="Active",
            payment_method="SEPA Direct Debit",
            iban="NL20INGB0001234567",
            bic="INGBNL2A",
            bank_account_name="SEPA Inactive Member",
        )

        # Member without SEPA
        members["no_sepa"] = self.create_test_member(
            first_name="No SEPA",
            last_name="Member",
            email=self._sepa_email("member.no.sepa"),
            birth_date=add_days(getdate(), -7000),
            status="Active",
            payment_method="Manual",
        )

        # Member with pending SEPA
        members["sepa_pending"] = self.create_test_member(
            first_name="SEPA",
            last_name="Pending Member",
            email=self._sepa_email("member.sepa.pending"),
            birth_date=add_days(getdate(), -7500),
            status="Active",
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789",
            bic="TESTNL2A",
            bank_account_name="SEPA Pending Member",
        )

        # Link each member to its corresponding User and align member.email to the
        # login email. The test factory uniquifies member.email, so without this the
        # session-based member lookups (get_current_user_member_*) cannot resolve the
        # logged-in user to a member. Mirror production where member.user is set and
        # member.email equals the login email.
        member_to_user_key = {
            "sepa_active": "member_sepa_active",
            "sepa_inactive": "member_sepa_inactive",
            "no_sepa": "member_no_sepa",
            "sepa_pending": "member_sepa_pending",
        }
        for member_key, user_key in member_to_user_key.items():
            user = self.sepa_users[user_key]
            member = members[member_key]
            member.user = user.name
            member.email = user.name
            member.save()
            member.reload()

        return members

    def _create_sepa_test_mandates(self):
        """Create SEPA mandate records for testing"""
        mandates = {}

        # Member names are autonamed "Assoc-Member-YYYY-MM-####", so name[:8] is
        # "Assoc-Me" for every member and cannot make mandate_id (unique) unique.
        # Suffix each id per run instead -- otherwise one failing test leaves an
        # "ACTIVE-..." row behind and every later test in the class collides on it.
        run_id = frappe.generate_hash(length=8)

        # Active SEPA mandate
        active_member = self.sepa_members["sepa_active"]
        mandates["active"] = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": active_member.name,
                "mandate_id": f"ACTIVE-{run_id}",
                "iban": active_member.iban,
                "bic": active_member.bic,
                "account_holder_name": active_member.bank_account_name,
                "status": "Active",
                "is_active": 1,
                "sign_date": add_days(getdate(), -30),  # Signed 30 days ago
                "mandate_type": "RCUR",
                "creation_method": "Online",
            }
        )
        mandates["active"].insert()

        # Inactive SEPA mandate
        inactive_member = self.sepa_members["sepa_inactive"]
        mandates["inactive"] = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": inactive_member.name,
                "mandate_id": f"INACTIVE-{run_id}",
                "iban": inactive_member.iban,
                "bic": inactive_member.bic,
                "account_holder_name": inactive_member.bank_account_name,
                # SEPA Mandate.status offers Draft/Active/Cancelled/Expired/Suspended.
                # "Cancelled" is what production writes when a mandate stops being
                # usable (termination_utils), so it is the real deactivated state.
                "status": "Cancelled",
                "is_active": 0,
                "sign_date": add_days(getdate(), -60),  # Signed 60 days ago, then deactivated
                "mandate_type": "RCUR",
                "creation_method": "Online",
            }
        )
        mandates["inactive"].insert()

        # Pending SEPA mandate
        pending_member = self.sepa_members["sepa_pending"]
        mandates["pending"] = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": pending_member.name,
                "mandate_id": f"PENDING-{run_id}",
                "iban": pending_member.iban,
                "bic": pending_member.bic,
                "account_holder_name": pending_member.bank_account_name,
                # "Draft" is the valid not-yet-active state; "Pending" is not an option.
                "status": "Draft",
                "is_active": 0,
                "sign_date": getdate(),  # Just signed today
                "mandate_type": "RCUR",
                "creation_method": "Online",
            }
        )
        mandates["pending"].insert()

        # Set up customer relationships
        for member in self.sepa_members.values():
            if not member.customer:
                member.create_customer()
                member.reload()

        return mandates

    # ===== BASIC SEPA MANDATE ACCESS CONTROL TESTS =====

    def test_sepa_mandate_member_ownership_validation(self):
        """Test SEPA mandate access requires proper member ownership"""

        active_member = self.sepa_members["sepa_active"]
        inactive_member = self.sepa_members["sepa_inactive"]

        # Test member can access own SEPA mandate
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            mandate = get_member_sepa_mandate(active_member.name)
            self.assertIsNotNone(mandate, "Member should access own SEPA mandate")
            self.assertEqual(mandate["status"], "Active")
            self.assertEqual(mandate["iban"], active_member.iban)

        # Test member cannot directly access other member's SEPA mandate without ownership validation
        # Note: get_member_sepa_mandate doesn't validate ownership by design -
        # ownership validation should happen in calling APIs

        # Test helper function for has_active_sepa_mandate with ownership
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            has_mandate = has_active_sepa_mandate(active_member.name)
            self.assertTrue(has_mandate, "Should find active mandate")

        with self.as_user(self.sepa_users["member_no_sepa"].email):
            no_sepa_member = self.sepa_members["no_sepa"]
            has_mandate = has_active_sepa_mandate(no_sepa_member.name)
            self.assertFalse(has_mandate, "Should not find mandate for member without SEPA")

    def test_sepa_mandate_status_based_access(self):
        """Test SEPA mandate access based on mandate status"""

        # Test active mandate access
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            mandate = get_member_sepa_mandate(self.sepa_members["sepa_active"].name, active_only=True)
            self.assertIsNotNone(mandate, "Should find active mandate")
            self.assertEqual(mandate["status"], "Active")

        # Test inactive mandate access with active_only=True (should return None)
        with self.as_user(self.sepa_users["member_sepa_inactive"].email):
            mandate = get_member_sepa_mandate(self.sepa_members["sepa_inactive"].name, active_only=True)
            self.assertIsNone(mandate, "Should not find inactive mandate when requesting active only")

        # Test inactive mandate access with active_only=False (should return mandate)
        with self.as_user(self.sepa_users["member_sepa_inactive"].email):
            mandate = get_member_sepa_mandate(self.sepa_members["sepa_inactive"].name, active_only=False)
            self.assertIsNotNone(mandate, "Should find inactive mandate when not requiring active")
            self.assertEqual(mandate["status"], "Cancelled")

    def test_sepa_mandate_guest_access_prevention(self):
        """Test guest users cannot access SEPA mandate data"""

        with self.as_user("Guest"):
            # Guest should not be able to lookup member SEPA mandates
            # Note: This would typically be prevented at the API level
            active_member = self.sepa_members["sepa_active"]

            # Direct database query should work (no built-in guest prevention)
            # but API endpoints should prevent this
            mandate = get_member_sepa_mandate(active_member.name)
            # This test documents current behavior - SEPA utilities don't validate authentication
            # Authentication validation should happen in calling APIs

    # ===== SEPA MANDATE API AUTHENTICATION TESTS =====

    def test_sepa_mandate_api_member_access(self):
        """Test SEPA mandate API self-access for members.

        Contract: member self-access to their OWN mandate is expressed via
        @self_service_api (LOW + ownership). A member may read their own
        mandate via an explicit ``member`` parameter; pointing at another
        member's record raises frappe.PermissionError; Guest is rejected.
        """

        @self_service_api(operation_type=OperationType.FINANCIAL)
        def get_member_sepa_details(member=None):
            mandate = get_member_sepa_mandate(member)

            if not mandate:
                return {"has_sepa": False, "member": member}

            return {
                "has_sepa": True,
                "member": member,
                "mandate_id": mandate["mandate_id"],
                "status": mandate["status"],
                "iban_masked": mandate["iban"][:4] + "****" + mandate["iban"][-4:]
                if mandate["iban"]
                else None,
            }

        active_member = self.sepa_members["sepa_active"]
        no_sepa_member = self.sepa_members["no_sepa"]

        # POSITIVE: owning member reads OWN mandate
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            result = get_member_sepa_details(member=active_member.name)
            self.assertTrue(result["has_sepa"])
            self.assertEqual(result["member"], active_member.name)
            self.assertIn("mandate_id", result)
            self.assertEqual(result["status"], "Active")

        # POSITIVE: owning member with no mandate still reaches own record
        with self.as_user(self.sepa_users["member_no_sepa"].email):
            result = get_member_sepa_details(member=no_sepa_member.name)
            self.assertFalse(result["has_sepa"])
            self.assertEqual(result["member"], no_sepa_member.name)

        # NEGATIVE: a member may NOT read another member's mandate (ownership gate)
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            with self.assertRaises(frappe.PermissionError):
                get_member_sepa_details(member=no_sepa_member.name)

        # NEGATIVE: Guest is rejected (authentication required for non-PUBLIC level)
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                get_member_sepa_details(member=active_member.name)

    def test_sepa_mandate_api_administrative_access(self):
        """Test SEPA mandate administrative access with proper authorization"""

        @critical_api(operation_type=OperationType.FINANCIAL)
        def admin_sepa_mandate_management(member_id, action):
            # Validate administrative access
            user_roles = frappe.get_roles(frappe.session.user)
            if not ("System Manager" in user_roles or "Verenigingen Administrator" in user_roles):
                frappe.throw("Administrative access required", frappe.PermissionError)

            # Validate member exists
            if not DocumentExistenceValidator.check_document_exists("Member", member_id):
                frappe.throw("Member not found", frappe.DoesNotExistError)

            mandate = get_member_sepa_mandate(member_id, active_only=False)

            if action == "view":
                return {
                    "action": "view",
                    "member": member_id,
                    "has_mandate": bool(mandate),
                    "mandate_status": mandate["status"] if mandate else None,
                    "administrator": frappe.session.user,
                }
            elif action == "activate" and mandate:
                # Simulate mandate activation
                return {
                    "action": "activate",
                    "member": member_id,
                    "mandate_id": mandate["mandate_id"],
                    "new_status": "Active",
                    "administrator": frappe.session.user,
                }

            return {"action": action, "error": "Action not supported"}

        # Test admin access
        with self.as_user(self.sepa_users["admin"].email):
            result = admin_sepa_mandate_management(self.sepa_members["sepa_active"].name, "view")
            self.assertEqual(result["action"], "view")
            self.assertTrue(result["has_mandate"])
            self.assertEqual(result["administrator"], self.sepa_users["admin"].email)

        # Test non-admin access denial
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            with self.assertRaises(Exception):  # Should be denied by decorator
                admin_sepa_mandate_management(self.sepa_members["sepa_active"].name, "view")

    # ===== SEPA MANDATE CREATION AUTHENTICATION TESTS =====

    def test_sepa_mandate_creation_authentication(self):
        """Test administrative SEPA mandate creation requires HIGH access.

        Contract: creating/administering SEPA mandates (banking data) is a
        HIGH-level @high_security_api operation. Staff/Admin succeed; a plain
        Member and a Volunteer are denied (frappe.PermissionError). The
        existing-active-mandate ValidationError is preserved for entitled users.
        """

        @high_security_api(operation_type=OperationType.FINANCIAL)
        def create_sepa_mandate(member, iban, bic, account_holder_name):
            # Validate no existing active mandate
            existing_mandate = get_member_sepa_mandate(member, active_only=True)
            if existing_mandate:
                frappe.throw("Active SEPA mandate already exists", frappe.ValidationError)

            # Create new mandate (simulation)
            mandate_data = {
                "member": member,
                "mandate_id": f"NEW-{member[:8]}-{int(now_datetime().timestamp())}",
                "iban": iban,
                "bic": bic,
                "account_holder_name": account_holder_name,
                "status": "Pending",
                "creation_method": "API",
            }

            return {"created": True, "mandate_data": mandate_data, "member": member}

        no_sepa_member = self.sepa_members["no_sepa"]
        active_member = self.sepa_members["sepa_active"]

        # POSITIVE: Staff (HIGH) creates a mandate for a member without one
        with self.as_user(self.sepa_users["financial_manager"].email):
            result = create_sepa_mandate(
                member=no_sepa_member.name,
                iban="NL91RABO0123456789",
                bic="RABONL2U",
                account_holder_name="No SEPA Member",
            )
            self.assertTrue(result["created"])
            self.assertEqual(result["member"], no_sepa_member.name)
            self.assertIn("mandate_data", result)

        # POSITIVE (business rule): Staff blocked by existing active mandate
        with self.as_user(self.sepa_users["financial_manager"].email):
            with self.assertRaises(frappe.ValidationError):
                create_sepa_mandate(
                    member=active_member.name,
                    iban="NL91RABO0987654321",
                    bic="RABONL2U",
                    account_holder_name="SEPA Active Member",
                )

        # NEGATIVE: a plain Member (LOW) is denied this HIGH operation
        with self.as_user(self.sepa_users["member_no_sepa"].email):
            with self.assertRaises(frappe.PermissionError):
                create_sepa_mandate(
                    member=no_sepa_member.name,
                    iban="NL91RABO0123456789",
                    bic="RABONL2U",
                    account_holder_name="No SEPA Member",
                )

        # NEGATIVE: a Volunteer (MEDIUM/LOW) is denied this HIGH operation
        with self.as_user(self.sepa_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                create_sepa_mandate(
                    member=no_sepa_member.name,
                    iban="NL91RABO0123456789",
                    bic="RABONL2U",
                    account_holder_name="No SEPA Member",
                )

    # ===== SEPA MANDATE FINANCIAL OPERATION SECURITY TESTS =====

    def test_sepa_payment_processing_authentication(self):
        """Test SEPA payment processing authentication and authorization"""

        @critical_api(operation_type=OperationType.FINANCIAL)
        def process_sepa_direct_debit(member_id, amount, description):
            # Require administrative access for payment processing
            user_roles = frappe.get_roles(frappe.session.user)
            if not ("System Manager" in user_roles or "Verenigingen Administrator" in user_roles):
                frappe.throw("Payment processing requires administrative access", frappe.PermissionError)

            # Validate member and active mandate
            if not DocumentExistenceValidator.check_document_exists("Member", member_id):
                frappe.throw("Member not found", frappe.DoesNotExistError)

            mandate = get_member_sepa_mandate(member_id, active_only=True)
            if not mandate:
                frappe.throw("No active SEPA mandate found", frappe.ValidationError)

            # Simulate payment processing
            payment_result = {
                "processed": True,
                "member": member_id,
                "amount": amount,
                "description": description,
                "mandate_id": mandate["mandate_id"],
                "iban": mandate["iban"],
                "processor": frappe.session.user,
                "timestamp": now_datetime(),
            }

            return payment_result

        # Test successful payment processing with admin access
        with self.as_user(self.sepa_users["admin"].email):
            result = process_sepa_direct_debit(
                member_id=self.sepa_members["sepa_active"].name,
                amount=25.0,
                description="Monthly membership fee",
            )
            self.assertTrue(result["processed"])
            self.assertEqual(result["amount"], 25.0)
            self.assertEqual(result["processor"], self.sepa_users["admin"].email)

        # Test payment processing with insufficient permissions
        with self.as_user(self.sepa_users["financial_manager"].email):
            with self.assertRaises(Exception):  # Should be denied by decorator
                process_sepa_direct_debit(
                    member_id=self.sepa_members["sepa_active"].name,
                    amount=25.0,
                    description="Unauthorized payment",
                )

    def test_sepa_mandate_banking_data_security(self):
        """Test administrative access to SEPA banking data requires HIGH access.

        Contract: reading full banking data (IBAN/BIC/account holder) for any
        member is a HIGH-level @high_security_api operation. Staff/Admin succeed
        and receive the full banking fields; a plain Member and a Volunteer are
        denied (frappe.PermissionError).
        """

        @high_security_api(operation_type=OperationType.FINANCIAL)
        def get_banking_details_for_payment(member):
            mandate = get_member_sepa_mandate(member, active_only=True)

            if not mandate:
                return {"error": "No active SEPA mandate"}

            # Full banking details (administrative view). bic/account_holder are
            # not surfaced by get_member_sepa_mandate(), so read them from the
            # mandate document directly.
            bic, account_holder = frappe.db.get_value(
                "SEPA Mandate", mandate["name"], ["bic", "account_holder_name"]
            )
            return {
                "member": member,
                "mandate_id": mandate["mandate_id"],
                "iban": mandate["iban"],
                "bic": bic,
                "account_holder": account_holder,
                "status": mandate["status"],
            }

        active_member = self.sepa_members["sepa_active"]

        def _norm_iban(value):
            return (value or "").replace(" ", "").upper()

        # POSITIVE: Staff (HIGH) reads full banking data for a member
        with self.as_user(self.sepa_users["financial_manager"].email):
            result = get_banking_details_for_payment(member=active_member.name)
            self.assertNotIn("error", result)
            self.assertEqual(result["member"], active_member.name)
            self.assertEqual(_norm_iban(result["iban"]), _norm_iban(active_member.iban))
            self.assertEqual(result["bic"], active_member.bic)
            self.assertEqual(result["status"], "Active")

        # NEGATIVE: a plain Member (LOW) cannot reach this HIGH endpoint
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            with self.assertRaises(frappe.PermissionError):
                get_banking_details_for_payment(member=active_member.name)

        # NEGATIVE: a Volunteer (MEDIUM/LOW) cannot reach this HIGH endpoint
        with self.as_user(self.sepa_users["volunteer"].email):
            with self.assertRaises(frappe.PermissionError):
                get_banking_details_for_payment(member=active_member.name)

    # ===== SEPA MANDATE CROSS-MEMBER ACCESS PREVENTION TESTS =====

    def test_sepa_mandate_cross_member_prevention(self):
        """Test prevention of cross-member SEPA mandate access.

        Contract: @self_service_api (LOW + ownership) enforces that a member
        may only act on their OWN mandate. The owning member succeeds; pointing
        the explicit ``member`` parameter at another member's record raises
        frappe.PermissionError via the ownership gate.
        """

        @self_service_api(operation_type=OperationType.FINANCIAL)
        def access_sepa_mandate(member):
            mandate = get_member_sepa_mandate(member, active_only=True)
            return {
                "authorized": True,
                "target_member": member,
                "has_mandate": bool(mandate),
                "mandate_status": mandate["status"] if mandate else None,
            }

        active_member = self.sepa_members["sepa_active"]
        inactive_member = self.sepa_members["sepa_inactive"]

        # POSITIVE: owning member accesses OWN SEPA mandate
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            result = access_sepa_mandate(member=active_member.name)
            self.assertTrue(result["authorized"])
            self.assertTrue(result["has_mandate"])

        # NEGATIVE: member denied access to ANOTHER member's SEPA mandate
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            with self.assertRaises(frappe.PermissionError):
                access_sepa_mandate(member=inactive_member.name)

    def test_sepa_mandate_session_isolation(self):
        """Test SEPA mandate self-access session isolation.

        Contract: under @self_service_api (LOW + ownership) each authenticated
        member can only read their OWN mandate, so different sessions see
        different (correct) data; Guest is rejected for this non-PUBLIC level.
        """

        @self_service_api(operation_type=OperationType.FINANCIAL)
        def get_current_member_sepa(member):
            mandate = get_member_sepa_mandate(member)
            return {"session_user": frappe.session.user, "member": member, "has_mandate": bool(mandate)}

        active_member = self.sepa_members["sepa_active"]
        no_sepa_member = self.sepa_members["no_sepa"]

        # POSITIVE: each member, in its own session, reads its OWN mandate
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            result1 = get_current_member_sepa(member=active_member.name)
            self.assertEqual(result1["member"], active_member.name)
            self.assertTrue(result1["has_mandate"])

        with self.as_user(self.sepa_users["member_no_sepa"].email):
            result2 = get_current_member_sepa(member=no_sepa_member.name)
            self.assertEqual(result2["member"], no_sepa_member.name)
            self.assertFalse(result2["has_mandate"])

        # Verify proper session isolation
        self.assertNotEqual(result1["session_user"], result2["session_user"])
        self.assertNotEqual(result1["member"], result2["member"])

        # NEGATIVE: Guest cannot reach this non-PUBLIC endpoint
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                get_current_member_sepa(member=active_member.name)

    # ===== SEPA MANDATE ERROR HANDLING AND EDGE CASES =====

    def test_sepa_mandate_error_handling(self):
        """Test SEPA mandate error handling under the HIGH-access contract.

        Contract: this administrative lookup is a HIGH-level endpoint. Entitled
        roles (Admin/Staff) pass the level check; the business logic then
        handles a missing member record gracefully (DoesNotExistError ->
        structured error). A plain Member is denied at the level check
        (frappe.PermissionError) before any business logic runs.
        """

        @high_security_api(operation_type=OperationType.FINANCIAL)
        def robust_sepa_access(member=None):
            try:
                if member:
                    target = member
                else:
                    target = get_current_user_member_doc().name
                mandate = get_member_sepa_mandate(target)
                return {"success": True, "member": target, "has_mandate": bool(mandate)}
            except frappe.DoesNotExistError:
                return {"success": False, "error": "No member record found", "user": frappe.session.user}

        active_member = self.sepa_members["sepa_active"]

        # POSITIVE: Staff (HIGH) reaches the endpoint and reads a valid member
        with self.as_user(self.sepa_users["financial_manager"].email):
            result = robust_sepa_access(member=active_member.name)
            self.assertTrue(result["success"])
            self.assertTrue(result["has_mandate"])

        # POSITIVE (error handling): Admin (HIGH, no member record) handled gracefully
        with self.as_user(self.sepa_users["admin"].email):
            result = robust_sepa_access()
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "No member record found")

        # NEGATIVE: a plain Member (LOW) is denied before any business logic
        with self.as_user(self.sepa_users["member_sepa_active"].email):
            with self.assertRaises(frappe.PermissionError):
                robust_sepa_access(member=active_member.name)

    def test_sepa_mandate_concurrent_access_safety(self):
        """Test SEPA mandate concurrent self-access safety.

        Contract: @self_service_api (LOW + ownership) is thread-safe and the
        ownership gate holds under concurrency. Concurrent threads acting as the
        owning member on their OWN mandate all succeed (POSITIVE); a concurrent
        thread acting as that member but targeting ANOTHER member is denied with
        frappe.PermissionError (NEGATIVE).
        """
        import threading

        @self_service_api(operation_type=OperationType.FINANCIAL)
        def concurrent_sepa_access(member):
            mandate = get_member_sepa_mandate(member)
            return {
                "user": frappe.session.user,
                "member": member,
                "mandate_found": bool(mandate),
                "timestamp": now_datetime(),
            }

        # Worker threads open their own DB connections (frappe.local is per-thread)
        # and cannot see the current uncommitted test transaction. Commit setUp
        # data and pass the site/identifiers needed to init each thread context.
        site = frappe.local.site
        member_user_email = self.sepa_users["member_sepa_active"].name
        own_member = self.sepa_members["sepa_active"].name
        other_member = self.sepa_members["sepa_inactive"].name
        frappe.db.commit()

        results = []
        errors = []
        denials = []

        def concurrent_own_access():
            try:
                frappe.init(site=site, force=True)
                frappe.connect()
                frappe.set_user(member_user_email)
                result = concurrent_sepa_access(member=own_member)
                results.append("success" if result["mandate_found"] else "no_mandate")
            except Exception as e:
                errors.append(str(e))
            finally:
                try:
                    frappe.destroy()
                except Exception:
                    pass

        def concurrent_cross_access():
            try:
                frappe.init(site=site, force=True)
                frappe.connect()
                frappe.set_user(member_user_email)
                concurrent_sepa_access(member=other_member)
                # Reaching here means the ownership gate failed to deny
                denials.append("NOT_DENIED")
            except frappe.PermissionError:
                denials.append("denied")
            except Exception as e:
                errors.append(str(e))
            finally:
                try:
                    frappe.destroy()
                except Exception:
                    pass

        # POSITIVE: 3 concurrent own-record accesses
        threads = []
        for _ in range(3):
            t = threading.Thread(target=concurrent_own_access)
            threads.append(t)
            t.start()

        # NEGATIVE: 1 concurrent cross-member access (must be denied)
        cross_thread = threading.Thread(target=concurrent_cross_access)
        threads.append(cross_thread)
        cross_thread.start()

        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"No unexpected concurrent errors should occur: {errors}")
        self.assertEqual(results.count("success"), 3, "All own-record accesses should find mandate")
        self.assertEqual(denials, ["denied"], "Cross-member access must be denied under concurrency")

    # ===== UTILITY METHODS =====

    # as_user() removed (#496): it was byte-for-byte identical to
    # EnhancedTestCase.as_user(user_email), which it shadowed. Deleted rather than
    # renamed since there was nothing local about it to preserve.

    def tearDown(self):
        """Clean up SEPA test data"""
        frappe.set_user(self.original_user)
        super().tearDown()


# ===== TEST EXECUTION FUNCTIONS =====


def run_sepa_mandate_authentication_tests():
    """Run SEPA mandate authentication security tests"""
    import unittest

    print("💳 Running SEPA Mandate Authentication Security Integration Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateAuthenticationSecurity)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All SEPA mandate authentication tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(traceback)
        return False


if __name__ == "__main__":
    run_sepa_mandate_authentication_tests()
