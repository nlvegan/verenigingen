"""#2540: ending a volunteer's last seat through a Chapter save must derive Volunteer.status.

Real flows only: the seat is added by a Chapter save and ended by
``BoardManager.remove_board_member`` (-> Chapter save). Nothing writes an assignment row
directly. Probe shortcuts are named in the docstring of the test that uses one.

Helper names carry the issue number on purpose: the duplicate-helper clone-family baseline
keys on the bare name, and generic ones (``_seat``, ``_status``) already have families.
"""

import inspect
from unittest import mock

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

FAILURE_TITLE_2540 = "Chapter Manager Error: Failed to refresh volunteer status"


class TestVolunteerStatusAfterSeatEnd2540(VereningingenTestCase):
    def _role_2540(self):
        name = f"Role2540 {frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _volunteer_2540(self):
        member = self.create_test_member(
            first_name="Seat", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        return self.create_test_volunteer(member_name=member.name)

    def _chapter_2540(self):
        return self.create_test_chapter(
            chapter_name=f"Ch2540 {frappe.generate_hash(length=6)}", postal_codes="7000-7999", published=1
        )

    def _seat_2540(self, chapter, volunteer, role):
        chapter = frappe.get_doc("Chapter", chapter.name)
        self.add_board_member_to_chapter(chapter, volunteer, role)

    def _end_2540(self, chapter, volunteer):
        chapter = frappe.get_doc("Chapter", chapter.name)
        result = chapter.board_manager.remove_board_member(volunteer.name, notify=False)
        self.assertTrue(result["success"], result)

    def _change_role_2540(self, chapter, volunteer, new_role):
        chapter = frappe.get_doc("Chapter", chapter.name)
        for row in chapter.board_members:
            if row.volunteer == volunteer.name and row.is_active:
                row.chapter_role = new_role
        chapter.save()

    def _status_2540(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def _live_seat_2540(self, volunteer):
        return frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1})

    def test_ending_the_only_board_seat_makes_the_volunteer_inactive(self):
        chapter, volunteer, role = self._chapter_2540(), self._volunteer_2540(), self._role_2540()
        self._seat_2540(chapter, volunteer, role)
        self.assertEqual(self._status_2540(volunteer), "Active", "control: seating derives Active")

        self._end_2540(chapter, volunteer)

        self.assertFalse(self._live_seat_2540(volunteer), "fixture: the seat really ended")
        self.assertEqual(self._status_2540(volunteer), "Inactive")

    def test_a_volunteer_with_a_seat_in_another_chapter_stays_active(self):
        """Control: ending seat A must not demote a volunteer who still holds seat B."""
        chapter_a, chapter_b = self._chapter_2540(), self._chapter_2540()
        volunteer, role = self._volunteer_2540(), self._role_2540()
        self._seat_2540(chapter_a, volunteer, role)
        self._seat_2540(chapter_b, volunteer, role)

        self._end_2540(chapter_a, volunteer)

        self.assertTrue(
            frappe.db.exists(
                "Chapter Board Member", {"parent": chapter_b.name, "volunteer": volunteer.name, "is_active": 1}
            ),
            "fixture: the other seat is live",
        )
        self.assertEqual(self._status_2540(volunteer), "Active")

    def _manual_status_case_2540(self, status, action):
        """Probe shortcut: the manual status is written with ``db.set_value`` after seating
        (a Retired volunteer cannot be seated, and Onboarding has no production writer
        short of full activation). The seat itself is real; ``action`` ends it or changes
        its role through a Chapter save."""
        chapter, volunteer, role = self._chapter_2540(), self._volunteer_2540(), self._role_2540()
        self._seat_2540(chapter, volunteer, role)
        frappe.db.set_value("Volunteer", volunteer.name, "status", status)
        self.assertEqual(self._status_2540(volunteer), status, "fixture")

        action(chapter, volunteer)

        self.assertEqual(self._status_2540(volunteer), status, f"{status} is not the derivation's to move")
        return chapter, volunteer

    def test_a_retired_volunteer_keeps_retired_when_the_seat_ends(self):
        chapter, volunteer = self._manual_status_case_2540("Retired", self._end_2540)
        self.assertFalse(self._live_seat_2540(volunteer), "fixture: the seat really ended")

    def test_a_retired_volunteer_keeps_retired_when_the_seat_role_changes(self):
        new_role = self._role_2540()
        self._manual_status_case_2540("Retired", lambda c, v: self._change_role_2540(c, v, new_role))

    def test_an_onboarding_volunteer_keeps_onboarding_when_the_seat_ends(self):
        chapter, volunteer = self._manual_status_case_2540("Onboarding", self._end_2540)
        self.assertFalse(self._live_seat_2540(volunteer), "fixture: the seat really ended")

    def test_an_onboarding_volunteer_keeps_onboarding_when_the_seat_role_changes(self):
        new_role = self._role_2540()
        self._manual_status_case_2540("Onboarding", lambda c, v: self._change_role_2540(c, v, new_role))

    # ------------------------------------------------------------------ failure path

    def _raise_only_from_the_flush_2540(self, error):
        """Wrap the real refresh; raise ``error`` only when called from the on_update flush,
        so the validate-time refreshes behave as on develop."""
        real = AssignmentHistoryManager.refresh_volunteer_status

        def fake(volunteer_id):
            if any(f.function == "flush_pending_board_profile_syncs" for f in inspect.stack()):
                raise error
            return real(volunteer_id)

        return mock.patch.object(AssignmentHistoryManager, "refresh_volunteer_status", side_effect=fake)

    def test_a_failing_refresh_is_logged_once_and_does_not_block_the_save(self):
        self.expectErrorLog(FAILURE_TITLE_2540)
        chapter, volunteer, role = self._chapter_2540(), self._volunteer_2540(), self._role_2540()
        self._seat_2540(chapter, volunteer, role)
        before = frappe.db.count("Error Log", {"method": FAILURE_TITLE_2540})

        # Mock justified: injects a failure at the on_update refresh only.
        with self._raise_only_from_the_flush_2540(frappe.ValidationError("injected 2540")):
            self._end_2540(chapter, volunteer)

        self.assertFalse(self._live_seat_2540(volunteer), "the Chapter save went through")
        self.assertEqual(frappe.db.count("Error Log", {"method": FAILURE_TITLE_2540}) - before, 1)

    def test_a_deadlock_in_the_refresh_reraises(self):
        chapter, volunteer, role = self._chapter_2540(), self._volunteer_2540(), self._role_2540()
        self._seat_2540(chapter, volunteer, role)
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        row = next(r for r in chapter_doc.board_members if r.volunteer == volunteer.name)
        row.is_active = 0
        row.to_date = today()

        # Mock justified: injects the non-resumable DB error at the on_update refresh only.
        with self._raise_only_from_the_flush_2540(frappe.QueryDeadlockError()):
            with self.assertRaises(frappe.QueryDeadlockError):
                chapter_doc.save()


