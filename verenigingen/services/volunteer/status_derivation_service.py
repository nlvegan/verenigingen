"""
Volunteer status derivation.

Owns the rule that turns a volunteer's assignments into `Volunteer.status`, plus
the Retired guard that keeps the manual state from contradicting a held role.
Extracted from the Volunteer controller (#705) so the rule is independently
testable and the controller stays inside its size budget.

Two entry points, deliberately asymmetric -- see `update_status` and
`apply_assignment_derivation` for why.
"""

import frappe
from frappe import _

# An assignment counts as CURRENT while it is in one of these states: the role is
# still held. Decided by the repo owner 2026-08-31 -- Paused and On Hold count,
# because the volunteer has not given the seat up. Only Completed and Cancelled
# release it. Used by both the status derivation and the Retired guard, so the two
# cannot drift apart.
CURRENT_ASSIGNMENT_STATUSES = ("Active", "Paused", "On Hold")

# Statuses the derivation must never write over. Retired is manual and terminal;
# Onboarding has no production writer at all and is left as it is (#705).
MANUAL_STATUSES = ("Retired", "Onboarding")


class VolunteerStatusDerivationService:
    """Derives Volunteer.status from assignment evidence.

    Stateless: every method takes the Volunteer document it acts on, and mutates
    only `volunteer.status`. Persisting is the caller's job, so this can run inside
    `validate()` without a second write.
    """

    def validate_retired_has_no_current_assignment(self, volunteer):
        """Retired is manual and terminal, so it must not contradict a held role (#705).

        Deliberately NOT wrapped in try/except. `validate_volunteer_age` caught its
        own frappe.throw in a broad `except Exception` for months and therefore never
        blocked a single save (#658); a guard that logs instead of refusing is not a
        guard. The test for this reads the row back rather than only asserting that an
        exception was raised.
        """
        if volunteer.status != "Retired":
            return

        if self.has_current_assignment(volunteer):
            frappe.throw(
                _(
                    "This volunteer still holds a current assignment, so they cannot be "
                    "set to Retired. End their assignments first (an assignment counts as "
                    "current while its status is Active, Paused or On Hold)."
                ),
                title=_("Volunteer still has assignments"),
            )

    def update_status(self, volunteer):
        """Derive status from assignments on an ordinary save (#705).

            New       zero assignment rows, ever          derived
            Active    at least one CURRENT assignment     derived
            Inactive  had assignments, none current now   derived, and termination
            Retired   manual only -- never written here
            Onboarding no writer exists -- left alone

        EVENT-DRIVEN, not a recompute-from-scratch: a volunteer with no assignment
        evidence in either direction keeps the status they were given. That is
        deliberate -- `volunteer_activation_service` sets Active when a reviewer
        ticks "activate as volunteer" during application review, and those
        volunteers hold no assignment row at all. Recomputing from scratch would
        silently demote every one of them and drop them out of the production
        queries that filter `v.status = 'Active'`.

        AN ORDINARY SAVE NEVER PROMOTES OUT OF "Inactive". That asymmetry is the
        whole reason termination survives, and it was found by a skeptical review
        that reproduced the bug rather than reading for it:

            terminate_volunteer_records_safe() sets Inactive and then save()s.
            EndBoardPositionsOperation, which clears the Chapter Board Member rows
            this derivation also consults, is CONDITIONAL --
            `self.enabled = termination_request.end_board_positions`, a user-facing
            checkbox -- and end_board_positions_safe() additionally swallows a
            failure on any single position. So a board seat can still read
            is_active=1 here, and a full derivation would compute the volunteer
            straight back to "Active" two lines after termination set them Inactive.

        Closing the seat instead would override an explicit operator choice, and
        would mean writing Chapter child rows from inside volunteer termination.
        Refusing to promote on an ordinary save costs nothing real: a genuinely
        returning volunteer is promoted by the assignment write itself, through
        apply_assignment_derivation() below.

        The version before #705 only ratcheted UPWARD, and only out of "New", so it
        could never move a volunteer down. It also never ran on the path that
        matters: assignments are written through update_child_table(), which does
        not run the Volunteer document's hooks at all.
        """
        if not volunteer.status:
            volunteer.status = "New"

        # Retired is the repo owner's manual, terminal state; Onboarding has no
        # writer at all. Neither is the derivation's to overwrite.
        if volunteer.status in MANUAL_STATUSES:
            return

        if volunteer.status == "New" and self.has_current_assignment(volunteer):
            # Safe in this direction: termination leaves Inactive, never New.
            volunteer.status = "Active"
        elif (
            volunteer.status == "Active"
            and self.has_any_assignment(volunteer)
            and not self.has_current_assignment(volunteer)
        ):
            # Held a role, holds none now. Not "New" -- the rule reserves New for
            # volunteers with zero historical OR current roles. `has_any_assignment`
            # is required so a manually-activated volunteer with no rows at all is
            # left alone rather than demoted.
            volunteer.status = "Inactive"

    def apply_assignment_derivation(self, volunteer):
        """Full derivation, for use immediately after an assignment row changed.

        Unlike update_status() this MAY promote out of Inactive, because here there
        is real evidence that the assignments just changed -- a volunteer coming
        back to a role should go Active. Called only from
        AssignmentHistoryManager.refresh_volunteer_status().
        """
        if volunteer.status in MANUAL_STATUSES:
            return

        if self.has_current_assignment(volunteer):
            volunteer.status = "Active"
        elif self.has_any_assignment(volunteer):
            volunteer.status = "Inactive"

    def has_current_assignment(self, volunteer):
        """Does this volunteer hold a role RIGHT NOW?

        "Current" is decided by Volunteer Assignment.status: Active, Paused and
        On Hold all mean the role is still held -- a paused board member has not
        given up the seat. Only Completed and Cancelled release it.
        """
        for row in volunteer.assignment_history or []:
            if row.status in CURRENT_ASSIGNMENT_STATUSES:
                return True

        if frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name, "is_active": 1}):
            return True

        if frappe.db.exists("Team Member", {"volunteer": volunteer.name, "is_active": 1}):
            return True

        return False

    def has_any_assignment(self, volunteer):
        """
        Check if volunteer has any assignments at all, using cheap existence queries.

        Returns True if volunteer has assignments in any of:
        - Assignment history child table
        - Chapter Board Member
        - Team Member
        """
        # Check assignment_history child table first (in-memory, no DB query)
        if volunteer.assignment_history and len(volunteer.assignment_history) > 0:
            return True

        # Check Chapter Board Member (single indexed query)
        if frappe.db.exists("Chapter Board Member", {"volunteer": volunteer.name}):
            return True

        # Check Team Member (single indexed query)
        if frappe.db.exists("Team Member", {"volunteer": volunteer.name}):
            return True

        return False


_service = VolunteerStatusDerivationService()


def get_volunteer_status_derivation_service() -> VolunteerStatusDerivationService:
    """Get the VolunteerStatusDerivationService. Stateless, so a single instance."""
    return _service
