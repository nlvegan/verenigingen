# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Volunteer.status derived from assignments, and the Retired guard (#705).

Decided by the repo owner, 2026-08-31:

    "Assignment should drive status. Retired should only be set manually."
    "New should only be for volunteers with zero historical or current team,
     board or movement roles."
    "Retired must not be settable while the volunteer still has active assignments."

The state machine that implies, and who owns each value:

    New          zero assignment rows, ever                     derived
    Active       at least one CURRENT assignment                derived
    Inactive     had assignments, none current now              derived, and termination
    Retired      manual only -- the derivation never writes or overwrites it
    Onboarding   no writer exists; the derivation leaves it alone

"Current" is `Volunteer Assignment.status in (Active, Paused, On Hold)`. Paused and
On Hold count: the role is still held, the person has not given it up. Only Completed
and Cancelled release the seat.

WHY THESE TESTS DRIVE THE REAL WRITE PATH RATHER THAN Volunteer.save()

`Volunteer.update_status()` has existed since long before this issue, and it already
derived Active from assignments. It never worked, for two reasons this file pins:

1. It only ratcheted UPWARD, and only out of "New" (`if not self.status or
   self.status == "New"`), so it could never move a volunteer down.
2. It runs in `Volunteer.before_save`, but assignments are written by
   `AssignmentHistoryManager` through `safe_child_table_update()` ->
   `update_child_table()`, which writes the child rows ONLY. The parent's
   validate / before_save / on_update never run. So seating someone never
   reached the derivation at all.

A test that calls `volunteer.save()` by hand would therefore pass against the OLD
code and prove nothing. Every derivation test below goes through
`AssignmentHistoryManager`, which is the single chokepoint every real seating path
uses (team_service, board_manager, volunteer_integration_manager, chapter.py).
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

CURRENT_ASSIGNMENT_STATUSES = ["Active", "Paused", "On Hold"]
CLOSED_ASSIGNMENT_STATUSES = ["Completed", "Cancelled"]


class _VolunteerFixtures:
    """Shared fixtures. A mixin, NOT a base test class: subclassing a TestCase to
    reuse its helpers re-runs every one of its tests in each subclass."""

    def _chapter(self):
        """A real Chapter -- Volunteer Assignment.reference_name is a Dynamic Link
        and is validated, so an invented name raises LinkValidationError."""
        if not getattr(self, "_chapter_doc", None):
            self._chapter_doc = self.create_test_chapter()
        return self._chapter_doc.name

    def _board_role(self):
        """A Chapter Role for a board seat.

        Chapter Role is `autoname: field:role_name`, so the name is a GLOBAL unique
        key -- a fixed name collides with any other test in the shard that wants one.
        Per-test unique name instead.
        """
        if not getattr(self, "_board_role_name", None):
            role = self.factory.ensure_chapter_role(
                f"TestBoardRole-{frappe.generate_hash(length=8)}", {"permissions_level": "Basic"}
            )
            self.factory.track_document("Chapter Role", role.name)
            self._board_role_name = role.name
        return self._board_role_name

    def _volunteer(self, status="New"):
        """A Volunteer with a Member and no assignments.

        The factory defaults Volunteer.status to "Active", which is fiction for a
        volunteer holding nothing; these tests state the starting status explicitly
        rather than inheriting it.
        """
        run = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Deriv", last_name=f"V{run[:6]}", birth_date="1985-01-01"
        )
        volunteer = self.create_test_volunteer(member_name=member.name)
        volunteer.db_set("status", status)
        volunteer.reload()
        return volunteer

    def _seat(self, volunteer, role="Secretary", reference_name=None):
        """Add an assignment through the real chokepoint, not by appending a row."""
        result = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=reference_name or self._chapter(),
            role=role,
            start_date=today(),
        )
        self.assertTrue(result, "the assignment write itself failed, so this test proves nothing")
        volunteer.reload()
        return volunteer

    def _status(self, volunteer):
        return frappe.db.get_value("Volunteer", volunteer.name, "status")

    def _set_assignment_status(self, volunteer, status):
        """Force every assignment row to `status` and re-run the derivation.

        Writes the child rows directly and then re-saves the parent, because the
        point under test is what the DERIVATION computes from a given set of rows,
        not how those rows got there.
        """
        for row in volunteer.assignment_history:
            frappe.db.set_value("Volunteer Assignment", row.name, "status", status)
        volunteer.reload()
        volunteer.save()
        volunteer.reload()
        return volunteer


