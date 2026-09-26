"""Scoping tests for #1486's follow-up leaks from #1365's census of
@standard_api(REPORTING) endpoints (the #1329 shape: an unfiltered listing
gated only by the generic MEDIUM tier, which "Verenigingen Chapter Board
Member", "Verenigingen Volunteer" and "Verenigingen Auditor" all clear on
their own per authorization_policy.ROLE_PROFILE_SECURITY_MAPPING).

Four fixes:

- export_agreements (api/periodic_donation_operations.py): maintainer ruling
  (#1486 comment, 2026-09-26) -- restrict to exactly the roles the "ANBI
  Periodic Agreements" report itself grants, derived from the Report doc's own
  role list via Report.is_permitted() rather than a hardcoded second copy.
  Volunteer and Chapter Board Member lose access (neither is on the report's
  role list); System Manager / Verenigingen Administrator keep it.

  NOTE: the report's role list also names "Verenigingen Treasurer" and
  "Verenigingen Auditor", but the checked-in role_profile.json fixtures for
  BOTH of those role profiles grant a *different* role than their own name
  ("Verenigingen Treasurer" -> no "Verenigingen Treasurer" role;
  "Verenigingen Auditor" -> "Auditor", not "Verenigingen Auditor") --
  confirmed live on test_site_6. So no *currently configured* Treasurer/Auditor
  role-profile user can satisfy Report.is_permitted() today, and (since Desk
  uses the same check to gate opening a Script Report) neither can they open
  this report from Desk. That mismatch is pre-existing, orthogonal to #1486,
  and does not change with this fix -- filed separately. The "admin keeps
  access" control below therefore uses "Verenigingen Administrator" (which
  DOES resolve to a real, matching role), and a second control demonstrates
  the *mechanism* is correct by granting the literal "Verenigingen Auditor"
  role directly (bypassing the Role Profile resync that would otherwise strip
  it), proving the check would admit a real Auditor if that separate mismatch
  is ever fixed.

- get_sepa_notification_history (verenigingen_payments/utils/
  sepa_notification_manager.py): SEPA Notification Log is a raw SQL table
  (`tabSEPA_Notification_Log`, created ad hoc by
  SEPANotificationManager._ensure_notification_tables), not a registered
  DocType -- no permission_query_conditions hook to lean on and no
  member/chapter link to scope by. Admin-only guard, the same shape as
  sepa_mandate_diagnostics._ensure_staff_only_diagnostics_access (#1329), kept
  as a separate function because that one's message is specific to mandate
  diagnostics.

- chapter_dues_split.get_data (verenigingen/report/chapter_dues_split/
  chapter_dues_split.py): same shape as export_agreements -- get_data wraps
  this Script Report's own logic directly, bypassing the Report role check
  Desk enforces when opening the report itself. The report's own role list is
  "Verenigingen Financial Manager" / "Verenigingen Administrator" / "System
  Manager" only -- NOT Chapter Board Member -- so today a Chapter Board
  Member (and Volunteer/Auditor) sees every OTHER chapter's paid/unpaid dues
  split and national/chapter allocation, not just their own. Fixed with the
  same shared ensure_report_role_access() helper as export_agreements (a new
  module, utils/security/report_role_gate.py, to avoid a clone of the same
  four-line body across two files).

  NOTE: get_application_stats (pages/membership_applications/__init__.py),
  one of #1486's five originally-named candidates, was investigated and NOT
  fixed here: BOTH of that file's two @standard_api endpoints reference a
  Member field, `suggested_chapter`, that does not exist on the Member
  DocType (confirmed against member.json and live on test_site_6 --
  get_pending_applications raises AttributeError from an unrelated dead
  `frappe.user.has_role(...)` call before it would even reach that field, and
  get_application_stats raises MySQLdb.OperationalError: Unknown column
  'suggested_chapter' unconditionally, for every caller, before it ever
  reaches the recent_approvals/recent_rejections listings #1486 flagged).
  The claimed leak does not currently reproduce live -- the endpoint 500s for
  everyone, including admins -- so per the dispatch brief ("anything not
  confirmed live gets a comment on #1486, not a fix") this was dropped in
  favour of chapter_dues_split (verified live below) and filed as its own,
  separate bug instead.

- analyze_churn_risk (verenigingen/page/membership_analytics/
  predictive_analytics.py, called by get_predictive_analytics): had NO gating
  of its own at all -- not even an attempted (broken) admin check -- and
  returns member name + payment-failure counts / days-inactive, app-wide.
  Scoped the same way. Only the "no recent activity" query is covered here
  (lighter fixture than constructing an overdue Sales Invoice for the
  "payment failures" query); both queries route through the same
  _churn_risk_member_scope_sql() helper, so a mutation of that helper reddens
  regardless of which query is exercised.

Common shape for all four: Roles.ADMIN_ROLES sees everything unrestricted;
a Chapter Board Member with an ACTIVE seat sees only their own chapter(s) (or,
for the admin-only sepa_notification guard, nothing); Volunteer/Auditor see
nothing.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.api.periodic_donation_operations import export_agreements
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import analyze_churn_risk
from verenigingen.verenigingen.report.chapter_dues_split.chapter_dues_split import (
    get_data as get_dues_split_data,
)
from verenigingen.verenigingen_payments.utils.sepa_notification_manager import (
    get_sepa_notification_history,
)


def _unwrap_operation_result(result):
    """@standard_api serialises an OperationResult return to a plain dict; a
    plain-dict return (no .to_dict) passes through unchanged. Normalise both."""
    if isinstance(result, dict):
        return result
    return result.to_dict()


class TestExportAgreementsReportRoleScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    def _export(self):
        return _unwrap_operation_result(export_agreements(filters={}))

    def test_volunteer_refused(self):
        self.expectErrorLog("Agreement Export Error")
        user_email, _member = self._user_linked_to_own_member(
            "ExportAgreementsVolunteer", "Verenigingen Member", "Verenigingen Volunteer"
        )
        with self.set_user(user_email):
            result = self._export()
        self.assertFalse(result["success"])

    def test_chapter_board_member_refused(self):
        self.expectErrorLog("Agreement Export Error")
        chapter = self.create_test_chapter()
        board = self.create_test_board_member(chapter.name)
        with self.set_user(board.user):
            result = self._export()
        self.assertFalse(result["success"])

    def test_admin_still_allowed(self):
        staff_user = self._staff_user("ExportAgreementsAdmin", role="Verenigingen Administrator")
        with self.set_user(staff_user):
            result = self._export()
        self.assertTrue(result["success"])

    def _grant_literal_role_bypassing_profile_resync(self, user_email, role):
        """Insert a bare Has Role row directly, bypassing User.save()'s
        populate_role_profile_roles resync (which would strip a role that isn't
        part of the user's assigned Role Profile's own role list -- see this
        class's docstring on the Auditor role/profile mismatch)."""
        frappe.get_doc(
            {
                "doctype": "Has Role",
                "parent": user_email,
                "parenttype": "User",
                "parentfield": "roles",
                "role": role,
            }
        ).insert(ignore_permissions=True)
        frappe.clear_cache(user=user_email)

    def test_mechanism_admits_a_real_holder_of_the_reports_own_role(self):
        """Demonstrates the fix reuses the report's OWN role list rather than a
        hardcoded subset: a user holding the literal "Verenigingen Auditor" role
        (as the report itself lists) is admitted, even though -- per this
        module's docstring -- no currently-configured Role Profile actually
        grants that literal role."""
        user_email, _member = self._user_linked_to_own_member(
            "ExportAgreementsAuditorMechanism", "Verenigingen Member", "Verenigingen Auditor"
        )
        self._grant_literal_role_bypassing_profile_resync(user_email, "Verenigingen Auditor")
        with self.set_user(user_email):
            # Precondition, read after the switch so it resolves through the
            # switched session rather than a pre-set_user cache (cache-guard).
            self.assertIn("Verenigingen Auditor", frappe.get_roles())
            result = self._export()
        self.assertTrue(result["success"])


class TestSepaNotificationHistoryStaffOnly(MemberOwnershipProbeMixin, EnhancedTestCase):
    def _get_history(self):
        return _unwrap_operation_result(get_sepa_notification_history())

    def test_volunteer_refused(self):
        self.expectErrorLog("You are not permitted to view SEPA notification history")
        user_email, _member = self._user_linked_to_own_member(
            "SepaNotifHistoryVolunteer", "Verenigingen Member", "Verenigingen Volunteer"
        )
        with self.set_user(user_email):
            result = self._get_history()
        self.assertFalse(result["success"])

    def test_auditor_refused(self):
        self.expectErrorLog("You are not permitted to view SEPA notification history")
        user_email, _member = self._user_linked_to_own_member(
            "SepaNotifHistoryAuditor", "Verenigingen Member", "Verenigingen Auditor"
        )
        with self.set_user(user_email):
            result = self._get_history()
        self.assertFalse(result["success"])

    def test_chapter_board_member_refused(self):
        """Opposite from the mandate-diagnostics precedent: unlike SEPA Mandate,
        SEPA Notification Log has no legitimate non-admin front door anywhere
        (no Page/Report grants a board role access), so this is admin-only, not
        chapter-scoped -- a board member is refused too."""
        self.expectErrorLog("You are not permitted to view SEPA notification history")
        chapter = self.create_test_chapter()
        board = self.create_test_board_member(chapter.name)
        with self.set_user(board.user):
            result = self._get_history()
        self.assertFalse(result["success"])

    def test_staff_still_allowed(self):
        staff_user = self._staff_user("SepaNotifHistoryStaff", role="Verenigingen Staff")
        with self.set_user(staff_user):
            result = self._get_history()
        self.assertTrue(result["success"])


class TestChapterDuesSplitReportRoleScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    def _get_dues_split(self):
        return get_dues_split_data(filters={})

    def test_volunteer_refused(self):
        user_email, _member = self._user_linked_to_own_member(
            "DuesSplitVolunteer", "Verenigingen Member", "Verenigingen Volunteer"
        )
        with self.set_user(user_email):
            self.assertRaises(frappe.PermissionError, self._get_dues_split)

    def test_chapter_board_member_refused(self):
        """The report's own role list is Financial Manager / Administrator /
        System Manager only -- NOT Chapter Board Member -- so a real board
        member (unlike the SEPA mandate diagnostics precedent) has no
        legitimate front door to this report at all."""
        chapter = self.create_test_chapter()
        board = self.create_test_board_member(chapter.name)
        with self.set_user(board.user):
            self.assertRaises(frappe.PermissionError, self._get_dues_split)

    def test_admin_still_allowed(self):
        staff_user = self._staff_user("DuesSplitAdmin", role="Verenigingen Administrator")
        with self.set_user(staff_user):
            result = self._get_dues_split()
        self.assertEqual(result, [])


class TestChurnRiskChapterScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    """Only the "no recent activity" (inactive_members) query is exercised --
    the lighter of analyze_churn_risk()'s two Member-anchored queries to build a
    fixture for. The "payment failures" query is not independently covered
    here, but both route through the same _churn_risk_member_scope_sql()
    helper, so a mutation of that shared helper reddens this suite regardless
    of which query would have surfaced it.

    Calls analyze_churn_risk() directly rather than through its whitelisted
    caller get_predictive_analytics(): the latter unconditionally also runs
    detect_seasonal_patterns(), which raises an unrelated, pre-existing
    ZeroDivisionError on a fresh/empty test site (confirmed live on
    test_site_6, filed separately -- not part of #1486's unscoped-listing
    shape). frappe.get_roles() reflects the caller session either way, so
    calling the helper directly still exercises the same role-based scoping
    this fix adds."""

    def setUp(self):
        super().setUp()
        self.chapter_a = self.create_test_chapter()
        self.chapter_b = self.create_test_chapter()
        self.board = self.create_test_board_member(self.chapter_a.name)

        self.member_a = self._inactive_member("ChurnInactiveA", self.chapter_a.name)
        self.member_b = self._inactive_member("ChurnInactiveB", self.chapter_b.name)

    def _inactive_member(self, first_name, chapter_name):
        member = self.create_test_member(first_name=first_name)
        member.db_set("status", "Active")
        self.add_member_to_test_chapter(member.name, chapter_name)
        old_modified = add_days(today(), -100)
        frappe.db.set_value("Member", member.name, "modified", old_modified, update_modified=False)
        return member.name

    def _churn_names(self):
        churn = analyze_churn_risk()
        return {row["member"] for row in churn["high_risk_members"]}

    def test_board_member_sees_only_own_chapter(self):
        with self.set_user(self.board.user):
            names = self._churn_names()
        self.assertIn(self.member_a, names)
        self.assertNotIn(self.member_b, names)

    def test_volunteer_sees_none(self):
        user_email, _member = self._user_linked_to_own_member(
            "ChurnVolunteer", "Verenigingen Member", "Verenigingen Volunteer"
        )
        with self.set_user(user_email):
            names = self._churn_names()
        self.assertNotIn(self.member_a, names)
        self.assertNotIn(self.member_b, names)

    def test_auditor_sees_none(self):
        user_email, _member = self._user_linked_to_own_member(
            "ChurnAuditor", "Verenigingen Member", "Verenigingen Auditor"
        )
        with self.set_user(user_email):
            names = self._churn_names()
        self.assertNotIn(self.member_a, names)
        self.assertNotIn(self.member_b, names)

    def test_staff_sees_all(self):
        staff_user = self._staff_user("ChurnStaff", role="Verenigingen Staff")
        with self.set_user(staff_user):
            names = self._churn_names()
        self.assertTrue({self.member_a, self.member_b} <= names)
