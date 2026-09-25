"""Role-scope enforcement test for sepa_mandate_diagnostics.py's get_mandate_issues
(#1329).

get_mandate_issues() carries no scoping of its own -- only the generic
@standard_api(operation_type=OperationType.REPORTING) tier gate, which defaults to
SecurityLevel.MEDIUM. Per authorization_policy.ROLE_PROFILE_SECURITY_MAPPING, MEDIUM is
cleared by several role profiles that hold none of Roles.ADMIN_ROLES -- "Verenigingen
Chapter Board Member", "Verenigingen Volunteer", "Verenigingen Auditor" (verified against
the checked-in verenigingen/fixtures/role_profile.json: none of their granted roles
include "System Manager" / "Verenigingen Administrator" / "Verenigingen Staff"). The
function itself runs six unfiltered `frappe.db.sql` queries across the whole
tabMember/tabSEPA Mandate tables and returns every match, including IBAN and
bank_account_name, to any caller who clears the tier gate.

Scope of this fix, per the maintainer's decision on #1329
(https://github.com/nlvegan/verenigingen/issues/1329#issuecomment-5830712514):

- "Verenigingen Volunteer" and "Verenigingen Auditor" have NO legitimate front door to
  this data: neither the "SEPA Mandate Diagnostics" page (page roles: System Manager,
  Verenigingen Administrator only) nor the "SEPA Mandate Issues" report (report roles:
  System Manager, Verenigingen Administrator, Verenigingen Staff, Verenigingen Chapter
  Board Member) grants them access. They are refused outright.
- Staff (Roles.ADMIN_ROLES) keep the full, unscoped, app-wide list.
- "Verenigingen Chapter Board Member" is allowed in, but scoped to members of the
  chapter(s) the caller holds an ACTIVE board seat on -- see
  test_sepa_mandate_diagnostics_chapter_scope.py for that behaviour in detail. This
  file's own `test_chapter_board_member_still_allowed`/`test_staff_still_allowed` only
  check that the two roles are not refused outright; the per-chapter content
  assertions live in the sibling module above.

Each attacker test below clears the @standard_api MEDIUM tier gate on its own merits
(via a real Role Profile from ROLE_PROFILE_SECURITY_MAPPING) -- no tier-gate bypass is
needed -- so the new explicit role check inside get_mandate_issues() is what refuses
them, and the message is asserted.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics import (
    bulk_fix_mandate_issues,
    get_mandate_issues,
)

MANDATE_DIAGNOSTICS_DENIAL_MESSAGE = "not permitted to view SEPA mandate diagnostics"


class TestGetMandateIssuesRoleScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    def test_volunteer_role_refused(self):
        """A bare 'Verenigingen Volunteer' Role Profile clears MEDIUM on its own
        (ROLE_PROFILE_SECURITY_MAPPING) but has no front door to this data anywhere
        in the app -- must be refused by the new role check."""
        user_email, _member = self._user_linked_to_own_member(
            "MandateVolunteerAttacker", "Verenigingen Member", "Verenigingen Volunteer"
        )
        self.assertFalse(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: volunteer-tier user must NOT hold an admin role",
        )

        with self.set_user(user_email):
            with self.assertRaisesRegex(frappe.PermissionError, MANDATE_DIAGNOSTICS_DENIAL_MESSAGE):
                get_mandate_issues()

    def test_auditor_role_refused(self):
        """Same shape as the volunteer case, for 'Verenigingen Auditor'."""
        user_email, _member = self._user_linked_to_own_member(
            "MandateAuditorAttacker", "Verenigingen Member", "Verenigingen Auditor"
        )
        self.assertFalse(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: auditor-tier user must NOT hold an admin role",
        )

        with self.set_user(user_email):
            with self.assertRaisesRegex(frappe.PermissionError, MANDATE_DIAGNOSTICS_DENIAL_MESSAGE):
                get_mandate_issues()

    def test_chapter_board_member_still_allowed(self):
        """Control: the real report caller (Chapter Board Member) must NOT be
        refused outright by the role gate. This user is built by
        _board_member_linked_user() -- a real Role Profile grant with NO actual
        Chapter Board Member seat -- so the per-chapter scope in
        _mandate_diagnostics_member_scope_sql() resolves to no chapters and the
        call returns an EMPTY result rather than an error or the app-wide list;
        see test_sepa_mandate_diagnostics_chapter_scope.py for the seated-board-
        member content assertions."""
        user_email, _member = self._board_member_linked_user("MandateBoardAllowed")

        with self.set_user(user_email):
            result = get_mandate_issues()

        self.assertIn("issues", result)
        self.assertIn("summary", result)
        self.assertEqual(result["summary"]["unique_members"], 0)

    def test_staff_still_allowed(self):
        """Control: Roles.ADMIN_ROLES must still pass."""
        staff_user = self._staff_user("MandateStaffAllowed", role="Verenigingen Staff")

        with self.set_user(staff_user):
            result = get_mandate_issues()

        self.assertIn("issues", result)

    def test_bulk_fix_default_listing_not_broken_for_admin(self):
        """bulk_fix_mandate_issues(member_ids=None) calls get_mandate_issues()
        internally to build its default worklist. Per the ownership test's own
        derivation, every Role Profile that clears bulk_fix_mandate_issues's
        CRITICAL tier already holds a Roles.ADMIN_ROLES role, so this call must
        keep working for a real admin caller after the new check is added."""
        result = bulk_fix_mandate_issues(issue_type=None, member_ids=None)
        self.assertIn("total", result)
