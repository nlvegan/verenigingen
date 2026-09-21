# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Tests for the application status page controller
(``verenigingen/templates/pages/application_status.py``), #1051.

``get_context`` used to load and render a Member (email, application status,
admin review notes) for ANY caller supplying a ``?id=`` query parameter, with
no check that the caller was that member. ``Member.autoname`` is
``format:Assoc-Member-{YYYY}-{MM}-{####}`` -- sequential and enumerable -- so
this disclosed a real applicant's PII to any guest who guessed or walked the
id series.

The fix requires the shared HMAC return token
(``verenigingen.utils.security.guest_return_tokens``) minted for this member
at application-submission time (see
``test_membership_application_api.py::test_submit_application_returns_a_status_token_that_authorizes_the_status_page``
for the mint side). The pre-existing "no id param, but a logged-in session"
fallback (``get_current_user_member_name()``) is untouched by this fix and is
covered here as a regression control.
"""

import frappe

from verenigingen.templates.pages.application_status import (
    APPLICATION_STATUS_TOKEN_PURPOSE,
    get_context,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token


class TestPageApplicationStatus(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        self._original_user = frappe.session.user
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    def _make_applicant_member(self, **kwargs):
        member = self.create_test_member(
            email=kwargs.pop("email", f"appstatus-{frappe.generate_hash(length=8)}@example.com"),
            application_status=kwargs.pop("application_status", "Rejected"),
            review_notes=kwargs.pop(
                "review_notes", "SECRET internal reviewer note: duplicate application"
            ),
            **kwargs,
        )
        self.track_doc("Member", member.name)
        return member

    # ------------------------------------------------------------------
    # The vulnerability: an unauthenticated caller supplying `id` alone.
    # ------------------------------------------------------------------

    def test_guest_with_no_token_cannot_read_another_members_application(self):
        """RED case: a bare `?id=<real member>` with no token must not disclose
        the member's email or review notes to a Guest caller (#1051)."""
        member = self._make_applicant_member()

        # NOTE: frappe.set_user() (which self.as_user() calls on entry) resets
        # frappe.local.form_dict to an empty dict -- so form_dict MUST be set
        # INSIDE the `with` block, after the user switch, or the assertion
        # below passes trivially on an empty form_dict regardless of this
        # page's own logic (i.e. red for the wrong reason).
        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": member.name})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNone(ctx.member)

    def test_guest_with_wrong_token_cannot_read_another_members_application(self):
        """A wrong/forged token is refused exactly like no token at all."""
        member = self._make_applicant_member()

        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": member.name, "token": "0" * 64})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNone(ctx.member)

    def test_guest_with_a_token_minted_for_a_different_member_is_refused(self):
        """A real, validly-signed token for a DIFFERENT member's id must not
        authorize reading this member (cross-identifier replay)."""
        member = self._make_applicant_member()
        other_member = self._make_applicant_member()
        foreign_token = generate_guest_return_token(APPLICATION_STATUS_TOKEN_PURPOSE, other_member.name)

        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": member.name, "token": foreign_token})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNone(ctx.member)

    def test_guest_with_a_non_ascii_token_fails_closed_not_500(self):
        """A malformed, non-ASCII token must be refused, not raise (#1108's
        shape: hmac.compare_digest itself raises TypeError on a non-ASCII
        str, so an uncaught path here would 500 instead of refusing)."""
        member = self._make_applicant_member()

        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": member.name, "token": "héllo"})
            ctx = frappe._dict()
            get_context(ctx)  # must not raise

        self.assertIsNone(ctx.member)

    def test_logged_in_as_a_different_member_cannot_read_via_id_param(self):
        """A logged-in member requesting a DIFFERENT member's id, with no
        token, must be refused -- being authenticated as somebody is not the
        same as being authorised for THIS id. The original vulnerability was
        not Guest-specific: any caller, authenticated or not, could pass
        `?id=<anyone>` and be shown that member's data."""
        target_member = self._make_applicant_member()

        own_email = f"appstatus-attacker-{frappe.generate_hash(length=8)}@example.com"
        own_member = self._make_applicant_member(email=own_email)
        if not frappe.db.exists("User", own_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": own_email,
                    "first_name": "AppStatus",
                    "last_name": "Attacker",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.as_user(own_email):
            frappe.local.form_dict = frappe._dict({"id": target_member.name})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNone(ctx.member)
        # Sanity: own_member is unused beyond proving a distinct, real member
        # exists for the logged-in session (own_member_ok's comparand).
        self.assertNotEqual(own_member.name, target_member.name)

    # ------------------------------------------------------------------
    # Control: a legitimately-authorised caller must still succeed.
    # ------------------------------------------------------------------

    def test_guest_with_the_correct_token_can_read_their_own_application(self):
        """CONTROL: the applicant's own return token (as minted by
        submit_application) authorizes reading their own status."""
        member = self._make_applicant_member()
        token = generate_guest_return_token(APPLICATION_STATUS_TOKEN_PURPOSE, member.name)

        with self.as_user("Guest"):
            frappe.local.form_dict = frappe._dict({"id": member.name, "token": token})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNotNone(ctx.member)
        self.assertEqual(ctx.member.name, member.name)
        self.assertEqual(ctx.member.email, member.email)
        self.assertEqual(ctx.member.review_notes, member.review_notes)

    def test_logged_in_own_member_can_read_via_own_id_param_with_no_token(self):
        """CONTROL: the session-ownership branch (payment_retry.py #1052
        shape) this fix adds alongside the token check. A member logged in
        as themself, requesting THEIR OWN docname via `?id=`, with NO token,
        must still succeed -- e.g. a member who bookmarked their own status
        link. Without this test, disabling `session_proves_ownership` alone
        (leaving only the token check) is invisible to the suite: every
        other test either supplies a token or takes the no-`id` `elif`
        fallback, so that mutation still passes 7/7 (found by review of
        d8c507987)."""
        email = f"appstatus-selfid-{frappe.generate_hash(length=8)}@example.com"
        member = self._make_applicant_member(email=email)

        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "AppStatus",
                    "last_name": "SelfId",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.as_user(email):
            frappe.local.form_dict = frappe._dict({"id": member.name})
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNotNone(ctx.member)
        self.assertEqual(ctx.member.name, member.name)
        self.assertEqual(ctx.member.email, member.email)
        self.assertEqual(ctx.member.review_notes, member.review_notes)

    def test_logged_in_own_session_without_id_param_is_unaffected(self):
        """CONTROL / regression: the pre-existing "no id, but logged in"
        fallback via get_current_user_member_name() must keep working -- it
        is unrelated to the id+token check this fix adds."""
        email = f"appstatus-owner-{frappe.generate_hash(length=8)}@example.com"
        member = self._make_applicant_member(email=email)

        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "AppStatus",
                    "last_name": "Owner",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()

        with self.as_user(email):
            frappe.local.form_dict = frappe._dict()
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIsNotNone(ctx.member)
        self.assertEqual(ctx.member.name, member.name)
