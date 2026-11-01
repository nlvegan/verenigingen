"""#1672: a plain board member seating another user must not log a refused role grant.

``ChapterBoardMember.assign_board_member_role`` appended the ``Verenigingen Chapter Board
Member`` role to the seated user's User doc under ``required_permissions=["User:write"]``.
An actor without User write (an ordinary chapter board member) was refused, and the refusal
was only logged, on every such seating. The seated user still ended with the role because
``Chapter.on_update`` drains the deferred role-profile sync (``ignore_permissions``), which
applies the board profile, and ``User`` validation derives ``roles`` from the profiles.

Everything here runs through the real flow: a Chapter save by a seated board member whose
User holds only the board role profile (his chapter write access is his role's DocPerm). The
only probe shortcut: the disabled-account test flips ``User.enabled`` with ``db.set_value``
to stand in for an account an administrator disabled.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"
BOARD_PROFILE = "Verenigingen Chapter Board Member"
NO_ROLE_PROFILE = "Verenigingen Auditor"  # a profile that does not carry the board role


class TestBoardSeatRoleGrant1672(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Seat1672 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.board_role = self._chapter_role_1672("Secretary")
        self.actor = self._seat_1672(self.chapter.name, "Actor")  # seated by the administrator

    def _chapter_role_1672(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_1672(self, label):
        email = f"seat1672.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Seat", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name)

    def _seat_1672(self, chapter_name, label):
        person = self._person_1672(label)
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", chapter_name), person.volunteer, self.board_role, email=person.user
        )
        return person

    def _seat_as(self, actor, chapter_name, person):
        """The real flow: the actor loads the Chapter, appends a row, saves."""
        with self.as_user(actor.user):
            chapter = frappe.get_doc("Chapter", chapter_name)
            chapter.append(
                "board_members",
                {
                    "volunteer": person.volunteer,
                    "chapter_role": self.board_role,
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                    "email": person.user,
                },
            )
            chapter.save()

    def _board_role_error_rows(self):
        return frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%elevated system operations%"]},
            pluck="name",
        )

    def _unseat_as(self, actor, chapter_name, person):
        with self.as_user(actor.user):
            chapter = frappe.get_doc("Chapter", chapter_name)
            for row in chapter.board_members:
                if row.volunteer == person.volunteer:
                    row.is_active = 0
                    row.to_date = frappe.utils.today()
            chapter.save()

    def _roles_of_1672(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _profiles_of_1672(self, user):
        return set(frappe.get_all("User Role Profile", filters={"parent": user}, pluck="role_profile"))

    # ------------------------------------------------------------------ the bug

    def test_plain_board_member_seating_logs_no_refused_grant_and_seat_holder_gets_the_role(self):
        seated = self._person_1672("Seated")
        refused_before = set(self._board_role_error_rows())  # Error Log is MyISAM: rows outlive tests
        self.assertNotIn(BOARD_ROLE, self._roles_of_1672(seated.user), "control: no role before the seat")
        self.assertNotIn("System Manager", self._roles_of_1672(self.actor.user), "control: actor has no User write")

        with self.assertNoErrorLog():
            self._seat_as(self.actor, self.chapter.name, seated)

        self.assertEqual(
            set(self._board_role_error_rows()) - refused_before, set(), "a refused role grant was logged"
        )
        self.assertIn(BOARD_ROLE, self._roles_of_1672(seated.user))
        self.assertEqual(self._profiles_of_1672(seated.user), {BOARD_PROFILE})

    def test_plain_board_member_unseating_logs_nothing_and_withdraws_the_role(self):
        """Outcome sweep: the withdrawal path uses the same secure_document_operation."""
        seated = self._seat_1672(self.chapter.name, "Leaver")
        self.assertIn(BOARD_ROLE, self._roles_of_1672(seated.user), "control: seat grants the role")

        with self.assertNoErrorLog():
            self._unseat_as(self.actor, self.chapter.name, seated)

        self.assertNotIn(BOARD_ROLE, self._roles_of_1672(seated.user))

    # ------------------------------------------- nothing depends on the direct grant

    def test_profile_without_the_role_never_kept_a_direct_grant(self):
        """Control for removing the grant: where the chapter maps a profile that does NOT carry
        the board role, the profile sync (a replace) strips a direct grant, so the grant was
        never the thing that conferred it. Holds on develop and after the fix."""
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.default_board_role_profile = NO_ROLE_PROFILE
        chapter.save()
        seated = self._person_1672("Mapped")

        self._seat_as(frappe._dict(user="Administrator"), self.chapter.name, seated)

        self.assertEqual(self._profiles_of_1672(seated.user), {NO_ROLE_PROFILE})
        self.assertNotIn(BOARD_ROLE, self._roles_of_1672(seated.user))

    def test_seated_before_the_account_exists_the_sync_grants_the_role(self):
        """ACR path: a seat taken before the user exists is picked up by the profile sync
        the account-creation pipeline runs (its Phase 3), not by a direct grant."""
        from verenigingen.services.member.account.user_role_profile_calculator import auto_sync_on_role_change

        email = f"seat1672.late.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(first_name="Late", last_name="Seat", email=email, status="Active")
        volunteer = self.create_test_volunteer(member=member.name)
        self.add_board_member_to_chapter(
            frappe.get_doc("Chapter", self.chapter.name), volunteer.name, self.board_role, email=email
        )
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member.db_set("user", user.name, update_modified=False)
        self.assertNotIn(BOARD_ROLE, self._roles_of_1672(user.name), "control: nothing granted yet")

        auto_sync_on_role_change(user.name)

        self.assertIn(BOARD_ROLE, self._roles_of_1672(user.name))

    def test_a_disabled_account_is_not_provisioned_until_it_is_enabled_and_synced(self):
        """The one measured dependence: the profile sync skips a disabled user, so with no
        direct grant a disabled seat holder gets nothing until re-enabled and synced. That is
        the sync's own rule for disabled accounts (see sync_user_role_profile)."""
        from verenigingen.services.member.account.user_role_profile_calculator import auto_sync_on_role_change

        seated = self._person_1672("Disabled")
        frappe.db.set_value("User", seated.user, "enabled", 0)  # probe shortcut, see module doc

        self._seat_as(frappe._dict(user="Administrator"), self.chapter.name, seated)
        self.assertNotIn(BOARD_ROLE, self._roles_of_1672(seated.user))

        frappe.db.set_value("User", seated.user, "enabled", 1)
        auto_sync_on_role_change(seated.user)
        self.assertIn(BOARD_ROLE, self._roles_of_1672(seated.user))
