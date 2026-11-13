"""#2540: ending a volunteer's last seat through a Chapter save must derive Volunteer.status.

Real flows only: the seat is added by a Chapter save and ended by
``BoardManager.remove_board_member`` (-> Chapter save). Nothing writes a status or an
assignment row directly, except where a test says so in its docstring.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerStatusAfterSeatEnd2540(VereningingenTestCase):
    def _role(self):
        name = f"Role2540 {frappe.generate_hash(length=8)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": name, "permissions_level": "Basic", "is_active": 1}
        ).insert()
        self.track_doc("Chapter Role", name)
        return name

    def _volunteer(self):
        member = self.create_test_member(
            first_name="Seat", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        return self.create_test_volunteer(member_name=member.name)

    def _chapter(self):
        return self.create_test_chapter(
            chapter_name=f"Ch2540 {frappe.generate_hash(length=6)}", postal_codes="7000-7999", published=1
        )

    def _seat(self, chapter, volunteer, role):
        chapter = frappe.get_doc("Chapter", chapter.name)
        self.add_board_member_to_chapter(chapter, volunteer, role)

    def _end(self, chapter, volunteer):
        chapter = frappe.get_doc("Chapter", chapter.name)
        result = chapter.board_manager.remove_board_member(volunteer.name, notify=False)
        self.assertTrue(result["success"], result)

    def _status(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def test_ending_the_only_board_seat_makes_the_volunteer_inactive(self):
        chapter, volunteer, role = self._chapter(), self._volunteer(), self._role()
        self._seat(chapter, volunteer, role)
        self.assertEqual(self._status(volunteer), "Active", "control: seating derives Active")

        self._end(chapter, volunteer)

        self.assertFalse(
            frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}),
            "fixture: the seat really ended",
        )
        self.assertEqual(self._status(volunteer), "Inactive")

    def test_a_volunteer_with_a_seat_in_another_chapter_stays_active(self):
        """Control: ending seat A must not demote a volunteer who still holds seat B."""
        chapter_a, chapter_b = self._chapter(), self._chapter()
        volunteer, role = self._volunteer(), self._role()
        self._seat(chapter_a, volunteer, role)
        self._seat(chapter_b, volunteer, role)

        self._end(chapter_a, volunteer)

        self.assertTrue(
            frappe.db.exists(
                "Chapter Board Member", {"parent": chapter_b.name, "volunteer": volunteer.name, "is_active": 1}
            ),
            "fixture: the other seat is live",
        )
        self.assertEqual(self._status(volunteer), "Active")


class TestVolunteerStatusAfterTeamSeatEnd2540(VereningingenTestCase):
    """The Team path has no ordering defect: the history completion is not run inside the
    Team save. ``Team.on_update`` emits ``team_membership_changed`` (enqueued after commit),
    and the subscriber ``handle_assignment_history_updates`` completes the entry when the
    Team Member row is already persisted, so ``has_current_assignment`` reads the truth.

    The subscriber is called in-process after the Team save, which stands in for the
    after-commit job (the row is persisted at that point in both cases)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def _volunteer(self):
        member = self.create_test_member(
            first_name="TeamSeat", last_name=f"V{frappe.generate_hash(length=6)}", birth_date="1985-01-01"
        )
        return self.create_test_volunteer(member_name=member.name)

    def _team_with(self, *volunteers):
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

    def _end_row(self, team, volunteer):
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

    def _status(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def test_ending_the_only_team_seat_makes_the_volunteer_inactive(self):
        volunteer = self._volunteer()
        team = self._team_with(volunteer)
        self.assertEqual(self._status(volunteer), "Active", "control: joining derives Active")

        self._end_row(team, volunteer)

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
            "fixture: the history entry was completed by the real subscriber",
        )
        self.assertEqual(self._status(volunteer), "Inactive")

    def test_a_volunteer_in_another_team_stays_active(self):
        volunteer = self._volunteer()
        team_a, team_b = self._team_with(volunteer), self._team_with(volunteer)

        self._end_row(team_a, volunteer)

        self.assertTrue(frappe.db.exists("Team Member", {"parent": team_b.name, "volunteer": volunteer.name, "is_active": 1}))
        self.assertEqual(self._status(volunteer), "Active")
