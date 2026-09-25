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

Scope of this fix (see the PR/issue discussion for the part left OPEN):

- "Verenigingen Volunteer" and "Verenigingen Auditor" have NO legitimate front door to
  this data: neither the "SEPA Mandate Diagnostics" page (page roles: System Manager,
  Verenigingen Administrator only) nor the "SEPA Mandate Issues" report (report roles:
  System Manager, Verenigingen Administrator, Verenigingen Staff, Verenigingen Chapter
  Board Member) grants them access. Blocking them is unambiguous and is what this fix
  does.
- "Verenigingen Chapter Board Member" DOES have a legitimate, currently-designed front
  door: the "SEPA Mandate Issues" report explicitly lists it in `roles` (added
  deliberately in 95d66ace7) and that report's get_data() calls this exact function.
  Restricting get_mandate_issues() to Roles.ADMIN_ROLES only would break that report for
  board members -- a real caller, not a hypothetical -- so this fix does NOT do that.
  Chapter Board Member callers still see the SAME unscoped, app-wide data they could
  already reach through the report; whether that should instead be scoped to the
  caller's own chapter(s) is a separate, NOT-YET-DECIDED product question (the issue's
  own "Not established" section says so) and is intentionally left open rather than
  decided unilaterally here.

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
        """Control: the real report caller (Chapter Board Member) must NOT be broken
        by this fix -- see module docstring for why this is intentionally left
        unscoped rather than refused."""
        user_email, _member = self._board_member_linked_user("MandateBoardAllowed")

        with self.set_user(user_email):
            result = get_mandate_issues()

        self.assertIn("issues", result)
        self.assertIn("summary", result)

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