class TestVolunteerStatusDerivation(_VolunteerFixtures, EnhancedTestCase):
    """Status follows assignments, through the path that actually writes them."""

    # ------------------------------------------------------------------ derived

    def test_a_volunteer_who_never_held_a_role_is_left_alone(self):
        """The derivation is EVENT-DRIVEN, not a recompute-from-scratch.

        The rule -- "New should only be for volunteers with zero historical or
        current roles" -- constrains what New may stick to. It does not say every
        volunteer without an assignment row must be demoted TO New, and reading it
        that way is actively wrong here: `volunteer_activation_service` sets Active
        deliberately when a reviewer ticks "activate as volunteer" during
        application review, and those volunteers hold no assignment row at all.
        A pure recompute would silently demote every one of them on their next
        save, and drop them out of the many production queries that filter
        `v.status = 'Active'`.

        So: assignments MOVE status when there is assignment evidence, and a
        volunteer with no evidence either way keeps what they were given.
        """
        for status in ("New", "Active", "Inactive"):
            with self.subTest(status=status):
                volunteer = self._volunteer(status=status)

                volunteer.reload()
                volunteer.note = "unrelated edit"
                volunteer.save()

                self.assertEqual(
                    status,
                    self._status(volunteer),
                    "A volunteer holding no assignment at all was reclassified. The "
                    "derivation must not demote a manually-activated volunteer.",
                )

    def test_being_seated_makes_the_volunteer_active(self):
        """The core regression: seating alone must move status, with no Volunteer save.

        This is the veg11 case -- a volunteer holding a board seat and three
        assignment rows who still read "New" because nothing ever re-saved them.
        """
        volunteer = self._volunteer()
        self.assertEqual("New", self._status(volunteer))

        self._seat(volunteer)

        self.assertEqual(
            "Active",
            self._status(volunteer),
            "Seating a volunteer did not advance status. The assignment write goes "
            "through update_child_table(), which does not run the parent's hooks, so "
            "the derivation has to be invoked by AssignmentHistoryManager itself.",
        )

    def test_losing_the_last_current_assignment_makes_the_volunteer_inactive(self):
        """Not New -- the rule is 'zero historical OR current roles' for New."""
        volunteer = self._seat(self._volunteer())
        self.assertEqual("Active", self._status(volunteer))

        AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=volunteer.assignment_history[0].reference_name,
            role=volunteer.assignment_history[0].role,
            start_date=volunteer.assignment_history[0].start_date,
            end_date=today(),
        )
        volunteer.reload()

        self.assertEqual(
            "Inactive",
            self._status(volunteer),
            "A volunteer whose only assignment ended is not New -- they have a history.",
        )

    def test_paused_and_on_hold_still_count_as_held(self):
        """Each assignment status, against the decided definition of 'current'."""
        for assignment_status in CURRENT_ASSIGNMENT_STATUSES + CLOSED_ASSIGNMENT_STATUSES:
            with self.subTest(assignment_status=assignment_status):
                volunteer = self._seat(self._volunteer())
                self._set_assignment_status(volunteer, assignment_status)

                expected = "Active" if assignment_status in CURRENT_ASSIGNMENT_STATUSES else "Inactive"
                self.assertEqual(
                    expected,
                    self._status(volunteer),
                    f"An assignment in status {assignment_status!r} was treated as the "
                    "wrong side of 'current'.",
                )

    def test_the_derivation_never_overwrites_retired(self):
        """Retired is manual and terminal. A stale Active row must not undo it."""
        volunteer = self._seat(self._volunteer())
        # Close the seat so the volunteer can legally be retired, then retire them.
        self._set_assignment_status(volunteer, "Completed")
        volunteer.reload()
        volunteer.status = "Retired"
        volunteer.save()
        self.assertEqual("Retired", self._status(volunteer))

        # A later save must not recompute them to Inactive.
        volunteer.reload()
        volunteer.note = "unrelated edit"
        volunteer.save()

        self.assertEqual(
            "Retired",
            self._status(volunteer),
            "The derivation overwrote a manually-set Retired.",
        )

    def test_the_derivation_leaves_onboarding_alone(self):
        """Onboarding has no writer; nothing here should start producing or clobbering it."""
        volunteer = self._volunteer(status="Onboarding")

        volunteer.reload()
        volunteer.note = "unrelated edit"
        volunteer.save()

        self.assertEqual("Onboarding", self._status(volunteer))


