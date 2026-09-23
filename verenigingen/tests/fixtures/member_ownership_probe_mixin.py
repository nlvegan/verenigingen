"""Shared test helpers for probing validate_member_ownership() call sites.

Consolidates the attacker/self/staff user setup and the CRITICAL-tier-gate
bypass that #1088/#1093's ownership tests were duplicating across three
files (test_sepa_mandate_manager_api_ownership.py,
test_sepa_mandate_diagnostics_ownership.py,
test_payment_plan_from_application_ownership.py) -- flagged by
scripts/validation/duplicate_helper_validator.py's pre-push clone-family gate.

Also absorbs PR #1322's (#1101) inline `_BoardMemberProbeMixin` from
test_payments_utils_gateways_endpoints_coverage.py, which built the same
"non-admin user cleared for a security tier" shape under a different name
(`_board_member_user`), invisible to the name-based clone gate until both
PRs landed in the same tree. `_board_member_linked_user` here is that
consolidated helper; test_payments_utils_gateways_endpoints_coverage.py now
imports this mixin instead of keeping its own copy.

See verenigingen/tests/services/test_sepa_mandate_manager_api_ownership.py's
module docstring for the full derivation of why the CRITICAL-tier tests need
_bypass_tier_gate(): per the checked-in verenigingen/fixtures/role_profile.json,
every Role Profile that authorization_policy.ROLE_PROFILE_SECURITY_MAPPING maps
to CRITICAL also grants a Roles.ADMIN_ROLES role, so there is no real,
currently-configured non-admin Role Profile that clears CRITICAL -- the bypass
isolates validate_member_ownership()'s own comparison from that separate,
incidental tier gate.

Mix into an EnhancedTestCase subclass:

    class TestX(MemberOwnershipProbeMixin, EnhancedTestCase):
        ...
"""

from contextlib import contextmanager
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.authorization_engine import AuthorizationEngine
from verenigingen.utils.security.types import AuthResult


class MemberOwnershipProbeMixin:
    """Helpers to build attacker/self/staff users for ownership-check tests."""

    def _user_linked_to_own_member(self, first_name, role, role_profile):
        """A new Member plus a User (role/role_profile as given) linked to it."""
        member = self.create_test_member(first_name=first_name)
        user_email = f"{first_name.lower()}.{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": first_name,
                "last_name": "Tier",
                "send_welcome_email": 0,
                "roles": [{"role": role}],
            }
        ).insert()
        if role_profile:
            grant_matching_role_profiles(user_email, role_profile)
        frappe.db.set_value("Member", member.name, "user", user_email)
        return user_email, member

    def _board_member_linked_user(self, first_name):
        """A user cleared for HIGH via the real "Verenigingen Chapter Board
        Member" role profile, holding none of Roles.ADMIN_ROLES (verified
        against the checked-in fixture -- see module docstring)."""
        user_email, member = self._user_linked_to_own_member(
            first_name, "Verenigingen Member", "Verenigingen Chapter Board Member"
        )
        self.assertFalse(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: board-tier user must NOT hold an admin role",
        )
        return user_email, member

    def _plain_member_linked_user(self, first_name):
        """A genuinely LOW-tier "Verenigingen Member" user -- clears none of
        HIGH/CRITICAL on its own; CRITICAL-tier tests pair this with
        _bypass_tier_gate() to isolate the ownership check."""
        user_email, member = self._user_linked_to_own_member(
            first_name, "Verenigingen Member", "Verenigingen Member"
        )
        self.assertFalse(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: plain-member user must NOT hold an admin role",
        )
        return user_email, member

    def _staff_user(self, first_name="StaffProbe", role="Verenigingen Administrator", assert_no_member=False):
        """A user holding Roles.ADMIN_ROLES whose matching Role Profile clears
        CRITICAL for real (the default, "Verenigingen Administrator", clears
        CRITICAL/HIGH/MEDIUM/LOW -- "Verenigingen Staff" alone only clears
        HIGH/MEDIUM/LOW per ROLE_PROFILE_SECURITY_MAPPING, so pass
        role="Verenigingen Staff" only for a HIGH-tier-or-lower endpoint).

        assert_no_member=True additionally asserts the new user has NO Member
        record of their own, matching validate_member_ownership's own
        allow_admin docstring ("even without an owning Member record").
        """
        user_email = f"staff.{first_name.lower()}.{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Staff",
                "last_name": first_name,
                "send_welcome_email": 0,
                "roles": [{"role": role}],
            }
        ).insert()
        grant_matching_role_profiles(user_email, role)
        self.assertTrue(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: staff user must hold a Roles.ADMIN_ROLES role",
        )
        if assert_no_member:
            self.assertIsNone(
                frappe.db.get_value("Member", {"user": user_email}, "name"),
                "test setup: staff user must have no Member record of their own",
            )
        return user_email

    @contextmanager
    def _bypass_tier_gate(self):
        """Force the security-tier gate to grant access, isolating
        validate_member_ownership()'s own comparison from
        authorization_policy's CRITICAL role-profile gate."""
        with patch.object(
            AuthorizationEngine,
            "authorize",
            return_value=AuthResult(
                granted=True,
                rule_matched="test_bypass_tier_gate",
                auth_path="test",
                reason="isolate ownership check from the CRITICAL tier gate",
            ),
        ):
            yield
