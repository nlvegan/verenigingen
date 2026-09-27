# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Real-flow tests for calculate_cohort_data()'s retention-exclusion clause.

Background (#1544): the retention subquery excluded a member from a cohort's
"retained" count if they had a `Membership Termination Request` with
`status = 'Completed'` before the check date. `'Completed'` is not a valid
Select option on that doctype (Draft/Pending/Approved/Rejected/Executed/
Cancelled), so the exclusion could never fire -- a naive swap to the valid
value `'Executed'` was reverted (see git history) because it changes
observable behaviour: a member who was voluntarily terminated and later
*legitimately reapplied and was reapproved* would then be wrongly excluded
from retention forever, on the strength of a termination request that
belongs to a membership they no longer hold.

Maintainer ruling (2026-09-28, issue #1544): a rejoined member does NOT
count old terminations -- only a termination belonging to the member's
CURRENT membership excludes them. The fix scopes the exclusion to
`t.termination_date > m.member_since`, since a real reapplication +
approval resets `member_since` to the rejoin date (verified below).

This PR also fixes #1548, folded in on coordinator instruction because it is
the SAME principle applied one layer down: `member_utils.
update_termination_status_display` (a `before_save` hook on Member) used to
re-derive `status` from ANY Executed termination request, with no notion of
"current membership" at all -- so a real reapplication + approval could
never actually reach `status = "Active"` (the hook reverted it to "Quit" on
every save, including the approval's own). That made #1544's rejoin
scenario unreachable through the real flow. #1548's fix (in
`member.py`/`member_utils.py`) scopes the hook the same way: it only forces
the terminal status for a termination that belongs to the CURRENT
membership. With both fixed, the test below drives the full real flow with
no hand-set status anywhere.
"""

import json

import frappe
from frappe.utils import add_months, getdate, today

from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists
from verenigingen.tests.support.termination_request import (
    create_draft_termination_request,
    execute_real_termination,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
    calculate_cohort_data,
)


class TestCohortRetentionRejoinTerminations(VereningingenTestCase):
    """calculate_cohort_data()'s retention exclusion, driven through real flows."""

    def setUp(self):
        super().setUp()
        ensure_membership_type_exists("Standard Member", amount=25.0)
        if not frappe.db.get_value("Membership Type", "Standard Member", "is_active"):
            frappe.db.set_value("Membership Type", "Standard Member", "is_active", 1)

    # ------------------------------------------------------------------ helpers

    def _cohort_entry(self, period_end_date, cohort_month_str):
        """Run the real calculate_cohort_data() and return the entry for one
        cohort month, or None if nobody joined that month (the production
        function omits empty cohorts entirely)."""
        snapshot = frappe._dict()
        calculate_cohort_data(snapshot, {"end_date": period_end_date})
        for entry in json.loads(snapshot.cohort_data):
            if entry["cohort"] == cohort_month_str:
                return entry
        return None

    def _retained_delta(self, period_end_date, cohort_month_str, month_offset, before):
        """(initial, retained) counts for one cohort/month_offset, read AFTER
        a change, minus what they were BEFORE it -- isolates the effect of
        this test's own fixture from whatever else already sits on the
        shared test site (#1544's own class sweep found ambient member_since
        collisions are common for "this month" cohorts)."""
        after = self._cohort_entry(period_end_date, cohort_month_str)
        before_initial = before["initial"] if before else 0
        before_retained = before[f"month_{month_offset}"]["count"] if before else 0
        after_initial = after["initial"] if after else 0
        after_retained = after[f"month_{month_offset}"]["count"] if after else 0
        return after_initial - before_initial, after_retained - before_retained

    def _real_rejoin_and_approve(self, member, membership_type="Standard Member"):
        """Drive the REAL reapplication + approval flow for a Quit member:
        api/membership_application.py::_handle_existing_member (Scenario 3)
        -> services/member/approval/application_helpers.py::
        update_member_from_reapplication -> api/membership_application_review.py::
        approve_membership_application. Returns the reloaded member.
        """
        from verenigingen.api.membership_application import _handle_existing_member
        from verenigingen.api.membership_application_review import (
            approve_membership_application,
        )
        from verenigingen.services.member.approval.application_helpers import (
            generate_application_id,
            update_member_from_reapplication,
        )

        existing_member = frappe.db.get_value(
            "Member",
            {"email": member.email},
            ["name", "status", "application_status"],
            as_dict=True,
        )
        data = {
            "first_name": member.first_name,
            "last_name": member.last_name,
            "email": member.email,
            "birth_date": str(member.birth_date),
            "selected_membership_type": membership_type,
        }
        action, blocked = _handle_existing_member(existing_member, data)
        self.assertEqual(action, "update", "Voluntary-terminated member must be allowed to reapply")
        self.assertIsNone(blocked)

        update_member_from_reapplication(member.name, data, generate_application_id(), address=None)
        member.reload()
        self.assertEqual(member.application_status, "Pending")

        approve_membership_application(
            member_name=member.name,
            membership_type=membership_type,
            chapter=None,
        )
        member.reload()
        self.assertEqual(member.application_status, "Approved")
        return member

    # ------------------------------------------------------------------ tests

    def test_rejoined_member_is_not_excluded_by_stale_termination(self):
        """The maintainer ruling (#1544): a member who was voluntarily
        terminated and later legitimately rejoined must be counted as
        retained in their NEW (post-rejoin) cohort -- the old, superseded
        termination request must not exclude them."""
        # The rejoin resets member_since to today(), so the cohort this member
        # will end up in is THIS calendar month. Snapshot it BEFORE the member
        # (and their rejoin) exist, so the delta below isolates this test's
        # fixture from whatever else already shares that cohort on this site.
        cohort_month = getdate(today()).replace(day=1)
        cohort_month_str = cohort_month.strftime("%Y-%m")
        period_end_date = add_months(cohort_month, 1)
        month_offset = 1
        before = self._cohort_entry(period_end_date, cohort_month_str)

        member = self.create_test_member(
            first_name="Rejoin",
            last_name="Retained",
            email=f"rejoin.retained.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved",
            selected_membership_type="Standard Member",
        )
        old_join_date = add_months(today(), -30)
        frappe.db.set_value("Member", member.name, "member_since", old_join_date, update_modified=False)

        termination_date = add_months(today(), -6)
        execute_real_termination(self, member.name, termination_date)
        member.reload()
        self.assertEqual(member.status, "Quit", "Sanity: a real termination must flip status off Active")

        member = self._real_rejoin_and_approve(member)
        self.assertEqual(
            getdate(member.member_since),
            getdate(today()),
            "A real reapproval resets member_since to the rejoin date -- this is the "
            "anchor the fix scopes the exclusion against.",
        )
        # #1548 fixed in this same PR: the before_save hook used to keep
        # reverting status to "Quit" on every save while the old Executed
        # request existed, so approval could never actually reach "Active".
        # No hand-set status anywhere in this test -- this is the real,
        # persisted outcome of the real approval call above.
        self.assertEqual(
            member.status,
            "Active",
            "The real approval flow must reach Active -- #1548's hook must not keep "
            "re-deriving status from the superseded termination",
        )
        self.assertIsNone(
            member.member_end_date,
            "A superseded termination must not leave a stale member_end_date on a "
            "now-current, Active membership (same #1544 outcome, different field -- "
            "membership_analytics.py's retention queries treat a set member_end_date "
            "as 'no longer a member')",
        )

        delta_initial, delta_retained = self._retained_delta(
            period_end_date, cohort_month_str, month_offset, before
        )
        self.assertEqual(
            delta_initial, 1, "The rejoined member must appear in their new cohort's initial count"
        )
        self.assertEqual(
            delta_retained,
            1,
            "The rejoined member must be counted as retained -- the old, superseded "
            "termination must not exclude them (maintainer ruling, #1544)",
        )

    def test_terminated_member_never_rejoined_is_excluded(self):
        """Control: a member who was terminated and never rejoined must stay
        excluded from retention. Note (verification discipline): today's
        outer `status = 'Active'` filter already excludes such a member
        regardless of the termination-status literal bug this issue fixes
        -- a real termination flips Member.status off "Active"
        (update_member_status_safe), so this scenario was never independently
        red on develop through calculate_cohort_data(); it is included as a
        control the fix must not regress, not as a red/green demonstration.
        The termination_date is deliberately placed INSIDE the
        [member_since, check_date) window the subquery evaluates (not just
        relying on the outer status filter), so this control also exercises
        the subquery's own date/status conditions directly."""
        join_date = add_months(today(), -24)
        cohort_month = getdate(join_date).replace(day=1)
        cohort_month_str = cohort_month.strftime("%Y-%m")
        month_offset = 6
        period_end_date = add_months(cohort_month, month_offset)

        # Snapshot BEFORE this test's member exists, so the delta below isolates
        # this fixture from whatever else already shares that cohort month.
        before = self._cohort_entry(period_end_date, cohort_month_str)

        member = self.create_test_member(
            first_name="NeverRejoin",
            last_name="Excluded",
            email=f"never.rejoin.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved",
            selected_membership_type="Standard Member",
        )
        frappe.db.set_value("Member", member.name, "member_since", join_date, update_modified=False)

        # Inside [member_since, check_date): 3 months after joining, well
        # before the 6-month check_date.
        termination_date = add_months(join_date, 3)
        execute_real_termination(self, member.name, termination_date)
        member.reload()
        self.assertEqual(member.status, "Quit")

        delta_initial, delta_retained = self._retained_delta(
            period_end_date, cohort_month_str, month_offset, before
        )
        self.assertEqual(delta_initial, 1, "The member still counts in the cohort's initial size")
        self.assertEqual(
            delta_retained, 0, "A terminated, never-rejoined member must not be counted as retained"
        )

    def test_draft_termination_does_not_exclude_anyone(self):
        """Control: a Draft (never executed) termination request must not
        exclude anyone -- only 'Executed' counts. termination_date sits
        INSIDE the [member_since, check_date) window (the same place a
        real Executed termination would need to be to exclude), so this
        actually exercises the subquery's status filter rather than being
        vacuously true because the date falls outside the window. The shared
        create_draft_termination_request() fixture (from
        verenigingen.tests.support.termination_request) fixes
        termination_date=today(), so member_since/check_date are placed
        around it instead: 2 months before today (member_since) and 6 months
        after the cohort month (check_date, comfortably past today
        regardless of day-of-month rounding)."""
        join_date = add_months(today(), -2)
        cohort_month = getdate(join_date).replace(day=1)
        cohort_month_str = cohort_month.strftime("%Y-%m")
        month_offset = 6
        period_end_date = add_months(cohort_month, month_offset)

        # Snapshot BEFORE this test's member exists, so the delta below isolates
        # this fixture from whatever else already shares that cohort month.
        before = self._cohort_entry(period_end_date, cohort_month_str)

        member = self.create_test_member(
            first_name="DraftOnly",
            last_name="StillRetained",
            email=f"draft.only.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved",
            selected_membership_type="Standard Member",
        )
        frappe.db.set_value("Member", member.name, "member_since", join_date, update_modified=False)

        create_draft_termination_request(self, member.name)

        delta_initial, delta_retained = self._retained_delta(
            period_end_date, cohort_month_str, month_offset, before
        )
        self.assertEqual(delta_initial, 1)
        self.assertEqual(delta_retained, 1, "A Draft termination request must not exclude anyone")