class TestRetiredGuard(_VolunteerFixtures, EnhancedTestCase):
    """Retired must not be settable while the volunteer still holds a current role."""

    def test_retiring_a_seated_volunteer_is_refused(self):
        """And the refusal must BLOCK THE WRITE, not merely raise.

        `validate_volunteer_age` caught its own frappe.throw in a broad
        `except Exception` for months and therefore never blocked a save (#658), so
        asserting the exception is not enough -- this reads the row back.
        """
        volunteer = self._seat(self._volunteer())
        self.assertEqual("Active", self._status(volunteer))

        volunteer.reload()
        volunteer.status = "Retired"
        with self.assertRaises(frappe.ValidationError):
            volunteer.save()

        self.assertNotEqual(
            "Retired",
            self._status(volunteer),
            "The guard raised but the row was still written -- the throw is being "
            "swallowed, or it fires after the write.",
        )

    def test_retiring_a_volunteer_whose_roles_have_all_ended_is_allowed(self):
        """CONTROL: proves the guard discriminates rather than blocking all retirement."""
        volunteer = self._seat(self._volunteer())
        self._set_assignment_status(volunteer, "Completed")

        volunteer.reload()
        volunteer.status = "Retired"
        volunteer.save()

        self.assertEqual("Retired", self._status(volunteer))

    def test_paused_and_on_hold_also_block_retirement(self):
        """The same definition of 'current' the derivation uses, applied to the guard."""
        for assignment_status in CURRENT_ASSIGNMENT_STATUSES:
            with self.subTest(assignment_status=assignment_status):
                volunteer = self._seat(self._volunteer())
                self._set_assignment_status(volunteer, assignment_status)

                volunteer.reload()
                volunteer.status = "Retired"
                with self.assertRaises(frappe.ValidationError):
                    volunteer.save()

    def test_seating_a_retired_volunteer_is_refused(self):
        """The mirror of the guard, per the repo owner's decision: block it.

        Un-retiring is a deliberate two-step (change status, then assign), which is
        the only option consistent with Retired being manual and terminal.
        """
        volunteer = self._seat(self._volunteer())
        self._set_assignment_status(volunteer, "Completed")
        volunteer.reload()
        volunteer.status = "Retired"
        volunteer.save()
        self.assertEqual("Retired", self._status(volunteer))

        before = len(frappe.get_doc("Volunteer", volunteer.name).assignment_history)
        result = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Team",
            reference_doctype="Chapter",
            reference_name=self._chapter(),
            role="Coordinator",
            start_date=today(),
        )

        self.assertFalse(result, "seating a Retired volunteer was accepted")
        self.assertEqual(
            before,
            len(frappe.get_doc("Volunteer", volunteer.name).assignment_history),
            "the assignment row was written despite the refusal",
        )
        self.assertEqual("Retired", self._status(volunteer))


class TestTerminationClosesAssignments(_VolunteerFixtures, EnhancedTestCase):
    """Termination must close the seats, or the derivation reactivates the volunteer."""

    def test_termination_closes_current_assignments(self):
        """Termination sets status Inactive; if the rows stay open the derivation
        computes the volunteer straight back to Active on the next save.

        Decided by the repo owner: termination closes the assignments, so
        derived-Inactive and termination-Inactive agree and no carve-out is needed.
        """
        from verenigingen.services.termination.termination_integration import (
            terminate_volunteer_records_safe,
        )

        volunteer = self._seat(self._volunteer())
        self.assertEqual("Active", self._status(volunteer))

        terminate_volunteer_records_safe(
            volunteer.member, "Voluntary", today(), "test termination"
        )
        volunteer.reload()

        self.assertEqual(
            [],
            [r.status for r in volunteer.assignment_history if r.status in CURRENT_ASSIGNMENT_STATUSES],
            "Termination left current assignment rows open.",
        )
        self.assertEqual("Inactive", self._status(volunteer))

        # And it must STAY Inactive through a later save -- the actual failure mode.
        volunteer.reload()
        volunteer.note = "a later unrelated edit"
        volunteer.save()
        self.assertEqual(
            "Inactive",
            self._status(volunteer),
            "A stale assignment row reactivated a terminated volunteer.",
        )


