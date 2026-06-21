"""
Authorization coverage tests for the SEPA authorization manager.

Targets verenigingen/utils/security/authorization.py:
- SEPAAuthorizationManager.get_user_permissions (role-profile lookup + fallback)
- SEPAAuthorizationManager.has_permission (allow/deny, required_level override)
- SEPAAuthorizationManager.validate_operation (grant/deny, raise_exception)
- _check_contextual_permissions / _check_batch_permissions branches
- The require_sepa_permission / require_role decorators
- The whitelisted permission-introspection endpoints

CRITICAL: these tests exercise the REAL authorization boundary. We create real
User records, assign real Role Profiles (which apply real Roles), and switch
identity with `self.as_user(...)` so each decision reflects the actual user's
real role state. No mocking of frappe.get_roles / frappe.session / the
function-under-test -- that would defeat the entire point of authorization tests.

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.security.test_authorization_coverage
"""

import json

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import PermissionError as VerenigingenPermissionError
from verenigingen.utils.security.authorization import (
    SEPAAuthorizationManager,
    SEPAOperation,
    SEPAPermissionLevel,
    check_sepa_operation_permission,
    get_auth_manager,
    get_user_sepa_permissions,
    require_role,
    require_sepa_permission,
)
from verenigingen.utils.security.authorization_engine import get_authorization_engine


class AuthorizationTestBase(VereningingenTestCase):
    """Shared helpers for building real users with real role profiles."""

    def setUp(self):
        super().setUp()
        self.manager = SEPAAuthorizationManager()

    def _make_user_with_role_profile(self, role_profile, prefix="az"):
        """Create a real User and assign a real Role Profile.

        Assigning a Role Profile applies its Roles to the User, so frappe.get_roles
        and the authorization engine both reflect the real assignment. We populate
        BOTH the v16 role_profiles child table and the legacy role_profile_name link
        so the engine's dual-read path resolves the profile on any Frappe version.
        """
        email = f"{prefix}-{frappe.generate_hash(length=8).lower()}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": prefix.title(),
                "last_name": "AuthUser",
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)

        user.set("role_profiles", [{"role_profile": role_profile}])
        user.role_profile_name = role_profile
        user.save(ignore_permissions=True)

        # Fresh user => no stale cache, but invalidate defensively so the engine
        # re-reads the just-assigned profile rather than an empty cached list.
        get_authorization_engine().invalidate_user_cache(email)
        return user

    def _make_user_with_roles(self, roles, prefix="azrole"):
        """Create a real User with explicit individual Roles (no Role Profile)."""
        email = f"{prefix}-{frappe.generate_hash(length=8).lower()}@example.com"
        user = self.create_test_user(email=email, roles=roles)
        get_authorization_engine().invalidate_user_cache(email)
        return user


class TestGetUserPermissions(AuthorizationTestBase):
    """SEPAAuthorizationManager.get_user_permissions"""

    def test_system_users_get_all_permission_levels(self):
        """Administrator/System short-circuit to the full permission set."""
        perms = self.manager.get_user_permissions("Administrator")
        self.assertEqual(set(perms), set(SEPAPermissionLevel))

    def test_treasurer_role_profile_grants_expected_levels(self):
        """A real Treasurer role profile grants READ/VALIDATE/CREATE/PROCESS/AUDIT,
        and NOT ADMIN (Treasurer is operational, not system-admin)."""
        user = self._make_user_with_role_profile("Verenigingen Treasurer", prefix="treas")
        with self.as_user(user.name):
            perms = set(self.manager.get_user_permissions())
        self.assertIn(SEPAPermissionLevel.READ, perms)
        self.assertIn(SEPAPermissionLevel.PROCESS, perms)
        self.assertIn(SEPAPermissionLevel.AUDIT, perms)
        self.assertNotIn(SEPAPermissionLevel.ADMIN, perms)

    def test_chapter_board_member_limited_to_read_validate(self):
        """Chapter Board Member is intentionally limited to READ + VALIDATE."""
        user = self._make_user_with_role_profile("Verenigingen Chapter Board Member", prefix="cbm")
        with self.as_user(user.name):
            perms = set(self.manager.get_user_permissions())
        self.assertEqual(perms, {SEPAPermissionLevel.READ, SEPAPermissionLevel.VALIDATE})

    def test_member_role_profile_grants_no_sepa_permissions(self):
        """A plain Member has no entry in ROLE_PROFILE_PERMISSIONS -> empty set.

        This is the deny-by-default guarantee: members cannot touch SEPA ops.
        """
        user = self._make_user_with_role_profile("Verenigingen Member", prefix="mbr")
        with self.as_user(user.name):
            perms = self.manager.get_user_permissions()
        self.assertEqual(perms, [])

    def test_fallback_individual_role_when_no_profile_match(self):
        """A user with an individual Frappe role that matches a permission-matrix
        key (and NO assigned role profile) still resolves via the fallback path.

        "System Manager" is a real role on the site AND a key in
        ROLE_PROFILE_PERMISSIONS (full access). Because the user has no role
        profile, the profile lookup yields an empty set and the code falls back
        to frappe.get_roles(), which is the branch under test.
        """
        user = self._make_user_with_roles(["System Manager"], prefix="sysmgrrole")
        # Confirm the precondition: no role profile assigned, so the primary
        # profile-based lookup returns nothing and the fallback must engage.
        self.assertEqual(get_authorization_engine().get_user_role_profiles(user.name), [])
        with self.as_user(user.name):
            perms = set(self.manager.get_user_permissions())
        # System Manager maps to the full permission set in the matrix.
        self.assertEqual(perms, set(SEPAPermissionLevel))


