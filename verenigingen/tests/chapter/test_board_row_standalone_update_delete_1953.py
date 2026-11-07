"""#1953: a standalone UPDATE or DELETE of a Chapter Board Member row must withdraw the seat's access.

#1922 made a standalone INSERT run the Chapter save's board access flush from the row's
``after_insert``. The same row written OUTSIDE a Chapter save by another route (REST
``PUT``/``DELETE`` on ``/api/resource/Chapter Board Member/<name>``, ``get_doc(row).save()``,
``frappe.delete_doc(row)``, and ``ChapterAssignmentService._cleanup_board_memberships``, which
loads and saves rows directly) ran only ``remove_board_member_role``. That strips the Frappe role
from a User who still carries the board role profile, and ``User.populate_role_profile_roles``
puts it straight back (#211), so role AND profile stayed.

Real flows throughout: the seat is added by a Chapter save, the end is a row save or delete.
The only probe shortcut is ``Member.user`` set with ``db_set`` (what account creation writes),
as in the #1922 and #1969 suites.
"""

import json
from unittest import mock

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    PROFILE_BOARD_MEMBER,
    get_user_role_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase

BOARD_ROLE = "Verenigingen Chapter Board Member"
STAFF = "Verenigingen Staff"


class TestBoardRowStandaloneUpdateDelete1953(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"Row1953 {frappe.generate_hash(length=6)}", postal_codes="3000-3999", published=1
        )
        self.chapter_role = self._chapter_role_1953("Secretary")

    def tearDown(self):
        for user in [d["name"] for d in self._test_docs if d["doctype"] == "User"]:
            for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
                self.track_doc("Employee", employee)  # a seat's profile carries Employee (#1694)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _chapter_role_1953(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _person_1953(self, label):
        email = f"row1953.{label.lower()}.{frappe.generate_hash(length=8)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        member = self.create_test_member(first_name=label, last_name="Row", email=email, status="Active")
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        return frappe._dict(user=user.name, volunteer=volunteer.name, email=email, member=member.name)

    def _seat_1953(self, person, chapter=None, role=None):
        """Seat through a Chapter save (the supported flow) and return the new row's name."""
        chapter = frappe.get_doc("Chapter", (chapter or self.chapter).name)
        self.add_board_member_to_chapter(chapter, person.volunteer, role or self.chapter_role, email=person.email)
        return frappe.db.get_value(
            "Chapter Board Member", {"parent": chapter.name, "volunteer": person.volunteer}, "name"
        )

    def _roles_1953(self, user):
        return set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

    def _assert_seated_1953(self, user, msg="control: the seat gives the board role and profile"):
        self.assertIn(BOARD_ROLE, self._roles_1953(user), msg)
        self.assertIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(user), msg)

    def _assert_withdrawn_1953(self, user):
        self.assertNotIn(BOARD_ROLE, self._roles_1953(user), "board role still on the user")
        self.assertNotIn(PROFILE_BOARD_MEMBER, get_user_role_profiles(user), "board profile still on user")

    def _deactivate_1953(self, row_name):
        row = frappe.get_doc("Chapter Board Member", row_name)
        row.is_active = 0
        row.to_date = frappe.utils.today()
        row.save()

    # ------------------------------------------------------------------ the bug

    def test_deactivating_a_standalone_row_withdraws_the_role_and_profile(self):
        person = self._person_1953("Deact")
        row = self._seat_1953(person)
        self._assert_seated_1953(person.user)

        self._deactivate_1953(row)

        self._assert_withdrawn_1953(person.user)

    def test_deleting_a_standalone_row_withdraws_the_role_and_profile(self):
        person = self._person_1953("Del")
        row = self._seat_1953(person)
        self._assert_seated_1953(person.user)

        frappe.delete_doc("Chapter Board Member", row)

        self._assert_withdrawn_1953(person.user)

    def test_rest_put_and_delete_routes_withdraw_the_access(self):
        """The routes' own functions, in-process as Administrator (as #1922's suite does).
        v1 ``update_doc`` saves the row and then re-saves its Chapter, which has no diff left
        to defer, so only the row hook can withdraw."""
        import frappe.api.v1

        person = self._person_1953("Put")
        row = self._seat_1953(person)
        frappe.form_dict.data = json.dumps({"is_active": 0, "to_date": frappe.utils.today()})
        frappe.api.v1.update_doc("Chapter Board Member", row)
        self._assert_withdrawn_1953(person.user)

        other = self._person_1953("Rest")
        other_row = self._seat_1953(other)
        self._assert_seated_1953(other.user)
        frappe.api.v1.delete_doc("Chapter Board Member", other_row)
        self._assert_withdrawn_1953(other.user)

    def test_assignment_service_board_term_ending_withdraws_the_access(self):
        from verenigingen.services.chapter.chapter_assignment_service import ChapterAssignmentService

        person = self._person_1953("Svc")
        row = self._seat_1953(person)
        self._assert_seated_1953(person.user)

        service = ChapterAssignmentService()
        self.assertTrue(service._cleanup_board_memberships(person.member, "test reassignment"))

        self.assertEqual(frappe.db.get_value("Chapter Board Member", row, "is_active"), 0, "row ended")
        self._assert_withdrawn_1953(person.user)

    def test_moving_a_row_to_another_volunteer_withdraws_the_previous_holder(self):
        """The row's ``volunteer`` is editable, so an update can unseat someone other than
        the row's current volunteer."""
        first = self._person_1953("First")
        second = self._person_1953("Second")
        row = self._seat_1953(first)
        self._assert_seated_1953(first.user)

        doc = frappe.get_doc("Chapter Board Member", row)
        doc.volunteer = second.volunteer
        doc.email = second.email
        doc.save()

        self._assert_withdrawn_1953(first.user)
        self._assert_seated_1953(second.user, "the new holder is seated")

    # ------------------------------------------------------------------ controls

    def test_a_second_active_seat_keeps_the_role_and_profile_on_deactivate_and_delete(self):
        """Control with a REAL second seat in another chapter (the wrong fix is an
        unconditional withdrawal)."""
        other_chapter = self.create_test_chapter(
            chapter_name=f"Row1953b {frappe.generate_hash(length=6)}", postal_codes="5000-5999", published=1
        )
        for label, end in (("Keep1", self._deactivate_1953), ("Keep2", lambda r: frappe.delete_doc("Chapter Board Member", r))):
            person = self._person_1953(label)
            first = self._seat_1953(person)
            second = self._seat_1953(person, chapter=other_chapter)
            self.assertEqual(frappe.db.count("Chapter Board Member", {"volunteer": person.volunteer, "is_active": 1}), 2)

            end(first)

            self.assertTrue(frappe.db.exists("Chapter Board Member", second) and frappe.db.get_value("Chapter Board Member", second, "is_active"))
            self._assert_seated_1953(person.user, "still seated on the other board")

    def test_an_unrelated_edit_of_a_live_row_keeps_the_access_and_runs_no_flush(self):
        """The changed-fields gate: a notes-only edit must not flush (no User saves, no locks)."""
        from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
            ChapterBoardMember,
        )

        person = self._person_1953("Notes")
        row = self._seat_1953(person)
        doc = frappe.get_doc("Chapter Board Member", row)
        doc.notes = "just a note"
        # Mock justified: wraps= counts the real calls; behaviour unchanged.
        with mock.patch.object(
            ChapterBoardMember, "_flush_board_access_for", autospec=True, side_effect=ChapterBoardMember._flush_board_access_for
        ) as flush:
            doc.save()
        flush.assert_not_called()
        self._assert_seated_1953(person.user)

        doc = frappe.get_doc("Chapter Board Member", row)
        doc.chapter_role = self._chapter_role_1953("Treasurer")
        with mock.patch.object(
            ChapterBoardMember, "_flush_board_access_for", autospec=True, side_effect=ChapterBoardMember._flush_board_access_for
        ) as flush:
            doc.save()
        self.assertEqual(flush.call_count, 1, "control: a role change does flush")

    def test_an_orphan_row_stays_deletable_and_editable_and_its_holder_loses_access(self):
        """Probe shortcut: the row is orphaned by pointing ``parent`` at a missing Chapter with
        ``db.set_value`` (what a Chapter deletion leaves behind)."""
        for label, end in (
            ("Orph1", lambda r: frappe.delete_doc("Chapter Board Member", r)),
            ("Orph2", self._deactivate_1953),
        ):
            person = self._person_1953(label)
            row = self._seat_1953(person)
            self._assert_seated_1953(person.user)
            frappe.db.set_value(
                "Chapter Board Member", row, "parent", f"Gone {frappe.generate_hash(length=6)}",
                update_modified=False,
            )

            end(row)

            self._assert_withdrawn_1953(person.user)
            if label == "Orph1":
                self.assertFalse(frappe.db.exists("Chapter Board Member", row), "the orphan row is gone")

    def test_a_failed_withdrawal_is_not_swallowed_by_the_assignment_service(self):
        """The failure is injected BELOW every swallowing layer (BoardManager._log_or_reraise
        and the service's per-row except): the two manager steps do nothing, so the real
        post-condition raises BoardAccessWithdrawalError, which must reach the caller."""
        from verenigingen.services.chapter.chapter_assignment_service import ChapterAssignmentService
        from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

        person = self._person_1953("Fail")
        self._seat_1953(person)
        base = "verenigingen.verenigingen.doctype.chapter.managers.board_manager.BoardManager."
        # Mock justified: removes the real withdrawal at the manager boundary to force the failure.
        with mock.patch(base + "_sync_role_profile_for_volunteer"), mock.patch(
            base + "_withdraw_board_role_if_unseated"
        ):
            with self.assertRaises(BoardAccessWithdrawalError):
                ChapterAssignmentService()._cleanup_board_memberships(person.member, "test")

        # The direct call above ended `row` before raising; the reassignment gets its own seat.
        other = self._person_1953("Fail2")
        other_row = self._seat_1953(other)
        with mock.patch(base + "_sync_role_profile_for_volunteer"), mock.patch(
            base + "_withdraw_board_role_if_unseated"
        ):
            result = ChapterAssignmentService().assign_with_cleanup(other.member, self.chapter.name)
        self.assertFalse(result["success"], f"the reassignment reports the failure: {result}")
        self.assertEqual(
            frappe.db.get_value("Chapter Board Member", other_row, "is_active"), 1, "ending rolled back with it"
        )
        self._assert_seated_1953(other.user, "access untouched when the withdrawal failed")

    def test_a_deadlock_during_the_withdrawal_propagates_from_the_assignment_service(self):
        from verenigingen.services.chapter.chapter_assignment_service import ChapterAssignmentService

        person = self._person_1953("Dead")
        self._seat_1953(person)
        base = "verenigingen.verenigingen.doctype.chapter.managers.board_manager.BoardManager."
        # Mock justified: injects a MariaDB 1213 at the manager boundary.
        with mock.patch(base + "_withdraw_board_role_if_unseated", side_effect=frappe.QueryDeadlockError):
            with self.assertRaises(frappe.QueryDeadlockError):
                ChapterAssignmentService()._cleanup_board_memberships(person.member, "test")

    def test_a_staffer_keeps_staff_when_the_standalone_seat_ends(self):
        """#1969: Staff (via a staff Team) is a second profile beside the seat's; ending the seat
        takes the board profile and role and leaves Staff and its roles."""
        from verenigingen.setup import create_default_team_roles

        person = self._person_1953("Staffer")
        sync_user_role_profile(person.user)
        create_default_team_roles()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"S1953 Staff {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "default_role_profile": STAFF,
                "is_association_wide": 1,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        team.append(
            "team_members",
            {"volunteer": person.volunteer, "team_role": "Team Member", "from_date": frappe.utils.today(), "status": "Active"},
        )
        team.save()
        sync_user_role_profile(person.user)
        row = self._seat_1953(person)
        self.assertEqual(set(get_user_role_profiles(person.user)), {STAFF, PROFILE_BOARD_MEMBER}, "fixture")

        self._deactivate_1953(row)

        self.assertEqual(get_user_role_profiles(person.user), [STAFF])
        self.assertNotIn(BOARD_ROLE, self._roles_1953(person.user))
        staff_roles = {r.role for r in frappe.get_doc("Role Profile", STAFF).roles}
        self.assertLessEqual(staff_roles, self._roles_1953(person.user), "Staff's roles intact")
