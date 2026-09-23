"""
Ownership enforcement tests for the SEPA mandate manager's whitelisted API
wrappers (#1088).

get_active_mandates_api, validate_mandate_creation_api, create_mandate_api, and
deactivate_mandates_for_iban_change_api took a caller-supplied ``member`` with
no check that it was the caller's own record or that the caller held an
admin/staff role. Per #1101's decision, the fix reuses
``validate_member_ownership(member, allow_admin=True)``
(verenigingen/utils/member_utils.py) at the top of each function: a plain
member acting on ANOTHER member is refused (frappe.PermissionError), the
member acting on themself is allowed, and staff (a Roles.ADMIN_ROLES holder,
cleared for the endpoint's own security tier) may act on another member's
behalf.

Tier-gate vs. ownership-check isolation (IMPORTANT, verified empirically):
All four endpoints are @high_security_api (get_active_mandates_api) or
@critical_api (the other three). api_security_framework.py's
validate_authentication() refuses a caller who does not clear the endpoint's
security tier BEFORE the function body -- and therefore before
validate_member_ownership() -- ever runs. A naive "plain member -> refused"
test can therefore pass on unpatched develop (no ownership check at all) for
the wrong reason: the tier gate, not the ownership check, produced the
PermissionError.

- get_active_mandates_api is HIGH. "Verenigingen Chapter Board Member" is a
  REAL role profile that clears HIGH while holding none of Roles.ADMIN_ROLES
  (verified: its role list has no System Manager / Verenigingen
  Administrator / Verenigingen Staff), the same population PR #1322 (#1101)
  used to probe a HIGH-tier sibling. No patching needed there.

- validate_mandate_creation_api / create_mandate_api /
  deactivate_mandates_for_iban_change_api are CRITICAL. Read directly from
  the checked-in verenigingen/fixtures/role_profile.json (not just this
  site's runtime state, so this holds in CI too): EVERY Role Profile that
  authorization_policy.ROLE_PROFILE_SECURITY_MAPPING maps to CRITICAL
  ("Verenigingen System Administrator", "Verenigingen Administrator",
  "Verenigingen Treasurer", "Verenigingen National Board Member") also
  grants at least one Roles.ADMIN_ROLES role (most carry "Verenigingen
  Staff" outright). So today there is NO real, currently-configured Role
  Profile that clears CRITICAL without also holding an admin role -- anyone
  who can even dispatch these three functions already qualifies for the
  allow_admin=True bypass. This is a genuine, fixture-verified fact, not a
  gap in this test: it means the ownership check on these three is real
  defense-in-depth (against a future/misconfigured non-admin CRITICAL grant,
  or an internal caller reaching the function without going through the
  decorator), not a fix for a LIVE today-reachable "ordinary member" exploit.
  To still test validate_member_ownership's own comparison in isolation --
  independent of this tier-gate coincidence, and so a red run here is
  attributable to the ownership branch, not the tier gate -- these three
  classes patch AuthorizationEngine.authorize to force tier clearance for a
  genuinely non-admin "Verenigingen Member" user, exactly the isolation
  technique requested in review. The "staff allowed" tests need no patch:
  "Verenigingen Administrator" clears CRITICAL for real.

One test class per function (not a single parametrized shape): each function
takes different required arguments and returns a different success shape
(get_active_mandates_api returns a plain dict; the other three return an
OperationResult serialized to the nested {"success": ...} schema by their
@critical_api decorator), so a shared assertion would obscure more than it
would save. The attacker/self/staff user setup and the tier-gate bypass ARE
shared, via MemberOwnershipProbeMixin (tests/fixtures/
member_ownership_probe_mixin.py) -- consolidated there because it was
duplicated verbatim across this file and the #1088/#1093 sibling ownership
test files, which scripts/validation/duplicate_helper_validator.py's pre-push
clone-family gate correctly flagged.
"""

import frappe
from frappe.utils import today

from verenigingen.services.payment.sepa_mandate_manager import (
    create_mandate_api,
    deactivate_mandates_for_iban_change_api,
    get_active_mandates_api,
    get_sepa_mandate_manager,
    validate_mandate_creation_api,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.utils.secure_operations import secure_document_operation


class _MandateApiOwnershipMixin(MemberOwnershipProbeMixin):
    """Adds the one SEPA-Mandate-specific fixture helper on top of the shared
    attacker/self/staff/tier-gate helpers in MemberOwnershipProbeMixin."""

    def _active_mandate(self, member_name, iban):
        """A real, Active/is_active SEPA Mandate (create_mandate() itself always
        starts a mandate as Draft/inactive, so get_active_mandates_api would see
        nothing without this)."""
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member_name,
                "mandate_id": f"OWNAPI-{frappe.generate_hash(length=8)}",
                "iban": iban,
                "bic": "ABNANL2A",
                "account_holder_name": "Ownership Api Test",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "used_for_memberships": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
            }
        )
        result = secure_document_operation(
            operation="insert",
            doc=mandate,
            justification="Test mandate for #1088 ownership coverage",
            required_permissions=["SEPA Mandate:create"],
        )
        if not result.success:
            raise frappe.ValidationError("; ".join(result.errors))
        return mandate


