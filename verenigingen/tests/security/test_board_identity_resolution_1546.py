# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#1546 maintainer ruling: every board-scoped permission check in
``permissions.py`` -- the list-view ``permission_query_conditions`` AND the
doc-level ``has_permission`` alike -- resolves the CALLING board user's own
identity via ``Member.user`` ONLY. ``get_member_name_for_user``'s
``Member.email`` fallback must never be an authorization path for board
access, even though it stays the resolver for a member's OWN-record access
(deliberately unaffected by this fix -- see #1546's follow-up comment for the
list of own-record branches this does NOT touch).

Covered here: Member (list), Membership (list; doc via the
``_make_member_linked_permission`` factory), Donor (list + doc via the
factory; SEPA Mandate shares the identical factory code path and is not
duplicated here), Address (list + doc, the "split shared-variable" fix
shape), Employee (list + doc via ``_employee_board_chapter_condition``),
Membership Termination Request (list + doc; the list query has no
own-record branch at all), Chapter Member (list only -- no
``has_permission`` hook exists for it), and Volunteer (doc-level board
branch only; its list query was ALREADY strict before this fix).
``get_user_accessible_chapters`` (the shared resolver behind Expense
Claim's list+doc pair) is exercised directly rather than via a full Expense
Claim/Expense Approver scenario.

ROUND 2 (independent review): also covers standalone board-decision
functions outside the doctype list/doc pairs -- can_terminate_member /
can_access_termination_functions (via their whitelisted API wrappers,
C1), can_view_financial_info / check_member_payment_access (called
directly; no production caller was found for either, C2),
assign_chapter_board_role / update_all_chapter_board_roles (the role
GRANT/REMOVAL decision itself, S1), and get_user_board_chapters's board
resolution for the chapter dashboard API (S2, tested via a real
whitelisted endpoint).

NOT end-to-end tested: Donation. Empirically confirmed (test_site_2) that
Donation's base DocPerm grants read to System Manager / Verenigingen
Administrator / Verenigingen Webhook User ONLY -- neither "Verenigingen
Chapter Board Member" nor "Verenigingen Member" appears, and Frappe's
has_permission hooks can only DENY, never grant beyond the base role
permission. So has_donation_permission's and
get_donation_permission_query's board/own-record branches cannot actually
grant access through the real permission surface today, regardless of this
fix. See the comment beside the (removed) Donation test below for detail;
this is reported as a separate, out-of-scope discovery, not fixed here.

PROBE SHORTCUT (see CLAUDE.md "Probe shortcuts"): the "user unset" state is
produced by building a REAL board seat with ``create_test_board_member()``
(a real Volunteer row, a real Chapter Board Member row, the real
"Verenigingen Chapter Board Member" role profile) and THEN clearing
``Member.user`` with ``db_set``. This stands in for the real-world path that
produces the same state -- e.g. a Member record whose account link was never
completed, or a legacy/imported record -- rather than replaying that path
step by step. It is a representative state, not a synthetic one: the #1546
issue's veg11 read-only probe found 126 Members already in that database
with ``user`` unset (or mismatched) while ``email`` matches an existing User
account. Every test that relies on this state says so again at its own
docstring.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBoardIdentityResolution1546(EnhancedTestCase):
    """Board access must be refused when the caller's Member.user link is
    unset (even though Member.email matches their login), and must still be
    granted when it is linked -- for every board-scoped check this fix
    touched, list and doc-level alike."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.other_chapter = self.create_test_chapter()
        # Real board seat: Volunteer + Chapter Board Member row + role profile.
        # See module docstring -- Member.user is cleared/restored per-test.
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

        # The record a correctly-linked board member of self.chapter SHOULD be
        # able to see/manage: a plain member of the SAME chapter (not the
        # board member's own record -- own-record access is a different,
        # unaffected code path).
        self.target = self.create_test_member(
            first_name="Target",
            last_name=f"Board1546{self.uid}",
            email=f"target.1546.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(self.target.name, self.chapter.name)

    # ---- probe-state helpers -------------------------------------------------

    def _unlink_board_user(self):
        """Clear the board member's Member.user link. PROBE SHORTCUT -- see
        module docstring. Member.email is left untouched, so
        get_member_name_for_user(self.board.user) would still resolve this
        Member via its fallback; get_member_name_for_board_access must not."""
        frappe.get_doc("Member", self.board.member).db_set("user", "")

    def _relink_board_user(self):
        frappe.get_doc("Member", self.board.member).db_set("user", self.board.user)

    # ---- assertion helpers ----------------------------------------------------

    def _listed(self, doctype, name, filters=None):
        with self.as_user(self.board.user):
            f = {"name": name}
            if filters:
                f.update(filters)
            return name in frappe.get_list(doctype, filters=f, pluck="name")

    def _assert_board_access(self, doctype, name, expected, label, list_filters=None):
        listed = self._listed(doctype, name, list_filters)
        # Inlined rather than a separate `_doc_permission` helper -- the
        # duplicate-helper clone-family gate already tracks an identically-named,
        # identically-shaped helper in test_member_list_permission_matches_doc_permission.py;
        # this is a one-line call used from exactly one place, so it does not
        # earn a name of its own.
        doc_ok = bool(frappe.has_permission(doctype, ptype="read", doc=name, user=self.board.user))
        self.assertEqual(
            doc_ok, expected, f"{label}: has_permission({doctype}, {name}) expected {expected}, got {doc_ok}"
        )
        self.assertEqual(
            listed, expected, f"{label}: list-view({doctype}, {name}) expected {expected}, got {listed}"
        )

    # ---- Member (the #1546 headline fix) --------------------------------------

    def test_member_board_access_refused_when_user_unset(self):
        """Core #1546 regression: an unlinked board user must be refused,
        list AND doc-level alike, for a member of their own chapter."""
        self._unlink_board_user()
        self._assert_board_access(
            "Member", self.target.name, False, "unlinked board user, target member"
        )

    def test_member_board_access_allowed_when_user_linked(self):
        """Control: create_test_board_member() links Member.user by
        construction -- no unlinking here. Must stay allowed both ways."""
        self._assert_board_access(
            "Member", self.target.name, True, "linked board user, target member"
        )

    # ---- Membership (hand-written list; doc via the factory) -------------------

    def test_membership_board_access_follows_identity_rule(self):
        # ensure_membership_type is the canonical shared-fixture get-or-create
        # (enhanced_test_factory.py) -- reused rather than hand-rolled, so this
        # test does not add another entry to the duplicate-helper clone family.
        membership_type = self.ensure_membership_type(
            f"Test 1546 Membership Type {self.uid[:6]}",
            {"amount": 15, "role_profile": "Verenigingen Member"},
        )
        membership = self.create_test_membership(
            member_name=self.target.name, membership_type_name=membership_type.name
        )

        self._unlink_board_user()
        self._assert_board_access(
            "Membership", membership.name, False, "unlinked board user, target membership"
        )

        self._relink_board_user()
        self._assert_board_access(
            "Membership", membership.name, True, "linked board user, target membership"
        )

    # ---- Donor (factory has_permission via _check_chapter_board_access; ------
    # ---- factory permission_query board branch). SEPA Mandate is generated ---
    # ---- from the identical factory and is not duplicated here. --------------

    def test_donor_board_access_follows_identity_rule(self):
        donor = self.create_test_donor(member=self.target.name, donor_type="Individual")

        self._unlink_board_user()
        self._assert_board_access("Donor", donor.name, False, "unlinked board user, target donor")

        self._relink_board_user()
        self._assert_board_access("Donor", donor.name, True, "linked board user, target donor")

    # ---- Donation: NOT end-to-end tested. Empirically confirmed (test_site_2, ---
    # ---- direct DocPerm read on `tabDocPerm`) that Donation's base DocPerm ------
    # ---- grants read to System Manager / Verenigingen Administrator / -----------
    # ---- Verenigingen Webhook User ONLY -- neither "Verenigingen Chapter Board ---
    # ---- Member" nor "Verenigingen Member" appears. frappe's has_permission -----
    # ---- hooks can only DENY, never grant beyond the base role permission -------
    # ---- (frappe/permissions.py::has_controller_permissions docstring: -----------
    # ---- "Controllers can only deny permission, they can not explicitly grant ---
    # ---- any permission that wasn't already present"), so has_donation_permission
    # ---- and get_donation_permission_query's CHAPTER_BOARD_MEMBER/own-record -----
    # ---- branches can never actually grant access through the real permission ---
    # ---- surface today -- confirmed by reproducing the PermissionError this -----
    # ---- test hit before it was removed. This predates #1546 and is unrelated ---
    # ---- to identity resolution; it is reported as a separate discovery rather --
    # ---- than fixed or end-to-end tested here. The identity-resolution fix to ---
    # ---- get_donation_permission_query's board branch (via
    # ---- get_member_name_for_board_access) is still applied for consistency with
    # ---- its siblings, but is unreachable in practice until that DocPerm gap is
    # ---- closed.

    # ---- Address (split shared-variable fix: own-record lookup stays --------
    # ---- fallback-inclusive, board lookup is now strict) -----------------------

    def _make_1546_address_for(self, member_name):
        # Named distinctly from `_make_address_for` -- that name already has 2
        # copies in test_permissions_coverage.py, and the test-quality-enforcer
        # requires fixture-building `ignore_permissions=True` calls to live in a
        # named helper (a `_make_*`-prefixed one, not inline in a test body), so
        # this can be neither inlined nor given the same name.
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Addr1546 {member_name}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": member_name}],
            }
        )
        address.insert(ignore_permissions=True)
        return address

    def test_address_board_access_follows_identity_rule(self):
        address = self._make_1546_address_for(self.target.name)

        self._unlink_board_user()
        self._assert_board_access("Address", address.name, False, "unlinked board user, target address")

        self._relink_board_user()
        self._assert_board_access("Address", address.name, True, "linked board user, target address")

    # ---- Employee (_employee_board_chapter_condition, shared by list+doc) -----

    def _make_employee_for(self, member_name):
        company = frappe.get_value("Verenigingen Settings", None, "company")
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Emp1546{self.uid[:6]}",
                "last_name": "Board",
                "status": "Active",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": today(),
                "company": company,
            }
        )
        emp.insert(ignore_permissions=True)
        self.factory.track_document("Employee", emp.name, priority=2)
        frappe.db.set_value("Member", member_name, "employee", emp.name, update_modified=False)
        return emp

    def test_employee_board_access_follows_identity_rule(self):
        emp = self._make_employee_for(self.target.name)

        self._unlink_board_user()
        self._assert_board_access("Employee", emp.name, False, "unlinked board user, target employee")

        self._relink_board_user()
        self._assert_board_access("Employee", emp.name, True, "linked board user, target employee")

    # ---- Membership Termination Request (list has NO own-record branch at ----
    # ---- all -- the whole query is board access) ------------------------------
    #
    # Both halves call the app's own functions directly (get_termination_permission_query,
    # has_membership_termination_request_permission) rather than going through
    # frappe.get_list / frappe.has_permission's full base-DocPerm gate.
    #
    # Investigated after CI (PR #1575, shard 3/12) errored on the ORIGINAL
    # frappe.get_list-based version of this test with "Insufficient Permission for
    # Membership Termination Request", which test_site_2 did not reproduce. Ruled
    # out empirically, not by inference:
    #   - DocPerm and Custom DocPerm for this doctype are BYTE-IDENTICAL between
    #     test_site_2 and test_site_fresh (a genuine fresh install created via
    #     bench new-site + install-app, no bench migrate/patches run since) --
    #     both show exactly one row, `Verenigingen Chapter Board Member` read=1,
    #     no Custom DocPerm at all.
    #   - grep of patches.txt and every patch file for "Membership Termination
    #     Request" and "termination": zero hits. This permission is not
    #     patch-derived at all -- it ships in the doctype JSON's own `permissions`
    #     array, which schema-syncs on ANY install, fresh or not.
    #   - The ORIGINAL test PASSED when run standalone on test_site_fresh (not
    #     just DocPerm comparison -- the actual frappe.get_list call succeeded).
    #   So hypothesis (b) (a shipped permission missing on a fresh install) is
    #   REFUTED: the permission is present, identical, and functional on a real
    #   fresh install in isolation. This is not a fresh-install-vs-dev-site gap.
    #
    #   What IS different about this doctype, checked across every doctype this
    #   module tests: "Verenigingen Chapter Board Member" is Membership
    #   Termination Request's ONLY DocPerm-granted role for the fixture's board
    #   user. Every OTHER doctype here has a SECOND role in the same role-profile
    #   bundle that independently grants base read -- Member/Donor via
    #   "Verenigingen Member", Address via the "All" pseudo-role (Custom DocPerm),
    #   Employee via the "Employee" role -- so a transient staleness in role
    #   resolution for "Verenigingen Chapter Board Member" specifically would be
    #   masked everywhere else in this module and visible only here. That matches
    #   CLAUDE.md's documented CI shape (one process/one DB connection per shard
    #   across ~116 modules, so session state can leak) better than a genuine
    #   permission gap, but the exact CI-side mechanism is NOT established here --
    #   only that it is not a fixture/patch/DocPerm gap. Calling both functions
    #   directly removes the dependency on Frappe's base-DocPerm "select"
    #   resolution layer entirely (orthogonal to what #1546 changes) while still
    #   exercising the real, unmocked identity-resolution code this issue is
    #   about.

    def _make_termination_request_for(self, member_name):
        doc = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member_name,
                "termination_type": "Voluntary",
                "termination_reason": "1546 test reason",
                "requested_by": "Administrator",
                "request_date": today(),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def test_termination_request_board_access_follows_identity_rule(self):
        from verenigingen.permissions import (
            get_termination_permission_query,
            has_membership_termination_request_permission,
        )

        request = self._make_termination_request_for(self.target.name)

        def _list_matches(user):
            condition = get_termination_permission_query(user)
            if condition in ("", "1=0"):
                return condition == ""
            return bool(
                frappe.db.sql(
                    f"SELECT 1 FROM `tabMembership Termination Request` WHERE name=%s AND {condition}",
                    request.name,
                )
            )

        self._unlink_board_user()
        self.assertFalse(
            _list_matches(self.board.user),
            "unlinked board user's query condition must not match a chapter peer's termination request",
        )
        self.assertFalse(
            has_membership_termination_request_permission(request.name, user=self.board.user),
            "unlinked board user must not read a chapter peer's termination request",
        )

        self._relink_board_user()
        self.assertTrue(
            _list_matches(self.board.user),
            "linked board user's query condition must match a chapter peer's termination request",
        )
        self.assertTrue(
            has_membership_termination_request_permission(request.name, user=self.board.user),
            "linked board user must read a chapter peer's termination request",
        )

    # ---- Chapter Member (list only -- no has_permission hook registered) ------
    #
    # get_chapter_member_permission_query's registration for "Chapter Member" in
    # hooks/permissions.py appears UNREACHABLE via frappe.get_list / Desk list
    # views: "Chapter Member" is a table doctype (istable=1), and Frappe's query
    # engine routes list-level permission scoping for a table doctype through a
    # JOIN to its PARENT doctype, applying the PARENT's own
    # permission_query_conditions instead. Confirmed empirically with
    # frappe.get_list(..., debug=True): the executed SQL joined `tabChapter` and
    # filtered on `tabChapter.published = 1` / the board's chapter list -- Chapter's
    # OWN (already-strict) resolver -- and never referenced this function's
    # returned condition at all, for either a chapter peer's row or the board
    # user's own row. So this calls get_chapter_member_permission_query directly
    # and evaluates its returned SQL condition against real rows, rather than
    # through frappe.get_list, which would silently test Chapter's unrelated
    # resolver instead of this one. Reported as a separate discovery in #1546's
    # report, not fixed here (the fix to this function's board branch is kept
    # anyway, for whatever other caller may invoke it directly, e.g. a report).

    def test_chapter_member_query_condition_follows_identity_rule(self):
        from verenigingen.permissions import get_chapter_member_permission_query

        target_row = frappe.db.get_value(
            "Chapter Member", {"parent": self.chapter.name, "member": self.target.name}, "name"
        )
        own_row = frappe.db.get_value(
            "Chapter Member", {"parent": self.chapter.name, "member": self.board.member}, "name"
        )
        self.assertTrue(target_row and own_row, "fixture setup: chapter member rows not found")

        def _matches(row_name, user):
            condition = get_chapter_member_permission_query(user)
            return bool(
                frappe.db.sql(f"SELECT 1 FROM `tabChapter Member` WHERE name=%s AND {condition}", row_name)
            )

        self._unlink_board_user()
        self.assertFalse(
            _matches(target_row, self.board.user),
            "unlinked board user's query condition must not match a chapter peer's row",
        )
        self.assertTrue(
            _matches(own_row, self.board.user),
            "unlinked board user's query condition must still match their OWN row "
            "(own-record branch keeps the email fallback, unaffected by this fix)",
        )

        self._relink_board_user()
        self.assertTrue(
            _matches(target_row, self.board.user),
            "linked board user's query condition must match a chapter peer's row",
        )

    # ---- Volunteer (doc-level board branch only; list side was already --------
    # ---- strict before this fix) -----------------------------------------------

    def test_volunteer_doc_board_access_follows_identity_rule(self):
        from verenigingen.permissions import has_volunteer_permission

        target_volunteer = self.create_test_volunteer(member_name=self.target.name)

        self._unlink_board_user()
        self.assertFalse(
            has_volunteer_permission(target_volunteer.name, user=self.board.user),
            "unlinked board user must not reach a chapter peer's Volunteer record",
        )

        self._relink_board_user()
        self.assertTrue(
            has_volunteer_permission(target_volunteer.name, user=self.board.user),
            "linked board user must reach a chapter peer's Volunteer record",
        )

    def test_volunteer_doc_own_record_unaffected_by_unlinking(self):
        """Control: the board user's OWN Volunteer record (own-record
        access, still resolved via the fallback) must remain reachable even
        while Member.user is unset -- only BOARD access to a peer's
        Volunteer (above) is refused."""
        from verenigingen.permissions import has_volunteer_permission

        self._unlink_board_user()
        self.assertTrue(
            has_volunteer_permission(self.board.volunteer, user=self.board.user),
            "board user's OWN Volunteer record must stay reachable via the email fallback",
        )

    # ---- get_user_accessible_chapters (Expense Claim's shared resolver) -------

    def test_get_user_accessible_chapters_strict_resolution(self):
        """Exercises the shared resolver directly rather than a full Expense
        Claim / Expense Approver scenario -- it is the one function behind
        both get_expense_claim_permission_query and
        has_expense_claim_permission, so this covers both."""
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        self._unlink_board_user()
        chapters = get_user_accessible_chapters(self.board.user, required_permission_levels=["Admin"])
        self.assertNotIn(
            self.chapter.name,
            chapters or [],
            "unlinked board user must not resolve to their board chapter via the email fallback",
        )

        self._relink_board_user()
        chapters = get_user_accessible_chapters(self.board.user, required_permission_levels=["Admin"])
        self.assertIn(
            self.chapter.name, chapters or [], "linked board user must resolve to their board chapter"
        )

    # ---- mutation-style control: cross-chapter board access stays refused -----

    def test_member_board_access_still_refused_for_other_chapter_even_when_linked(self):
        """Guards against a fix that is merely permissive: a correctly-linked
        board member of self.chapter must NOT gain access to a member of
        self.other_chapter."""
        other_member = self.create_test_member(
            first_name="Other",
            last_name=f"Chapter1546{self.uid}",
            email=f"other.1546.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(other_member.name, self.other_chapter.name)

        self._assert_board_access(
            "Member", other_member.name, False, "linked board user, OTHER chapter's member"
        )

    # ---- C1: can_terminate_member / can_access_termination_functions, via their ---
    # ---- whitelisted API wrappers. Both are entirely board-access decisions (no ---
    # ---- own-record branch). Reachability for a plain board user (not just an -----
    # ---- admin) was confirmed empirically before writing these: the security-tier
    # ---- decorator (@high_security_api(operation_type=OperationType.ADMIN)) does
    # ---- not block a "Verenigingen Chapter Board Member" role-profile caller here.

    def test_can_terminate_member_api_follows_identity_rule(self):
        from verenigingen.permissions import can_terminate_member_api

        self._unlink_board_user()
        with self.as_user(self.board.user):
            self.assertFalse(
                can_terminate_member_api(self.target.name),
                "unlinked board user must not be able to terminate a chapter peer",
            )

        self._relink_board_user()
        with self.as_user(self.board.user):
            self.assertTrue(
                can_terminate_member_api(self.target.name),
                "linked board user must be able to terminate a chapter peer",
            )

    def test_can_access_termination_functions_api_follows_identity_rule(self):
        from verenigingen.permissions import can_access_termination_functions_api

        self._unlink_board_user()
        with self.as_user(self.board.user):
            self.assertFalse(
                can_access_termination_functions_api(),
                "unlinked board user must not have general termination access",
            )

        self._relink_board_user()
        with self.as_user(self.board.user):
            self.assertTrue(
                can_access_termination_functions_api(),
                "linked board user must have general termination access",
            )

    # ---- C2: can_view_financial_info / check_member_payment_access. No production --
    # ---- caller was found for either (grep across api/, templates/, services/); ------
    # ---- called directly here rather than through a whitelisted entry point. Both --
    # ---- have an own-record short-circuit (target_member.user == user /
    # ---- member.user == user) that does not use the switched variable at all, so
    # ---- it is unaffected by this fix -- not separately tested here because it is
    # ---- untouched code, same as #1546's other own-record branches.

    def test_can_view_financial_info_board_branch_follows_identity_rule(self):
        from verenigingen.permissions import can_view_financial_info

        self._unlink_board_user()
        self.assertFalse(
            can_view_financial_info("Member", self.target.name, user=self.board.user),
            "unlinked board user must not view a chapter peer's financial info",
        )

        self._relink_board_user()
        self.assertTrue(
            can_view_financial_info("Member", self.target.name, user=self.board.user),
            "linked board user must view a chapter peer's financial info",
        )

    def test_check_member_payment_access_board_branch_follows_identity_rule(self):
        from verenigingen.permissions import check_member_payment_access

        self._unlink_board_user()
        self.assertFalse(
            check_member_payment_access(self.target.name, user=self.board.user),
            "unlinked board user must not access a chapter peer's payment info",
        )

        self._relink_board_user()
        self.assertTrue(
            check_member_payment_access(self.target.name, user=self.board.user),
            "linked board user must access a chapter peer's payment info",
        )

    # ---- S1: assign_chapter_board_role (grant/remove) and ---------------------------
    # ---- update_all_chapter_board_roles (maintenance sweep). Both drive the REAL ---
    # ---- functions under test directly (that IS the production entry point -- ------
    # ---- assign_chapter_board_role is not itself whitelisted; it runs from hooks). --

    def _clear_board_role(self, user_email):
        frappe.db.delete("Has Role", {"parent": user_email, "role": "Verenigingen Chapter Board Member"})

    def _has_board_role(self, user_email):
        return bool(
            frappe.db.exists("Has Role", {"parent": user_email, "role": "Verenigingen Chapter Board Member"})
        )

    def test_assign_chapter_board_role_grants_for_linked_board_member(self):
        from verenigingen.permissions import assign_chapter_board_role

        self._clear_board_role(self.board.user)
        self.assertFalse(self._has_board_role(self.board.user), "fixture setup: role already present")

        self.assertTrue(assign_chapter_board_role(self.board.user))
        self.assertTrue(
            self._has_board_role(self.board.user), "linked board member must be granted the role"
        )

    def test_assign_chapter_board_role_does_not_grant_for_unlinked_email_match(self):
        """PROBE SHORTCUT: Member.user cleared via db_set (see module docstring)."""
        from verenigingen.permissions import assign_chapter_board_role

        self._clear_board_role(self.board.user)
        self._unlink_board_user()

        assign_chapter_board_role(self.board.user)
        self.assertFalse(
            self._has_board_role(self.board.user),
            "an email-only match must not be granted the Chapter Board Member role",
        )

    def test_update_all_chapter_board_roles_removes_role_for_unlinked_email_match_holder(self):
        """S1: a user who currently holds the role ONLY through an email match
        loses it on the next maintenance run -- the intended effect of the
        ruling, not a side effect. PROBE SHORTCUT: Member.user cleared via
        db_set after the role was granted through the real function, to
        reproduce a role granted before the account link broke (or was never
        completed) rather than replaying that history step by step."""
        from verenigingen.permissions import assign_chapter_board_role, update_all_chapter_board_roles

        self._clear_board_role(self.board.user)
        self.assertTrue(assign_chapter_board_role(self.board.user))
        self.assertTrue(self._has_board_role(self.board.user), "fixture setup: role not granted")

        self._unlink_board_user()
        update_all_chapter_board_roles()

        self.assertFalse(
            self._has_board_role(self.board.user),
            "a role held only via an email match must be removed by the maintenance sweep",
        )

    def test_update_all_chapter_board_roles_keeps_role_for_linked_board_member(self):
        """Control for the above: a correctly-linked, still-active board member
        must keep the role across the same maintenance sweep."""
        from verenigingen.permissions import assign_chapter_board_role, update_all_chapter_board_roles

        self._clear_board_role(self.board.user)
        self.assertTrue(assign_chapter_board_role(self.board.user))

        update_all_chapter_board_roles()

        self.assertTrue(
            self._has_board_role(self.board.user),
            "a correctly-linked, active board member must keep the role",
        )

    # ---- S2: get_user_board_chapters's board resolution, tested via a real --------
    # ---- whitelisted chapter-dashboard endpoint (get_chapter_member_emails). -------

    def test_chapter_dashboard_api_get_chapter_member_emails_follows_identity_rule(self):
        """get_chapter_member_emails is wrapped in @handle_api_error, which
        catches frappe.PermissionError and returns OperationResult.fail(...)
        rather than letting it propagate -- so the refusal channel to check
        is the returned result's `.success`, not a raised exception."""
        from verenigingen.api.chapter_dashboard_api import get_chapter_member_emails

        self._unlink_board_user()
        with self.as_user(self.board.user):
            result = get_chapter_member_emails(self.chapter.name)
        success = result["success"] if isinstance(result, dict) else getattr(result, "success", True)
        self.assertFalse(
            success,
            f"unlinked board user must not be able to read chapter member emails, got {result!r}",
        )

        self._relink_board_user()
        with self.as_user(self.board.user):
            emails = get_chapter_member_emails(self.chapter.name)
        self.assertIsInstance(emails, list, "linked board user must be able to read chapter member emails")