class TestHasPermission(AuthorizationTestBase):
    """SEPAAuthorizationManager.has_permission"""

    def test_system_user_always_allowed(self):
        self.assertTrue(self.manager.has_permission(SEPAOperation.SETTINGS_MODIFY, user="Administrator"))

    def test_staff_allowed_create_denied_admin(self):
        """Staff has CREATE/PROCESS but not ADMIN: allow BATCH_CREATE, deny BATCH_DELETE."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="staff")
        with self.as_user(user.name):
            self.assertTrue(self.manager.has_permission(SEPAOperation.BATCH_CREATE))
            self.assertFalse(self.manager.has_permission(SEPAOperation.BATCH_DELETE))

    def test_member_denied_read_operation(self):
        """A plain Member (no SEPA permissions) is denied even a READ operation."""
        user = self._make_user_with_role_profile("Verenigingen Member", prefix="mbr2")
        with self.as_user(user.name):
            self.assertFalse(self.manager.has_permission(SEPAOperation.ANALYTICS_VIEW))

    def test_required_level_override_denies_when_user_lacks_higher_level(self):
        """required_level override is enforced over the operation's default mapping.

        ANALYTICS_VIEW defaults to READ (which Staff has). Forcing required_level=ADMIN
        must deny Staff, proving the override wins over OPERATION_REQUIREMENTS.
        """
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="staff2")
        with self.as_user(user.name):
            self.assertTrue(self.manager.has_permission(SEPAOperation.ANALYTICS_VIEW))
            self.assertFalse(
                self.manager.has_permission(
                    SEPAOperation.ANALYTICS_VIEW,
                    required_level=SEPAPermissionLevel.ADMIN,
                )
            )

    def test_required_level_override_allows_lower_level_view(self):
        """Override can also LOWER the bar: gate a VALIDATE op at READ so a
        read-only role passes. Auditor has READ but not VALIDATE."""
        user = self._make_user_with_role_profile("Verenigingen Auditor", prefix="aud")
        with self.as_user(user.name):
            # Default mapping for INVOICE_VALIDATE is VALIDATE -> auditor denied.
            self.assertFalse(self.manager.has_permission(SEPAOperation.INVOICE_VALIDATE))
            # Gated at READ -> auditor allowed.
            self.assertTrue(
                self.manager.has_permission(
                    SEPAOperation.INVOICE_VALIDATE,
                    required_level=SEPAPermissionLevel.READ,
                )
            )


class TestBatchContextualPermissions(AuthorizationTestBase):
    """_check_batch_permissions via has_permission with batch context."""

    def _make_batch(self, owner=None):
        """Build a real, valid Direct Debit Batch.

        The batch controller rejects an empty batch ("No invoices added to
        batch"), so we mint a member + customer + mandate + submitted EUR invoice
        and add one row -- the same pattern used by the SEPA payment tests.
        _check_batch_permissions only reads batch.owner and batch.status, so the
        row content just has to make insert() succeed.
        """
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        member = self.create_test_member(birth_date="1985-03-03")
        membership = self.create_test_membership(member=member.name)
        mandate = self.create_test_sepa_mandate(member=member.name)
        member.reload()

        sepa_factory = SEPATestDataFactory()
        invoice = sepa_factory.create_test_sales_invoice(
            customer=member.customer,
            member=member.name,
            status="Unpaid",
            submit=True,
        )
        self.track_doc("Sales Invoice", invoice.name)

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.batch_description = f"Auth Test Batch {frappe.generate_hash(length=6)}"
        batch.batch_type = "CORE"
        batch.currency = "EUR"
        batch.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": membership.name,
                "member": member.name,
                "member_name": f"{member.first_name} {member.last_name}",
                "amount": invoice.grand_total,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                "sequence_type": "FRST",
            },
        )
        batch.insert(ignore_permissions=True)
        if owner:
            frappe.db.set_value("Direct Debit Batch", batch.name, "owner", owner, update_modified=False)
        self.track_doc("Direct Debit Batch", batch.name)
        return batch

    def test_admin_user_passes_batch_check_for_foreign_batch(self):
        """A System Administrator role profile (has ADMIN) may process a batch it
        does not own."""
        owner_user = self._make_user_with_role_profile("Verenigingen Staff", prefix="owner")
        admin_user = self._make_user_with_role_profile("Verenigingen System Administrator", prefix="sysadmin")
        batch = self._make_batch(owner=owner_user.name)
        with self.as_user(admin_user.name):
            self.assertTrue(
                self.manager.has_permission(SEPAOperation.BATCH_PROCESS, context={"batch_name": batch.name})
            )

    def test_owner_passes_batch_check(self):
        """The batch owner (with PROCESS perms) passes the batch ownership check."""
        owner_user = self._make_user_with_role_profile("Verenigingen Staff", prefix="owner2")
        batch = self._make_batch(owner=owner_user.name)
        with self.as_user(owner_user.name):
            self.assertTrue(
                self.manager.has_permission(SEPAOperation.BATCH_PROCESS, context={"batch_name": batch.name})
            )

    def test_no_batch_name_in_context_skips_batch_check(self):
        """Empty/absent batch_name short-circuits _check_batch_permissions to True,
        so the decision falls back to the plain permission-level check."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="staff3")
        with self.as_user(user.name):
            self.assertTrue(
                self.manager.has_permission(SEPAOperation.BATCH_PROCESS, context={"unrelated": "x"})
            )


class TestValidateOperation(AuthorizationTestBase):
    """SEPAAuthorizationManager.validate_operation"""

    def test_grant_returns_true(self):
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="vstaff")
        with self.as_user(user.name):
            self.assertTrue(self.manager.validate_operation(SEPAOperation.BATCH_CREATE))

    def test_deny_raises_permission_error(self):
        """Denied operation with raise_exception=True raises VerenigingenPermissionError
        and the message names the operation + required permission."""
        user = self._make_user_with_role_profile("Verenigingen Member", prefix="vmbr")
        with self.as_user(user.name):
            with self.assertRaises(VerenigingenPermissionError) as ctx:
                self.manager.validate_operation(SEPAOperation.BATCH_DELETE)
        self.assertIn("batch_delete", str(ctx.exception))

    def test_deny_returns_false_when_not_raising(self):
        user = self._make_user_with_role_profile("Verenigingen Member", prefix="vmbr2")
        with self.as_user(user.name):
            self.assertFalse(
                self.manager.validate_operation(SEPAOperation.BATCH_DELETE, raise_exception=False)
            )

    def test_validate_operation_honours_required_level_override(self):
        """validate_operation must propagate required_level so the effective level
        appears in the denial. Auditor lacks ADMIN; gate ANALYTICS_VIEW at ADMIN."""
        user = self._make_user_with_role_profile("Verenigingen Auditor", prefix="vaud")
        with self.as_user(user.name):
            with self.assertRaises(VerenigingenPermissionError) as ctx:
                self.manager.validate_operation(
                    SEPAOperation.ANALYTICS_VIEW,
                    required_level=SEPAPermissionLevel.ADMIN,
                )
        self.assertIn("admin", str(ctx.exception).lower())


