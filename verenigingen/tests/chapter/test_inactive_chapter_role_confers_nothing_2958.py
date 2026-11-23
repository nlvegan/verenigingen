"""#2958: an inactive Chapter Role confers no board access.

Maintainer ruling: deactivating a Chapter Role withdraws its holders' board access. The handler
``on_chapter_role_on_update`` already re-evaluates every holder on an ``is_active`` flip, but both seat
readers it relies on ignored ``Chapter Role.is_active``, so the re-evaluation found the seat and changed
nothing: ``permissions.get_user_chapter_board_positions`` (decides the Frappe role) and
``get_board_member_profiles`` (decides the role profile).

The holders are real (Member.user linked, seated through a real Chapter save); the deactivation is a real
Chapter Role save, not a ``db.set_value``.
"""

import frappe

from verenigingen.api.member_management import can_assign_member_to_chapter
from verenigingen.permissions import get_user_chapter_board_positions
from verenigingen.services.member.account.user_role_profile_calculator import (
    get_board_member_profiles,
    get_user_role_profiles,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles

BOARD_PROFILE = "Verenigingen Chapter Board Member"


class TestInactiveChapterRoleConfersNothing2958(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"R2958 {frappe.generate_hash(length=6)}", postal_codes="1000-9999", published=1
        )

    def _role_2958(self, level="Basic"):
        name = f"Role2958{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": level, "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _holder_2958(self, role_name, label="Holder"):
        email = f"r2958.{label.lower()}.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="R2958", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        self.add_board_member_to_chapter(chapter, volunteer, role_name, email=user.name)
        return frappe._dict(user=user.name, member=member.name, volunteer=volunteer.name)

    def _set_active_2958(self, role_name, active):
        role = frappe.get_doc("Chapter Role", role_name)
        role.is_active = active
        role.save()

    def _has_access_2958(self, user):
        frappe.clear_cache(user=user)
        return {
            "role": Roles.CHAPTER_BOARD_MEMBER in frappe.get_roles(user),
            "row": bool(frappe.db.exists("Has Role", {"parent": user, "role": Roles.CHAPTER_BOARD_MEMBER})),
            "profile": BOARD_PROFILE in get_user_role_profiles(user),
        }

    # ---------------------------------------------------------------- the real flow

    def test_deactivating_a_role_withdraws_its_holders_board_access(self):
        role = self._role_2958()
        holder = self._holder_2958(role)
        self.assertEqual(
            self._has_access_2958(holder.user),
            {"role": True, "row": True, "profile": True},
            "fixture: seating must grant access first, or the withdrawal below proves nothing",
        )

        self._set_active_2958(role, 0)

        self.assertEqual(
            self._has_access_2958(holder.user), {"role": False, "row": False, "profile": False}
        )

    def test_an_active_role_still_confers_access_after_an_unrelated_edit(self):
        """Control: the same handler run on a role that stays active must not withdraw anything."""
        role = self._role_2958()
        holder = self._holder_2958(role)
        doc = frappe.get_doc("Chapter Role", role)
        doc.permissions_level = "Admin"
        doc.save()
        self.assertEqual(
            self._has_access_2958(holder.user), {"role": True, "row": True, "profile": True}
        )

    def test_deactivating_one_role_keeps_access_held_through_another_active_role(self):
        """Control with a real candidate: the holder has a second seat on a role that stays active."""
        dying, staying = self._role_2958(), self._role_2958()
        holder = self._holder_2958(dying)
        other_chapter = self.create_test_chapter(
            chapter_name=f"R2958b {frappe.generate_hash(length=6)}", postal_codes="2000-2999", published=1
        )
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", other_chapter.name), holder.volunteer, staying, email=holder.user
        )

        self._set_active_2958(dying, 0)

        self.assertTrue(self._has_access_2958(holder.user)["role"])
        positions = get_user_chapter_board_positions(holder.member)
        self.assertEqual([p.chapter_role for p in positions], [staying])

    # ---------------------------------------------------------------- the two readers

    def test_position_reader_skips_an_inactive_role_and_keeps_an_active_one(self):
        active, inactive = self._role_2958(), self._role_2958()
        holder = self._holder_2958(active)
        other = self.create_test_chapter(
            chapter_name=f"R2958c {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", other.name), holder.volunteer, inactive, email=holder.user
        )
        frappe.db.set_value("Chapter Role", inactive, "is_active", 0)  # probe shortcut: reader-level only

        roles = [p.chapter_role for p in get_user_chapter_board_positions(holder.member)]
        self.assertEqual(roles, [active])

    def test_profile_reader_skips_an_inactive_role_and_keeps_an_active_one(self):
        active, inactive = self._role_2958(), self._role_2958()
        holder = self._holder_2958(active)
        other = self.create_test_chapter(
            chapter_name=f"R2958d {frappe.generate_hash(length=6)}", postal_codes="4000-4999", published=1
        )
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", other.name), holder.volunteer, inactive, email=holder.user
        )
        self.assertEqual(len(get_board_member_profiles(holder.user, holder.member)), 2, "fixture: two seats")
        frappe.db.set_value("Chapter Role", inactive, "is_active", 0)  # probe shortcut: reader-level only

        self.assertEqual(len(get_board_member_profiles(holder.user, holder.member)), 1)

    # ---------------------------------------------------------------- grant readers beyond the two

    def _can_assign_as_2958(self, holder):
        previous = frappe.session.user
        frappe.set_user(holder.user)
        try:
            return can_assign_member_to_chapter(holder.member, self.chapter.name)
        finally:
            frappe.set_user(previous)

    def test_a_deactivated_admin_role_no_longer_lets_its_holder_assign_members(self):
        role = self._role_2958("Admin")
        holder = self._holder_2958(role)
        self.assertTrue(self._can_assign_as_2958(holder), "fixture: an active Admin seat may assign")

        self._set_active_2958(role, 0)

        self.assertFalse(self._can_assign_as_2958(holder))

    # ---------------------------------------------------------------- reactivation

    def test_reactivating_a_role_restores_role_and_profile_and_survives_a_user_save(self):
        role = self._role_2958()
        holder = self._holder_2958(role)
        self._set_active_2958(role, 0)
        self.assertEqual(
            self._has_access_2958(holder.user), {"role": False, "row": False, "profile": False}
        )

        self._set_active_2958(role, 1)
        frappe.get_doc("User", holder.user).save()

        self.assertEqual(self._has_access_2958(holder.user), {"role": True, "row": True, "profile": True})