class TestDerivationCannotResurrectATerminatedVolunteer(_VolunteerFixtures, EnhancedTestCase):
    """A REAL Chapter Board Member seat, which the assignment_history tests never create.

    Found by a skeptical review, which reproduced it rather than reading for it. The
    first version of this fix closed only `assignment_history` rows on termination and
    claimed in a comment that the Chapter Board Member rows the derivation also consults
    were "already deactivated by the time this runs, because EndBoardPositionsOperation
    runs earlier in the operation list".

    That claim was wrong. `EndBoardPositionsOperation.enabled =
    termination_request.end_board_positions` -- a user-facing checkbox -- and
    `end_board_positions_safe()` additionally swallows a failure on any single position.
    So the seat can still read is_active=1, and a full derivation computed the volunteer
    straight back to "Active" two lines after termination set them Inactive: a terminated
    volunteer reading Active, which is worse than the bug being fixed.

    The class-level lesson is that `test_termination_closes_current_assignments` seats
    only through AssignmentHistoryManager, so it could not see this no matter how it was
    asserted -- the scenario its own docstring names was the one it could not reach.
    """

    def test_a_live_board_seat_does_not_reactivate_a_terminated_volunteer(self):
        from verenigingen.services.termination.termination_integration import (
            terminate_volunteer_records_safe,
        )

        volunteer = self._volunteer(status="Active")
        chapter = frappe.get_doc("Chapter", self._chapter())
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": self._board_role(),
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter.save()

        # CONTROL: the seat must really be live, or this test proves nothing -- it
        # would pass just as happily against a volunteer holding no seat at all.
        self.assertTrue(
            frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}),
            "control failed: no live board seat was created",
        )

        # end_board_positions is OFF, so nothing clears that seat. This is the
        # operator's explicit choice and termination must still stick.
        terminate_volunteer_records_safe(volunteer.member, "Voluntary", today(), "test termination")

        self.assertEqual("Inactive", self._status(volunteer))
        self.assertTrue(
            frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}),
            "the seat was closed after all, so this test no longer covers the case it "
            "exists for -- re-read the docstring before deleting it",
        )

        # The failure mode is the LATER save, once the in-memory doc is gone.
        volunteer.reload()
        volunteer.note = "a later unrelated edit"
        volunteer.save()

        self.assertEqual(
            "Inactive",
            self._status(volunteer),
            "A live board seat promoted a terminated volunteer back to Active. An "
            "ordinary save must never promote out of Inactive.",
        )


class TestSeatingDoesNotQueueAccountCreation(_VolunteerFixtures, EnhancedTestCase):
    """The status refresh must not switch on volunteer account provisioning (#705).

    Also from the skeptical review. Before #705 `_check_auto_activation` was dead for
    the case it was written for, because nothing save()d the Volunteer after a seating.
    Adding that save makes it reachable on every board/team seating, and the review
    measured one Account Creation Request created per first-time seating.

    That is not just an extra row: `ACR.queue_processing()` calls `frappe.db.commit()`
    unless `frappe.flags.in_test`, so the commit is invisible to this entire suite and
    live in production -- inside callers that hold savepoints and FOR UPDATE locks.
    Enabling that provisioning may be right, but it is a separate decision, not a side
    effect of a status fix.

    This test can still see the ACR itself, which is what makes it worth writing: the
    row is created in test mode even though the commit is not.
    """

    def test_seating_a_volunteer_creates_no_account_creation_request(self):
        volunteer = self._volunteer(status="New")

        before = frappe.db.count("Account Creation Request", {"source_record": volunteer.member})
        self._seat(volunteer)

        # CONTROL: the seating must actually have moved the status, or the save under
        # test never happened and the assertion below is vacuous.
        self.assertEqual("Active", self._status(volunteer), "control failed: the seating did nothing")

        self.assertEqual(
            before,
            frappe.db.count("Account Creation Request", {"source_record": volunteer.member}),
            "Seating a volunteer queued an Account Creation Request. That path commits "
            "in production (ACR.queue_processing, skipped under frappe.flags.in_test) "
            "and would destroy the savepoints its callers hold.",
        )
