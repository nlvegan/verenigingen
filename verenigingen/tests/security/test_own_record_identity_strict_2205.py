# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#2205 maintainer ruling (2026-11-11): own-record DOCUMENT permissions in
``permissions.py`` resolve the caller's Member by ``Member.user`` ONLY -- no
``Member.email`` fallback, no backfill (same as #1936/#1853/#1546). A User who
merely shares an email with a Member must not read that Member's own records.

Three real callers, all holding only the "Verenigingen Member" role (no admin,
no board seat):

- ``linked``     a User whose Member carries ``Member.user`` = that User
- ``email_only`` a User whose login equals a Member's ``email``, with
                 ``Member.user`` UNSET (the ~126 veg11 Members of #1546)
- ``nobody``     a User with no Member at all

For every own-record site changed (Member, Volunteer, Donor, SEPA Mandate,
Donation, Address, Membership, Chapter Member, Team Member) both the doc-level
check and the list-query condition are asserted: ``linked`` sees the record,
``email_only`` does not, and ``email_only`` is refused IDENTICALLY to ``nobody``
(same return value / SQL condition, same ``message_log`` length, same Error Log
row count).

PROBE SHORTCUTS: the unlinked state is a Member built by the real factory whose
``user`` field is simply never written; the linked state is ``Member.user``
written with ``db.set_value`` (what staff do through the form field). SEPA
Mandate and Donation doc-level checks receive a ``frappe._dict`` carrying only the
linking field, because both read nothing else from the doc; the real Donor /
Donation rows exist and drive the list-query half.
"""

import frappe

from verenigingen import permissions as perms
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _sql_ids(table, condition, names):
    """Names (out of `names`) that survive a permission_query condition."""
    if condition == "":
        return set(names)
    rows = frappe.db.sql(
        f"SELECT name FROM `tab{table}` WHERE name IN %(names)s AND ({condition})",
        {"names": tuple(names)},
    )
    return {r[0] for r in rows}


class TestOwnRecordIdentityStrict2205(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.linked_user = self.create_test_user_with_roles(
            email=f"own2205-linked-{frappe.generate_hash(length=6)}0@example.com",
            roles=["Verenigingen Member"],
        ).name
        self.email_user = self.create_test_user_with_roles(
            email=f"own2205-emailonly-{frappe.generate_hash(length=6)}0@example.com",
            roles=["Verenigingen Member"],
        ).name
        self.nobody_user = self.create_test_user_with_roles(
            email=f"own2205-nobody-{frappe.generate_hash(length=6)}0@example.com",
            roles=["Verenigingen Member"],
        ).name
        for user in (self.linked_user, self.email_user, self.nobody_user):
            frappe.clear_cache(user=user)

        self.linked = self._build_records(self.linked_user, link_user=True)
        self.email_only = self._build_records(self.email_user, link_user=False)

        # Preconditions: the unlinked fixture really is unlinked, the email really matches.
        self.assertFalse(frappe.db.get_value("Member", self.email_only["member"], "user"))
        self.assertEqual(frappe.db.get_value("Member", self.email_only["member"], "email"), self.email_user)
        self.assertEqual(frappe.db.get_value("Member", self.linked["member"], "user"), self.linked_user)
        self.assertFalse(frappe.db.exists("Member", {"user": self.nobody_user}))
        self.assertFalse(frappe.db.exists("Member", {"email": self.nobody_user}))

    # ---- fixtures -----------------------------------------------------------------

    def _build_records(self, user, link_user):
        member_email = user if not link_user else f"m-{user}"
        member = self.create_test_member(email=member_email)
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        if link_user:
            frappe.db.set_value("Member", member.name, "user", user, update_modified=False)
        volunteer = self.create_test_volunteer(member=member)
        donor = self.create_test_donor(member=member.name, donor_email=f"d-{user}")
        donation = self.create_test_donation(donor=donor.name)
        membership = self.create_test_membership(member.name)
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Own2205 {frappe.generate_hash(length=6)}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": member.name}],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Address", address.name)
        team = self.factory.create_team()
        team_member = self.factory.create_team_member(team.name, volunteer.name)
        rows = frappe.db.sql("SELECT name FROM `tabChapter Member` WHERE member = %s", member.name)
        chapter_member = rows[0][0] if rows else None
        self.assertTrue(chapter_member, "fixture: member has no Chapter Member row")
        return {
            "member": member.name,
            "volunteer": volunteer.name,
            "donor": donor.name,
            "donation": donation.name,
            "membership": membership.name,
            "address": address.name,
            "team_member": team_member.name,
            "chapter_member": chapter_member,
        }

    # ---- channels -----------------------------------------------------------------

    def _doc_checks(self, user, rec):
        """Every doc-level own-record check changed by #2205, as {label: bool}."""
        return {
            "Member": bool(perms.has_member_permission(rec["member"], user, "read")),
            "Volunteer": bool(perms.has_volunteer_permission(rec["volunteer"], user, "read")),
            "Donor": bool(perms.has_donor_permission(rec["donor"], user, "read")),
            "SEPA Mandate": bool(
                perms.has_sepa_mandate_permission(frappe._dict(member=rec["member"]), user, "read")
            ),
            "Donation": bool(perms.has_donation_permission(rec["donation"], user, "read")),
            "Address": bool(perms.has_address_permission(rec["address"], user, "read")),
            "Membership": bool(perms.has_membership_permission(rec["membership"], user, "read")),
        }

    def _query_conditions(self, user):
        return {
            "Donor": perms.get_donor_permission_query(user),
            "SEPA Mandate": perms.get_sepa_mandate_permission_query(user),
            "Donation": perms.get_donation_permission_query(user),
            "Address": perms.get_address_permission_query(user),
            "Membership": perms.get_membership_permission_query(user),
            "Chapter Member": perms.get_chapter_member_permission_query(user),
            "Volunteer": perms.get_volunteer_permission_query(user),
            "Team Member": perms.get_team_member_permission_query(user),
        }

    def _row_listed_by_2205(self, label, condition, rec):
        key = {
            "Donor": "donor",
            "Donation": "donation",
            "Address": "address",
            "Membership": "membership",
            "Chapter Member": "chapter_member",
            "Volunteer": "volunteer",
            "Team Member": "team_member",
        }.get(label)
        if key is None:  # SEPA Mandate: no row built; the condition itself is compared instead
            return None
        table = label
        return rec[key] in _sql_ids(table, condition, [rec[key]])

    # ---- tests --------------------------------------------------------------------

    def test_linked_user_keeps_own_record_access_doc_level(self):
        """Control: the properly linked user is still allowed on every own record."""
        self.assertEqual(
            self._doc_checks(self.linked_user, self.linked),
            {k: True for k in self._doc_checks(self.linked_user, self.linked)},
        )

    def test_email_only_user_is_refused_own_record_doc_level(self):
        result = self._doc_checks(self.email_user, self.email_only)
        self.assertEqual(result, {k: False for k in result}, f"email-only user got access: {result}")

    def test_linked_user_sees_own_rows_in_every_list_query(self):
        conds = self._query_conditions(self.linked_user)
        for label, cond in conds.items():
            visible = self._row_listed_by_2205(label, cond, self.linked)
            if visible is not None:
                self.assertTrue(visible, f"{label}: linked user cannot list own row (cond={cond!r})")
        self.assertIn(self.linked["member"], cond_text(conds["SEPA Mandate"]))

    def test_email_only_user_sees_nothing_in_any_list_query(self):
        conds = self._query_conditions(self.email_user)
        for label, cond in conds.items():
            visible = self._row_listed_by_2205(label, cond, self.email_only)
            if visible is not None:
                self.assertFalse(visible, f"{label}: email-only user lists own row (cond={cond!r})")
        self.assertNotIn(self.email_only["member"], cond_text(conds["SEPA Mandate"]))

    def test_email_only_user_is_refused_identically_to_a_user_with_no_member(self):
        """Existence-oracle: the email-matching caller and the memberless caller must be
        indistinguishable on every channel (return value, SQL condition, message_log,
        Error Log row count)."""
        outcome = {}
        for who, user in (("email_only", self.email_user), ("nobody", self.nobody_user)):
            log_len = len(frappe.local.message_log)
            errors_before = frappe.db.count("Error Log")
            docs = self._doc_checks(user, self.email_only)
            conds = self._query_conditions(user)
            # Address's condition also carries the standard Contact.email_id branch (a
            # separate, unchanged path: the caller's Contact, not the Member), so an
            # email-matching caller's SQL text legitimately differs there; compare what the
            # caller can observe instead: whether the Member-linked row is listed.
            conds["Address"] = self._row_listed_by_2205("Address", conds["Address"], self.email_only)
            outcome[who] = {
                "docs": docs,
                "conds": conds,
                "message_log_growth": len(frappe.local.message_log) - log_len,
                "error_log_growth": frappe.db.count("Error Log") - errors_before,
            }
        self.assertEqual(outcome["email_only"], outcome["nobody"])

    def test_has_permission_through_frappe_dispatch_refuses_email_only(self):
        """End to end through frappe.has_permission (hook dispatch + DocPerm), for the
        doctypes whose base DocPerm lets the Member role read at all."""
        # Volunteer only: Member and Membership grant the Member role read `if_owner`, so the
        # linked control would be refused by DocPerm for an unrelated reason.
        for doctype, key in (("Volunteer", "volunteer"),):
            self.assertTrue(
                frappe.has_permission(doctype, "read", doc=self.linked[key], user=self.linked_user),
                f"{doctype}: linked user refused (control)",
            )
            self.assertFalse(
                frappe.has_permission(doctype, "read", doc=self.email_only[key], user=self.email_user),
                f"{doctype}: email-only user allowed",
            )


def cond_text(condition):
    return condition or ""
