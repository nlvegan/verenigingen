"""
Ownership enforcement test for sepa_mandate_diagnostics.py's
fix_member_mandate_issues (#1088).

fix_member_mandate_issues(member_id, ...) took a caller-supplied member_id and
called member.refresh_sepa_mandates_table() with no check that it was the
caller's own record or that the caller held an admin/staff role. Per #1101's
decision, the fix reuses validate_member_ownership(member_id,
allow_admin=True) at the top of the function.

Tier-gate note (see test_sepa_mandate_manager_api_ownership.py's module
docstring for the full derivation): fix_member_mandate_issues is @critical_api
(CRITICAL). Per the checked-in verenigingen/fixtures/role_profile.json, every
Role Profile mapped to CRITICAL also grants a Roles.ADMIN_ROLES role, so there
is no real, currently-configured non-admin caller for this endpoint today.
The refused/self tests below therefore use a plain "Verenigingen Member" user
with the tier gate patched open, isolating validate_member_ownership()'s own
comparison from that separate, incidental gate -- so a red run here is
attributable to the ownership branch alone. The attacker/self/staff user
setup and the tier-gate bypass are shared via MemberOwnershipProbeMixin
(tests/fixtures/member_ownership_probe_mixin.py), consolidated there because
it was duplicated verbatim across this file and its #1088/#1093 siblings,
which scripts/validation/duplicate_helper_validator.py's pre-push
clone-family gate correctly flagged.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics import (
    fix_member_mandate_issues,
)


class TestFixMemberMandateIssuesOwnership(MemberOwnershipProbeMixin, EnhancedTestCase):
    def test_foreign_member_refused(self):
        attacker_user, _attacker_member = self._plain_member_linked_user("DiagFixAttacker")
        victim = self.create_test_member(first_name="DiagFixVictim")

        with self.set_user(attacker_user):
            with self._bypass_tier_gate():
                with self.assertRaises(frappe.PermissionError):
                    fix_member_mandate_issues(member_id=victim.name)

    def test_own_member_allowed(self):
        self_user, self_member = self._plain_member_linked_user("DiagFixSelf")

        with self.set_user(self_user):
            with self._bypass_tier_gate():
                result = fix_member_mandate_issues(member_id=self_member.name)

        self.assertTrue(result["success"], result)

    def test_staff_allowed_for_another_member(self):
        member = self.create_test_member(first_name="DiagFixStaffTarget")
        staff_user = self._staff_user("DiagFixStaff")

        with self.set_user(staff_user):
            result = fix_member_mandate_issues(member_id=member.name)

        self.assertTrue(result["success"], result)
