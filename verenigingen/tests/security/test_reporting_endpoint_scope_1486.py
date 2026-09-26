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
  "Verenigingen Auditor". Until #1504 those Role Profiles did not grant their
  own literal role, so a profile-provisioned Auditor/Treasurer was refused
  here (and from Desk). #1504 fixed the profiles, so the Auditor control
  below provisions through the real Role Profile path.

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
from verenigingen.utils.constants import Roles
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

    def test_auditor_role_profile_user_allowed(self):
        """A user provisioned through the real "Verenigingen Auditor" Role
        Profile holds the literal role the report lists (#1504), so the fix's
        reuse of the report's own role list admits them."""
        user_email, _member = self._user_linked_to_own_member(
            "ExportAgreementsAuditor", "Verenigingen Member", "Verenigingen Auditor"
        )
        with self.set_user(user_email):
            # Precondition, read after the switch so it resolves through the
            # switched session rather than a pre-set_user cache (cache-guard).
            self.assertIn("Verenigingen Auditor", frappe.get_roles())
            result = self._export()
        self.assertTrue(result["success"])


class TestSepaNotificationHistoryStaffOnly(MemberOwnershipProbeMixin, EnhancedTestCase):
    """Assertions key on the guard's decision (the denial code), never on "success".

    tabSEPA_Notification_Log is created ad hoc by SEPANotificationManager.__init__,
    and that CREATE TABLE is swallowed as ImplicitCommitError once the transaction
    holds a write -- which every test here does before the call. So on a site that
    never had the table (every fresh CI shard) the query AFTER the guard returns
    success=False too (#1510): a bare assertFalse(success) passes with the guard
    deleted, and assertTrue(success) fails with the guard correct.
    """

    def _get_history(self):
        return _unwrap_operation_result(get_sepa_notification_history())

    @staticmethod
    def _denial_code(result):
        # A refusal comes back through handle_api_error as {"error": {"code": ...}};
        # the missing-table failure is the manager's own plain-string "error".
        error = result.get("error")
        return error.get("code") if isinstance(error, dict) else None

    def _assert_refused(self, result):
        self.assertEqual(self._denial_code(result), "PERMISSION_DENIED", result)

    def test_volunteer_refused(self):
        self.expectErrorLog("You are not permitted to view SEPA notification history")
        user_email, _member = self._user_linked_to_own_member(
            "SepaNotifHistoryVolunteer", "Verenigingen Member", "Verenigingen Volunteer"
        )
        with self.set_user(user_email):
            result = self._get_history()
        self._assert_refused(result)

    def test_auditor_refused(self):
        self.expectErrorLog("You are not permitted to view SEPA notification history")
        user_email, _member = self._user_linked_to_own_member(
            "SepaNotifHistoryAuditor", "Verenigingen Member", "Verenigingen Auditor"
        )
        with self.set_user(user_email):
            result = self._get_history()
        self._assert_refused(result)

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
        self._assert_refused(result)

    def test_staff_still_allowed(self):
        staff_user = self._staff_user("SepaNotifHistoryStaff", role="Verenigingen Staff")
        with self.set_user(staff_user):
            # Diagnostic precondition (#1511): this user was once refused by the
            # guard despite _staff_user's own role assertion passing. If that
            # recurs, this line says whether the role was missing under set_user
            # or the guard refused for another reason.
            self.assertTrue(set(frappe.get_roles()) & Roles.ADMIN_ROLES, frappe.get_roles())
            result = self._get_history()
        # The refusal tests above are this assertion's control: they fail if a
        # refusal ever stops carrying the code, so this cannot pass vacuously.
        self.assertNotEqual(self._denial_code(result), "PERMISSION_DENIED", result)


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
