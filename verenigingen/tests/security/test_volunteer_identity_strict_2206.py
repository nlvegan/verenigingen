# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#2206 maintainer ruling (2026-11-11): the caller's Volunteer is resolved by an explicit
link only -- ``Volunteer.member`` -> ``Member.user``, or ``Volunteer.user`` -- with no
``Volunteer.email`` / ``Member.email`` fallback and no backfill.

Callers covered: the volunteer profile and dashboard pages' ``get_user_volunteer_record``
and ``utils.member_utils.get_volunteer_name_for_user``. ``suspension_api``'s team count is
NOT caller identity (staff look at a MEMBER's teams); it now follows ``Volunteer.member``
and a decoy Volunteer that merely carries the member's login email must not be counted.

Real callers: ``linked`` (Member.user = login, Volunteer.member = that Member),
``email_only`` (Member.email AND Volunteer.email both equal the login, no Member.user,
no Volunteer.user) and ``nobody`` (no Member/Volunteer at all).

PROBE SHORTCUTS: the linked state writes ``Member.user`` with ``db.set_value`` (what staff
do through the form field); ``Volunteer.user`` for the legacy control is likewise set
directly (it is a read-only fetch from Member.user in the form).
"""

import frappe

from verenigingen import auth_hooks
from verenigingen.api import suspension_api
from verenigingen.templates.pages.volunteer import (
    dashboard as volunteer_dashboard,
    profile as volunteer_profile,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import get_volunteer_name_for_user


class TestVolunteerIdentityStrict2206(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.linked_user = self.create_test_user_with_roles(
            email=f"vol2206-linked-{frappe.generate_hash(length=6)}0@example.com",
            roles=["Verenigingen Member"],
        ).name
        self.email_user = self.create_test_user_with_roles(
            email=f"vol2206-emailonly-{frappe.generate_hash(length=6)}0@example.com",
            roles=["Verenigingen Member"],
        ).name
        self.nobody_user = self.create_test_user_with_roles(
            email=f"vol2206-nobody-{frappe.generate_hash(length=6)}0@example.com",
            roles=["Verenigingen Member"],
        ).name
        for user in (self.linked_user, self.email_user, self.nobody_user):
            frappe.clear_cache(user=user)

        self.linked_member = self.create_test_member(email=f"m-{self.linked_user}")
        frappe.db.set_value(
            "Member", self.linked_member.name, "user", self.linked_user, update_modified=False
        )
        self.linked_volunteer = self.create_test_volunteer(member=self.linked_member)

        self.email_member = self.create_test_member(email=self.email_user)
        self.email_volunteer = self.create_test_volunteer(member=self.email_member)
        frappe.db.set_value("Volunteer", self.email_volunteer.name, "email", self.email_user)

        self.assertFalse(frappe.db.get_value("Member", self.email_member.name, "user"))
        self.assertFalse(frappe.db.get_value("Volunteer", self.email_volunteer.name, "user"))

    def _records_as(self, user):
        original_user = frappe.session.user
        frappe.set_user(user)
        try:
            return (
                volunteer_profile.get_user_volunteer_record(),
                volunteer_dashboard.get_user_volunteer_record(),
                get_volunteer_name_for_user(user),
            )
        finally:
            frappe.set_user(original_user)

    def test_linked_volunteer_resolves_on_every_path(self):
        profile, dash, name = self._records_as(self.linked_user)
        self.assertEqual(profile.name, self.linked_volunteer.name)
        self.assertEqual(dash["name"], self.linked_volunteer.name)
        self.assertEqual(name, self.linked_volunteer.name)

    def test_legacy_volunteer_user_link_still_resolves(self):
        """Control: Volunteer.user is an explicit link too (ruling), even without Member.user."""
        frappe.db.set_value("Volunteer", self.email_volunteer.name, "user", self.email_user)
        profile, dash, name = self._records_as(self.email_user)
        self.assertEqual(profile.name, self.email_volunteer.name)
        self.assertEqual(dash["name"], self.email_volunteer.name)
        self.assertEqual(name, self.email_volunteer.name)

    def test_member_user_link_set_after_volunteer_creation_still_resolves(self):
        """Control for the Volunteer.member -> Member.user path on every resolver.

        setUp links Member.user BEFORE creating the Volunteer, so Volunteer.user
        (fetch_from member.user) is always populated and resolves first, which hides
        this path. Here the Volunteer is created FIRST and Member.user is set after
        (probe shortcut: db.set_value stands in for staff filling the form field), so
        Volunteer.user stays empty and only the member link can resolve it."""
        late_member = self.create_test_member()
        late_volunteer = self.create_test_volunteer(member=late_member)
        self.assertFalse(frappe.db.get_value("Volunteer", late_volunteer.name, "user"))
        frappe.db.set_value("Member", late_member.name, "user", self.nobody_user, update_modified=False)
        self.assertFalse(frappe.db.get_value("Volunteer", late_volunteer.name, "user"))

        profile, dash, name = self._records_as(self.nobody_user)
        self.assertEqual(profile.name, late_volunteer.name)
        self.assertEqual(dash["name"], late_volunteer.name)
        self.assertEqual(name, late_volunteer.name)

    def test_email_only_volunteer_resolves_nowhere(self):
        self.assertEqual(self._records_as(self.email_user), (None, None, None))

    def test_email_only_is_indistinguishable_from_no_member(self):
        log_len = len(frappe.local.message_log)
        errors_before = frappe.db.count("Error Log")
        email_only = self._records_as(self.email_user)
        nobody = self._records_as(self.nobody_user)
        self.assertEqual(email_only, nobody)
        self.assertEqual(len(frappe.local.message_log), log_len)
        self.assertEqual(frappe.db.count("Error Log"), errors_before)

    def test_volunteer_email_alone_does_not_match_a_different_member_login(self):
        """A Volunteer carrying someone ELSE's login as its email must not resolve for them,
        even when that login is a properly linked Member's user (the decoy case)."""
        decoy = self.create_test_volunteer(member=self.create_test_member())
        frappe.db.set_value("Volunteer", decoy.name, "email", self.nobody_user)
        self.assertIsNone(get_volunteer_name_for_user(self.nobody_user))

    def test_routing_is_unchanged_for_linked_and_unlinked_volunteers(self):
        """auth_hooks only uses get_volunteer_name_for_user to choose between two routes that
        are both /member_portal, so strict resolution cannot change where anyone lands."""
        for user in (self.linked_user, self.email_user, self.nobody_user):
            self.assertEqual(auth_hooks.get_default_home_page(user), "/member_portal", user)

    def test_suspension_preview_counts_the_members_own_volunteer_teams(self):
        """Not caller identity: the staff preview counts the MEMBER's volunteer teams. The old
        lookup used Volunteer.email == the member's login, which both missed the real
        Volunteer (differing contact email) and counted a decoy that merely shared the email."""
        frappe.db.set_value("Volunteer", self.linked_volunteer.name, "email", f"other-{self.linked_user}")
        team = self.factory.create_team()
        self.factory.create_team_member(team.name, self.linked_volunteer.name)

        decoy_member = self.create_test_member()
        decoy = self.create_test_volunteer(member=decoy_member)
        frappe.db.set_value("Volunteer", decoy.name, "email", self.linked_user)
        decoy_team = self.factory.create_team()
        self.factory.create_team_member(decoy_team.name, decoy.name)

        result = suspension_api.get_suspension_preview(member_name=self.linked_member.name)
        self.assertTrue(result["success"], msg=result)
        teams = [t["team"] for t in result["data"]["team_details"]]
        self.assertEqual(teams, [team.name])
        self.assertEqual(result["data"]["active_teams"], 1)
