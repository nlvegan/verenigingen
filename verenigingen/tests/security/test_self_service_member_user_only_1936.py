"""#1936 (#1853 class): "who is the caller's Member" is decided by Member.user ONLY.

Maintainer rulings #1853 and #1546: no Member.email fallback for caller identity. A logged-in
user whose login email merely equals some Member's email (Member.user unset) must not be admitted
as that Member by the @self_service_api gate, the portal pages, the SEPA Mandate permission hooks,
validate_member_for_user, or the board summary.

Fixture note: the unlinked state is built by clearing Member.user with db_set. That is the state
under test (a legacy record whose email matches a User), not a stand-in for a flow. Callers are
plain "Verenigingen Member" users, not Administrator, except for the admin-only board summary
where the CALLER is Administrator and the looked-up user is the subject.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberUserOnlyIdentity1936(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.linked = self._user_and_member(linked=True)
        self.unlinked = self._user_and_member(linked=False)

    def _user_and_member(self, linked):
        # Trailing digit: the factory rewrites Member.email otherwise (see create_test_board_member).
        email = f"ss1936-{frappe.generate_hash(length=8)}0@example.com"
        member = self.create_test_member(
            first_name="Ss", last_name="Link" if linked else "Email", email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email if linked else None)
        member.reload()
        self.assertEqual(member.email, email, "fixture: Member.email must equal the login email")
        return frappe._dict(member=member, user=email)

    # ---- the gate -----------------------------------------------------------

    def test_gate_refuses_an_email_only_user(self):
        from verenigingen.templates.pages.address_change import get_current_address

        with self.as_user(self.unlinked.user):
            with self.assertRaises(frappe.PermissionError) as ctx:
                get_current_address()
        self.assertIn("No member record found", str(ctx.exception))

    def test_gate_admits_the_linked_user(self):
        from verenigingen.templates.pages.address_change import get_current_address

        with self.as_user(self.linked.user):
            self.assertEqual(get_current_address(), {"address": None})

    def test_controller_get_user_member_is_user_link_only(self):
        from verenigingen.utils.security.self_service_access_controller import SelfServiceAccessController

        controller = SelfServiceAccessController()
        self.assertIsNone(controller.get_user_member(self.unlinked.user))
        self.assertEqual(controller.get_user_member(self.linked.user), self.linked.member.name)

    def test_current_user_member_name_is_user_link_only(self):
        from verenigingen.utils.member_utils import get_current_user_member_name

        with self.as_user(self.unlinked.user):
            self.assertIsNone(get_current_user_member_name())
        with self.as_user(self.linked.user):
            self.assertEqual(get_current_user_member_name(), self.linked.member.name)

    # ---- non-gated readers --------------------------------------------------

    def test_my_addresses_page_does_not_resolve_an_email_only_user(self):
        from verenigingen.templates.pages.my_addresses import get_context

        with self.as_user(self.unlinked.user):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertTrue(ctx.no_member_record)
        self.assertFalse(ctx.get("member"))
        with self.as_user(self.linked.user):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertFalse(ctx.no_member_record)
        self.assertEqual(ctx.member.name, self.linked.member.name)

    def test_address_change_page_does_not_resolve_an_email_only_user(self):
        from verenigingen.templates.pages.address_change import get_context

        with self.as_user(self.unlinked.user):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertTrue(ctx.no_member_record)
        self.assertFalse(ctx.get("address_data"))

    # ---- SEPA Mandate permission hooks -------------------------------------

    def test_sepa_mandate_hooks_do_not_grant_by_email(self):
        from verenigingen.verenigingen_payments.doctype.sepa_mandate.sepa_mandate import (
            get_permission_query_conditions,
            has_permission,
        )

        # Probe shortcut: a bare doc stands in for a stored mandate; has_permission reads only .member.
        for who, expected in ((self.unlinked, False), (self.linked, True)):
            doc = frappe._dict(member=who.member.name)
            self.assertEqual(has_permission(doc, who.user), expected, who.user)
            condition = get_permission_query_conditions(who.user)
            if expected:
                self.assertIn(who.member.name, condition)
            else:
                self.assertEqual(condition, "1=0")

    # ---- board summary (board identity is Member.user only, #1546) -----------

    def test_board_summary_does_not_resolve_an_email_only_user(self):
        from verenigingen.services.chapter.chapter_role_events import get_user_board_summary

        with self.as_user("Administrator"):
            refused = get_user_board_summary(user_email=self.unlinked.user)
            found = get_user_board_summary(user_email=self.linked.user)
        self.assertFalse(refused["success"], refused)
        self.assertTrue(found["success"], found)
        self.assertEqual(found["member_name"], self.linked.member.name)

    # ---- in-body ownership compare (payment plans) ---------------------------

    def test_payment_plan_listing_compares_member_user_not_member_email(self):
        """A linked user whose Member.email differs from the login is the owner (and was refused);
        an email-only user is not (admitted by the old body compare, behind a gate that now refuses)."""
        from verenigingen.api.payment_plan_management import get_member_payment_plans

        other_email = f"ss1936-other-{frappe.generate_hash(length=8)}0@example.com"
        self.linked.member.db_set("email", other_email)  # linked via Member.user, login email differs
        with self.as_user(self.linked.user):
            result = get_member_payment_plans(member=self.linked.member.name)
        self.assertTrue(result["success"], msg=result)
        with self.as_user(self.unlinked.user):
            with self.assertRaises(frappe.PermissionError):
                get_member_payment_plans(member=self.unlinked.member.name)
