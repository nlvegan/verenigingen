"""
Unit tests for the self-service validator (SelfServiceAccessController).

Companion to tests/security/test_self_service_doc_method_regression.py, which
covers the wrapper end-to-end. This file unit-tests the validator's behaviour
in isolation: explicit-target acceptance, cross-user rejection, implicit
self-service rules, and the policy mapping that backs @self_service_api.

The validator looks up the caller via frappe.session.user (NOT a `user=` kwarg)
and identifies the target via the kwargs keys in
SelfServiceAccessController.MEMBER_FIELDS — so all tests here drive the
session with `frappe.set_user(...)` and pass `member=...` rather than the
legacy `target_member=...`. Member→User linkage is via Member.email ==
User.email (NOT Member.user).
"""

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.api_security_framework import (
    APISecurityFramework,
    self_service_api,
    standard_api,
)
from verenigingen.utils.security.authorization_policy import AuthorizationPolicy
from verenigingen.utils.security.types import OperationType, SecurityLevel


class TestSelfServiceOperations(PortalSelfServiceTestMixin, EnhancedTestCase):
    """Unit tests for SelfServiceAccessController via APISecurityFramework."""

    def setUp(self):
        super().setUp()
        self.framework = APISecurityFramework()

    def _link_member_to_user(self, member, roles=("Verenigingen Volunteer",)):
        """Volunteer-tier, email-only link (the field SelfServiceAccessController
        looks up): no Member role profile, no Member.user. Delegates the body to
        PortalSelfServiceTestMixin."""
        return super()._link_member_to_user(member, roles=roles, role_profile=None, link_user=False)

    # --- _validate_self_service_access ---------------------------------------

    def test_owner_passes_with_explicit_member_kwarg(self):
        """When session user owns the target member, validator returns True."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            self.assertTrue(self.framework._validate_self_service_access(member=member.name))

    def test_cross_user_explicit_member_is_rejected(self):
        """Validator must reject explicit-target access to another member's record."""
        owner = self.create_test_member(birth_date="1990-01-01")
        intruder = self.create_test_member(birth_date="1991-02-02")
        intruder_user = self._link_member_to_user(intruder)

        with self._as_user(intruder_user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.framework._validate_self_service_access(member=owner.name)
        self.assertIn("only perform this operation on your own data", str(ctx.exception))

    def test_implicit_default_rejects_when_no_target(self):
        """No target kwarg + implicit_allowed=False → 'explicit member required'."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.framework._validate_self_service_access()
        self.assertIn("explicit member parameter", str(ctx.exception))

    def test_implicit_allowed_passes_when_user_has_member(self):
        """No target + implicit_allowed=True + user has linked Member → True."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        with self._as_user(user.name):
            self.assertTrue(
                self.framework._validate_self_service_access(implicit_allowed=True)
            )

    def test_implicit_allowed_rejects_user_with_no_member_link(self):
        """No target + implicit_allowed=True + user has NO Member → rejected."""
        # User without a linked Member record
        orphan_user = self.factory.create_user_with_roles(
            email=f"selfservice-orphan-{self.uid}@example.com",
            roles=["Verenigingen Member"],
        )

        with self._as_user(orphan_user.name):
            with self.assertRaises(VPermissionError) as ctx:
                self.framework._validate_self_service_access(implicit_allowed=True)
        self.assertIn("No member record found", str(ctx.exception))

    def test_administrator_bypasses_self_service(self):
        """Administrator (and Guest) skip the self-service check by design.

        This is the documented behaviour in SelfServiceAccessController:
            if current_user in ("Administrator", "Guest"): return True
        It's also why self-service tests must NEVER run as Administrator —
        the bug that triggered all this work was invisible under Admin.
        """
        owner = self.create_test_member(birth_date="1990-01-01")
        # Don't link anyone — Administrator should pass regardless
        with self._as_user("Administrator"):
            self.assertTrue(self.framework._validate_self_service_access(member=owner.name))

    # --- decorator wiring ---------------------------------------------------

    def test_self_service_decorator_runs_through_wrapper(self):
        """A function decorated with self_service_only=True runs the wrapper
        and reaches the inner function for the legitimate owner."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)

        @standard_api(operation_type=OperationType.MEMBER_DATA, self_service_only=True)
        def fake_endpoint(member=None):
            return {"ok": True, "member": member}

        with self._as_user(user.name):
            result = fake_endpoint(member=member.name)
        self.assertEqual(result, {"ok": True, "member": member.name})

    def test_self_service_decorator_blocks_other_member(self):
        """Decorator-wrapped endpoint rejects cross-user access via VPermissionError."""
        owner = self.create_test_member(birth_date="1990-01-01")
        intruder = self.create_test_member(birth_date="1991-02-02")
        intruder_user = self._link_member_to_user(intruder)

        @standard_api(operation_type=OperationType.MEMBER_DATA, self_service_only=True)
        def fake_endpoint(member=None):
            return {"ok": True}

        with self._as_user(intruder_user.name):
            with self.assertRaises(VPermissionError):
                fake_endpoint(member=owner.name)

    def test_self_service_api_decorator_uses_low_tier(self):
        """@self_service_api is reachable by plain Verenigingen Member callers
        (only LOW). This is the whole point of the helper — see
        memory/project_self_service_api.md."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member, roles=["Verenigingen Member"])

        @self_service_api(operation_type=OperationType.FINANCIAL)
        def fake_endpoint(member=None):
            return "ok"

        with self._as_user(user.name):
            self.assertEqual(fake_endpoint(member=member.name), "ok")

    # --- policy introspection -----------------------------------------------

    def test_volunteer_role_grants_medium_for_self_service_operations(self):
        """Verenigingen Volunteer must grant MEDIUM — that's the role tier
        @standard_api(self_service_only=True) endpoints (e.g. submit_expense)
        depend on. Regression guard for accidental policy edits."""
        policy = AuthorizationPolicy()
        levels = policy.ROLE_PROFILE_SECURITY_MAPPING.get("Verenigingen Volunteer", [])
        self.assertIn(SecurityLevel.MEDIUM, levels)
        self.assertIn(SecurityLevel.LOW, levels)

    def test_member_role_only_has_low(self):
        """Verenigingen Member intentionally has only LOW — granting MEDIUM
        would expose ~120 admin-flavoured @standard_api endpoints. Self-service
        for plain members goes through @self_service_api (LOW + ownership-gated)
        instead. Regression guard."""
        policy = AuthorizationPolicy()
        levels = policy.ROLE_PROFILE_SECURITY_MAPPING.get("Verenigingen Member", [])
        self.assertEqual(levels, [SecurityLevel.LOW])
