"""Role-scope enforcement test for sepa_mandate_management.py's
detect_sepa_mandate_inconsistencies (#1329 sibling).

Same shape as get_mandate_issues() in sepa_mandate_diagnostics.py: no member
parameter, no scoping, @standard_api(operation_type=OperationType.REPORTING)
(SecurityLevel.MEDIUM) is the only gate, and several non-admin, non-staff role
profiles clear MEDIUM on their own. Unlike get_mandate_issues(), this endpoint has
NO front door anywhere in the app (no Page, no Report references it -- grepped the
whole app; the only callers are its own tests), so there is no real caller to
preserve and no chapter-scoping question to leave open: any role outside
Roles.ADMIN_ROLES is refused outright.

The attacker clears the @standard_api MEDIUM tier gate on its own merits (a real
"Verenigingen Chapter Board Member" Role Profile, which grants HIGH/MEDIUM/LOW per
ROLE_PROFILE_SECURITY_MAPPING) -- no tier-gate bypass needed -- so the new explicit
role check is what refuses it.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.api import sepa_mandate_management as mgmt

INCONSISTENCIES_DENIAL_MESSAGE = "not permitted to view SEPA mandate diagnostics"


class TestDetectSepaMandateInconsistenciesRoleScope(MemberOwnershipProbeMixin, EnhancedTestCase):
    def test_chapter_board_member_refused(self):
        """No Page or Report grants this role access to this endpoint (unlike
        get_mandate_issues(), which the "SEPA Mandate Issues" report exempts) --
        must be refused."""
        user_email, _member = self._board_member_linked_user("InconsistBoardAttacker")
        self.assertFalse(set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES)

        with self.set_user(user_email):
            with self.assertRaisesRegex(frappe.PermissionError, INCONSISTENCIES_DENIAL_MESSAGE):
                mgmt.detect_sepa_mandate_inconsistencies()

    def test_staff_still_allowed(self):
        """Control: Roles.ADMIN_ROLES must still pass, and the existing success
        contract (a dict with success=True) is unchanged for an authorised caller."""
        staff_user = self._staff_user("InconsistStaffAllowed", role="Verenigingen Staff")

        with self.set_user(staff_user):
            result = mgmt.detect_sepa_mandate_inconsistencies()

        self.assertTrue(result["success"], result)