class TestDecorators(AuthorizationTestBase):
    """require_sepa_permission and require_role decorators."""

    def test_require_sepa_permission_allows_authorized_user(self):
        @require_sepa_permission(SEPAPermissionLevel.CREATE, SEPAOperation.BATCH_CREATE)
        def create_batch():
            return "created"

        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="decstaff")
        with self.as_user(user.name):
            self.assertEqual(create_batch(), "created")

    def test_require_sepa_permission_blocks_unauthorized_user(self):
        """Denied caller gets a frappe.PermissionError (the decorator converts the
        internal VerenigingenPermissionError via frappe.throw)."""

        @require_sepa_permission(SEPAPermissionLevel.ADMIN, SEPAOperation.SETTINGS_MODIFY)
        def modify_settings():
            return "modified"

        user = self._make_user_with_role_profile("Verenigingen Member", prefix="decmbr")
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                modify_settings()

    def test_require_sepa_permission_propagates_inner_exception_type(self):
        """The body runs AFTER the auth check, so a non-permission error raised by
        the endpoint body propagates with its real type (not masked as PermissionError)."""

        @require_sepa_permission(SEPAPermissionLevel.CREATE, SEPAOperation.BATCH_CREATE)
        def boom():
            raise ValueError("boom-from-body")

        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="decboom")
        with self.as_user(user.name):
            with self.assertRaises(ValueError):
                boom()

    def test_require_role_allows_matching_role(self):
        @require_role(["Verenigingen Staff"])
        def staff_only():
            return "ok"

        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="rrstaff")
        with self.as_user(user.name):
            self.assertEqual(staff_only(), "ok")

    def test_require_role_blocks_non_matching_role(self):
        @require_role(["System Manager"])
        def admin_only():
            return "ok"

        user = self._make_user_with_role_profile("Verenigingen Member", prefix="rrmbr")
        with self.as_user(user.name):
            with self.assertRaises(frappe.PermissionError):
                admin_only()

    def test_require_role_blocks_guest(self):
        @require_role(["Verenigingen Staff"])
        def staff_only():
            return "ok"

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                staff_only()


