"""#3191: suggest_chapters_for_member(member=<other>) derived chapter suggestions from another
member's Address with no Member read check (ChapterMatchingService._get_member_location does
get_doc Member / Address as the service user of the call, not as a permission-checked read).

The attacker personas are the two measured in the issue: a Verenigingen Member + Volunteer user
and a Chapter Board Member seated on a DIFFERENT chapter, neither of whom may read the victim
(asserted as a precondition, not assumed). Controls: the member's own user, staff, an in-chapter
board member and the caller-supplied location path keep working; a member-only user is still
refused at the MEDIUM gate before the new check. The unknown and the forbidden member must be
refused identically on every caller-visible channel (exception type, message, message_log,
Error Log rows).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import (
    suggest_chapter_for_member,
    suggest_chapters_for_member,
)


class TestSuggestChaptersMemberRead3191(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        token = frappe.generate_hash(length=6)
        # Unique 4-digit block so only this chapter matches the victim's postcode.
        self.victim_chapter = self.create_test_chapter(postal_codes="7770-7779", published=1)
        self.other_chapter = self.create_test_chapter(postal_codes="8880-8889", published=1)

        self.victim = self.create_test_member(email=f"victim3191-{token}0@example.com")
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Victim3191 {token}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Zzzzstad3191",
                "pincode": "7775AB",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": self.victim.name}],
            }
        ).insert()
        self.track_doc("Address", address.name)
        frappe.db.set_value("Member", self.victim.name, "primary_address", address.name, update_modified=False)

        # Attacker 1: Member + Volunteer profiles, no board seat.
        self.volunteer_user = self.create_test_user_with_roles(
            email=f"vol3191-{token}0@example.com",
            roles=["Verenigingen Member", "Verenigingen Volunteer"],
        ).name
        # Attacker 2: board seat on a chapter that does not contain the victim.
        self.outside_board = self.create_test_board_member(self.other_chapter.name)
        # Controls.
        self.member_only_user = self.create_test_user_with_roles(
            email=f"memonly3191-{token}0@example.com", roles=["Verenigingen Member"]
        ).name
        self.staff_user = self.create_test_user_with_roles(
            email=f"staff3191-{token}0@example.com", roles=["Verenigingen Staff"]
        ).name
        self.inside_board = self.create_test_board_member(self.victim_chapter.name)
        self.add_member_to_test_chapter(self.victim.name, self.victim_chapter.name)
        for user in (self.volunteer_user, self.member_only_user, self.staff_user):
            frappe.clear_cache(user=user)

    def _names(self, user, **kwargs):
        with self.as_user(user):
            result = suggest_chapters_for_member(self.victim.name, **kwargs)
        return [row["name"] for row in result]

    def _can_read_victim(self, user):
        with self.as_user(user):
            return bool(frappe.has_permission("Member", "read", doc=self.victim.name))

    def _observed_refusal_3191(self, user, member):
        """Everything the caller can observe about a refused call."""
        with self.as_user(user):
            frappe.clear_messages()
            errors_before = frappe.db.count("Error Log")
            try:
                suggest_chapters_for_member(member)
                outcome = ("returned", None)
            except Exception as exc:
                outcome = (type(exc).__name__, str(exc))
            return (
                outcome,
                # __frappe_exc_id is a per-exception random token, not content.
                [{k: v for k, v in m.items() if k != "__frappe_exc_id"} for m in frappe.local.message_log],
                frappe.db.count("Error Log") - errors_before,
            )

    # ---- the defect ---------------------------------------------------------

    def test_member_volunteer_user_cannot_derive_location_from_another_member(self):
        self.assertFalse(self._can_read_victim(self.volunteer_user))
        with self.assertRaises(frappe.PermissionError):
            self._names(self.volunteer_user)

    def test_outside_board_member_cannot_derive_location_from_another_member(self):
        self.assertFalse(self._can_read_victim(self.outside_board.user))
        with self.assertRaises(frappe.PermissionError):
            self._names(self.outside_board.user)

    def test_legacy_wrapper_is_refused_too(self):
        with self.as_user(self.volunteer_user), self.assertRaises(frappe.PermissionError):
            suggest_chapter_for_member(self.victim.name)

    # ---- controls (each has a real victim address + matching chapter) --------

    def test_staff_keeps_access_and_gets_the_victims_chapter(self):
        self.assertTrue(self._can_read_victim(self.staff_user))
        self.assertIn(self.victim_chapter.name, self._names(self.staff_user))

    def test_in_chapter_board_member_keeps_access_as_permission_system_grants(self):
        expected = self._can_read_victim(self.inside_board.user)
        self.assertTrue(expected, "fixture: in-chapter board member should read the member")
        self.assertIn(self.victim_chapter.name, self._names(self.inside_board.user))

    def test_own_member_record_is_allowed(self):
        # PROBE SHORTCUT: set directly instead of the self-registration flow. The Verenigingen
        # Member DocPerm is read + if_owner, so own-record read needs BOTH the user link and
        # owner == user; a real self-registered member has both.
        frappe.db.set_value(
            "Member", self.victim.name, {"user": self.volunteer_user, "owner": self.volunteer_user},
            update_modified=False,
        )
        frappe.clear_cache(user=self.volunteer_user)
        self.assertTrue(self._can_read_victim(self.volunteer_user))
        self.assertIn(self.victim_chapter.name, self._names(self.volunteer_user))

    def test_caller_supplied_postal_code_needs_no_member_read(self):
        names = self._names(self.volunteer_user, postal_code="7775AB")
        self.assertIn(self.victim_chapter.name, names)

    def test_member_only_user_is_still_refused_at_the_gate(self):
        with self.assertRaises(frappe.PermissionError):
            self._names(self.member_only_user)

    # ---- existence oracle ----------------------------------------------------

    def test_unknown_and_forbidden_member_are_refused_identically(self):
        for user in (self.volunteer_user, self.outside_board.user):
            forbidden = self._observed_refusal_3191(user, self.victim.name)
            unknown = self._observed_refusal_3191(user, f"no-such-member-{self.victim.name}")
            self.assertEqual(forbidden[0][0], "PermissionError", "forbidden member must be refused")
            self.assertEqual(forbidden, unknown, f"refusal differs for {user}")

    def test_blank_member_is_refused_like_an_unknown_member(self):
        # A blank member must not skip the check (mutant: `(not member) or has_permission`).
        for user in (self.volunteer_user, self.outside_board.user, self.staff_user):
            blank = self._observed_refusal_3191(user, "")
            unknown = self._observed_refusal_3191(user, f"no-such-member-{self.victim.name}")
            self.assertEqual(blank[0][0], "PermissionError", f"blank member not refused for {user}")
            self.assertEqual(blank, unknown, f"blank vs unknown refusal differs for {user}")