class TestGetActiveMandatesApiOwnership(_MandateApiOwnershipMixin, EnhancedTestCase):
    """@high_security_api -- HIGH tier, cleared by the real "Verenigingen
    Chapter Board Member" role profile without patching."""

    def setUp(self):
        super().setUp()
        self.manager = get_sepa_mandate_manager()

    def test_foreign_member_refused(self):
        attacker_user, _attacker_member = self._board_member_linked_user("MandateGetAttacker")
        victim = self.create_test_member(first_name="MandateGetVictim")

        with self.set_user(attacker_user):
            with self.assertRaises(frappe.PermissionError):
                get_active_mandates_api(member=victim.name)

    def test_own_member_allowed(self):
        self_user, self_member = self._board_member_linked_user("MandateGetSelf")
        self._active_mandate(self_member.name, "NL91ABNA0417164300")

        with self.set_user(self_user):
            result = get_active_mandates_api(member=self_member.name)

        self.assertEqual(result["count"], 1)

    def test_staff_allowed_for_another_member(self):
        member = self.create_test_member(first_name="MandateGetStaffTarget")
        self._active_mandate(member.name, "NL91ABNA0417164300")
        staff_user = self._staff_user()

        with self.set_user(staff_user):
            result = get_active_mandates_api(member=member.name)

        self.assertEqual(result["count"], 1)


class TestValidateMandateCreationApiOwnership(_MandateApiOwnershipMixin, EnhancedTestCase):
    """@critical_api -- see module docstring: no real non-admin Role Profile
    clears CRITICAL today, so the refused/self tests use a plain
    "Verenigingen Member" user with the tier gate patched open, isolating
    validate_member_ownership()'s own comparison."""

    def test_foreign_member_refused(self):
        attacker_user, _attacker_member = self._plain_member_linked_user("MandateValidateAttacker")
        victim = self.create_test_member(first_name="MandateValidateVictim")

        with self.set_user(attacker_user):
            with self._bypass_tier_gate():
                with self.assertRaises(frappe.PermissionError):
                    validate_mandate_creation_api(
                        member=victim.name, iban="NL91ABNA0417164300", mandate_id="OWN-TEST-001"
                    )

    def test_own_member_allowed(self):
        self_user, self_member = self._plain_member_linked_user("MandateValidateSelf")

        with self.set_user(self_user):
            with self._bypass_tier_gate():
                result = validate_mandate_creation_api(
                    member=self_member.name, iban="NL91ABNA0417164300", mandate_id="OWN-TEST-002"
                )

        self.assertIn("success", result)

    def test_staff_allowed_for_another_member(self):
        member = self.create_test_member(first_name="MandateValidateStaffTarget")
        staff_user = self._staff_user()

        with self.set_user(staff_user):
            result = validate_mandate_creation_api(
                member=member.name, iban="NL91ABNA0417164300", mandate_id="OWN-TEST-003"
            )

        self.assertIn("success", result)


class TestCreateMandateApiOwnership(_MandateApiOwnershipMixin, EnhancedTestCase):
    """@critical_api -- same tier-gate isolation as TestValidateMandateCreationApiOwnership."""

    def test_foreign_member_refused(self):
        attacker_user, _attacker_member = self._plain_member_linked_user("MandateCreateAttacker")
        victim = self.create_test_member(first_name="MandateCreateVictim")

        with self.set_user(attacker_user):
            with self._bypass_tier_gate():
                with self.assertRaises(frappe.PermissionError):
                    create_mandate_api(member=victim.name, iban="NL91ABNA0417164300")

        # The point of the fix: no mandate was created against the victim's
        # IBAN by the attacker's request.
        self.assertFalse(
            frappe.db.exists("SEPA Mandate", {"member": victim.name}),
            "attacker must not be able to create a mandate for the victim",
        )

    def test_own_member_allowed(self):
        self_user, self_member = self._plain_member_linked_user("MandateCreateSelf")

        with self.set_user(self_user):
            with self._bypass_tier_gate():
                result = create_mandate_api(
                    member=self_member.name, iban="NL91ABNA0417164300", account_holder_name="Create Api Self"
                )

        self.assertTrue(result["success"], result)

    def test_staff_allowed_for_another_member(self):
        member = self.create_test_member(first_name="MandateCreateStaffTarget")
        staff_user = self._staff_user()

        with self.set_user(staff_user):
            result = create_mandate_api(
                member=member.name, iban="NL91ABNA0417164300", account_holder_name="Create Api Staff"
            )

        self.assertTrue(result["success"], result)


class TestDeactivateMandatesForIbanChangeApiOwnership(_MandateApiOwnershipMixin, EnhancedTestCase):
    """@critical_api -- same tier-gate isolation as TestValidateMandateCreationApiOwnership."""

    def test_foreign_member_refused(self):
        attacker_user, _attacker_member = self._plain_member_linked_user("MandateDeactAttacker")
        victim = self.create_test_member(first_name="MandateDeactVictim")
        victim_mandate = self._active_mandate(victim.name, "NL91ABNA0417164300")

        with self.set_user(attacker_user):
            with self._bypass_tier_gate():
                with self.assertRaises(frappe.PermissionError):
                    deactivate_mandates_for_iban_change_api(
                        member=victim.name, new_iban="NL20INGB0001234567"
                    )

        # The victim's mandate is unaffected by the refused attempt.
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate", victim_mandate.name, "status"),
            "Active",
        )

    def test_own_member_allowed(self):
        self_user, self_member = self._plain_member_linked_user("MandateDeactSelf")
        self._active_mandate(self_member.name, "NL91ABNA0417164300")

        with self.set_user(self_user):
            with self._bypass_tier_gate():
                result = deactivate_mandates_for_iban_change_api(
                    member=self_member.name, new_iban="NL20INGB0001234567"
                )

        self.assertTrue(result["success"], result)

    def test_staff_allowed_for_another_member(self):
        member = self.create_test_member(first_name="MandateDeactStaffTarget")
        self._active_mandate(member.name, "NL91ABNA0417164300")
        staff_user = self._staff_user()

        with self.set_user(staff_user):
            result = deactivate_mandates_for_iban_change_api(
                member=member.name, new_iban="NL20INGB0001234567"
            )

        self.assertTrue(result["success"], result)