class TestVolunteerStatusAfterTeamSeatEnd2540(VereningingenTestCase):
    """Control for the Team path: it is eventually consistent, and correct once the
    after-commit job has run.

    ``Team.on_update`` emits ``team_membership_changed`` (enqueued after commit) and the
    subscriber ``handle_assignment_history_updates`` completes the entry when the Team
    Member row is already persisted, so ``has_current_assignment`` reads the truth. These
    tests call the subscriber BY HAND after the Team save: the job does not run inline
    under the test runner and CI has no workers, so they prove the subscriber's outcome,
    not that the job is delivered."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def _volunteer_team_2540(self):
        member = self.create_test_member(
            first_name="TeamSeat", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        return self.create_test_volunteer(member_name=member.name)

    def _team_with_2540(self, *volunteers):
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Team2540 {frappe.generate_hash(length=8)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
                "description": "2540",
            }
        )
        for volunteer in volunteers:
            team.append(
                "team_members",
                {
                    "volunteer": volunteer.name,
                    "volunteer_name": volunteer.volunteer_name,
                    "team_role": "Team Member",
                    "role_type": "Team Member",
                    "role": "Helper",
                    "from_date": today(),
                    "is_active": 1,
                    "status": "Active",
                },
            )
        team.insert()
        self.track_doc("Team", team.name)
        return team

    def _end_row_2540(self, team, volunteer):
        team.reload()
        for row in team.team_members:
            if row.volunteer == volunteer.name:
                row.is_active = 0
                row.status = "Inactive"
                row.to_date = today()
        team.save()
        from verenigingen.events.subscribers.team_subscribers import handle_assignment_history_updates

        row = next(r for r in team.team_members if r.volunteer == volunteer.name)
        handle_assignment_history_updates(
            "team_membership_changed",
            {
                "team": team.name,
                "volunteer": volunteer.name,
                "action": "removed",
                "old_role": "Team Member",
                "from_date": row.from_date,
                "row_name": row.name,
                "to_date": today(),
            },
        )

    def _status_team_2540(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def test_ending_the_only_team_seat_makes_the_volunteer_inactive_once_the_job_ran(self):
        volunteer = self._volunteer_team_2540()
        team = self._team_with_2540(volunteer)
        self.assertEqual(self._status_team_2540(volunteer), "Active", "control: joining derives Active")

        self._end_row_2540(team, volunteer)

        self.assertFalse(
            frappe.db.exists("Team Member", {"volunteer": volunteer.name, "is_active": 1}),
            "fixture: the seat really ended",
        )
        self.assertEqual(
            frappe.db.get_value(
                "Volunteer Assignment",
                {"parent": volunteer.name, "reference_doctype": "Team", "reference_name": team.name},
                "status",
            ),
            "Completed",
            "fixture: the history entry was completed by the subscriber",
        )
        self.assertEqual(self._status_team_2540(volunteer), "Inactive")

    def test_a_volunteer_in_another_team_stays_active(self):
        volunteer = self._volunteer_team_2540()
        team_a, team_b = self._team_with_2540(volunteer), self._team_with_2540(volunteer)

        self._end_row_2540(team_a, volunteer)

        self.assertTrue(
            frappe.db.exists("Team Member", {"parent": team_b.name, "volunteer": volunteer.name, "is_active": 1})
        )
        self.assertEqual(self._status_team_2540(volunteer), "Active")
