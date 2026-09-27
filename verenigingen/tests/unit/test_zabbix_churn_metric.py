"""The Zabbix churn metric must count real terminations, not a status that cannot exist.

``scripts/monitoring/zabbix_integration.py::get_business_metrics`` computed churn from
``Member.status = "Terminated"``. That is not one of the Member.status Select options
(Pending/Active/Rejected/Expired/Suspended/Banned/Deceased/Quit), so the filter matched
zero rows on every real site and the metric was permanently 0 (#1541).

**Maintainer ruling (2026-09-27, on #1541):** churn counts every terminated Member status
-- Quit, Deceased, Banned.

The time window matters as much as the status list. The buggy query keyed on ``modified``,
which changes on ANY later edit to the Member document (an address correction, a nightly
job) -- so an old leaver touched again would be re-counted every month, and a leaver never
touched again would silently drop out of the metric after 30 days regardless of when they
actually left. The real termination flow
(``verenigingen.services.termination.termination_integration.update_member_status_safe``,
and the ``before_save`` hook
``verenigingen.verenigingen.doctype.member.member_utils.update_termination_status_display``)
writes ``member_end_date`` -- the same field the existing membership analytics reports
(``verenigingen/verenigingen/page/membership_analytics/membership_analytics.py``) already
use to answer "when did this member leave" -- so the fix keys on that field instead.

This module reaches the real code path: it builds a ``Membership Termination Request`` the
same way ``tests/support/termination_request.py`` does (that shared helper is reused where
its fixed Voluntary/today() shape is enough) and drives it through
``TerminationExecutionService.execute_system_updates``, exactly like
``tests/unit/test_history_lock_order.py`` and ``tests/unit/test_termination_non_resumable_errors.py``
do -- the only code path that writes Member.status/member_end_date the way a production
termination does.

All assertions are deltas (before/after counts), never absolutes, because the site carries
ambient Members outside this test's control.
"""

import sys
from pathlib import Path

import frappe
from frappe.utils import add_days, today

from verenigingen.services.termination import TerminationExecutionService
from verenigingen.tests.support.termination_request import create_termination_request
from verenigingen.tests.utils.base import VereningingenTestCase

# scripts/ sits at the app repo root, outside the installed `verenigingen` package, so it
# is not importable by dotted path. Mirrors the sys.path trick
# verenigingen/monitoring/zabbix_integration.py itself uses to reach it, and the pattern
# tests/test_doctype_name_ratchet.py already uses for scripts/validation.
APP_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_MONITORING = str(APP_ROOT / "scripts" / "monitoring")
if _SCRIPTS_MONITORING not in sys.path:
    sys.path.insert(0, _SCRIPTS_MONITORING)

import zabbix_integration  # noqa: E402


def _create_and_execute_termination(case, member_name, termination_type="Voluntary", termination_date=None, reason=None):
    """Drive a member through the real termination execution flow.

    ``create_termination_request`` fixes termination_type="Voluntary" and
    termination_date=today() -- fine for most cases here, but the Deceased/Banned and
    old-leaver tests need to control both, so those build the request directly, matching
    the shared helper's own shape (member/termination_type/termination_reason/
    member_request_date/termination_date/end_board_positions) instead of mutating it after
    insert.
    """
    reason = reason or f"churn metric test (#1541) - {termination_type}"
    if termination_type == "Voluntary" and termination_date is None:
        request = create_termination_request(case, member_name, reason)
    else:
        # member_request_date must not be after termination_date (validate_dates()), so
        # when termination_date is pushed into the past the request date has to move
        # with it.
        effective_termination_date = termination_date or today()
        request_data = {
            "doctype": "Membership Termination Request",
            "member": member_name,
            "termination_type": termination_type,
            "termination_reason": reason,
            "member_request_date": effective_termination_date,
            "termination_date": effective_termination_date,
            "end_board_positions": 1,
        }
        # Disciplinary types (Policy Violation/Disciplinary Action/Expulsion) require
        # documentation (validate_termination_request()).
        if termination_type in ("Policy Violation", "Disciplinary Action", "Expulsion"):
            request_data["disciplinary_documentation"] = reason
        request = frappe.get_doc(request_data)
        request.insert()
        case.track_doc("Membership Termination Request", request.name)
        frappe.db.commit()

    TerminationExecutionService().execute_system_updates(request)
    # execute_system_updates() alone (unlike execute()) does not flip the request's own
    # status -- set it the way the real flow does, since _handle_existing_member's
    # reapplication gate keys on Membership Termination Request.status == "Executed".
    frappe.db.set_value("Membership Termination Request", request.name, "status", "Executed")
    frappe.db.commit()
    return request