class TestPermissionApiEndpoints(AuthorizationTestBase):
    """Whitelisted introspection endpoints."""

    def test_get_user_sepa_permissions_self(self):
        user = self._make_user_with_role_profile("Verenigingen Treasurer", prefix="apitreas")
        with self.as_user(user.name):
            result = get_user_sepa_permissions()
        self.assertTrue(result["success"])
        self.assertEqual(result["user"], user.name)
        self.assertIn("read", result["permissions"])
        self.assertIn("Verenigingen Treasurer", result["role_profiles"])
        # available_operations reflects real allow/deny per operation
        self.assertTrue(result["available_operations"]["batch_create"])
        self.assertFalse(result["available_operations"]["batch_delete"])

    def test_get_user_sepa_permissions_other_user_denied_for_non_admin(self):
        """A non-admin user querying another user's permissions is denied."""
        target = self._make_user_with_role_profile("Verenigingen Staff", prefix="apitarget")
        caller = self._make_user_with_role_profile("Verenigingen Staff", prefix="apicaller")
        # The endpoint deliberately logs the cross-user denial via log_error; mark it
        # expected so the Error Log guard doesn't flag this intended security event.
        self.expectErrorLog("Access denied")
        with self.as_user(caller.name):
            # The endpoint catches the PermissionError and returns success=False.
            result = get_user_sepa_permissions(user=target.name)
        self.assertFalse(result["success"])

    def test_check_sepa_operation_permission_valid_operation(self):
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="chkstaff")
        with self.as_user(user.name):
            result = check_sepa_operation_permission("batch_create")
        self.assertTrue(result["success"])
        self.assertTrue(result["allowed"])

    def test_check_sepa_operation_permission_denied(self):
        user = self._make_user_with_role_profile("Verenigingen Member", prefix="chkmbr")
        with self.as_user(user.name):
            result = check_sepa_operation_permission("batch_delete")
        self.assertTrue(result["success"])
        self.assertFalse(result["allowed"])

    def test_check_sepa_operation_permission_invalid_operation(self):
        result = check_sepa_operation_permission("not_a_real_operation")
        self.assertFalse(result["success"])
        self.assertFalse(result["allowed"])

    def test_check_sepa_operation_permission_bad_context_json(self):
        result = check_sepa_operation_permission("batch_create", context="{not valid json")
        self.assertFalse(result["success"])
        self.assertFalse(result["allowed"])

    def test_check_sepa_operation_permission_with_valid_context(self):
        """A well-formed context JSON is parsed and passed through to has_permission."""
        user = self._make_user_with_role_profile("Verenigingen Staff", prefix="chkctx")
        with self.as_user(user.name):
            result = check_sepa_operation_permission("analytics_view", context=json.dumps({"foo": "bar"}))
        self.assertTrue(result["success"])
        self.assertTrue(result["allowed"])


class TestGlobalAuthManager(AuthorizationTestBase):
    def test_get_auth_manager_is_singleton(self):
        self.assertIs(get_auth_manager(), get_auth_manager())
        self.assertIsInstance(get_auth_manager(), SEPAAuthorizationManager)
