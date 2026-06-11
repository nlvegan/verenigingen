"""
Member portal — real integration coverage.

Replaces the self-mocked test_portal_functionality_integration.py (deleted in
f47d89ce, which asserted against test-local reimplementations and a removed
schema). These tests exercise the REAL portal page handlers / utilities with a
real logged-in member, and verify the core ownership-isolation property: a
member can read their own data and cannot reach another member's.

Entry points exercised:
- verenigingen/templates/pages/member_portal.py:get_context (landing page)
- verenigingen/utils/member_utils.py:get_current_user_member_name / validate_member_ownership
- verenigingen/templates/pages/address_change.py:get_current_address / update_member_address
"""

import frappe

from verenigingen.templates.pages import member_portal
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.member_utils import get_current_user_member_name, validate_member_ownership


class TestPortalFunctionalityIntegration(PortalSelfServiceTestMixin, EnhancedTestCase):
    """Logged-in member portal access + ownership isolation.

    Uses PortalSelfServiceTestMixin's canonical _link_member_to_user (Member role
    profile + Member.user/email); the portal lookup resolves either field.
    """

    # --- login guard ---------------------------------------------------------

    def test_guest_cannot_access_member_portal(self):
        """The portal landing page requires login (Guest is rejected)."""
        with self._as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                member_portal.get_context(frappe._dict())

    # --- own-data access -----------------------------------------------------

    def test_member_sees_own_record_and_membership_on_portal(self):
        """A logged-in member's portal context is populated with their own data."""
        member = self.create_test_member(birth_date="1990-01-01")
        self.create_test_membership(member_name=member.name)
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            context = member_portal.get_context(frappe._dict())

        self.assertFalse(context.no_member_record)
        self.assertEqual(context.member.name, member.name)
        # payment status is always computed for a real member (not crashed)
        self.assertIsNotNone(context.payment_status)

    def test_portal_is_graceful_for_user_without_member_record(self):
        """A logged-in user with no Member record gets a graceful message, not a crash."""
        orphan = self.factory.create_user_with_roles(
            email=f"portal-orphan-{self.uid}@example.com",
            roles=["Verenigingen Member"],
        )

        with self._as_user(orphan.name):
            context = member_portal.get_context(frappe._dict())

        self.assertTrue(context.no_member_record)
        self.assertTrue(context.error_message)

    def test_session_user_resolves_to_own_member(self):
        """get_current_user_member_name maps the session user to their own member."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            self.assertEqual(get_current_user_member_name(), member.name)

    # --- ownership isolation (the core security property) --------------------

    def test_member_can_access_only_own_record(self):
        """validate_member_ownership permits the owner and rejects access to another member."""
        owner = self.create_test_member(birth_date="1990-01-01")
        intruder = self.create_test_member(birth_date="1991-02-02")
        intruder_user = self._link_member_to_user(intruder)

        with self._as_user(intruder_user.name):
            # own record: allowed (no raise)
            validate_member_ownership(intruder.name)
            # another member's record: rejected
            with self.assertRaises(frappe.PermissionError):
                validate_member_ownership(owner.name)

    # Member-as-self coverage of the address-change endpoints (get_current_address
    # / update_member_address) and the other batch-1 portal self-service endpoints
    # now lives in test_member_portal_self_service.py — the @standard_api (MEDIUM)
    # decorations that previously locked out plain members were swapped to
    # @self_service_api (LOW), so those endpoints are now directly testable.
