"""
Regression tests for self-service operations.

Two related concerns covered here:

1. Doc-method routing — bug fixed 2026-05-02. high_security_api with
   self_service_only=True was added to Contribution Amendment Request's
   apply_amendment, but the framework's self-service validator only inspected
   request kwargs. Doc-method calls via frappe.handler.run_doc_method pass
   the document as args[0] with empty kwargs, so the validator unconditionally
   rejected every non-Admin caller — including the legitimate owner.

   Fix: surface member/volunteer fields from a Document positional arg into the
   kwargs the validator inspects (see _extract_doc_self_service_kwargs in
   api_security_framework.py).

2. Auth tier for self-service (fixed 2026-05-02): apply_amendment and the portal
   submit endpoints were @high_security_api (HIGH). Verenigingen Member only has
   LOW access, so plain members couldn't even reach the self-service check —
   they hit "Access denied" at the auth layer.

   Fix: a dedicated @self_service_api decorator at LOW + self_service_only=True.
   Auth lets any authenticated user through; ownership is enforced by
   SelfServiceAccessController. The 120 existing @standard_api admin-flavoured
   endpoints stay locked to Volunteer+.

These tests must run as a non-Admin member user — the bugs were invisible under
Administrator (which bypasses self-service) which is why they slipped through.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.api_security_framework import (
    self_service_api,
    standard_api,
)
from verenigingen.utils.security.types import OperationType


def _build_standard_self_service_method():
    """Decorate as @standard_api (MEDIUM) — exercises the doc-method extraction
    fix for Volunteer-tier callers (matches the historic apply_amendment shape)."""

    @standard_api(operation_type=OperationType.MEMBER_DATA, self_service_only=True)
    def fake_doc_method(_doc):
        return "applied"

    return fake_doc_method


def _build_member_tier_self_service_method():
    """Decorate as @self_service_api (LOW) — exercises the new tier reachable
    by plain Verenigingen Member users."""

    @self_service_api(operation_type=OperationType.FINANCIAL)
    def fake_doc_method(_doc):
        return "applied"

    return fake_doc_method


def _build_member_tier_implicit_method():
    """@self_service_api with implicit_allowed=True — for portal endpoints
    that derive the member from the session (no doc/kwargs target)."""

    @self_service_api(operation_type=OperationType.FINANCIAL, implicit_allowed=True)
    def fake_session_method():
        return "applied"

    return fake_session_method


class TestSelfServiceDocMethodRegression(EnhancedTestCase):
    """Verify self_service_only=True works for Document instance methods."""

    def _link_member_to_user(self, member, roles):
        """Create a User with the given roles and link to member.

        Member.email is the lookup field used by SelfServiceAccessController
        (see frappe.db.get_value("Member", {"email": user}, "name")).
        """
        user = self.factory.create_user_with_roles(
            email=f"selfservice-{member.name}-{self.uid}@example.com",
            roles=roles,
        )
        member.email = user.name
        member.save(ignore_permissions=True)
        return user

    # --- @standard_api (MEDIUM) doc-method extraction -----------------------

    def test_owner_can_invoke_self_service_doc_method(self):
        """REGRESSION: a Volunteer-tier member calling a self-service doc method
        on their own document must succeed — previously failed with 'explicit
        member parameter'."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member, roles=["Verenigingen Volunteer"])

        doc = frappe.new_doc("Contribution Amendment Request")
        doc.member = member.name
        method = _build_standard_self_service_method()

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            self.assertEqual(method(doc), "applied")
        finally:
            frappe.set_user(original)

    def test_other_member_blocked_from_self_service_doc_method(self):
        """A Volunteer-tier member calling on someone else's document must be blocked."""
        owner = self.create_test_member(birth_date="1990-01-01")
        intruder = self.create_test_member(birth_date="1991-02-02")
        intruder_user = self._link_member_to_user(intruder, roles=["Verenigingen Volunteer"])

        doc = frappe.new_doc("Contribution Amendment Request")
        doc.member = owner.name
        method = _build_standard_self_service_method()

        original = frappe.session.user
        try:
            frappe.set_user(intruder_user.name)
            with self.assertRaises(VPermissionError) as ctx:
                method(doc)
            self.assertIn("only perform this operation on your own data", str(ctx.exception))
        finally:
            frappe.set_user(original)

    # --- @self_service_api (LOW) — plain Verenigingen Member callers --------

    def test_plain_member_can_invoke_self_service_api_doc_method(self):
        """REGRESSION: a plain `Verenigingen Member` (no other roles) must be
        able to invoke a @self_service_api doc method on their own document.
        Previously failed at validate_authentication (Member only had LOW;
        endpoint required HIGH)."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member, roles=["Verenigingen Member"])

        doc = frappe.new_doc("Contribution Amendment Request")
        doc.member = member.name
        method = _build_member_tier_self_service_method()

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            self.assertEqual(method(doc), "applied")
        finally:
            frappe.set_user(original)

    def test_plain_member_blocked_from_other_member_via_self_service_api(self):
        """A plain Member calling @self_service_api on someone else's document
        must be blocked — proves the LOW tier is gated by ownership, not by role."""
        owner = self.create_test_member(birth_date="1990-01-01")
        intruder = self.create_test_member(birth_date="1991-02-02")
        intruder_user = self._link_member_to_user(intruder, roles=["Verenigingen Member"])

        doc = frappe.new_doc("Contribution Amendment Request")
        doc.member = owner.name
        method = _build_member_tier_self_service_method()

        original = frappe.session.user
        try:
            frappe.set_user(intruder_user.name)
            with self.assertRaises(VPermissionError) as ctx:
                method(doc)
            self.assertIn("only perform this operation on your own data", str(ctx.exception))
        finally:
            frappe.set_user(original)

    def test_plain_member_can_invoke_self_service_api_implicit(self):
        """A plain Member calling a session-derived (implicit_allowed) endpoint
        must succeed — covers the membership_adjustment.py portal pattern."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member, roles=["Verenigingen Member"])
        method = _build_member_tier_implicit_method()

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            self.assertEqual(method(), "applied")
        finally:
            frappe.set_user(original)

    def test_implicit_self_service_blocks_user_with_no_member_link(self):
        """A logged-in user with no linked Member record must be rejected by
        the implicit-self-service path (defence: a Volunteer with no Member
        link should not be able to invoke a member-only endpoint)."""
        # Create a user that is NOT linked to any Member
        user = self.factory.create_user_with_roles(
            email=f"selfservice-orphan-{self.uid}@example.com",
            roles=["Verenigingen Member"],
        )
        method = _build_member_tier_implicit_method()

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            with self.assertRaises(VPermissionError) as ctx:
                method()
            self.assertIn("No member record found", str(ctx.exception))
        finally:
            frappe.set_user(original)
