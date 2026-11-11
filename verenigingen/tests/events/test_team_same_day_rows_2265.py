"""#2265: two Team Member rows of one volunteer with the same from_date.

The rows stay allowed (a volunteer may hold two roles from one start date; maintainer ruling
on #2265). Team's membership events, member snapshots and the volunteer's assignment history
must therefore identify a row by its child-row NAME, never by (volunteer, from_date).

The saves go through the desk's own endpoint (``frappe.desk.form.save.savedocs``) and the
queued history job is run by hand with the kwargs a worker would receive (CI has no RQ
workers, this bench does), as in test_member_team_events_rollback.
"""

import json

import frappe
import frappe.desk.form.save
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase

HISTORY_JOB = "verenigingen.events.subscribers.team_subscribers.handle_assignment_history_updates"


class TestTeamSameDayRows2265(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._saved_flags = {
            k: getattr(frappe.flags, k, None)
            for k in ("in_import", "in_bulk_import", "bulk_team_operations", "in_test")
        }
        # The harness sets in_import (subscribers early-return) and in_test; production has neither.
        for k in self._saved_flags:
            setattr(frappe.flags, k, False)
        frappe.flags.skip_volunteer_account_creation = True
        self.volunteer = self.create_test_volunteer()
        suffix = frappe.generate_hash(length=6)
        self.member_role = self._make_role_2265(f"Same Day Member {suffix}", leader=0)
        self.leader_role = self._make_role_2265(f"Same Day Lead {suffix}", leader=1)
        self.start = add_days(today(), -10)
        self.team = self._insert(
            {
                "doctype": "Team",
                "team_name": f"Same Day Team {suffix}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": self.start,
                "description": "#2265 same-day rows",
                "team_members": [self._row(self.member_role), self._row(self.leader_role)],
            }
        )

    def tearDown(self):
        for k, v in self._saved_flags.items():
            setattr(frappe.flags, k, v)
        super().tearDown()

    def _insert(self, values):
        doc = frappe.get_doc(values).insert()
        self.track_doc(doc.doctype, doc.name)
        return doc

    def _make_role_2265(self, name, leader):
        # Not unique: both volunteers' rows must be able to coexist on any role.
        return self._insert(
            {
                "doctype": "Team Role",
                "role_name": name,
                "permissions_level": "Leader" if leader else "Basic",
                "is_team_leader": leader,
                "is_unique": 0,
                "is_active": 1,
            }
        )

    def _row(self, role):
        return {
            "volunteer": self.volunteer.name,
            "team_role": role.name,
            "from_date": self.start,
            "is_active": 1,
            "status": "Active",
        }

    def _desk_save(self, mutate):
        """Save the Team the way the desk form does: the whole doc as JSON via savedocs."""
        payload = frappe.get_doc("Team", self.team.name).as_dict()
        doc = json.loads(json.dumps(payload, default=str))
        mutate(doc)
        jobs = []
        real_enqueue = frappe.enqueue

        def recording_enqueue(*args, **kwargs):
            if str(kwargs.get("method", "")).startswith("verenigingen.events.subscribers."):
                jobs.append(kwargs)

        frappe.enqueue = recording_enqueue
        try:
            frappe.desk.form.save.savedocs(json.dumps(doc), "Save")
        finally:
            frappe.enqueue = real_enqueue
        return jobs

    def _run_history_jobs(self, jobs):
        for job in jobs:
            if job["method"] == HISTORY_JOB:
                frappe.call(
                    job["method"],
                    **{k: v for k, v in job.items() if k in ("event_name", "event_data", "is_bulk_import")},
                )

    def _history(self, status):
        return sorted(
            frappe.get_all(
                "Volunteer Assignment",
                filters={
                    "parent": self.volunteer.name,
                    "reference_doctype": "Team",
                    "reference_name": self.team.name,
                    "status": status,
                },
                pluck="role",
            )
        )

    def _row_named(self, doc, name):
        return next(r for r in doc["team_members"] if r["name"] == name)

    def _rows(self):
        return frappe.get_doc("Team", self.team.name).team_members

    def test_starting_history_has_one_active_entry_per_row(self):
        """Control for the fixture: insert records both rows."""
        self.assertEqual(
            self._history("Active"),
            sorted([self.member_role.role_name, self.leader_role.role_name]),
        )

    def test_changing_one_same_day_row_completes_that_rows_own_entry(self):
        row_a, row_b = self._rows()
        self.assertEqual(row_b.team_role, self.leader_role.name)

        def make_member(doc):
            self._row_named(doc, row_b.name)["team_role"] = self.member_role.name

        jobs = self._desk_save(make_member)
        events = [j["event_data"]["action"] for j in jobs if j["method"] == HISTORY_JOB]
        self.assertEqual(events, ["role_changed"], events)
        self._run_history_jobs(jobs)

        role = self.member_role.role_name
        self.assertEqual(self._history("Active"), [role, role])
        self.assertEqual(self._history("Completed"), [self.leader_role.role_name])

    def test_deactivating_one_same_day_row_completes_only_that_row(self):
        row_a, row_b = self._rows()

        def deactivate(doc):
            self._row_named(doc, row_b.name)["is_active"] = 0

        jobs = self._desk_save(deactivate)
        self._run_history_jobs(jobs)
        self.assertEqual(self._history("Active"), [self.member_role.role_name])
        self.assertEqual(self._history("Completed"), [self.leader_role.role_name])

    def test_removing_one_same_day_row_completes_only_that_row(self):
        row_a, row_b = self._rows()

        def remove(doc):
            doc["team_members"] = [r for r in doc["team_members"] if r["name"] != row_b.name]

        jobs = self._desk_save(remove)
        self._run_history_jobs(jobs)
        self.assertEqual(self._history("Active"), [self.member_role.role_name])
        self.assertEqual(self._history("Completed"), [self.leader_role.role_name])

    def test_row_names_are_stable_across_a_desk_resave(self):
        """The design keys on the child-row name: it must survive an unrelated desk save."""
        before = [r.name for r in self._rows()]
        self._desk_save(lambda doc: doc.update(description="changed"))
        self.assertEqual([r.name for r in self._rows()], before)

    def _history_links(self, status="Active"):
        return sorted(
            frappe.get_all(
                "Volunteer Assignment",
                filters={
                    "parent": self.volunteer.name,
                    "reference_doctype": "Team",
                    "reference_name": self.team.name,
                    "status": status,
                },
                pluck="reference_row",
            ),
            key=str,
        )

    def test_a_new_same_day_row_with_the_same_role_gets_its_own_entry(self):
        """Added from the desk, where the new row arrives as ``new-team-member-...``: the
        event must name the row by its stored name, and the entry is not deduplicated
        against the other row that holds the same role."""
        row_a, row_b = self._rows()

        def add_row(doc):
            doc["team_members"].append(
                {
                    "doctype": "Team Member",
                    "name": "new-team-member-1",
                    "__islocal": 1,
                    **{k: v for k, v in self._row(self.member_role).items()},
                    "parent": self.team.name,
                    "parentfield": "team_members",
                    "parenttype": "Team",
                }
            )

        jobs = self._desk_save(add_row)
        rows = self._rows()
        self.assertEqual(len(rows), 3)
        new_row = next(r for r in rows if r.name not in (row_a.name, row_b.name))
        history_events = [j["event_data"] for j in jobs if j["method"] == HISTORY_JOB]
        self.assertEqual([(e["action"], e["row_name"]) for e in history_events], [("added", new_row.name)])
        self._run_history_jobs(jobs)
        self.assertEqual(self._history_links(), sorted([row_a.name, row_b.name, new_row.name]))

    def test_two_same_day_rows_changed_in_one_save_queue_two_jobs(self):
        row_a, row_b = self._rows()

        def swap(doc):
            self._row_named(doc, row_a.name)["team_role"] = self.leader_role.name
            self._row_named(doc, row_b.name)["team_role"] = self.member_role.name

        jobs = self._desk_save(swap)
        history_jobs = [j for j in jobs if j["method"] == HISTORY_JOB]
        self.assertEqual(
            sorted(j["event_data"]["row_name"] for j in history_jobs), sorted([row_a.name, row_b.name])
        )
        # emit_event deduplicates on job_id: the two must not share one.
        self.assertEqual(len({j["job_id"] for j in history_jobs}), 2, [j["job_id"] for j in history_jobs])

    def test_an_entry_written_before_rows_were_recorded_is_claimed_not_duplicated(self):
        """Probe shortcut: the legacy shape (no reference_row) is made by clearing the column on
        the entries the insert wrote. Control: the two linked entries before the clear."""
        row_a, row_b = self._rows()
        self.assertEqual(self._history_links(), sorted([row_a.name, row_b.name]))
        frappe.db.sql(
            "update `tabVolunteer Assignment` set reference_row = NULL where parent = %s and reference_name = %s",
            (self.volunteer.name, self.team.name),
        )
        from verenigingen.services.team_service import TeamService

        team = frappe.get_doc("Team", self.team.name)
        TeamService().add_assignment_history(
            team, self.volunteer.name, row_a.team_role, row_a.from_date, row_name=row_a.name
        )
        self.assertEqual(len(self._history_links()), 2, "the legacy entry is claimed, not duplicated")
        self.assertIn(row_a.name, self._history_links())

    # ---- review round 1 (F1-F3) --------------------------------------------------------

    def _make_history_legacy(self):
        """Probe shortcut: the pre-#2265 shape (no reference_row) is made by clearing the
        column on the entries the insert wrote."""
        frappe.db.sql(
            "update `tabVolunteer Assignment` set reference_row = NULL where parent = %s and reference_name = %s",
            (self.volunteer.name, self.team.name),
        )
        self.assertEqual(self._history_links(), [None, None])

    def test_legacy_entries_a_changed_same_day_row_completes_the_entry_of_its_own_role(self):
        row_a, row_b = self._rows()
        self._make_history_legacy()

        def make_member(doc):
            self._row_named(doc, row_b.name)["team_role"] = self.member_role.name

        jobs = self._desk_save(make_member)
        self._run_history_jobs(jobs)

        role = self.member_role.role_name
        self.assertEqual(self._history("Active"), [role, role])
        self.assertEqual(self._history("Completed"), [self.leader_role.role_name])

    def test_legacy_entry_of_one_row_is_not_claimed_by_a_new_same_role_row(self):
        row_a, row_b = self._rows()
        self._make_history_legacy()

        def add_row(doc):
            doc["team_members"].append(
                {
                    "doctype": "Team Member",
                    "name": "new-team-member-1",
                    "__islocal": 1,
                    **self._row(self.member_role),
                    "parent": self.team.name,
                    "parentfield": "team_members",
                    "parenttype": "Team",
                }
            )

        jobs = self._desk_save(add_row)
        self._run_history_jobs(jobs)
        new_row = next(r for r in self._rows() if r.name not in (row_a.name, row_b.name))
        self.assertEqual(self._history_links(), sorted([None, None, new_row.name], key=str))

    def test_a_save_whose_rows_carry_no_names_changes_no_history(self):
        """An API/import-style rewrite of team_members gives every row a fresh name. Nothing
        about the membership changed, so nothing may be emitted or completed."""
        old_names = sorted(r.name for r in self._rows())

        def strip_names(doc):
            doc["description"] = "rewritten without row names"
            for row in doc["team_members"]:
                row.pop("name")

        jobs = self._desk_save(strip_names)
        new_rows = self._rows()
        self.assertNotEqual(sorted(r.name for r in new_rows), old_names, "fixture: rows really were renamed")
        self.assertEqual([j["event_data"]["action"] for j in jobs if j["method"] == HISTORY_JOB], [])
        self._run_history_jobs(jobs)
        self.assertEqual(self._history("Completed"), [])
        # The entries follow their rows to the new names.
        self.assertEqual(self._history_links(), sorted(r.name for r in new_rows))

    def test_a_job_queued_before_the_row_name_existed_still_changes_the_history(self):
        """Payload without row_name (queued before this deploy). One row only: a payload
        without a row cannot tell same-day rows apart, which is why the name exists."""
        team = self._insert(
            {
                "doctype": "Team",
                "team_name": f"Legacy Payload {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": self.start,
                "description": "#2265 pre-deploy payload",
                "team_members": [self._row(self.leader_role)],
            }
        )
        self.team = team
        row = self._rows()[0]
        jobs = self._desk_save(lambda doc: self._row_named(doc, row.name).update(team_role=self.member_role.name))
        for job in jobs:
            job["event_data"].pop("row_name", None)
        self._run_history_jobs(jobs)
        self.assertEqual(self._history("Active"), [self.member_role.role_name])
        self.assertEqual(self._history("Completed"), [self.leader_role.role_name])

    def test_a_nameless_rewrite_pairs_only_rows_of_the_same_role(self):
        """Control for the pairing: the unchanged row is paired (no event); the row whose role
        changed in the same nameless save has no twin, so it is read as removed + added, and
        the history still ends right."""
        row_a, row_b = self._rows()

        def rewrite(doc):
            for row in doc["team_members"]:
                if row["name"] == row_b.name:
                    row["team_role"] = self.member_role.name
                row.pop("name")

        jobs = self._desk_save(rewrite)
        events = sorted(
            (j["event_data"]["action"], j["event_data"].get("role") or j["event_data"].get("old_role"))
            for j in jobs
            if j["method"] == HISTORY_JOB
        )
        self.assertEqual(
            events,
            sorted([("added", self.member_role.name), ("removed", self.leader_role.name)]),
            events,
        )
        self._run_history_jobs(jobs)
        role = self.member_role.role_name
        self.assertEqual(self._history("Active"), [role, role])
        self.assertEqual(self._history("Completed"), [self.leader_role.role_name])
