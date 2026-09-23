"""
Ownership enforcement test for payment_plan.py's
create_payment_plan_from_application (#1093).

create_payment_plan_from_application(member, total_amount, installments,
frequency, reason=None) assigned a caller-supplied member straight onto a new
Payment Plan document with no check that it was the caller's own record or
that the caller held an admin/staff role. Per #1101's decision, the fix
reuses validate_member_ownership(member, allow_admin=True) before the
document is even built.

Caller check (per the dispatch brief): grepped the whole tree for
"create_payment_plan_from_application" outside this file and its own module
-- there is no JS/template/Python caller anywhere in the app (confirmed via
`grep -rln` against *.js/*.html/*.py). So there is no existing legitimate
caller (e.g. a membership-application flow acting before the applicant has a
Member record) that this ownership check could break; the function is
reachable only as a bare whitelisted endpoint today.

Tier-gate note (see test_sepa_mandate_manager_api_ownership.py's module
docstring for the full derivation of this pattern): this endpoint is
@high_security_api (HIGH), and "Verenigingen Chapter Board Member" is a REAL
role profile that clears HIGH while holding none of Roles.ADMIN_ROLES
(verified against the checked-in verenigingen/fixtures/role_profile.json),
the same population PR #1322 (#1101) used to probe a HIGH-tier sibling. No
tier-gate patching is needed here, unlike the CRITICAL-tier #1088 endpoints.
The attacker/self/staff user setup is shared via MemberOwnershipProbeMixin
(tests/fixtures/member_ownership_probe_mixin.py), consolidated there because
it was duplicated verbatim across this file and its #1088 siblings, which
scripts/validation/duplicate_helper_validator.py's pre-push clone-family gate
correctly flagged.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.verenigingen_payments.doctype.payment_plan.payment_plan import (
    create_payment_plan_from_application,
)


class TestCreatePaymentPlanFromApplicationOwnership(MemberOwnershipProbeMixin, EnhancedTestCase):
    def test_foreign_member_refused(self):
        attacker_user, _attacker_member = self._board_member_linked_user("PlanAppAttacker")
        victim = self.create_test_member(first_name="PlanAppVictim")

        with self.set_user(attacker_user):
            with self.assertRaises(frappe.PermissionError):
                create_payment_plan_from_application(
                    member=victim.name, total_amount=150.0, installments=3, frequency="Monthly"
                )

        # The point of the fix: no plan was created against the victim's name.
        self.assertFalse(
            frappe.db.exists("Payment Plan", {"member": victim.name}),
            "attacker must not be able to create a payment plan for the victim",
        )

    def test_own_member_allowed(self):
        self_user, self_member = self._board_member_linked_user("PlanAppSelf")

        with self.set_user(self_user):
            plan_name = create_payment_plan_from_application(
                member=self_member.name, total_amount=150.0, installments=3, frequency="Monthly"
            )

        self.assertEqual(frappe.db.get_value("Payment Plan", plan_name, "member"), self_member.name)

    def test_staff_allowed_for_another_member(self):
        member = self.create_test_member(first_name="PlanAppStaffTarget")
        staff_user = self._staff_user("PlanAppStaff", role="Verenigingen Staff")

        with self.set_user(staff_user):
            plan_name = create_payment_plan_from_application(
                member=member.name, total_amount=150.0, installments=3, frequency="Monthly"
            )

        self.assertEqual(frappe.db.get_value("Payment Plan", plan_name, "member"), member.name)