class TestZabbixChurnMetric(VereningingenTestCase):
    def test_real_termination_is_counted_within_window(self):
        before = zabbix_integration._count_recent_member_terminations()

        member = self.create_test_member()
        _create_and_execute_termination(self, member.name)

        after = zabbix_integration._count_recent_member_terminations()
        self.assertEqual(after, before + 1)

        member.reload()
        self.assertEqual(member.status, "Quit")
        self.assertEqual(str(member.member_end_date), str(today()))

    def test_deceased_and_banned_are_also_counted(self):
        """Maintainer ruling: churn is ALL terminated statuses, not just Quit."""
        before = zabbix_integration._count_recent_member_terminations()

        deceased = self.create_test_member()
        _create_and_execute_termination(self, deceased.name, termination_type="Deceased")

        banned = self.create_test_member()
        _create_and_execute_termination(self, banned.name, termination_type="Expulsion")

        after = zabbix_integration._count_recent_member_terminations()
        self.assertEqual(after, before + 2)

        deceased.reload()
        banned.reload()
        self.assertEqual(deceased.status, "Deceased")
        self.assertEqual(banned.status, "Banned")

    def test_suspended_and_expired_members_are_not_counted(self):
        """Control: being merely Suspended/Expired is not a churn event."""
        before = zabbix_integration._count_recent_member_terminations()

        self.create_test_member(status="Suspended")
        self.create_test_member(status="Expired")

        after = zabbix_integration._count_recent_member_terminations()
        self.assertEqual(after, before)

    def test_old_leaver_touched_recently_is_not_recounted(self):
        """Control: bumping `modified` on an unrelated edit must not re-trigger churn.

        This is exactly the failure mode the buggy `modified`-keyed filter had: it counted
        ANY member touched in the last 30 days who happens to carry a terminated status,
        however long ago they actually left.
        """
        before = zabbix_integration._count_recent_member_terminations()

        member = self.create_test_member()
        old_date = add_days(today(), -60)
        _create_and_execute_termination(self, member.name, termination_date=old_date)

        # Unrelated edit -- bumps `modified` to "now" without changing when membership
        # actually ended.
        member.reload()
        member.notes = (member.notes or "") + "\naddress correction"
        member.save()

        after = zabbix_integration._count_recent_member_terminations()
        self.assertEqual(after, before)

        member.reload()
        self.assertEqual(str(member.member_end_date), str(old_date))

    def test_rejoined_member_is_not_counted(self):
        """A Quit member who reapplies and is reset to Pending must not stay counted.

        Mirrors api/membership_application.py::_handle_existing_member, which allows a
        Voluntary-terminated ("Quit") member to reapply, and
        application_helpers.update_member_from_reapplication, which is the function that
        resets status back to "Pending".

        Driving `update_member_from_reapplication` alone (no follow-up save) hits a
        SEPARATE, pre-existing defect filed as #1548: Member's `before_save` hook
        (`update_termination_status_display`) unconditionally re-derives `status` from
        the member's most recent *Executed* Membership Termination Request, and nothing
        in the reapplication path cancels or supersedes that row -- so the "Pending"
        reset is silently overwritten back to "Quit" on the very save that set it.
        Measured directly: without the workaround below, `member.status` reads back
        "Quit", not "Pending", immediately after this call. That is #1548's bug, not
        #1541's, so it is worked around here (superseding the stale Executed request,
        which is what actually needs to happen for a rejoin to stick) rather than
        silently accepted as this test's expected outcome -- an assertion of "still
        Quit" here would bake #1548's defect into this suite as if it were correct.

        What THIS test is actually establishing for #1541: once a member's status is
        genuinely reset away from the churned set, the churn metric must reflect that
        immediately, using the field it now keys on (`member_end_date`) which is left
        untouched and still recent -- the status filter alone must be enough.
        """
        from verenigingen.services.member.approval.application_helpers import (
            update_member_from_reapplication,
        )
        from verenigingen.utils.secure_operations import get_system_user_for_operation

        member = self.create_test_member()
        request = _create_and_execute_termination(self, member.name, termination_type="Voluntary")

        member.reload()
        self.assertEqual(member.status, "Quit")
        after_termination = zabbix_integration._count_recent_member_terminations()

        # Workaround for #1548 (see docstring): supersede the Executed request so
        # update_termination_status_display's before_save hook no longer finds it and
        # re-asserts "Quit".
        frappe.db.set_value("Membership Termination Request", request.name, "status", "Cancelled")

        # The background service user update_member_from_reapplication saves as needs the
        # Staff role for the fee-override permission check on member.save(); grant it for
        # the duration of this test only, matching
        # tests/backend/unit/utils/test_application_helpers_reapplication.py.
        system_user = get_system_user_for_operation("member_reapplication_update")
        role_added = not frappe.db.exists(
            "Has Role", {"parent": system_user, "role": "Verenigingen Staff"}
        )
        if role_added:
            frappe.db.sql(
                """INSERT INTO `tabHas Role` (name, parent, parenttype, parentfield, role)
                VALUES (%s, %s, 'User', 'roles', 'Verenigingen Staff')""",
                (frappe.generate_hash(length=10), system_user),
            )
            frappe.clear_cache(user=system_user)

        try:
            update_member_from_reapplication(
                member.name,
                {"first_name": member.first_name, "last_name": member.last_name},
                application_id=f"REAPPLY-{member.name}",
            )
        finally:
            if role_added:
                frappe.db.sql(
                    "DELETE FROM `tabHas Role` WHERE parent=%s AND role='Verenigingen Staff'",
                    system_user,
                )
                frappe.clear_cache(user=system_user)

        member.reload()
        self.assertEqual(member.status, "Pending")
        # member_end_date is deliberately left as-is (still recent) -- the status filter
        # alone must be sufficient to drop the member from the metric.
        self.assertIsNotNone(member.member_end_date)

        after_reapply = zabbix_integration._count_recent_member_terminations()
        self.assertEqual(after_reapply, after_termination - 1)
