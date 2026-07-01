# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Real integration tests for verenigingen/setup/public_document_creator_setup.py

Covers the public-document-creator provisioning flow: role creation with minimal
permissions, secure credential generation, User account creation (+ idempotency),
role assignment, Verenigingen Settings configuration, verification helpers, and the
whitelisted manual setup/verify API endpoints.

These tests exercise the real functions against the test DB (no business-logic
mocking). Because the module under test calls frappe.db.commit() internally, the
normal per-test rollback does NOT undo its writes, so tearDown explicitly removes
the created Role / User / Custom DocPerm records and restores the mutated
Verenigingen Settings Single value.
"""

import string

import frappe

from verenigingen.setup.public_document_creator_setup import (
    PUBLIC_CREATOR_ROLE,
    assign_public_creator_roles,
    configure_creation_user_in_settings,
    create_public_creator_account,
    ensure_public_creator_role_exists,
    generate_public_creator_email,
    generate_secure_password,
    setup_public_document_creator,
    setup_public_document_creator_manual,
    verify_public_document_creator_manual,
    verify_public_document_creator_setup,
    verify_role_permissions,
)
from verenigingen.tests.utils.base import VereningingenTestCase

MANAGED_DOCTYPES = ["Donor", "Donation", "Member", "Address", "Contact"]


class TestPublicDocumentCreatorSetup(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Capture the current Single value so we can restore it: the module commits
        # its mutation, defeating the per-test rollback.
        self._original_creation_user = frappe.db.get_single_value(
            "Verenigingen Settings", "creation_user"
        )
        # The shared Verenigingen Settings Single carries stale Account link values
        # in the test DB (accounts that don't exist here). configure_creation_user_in_settings
        # does a full document save(), which re-runs Frappe link validation and would
        # fail on those. Neutralise the broken links (capturing originals) so the
        # module's real save() can run; restored in tearDown.
        self._neutralized_links = self._neutralize_broken_single_links()
        # Snapshot the existing Custom DocPerm rows on the doctypes the module
        # touches. ensure_public_creator_role_exists routes through add_permission,
        # which (via copy_perms) materialises the standard perms into Custom DocPerm
        # for any doctype that had none. tearDown removes everything NOT in this
        # snapshot to revert the site's permission model exactly.
        self._managed_doctypes = ["Donor", "Donation", "Member", "Address", "Contact"]
        self._custom_docperm_snapshot = {
            dt: set(frappe.get_all("Custom DocPerm", filters={"parent": dt}, pluck="name"))
            for dt in self._managed_doctypes
        }

    def _neutralize_broken_single_links(self):
        meta = frappe.get_meta("Verenigingen Settings")
        settings = frappe.get_single("Verenigingen Settings")
        neutralized = {}
        for field in meta.get("fields"):
            if field.fieldtype == "Link" and field.options:
                value = settings.get(field.fieldname)
                if value and not frappe.db.exists(field.options, value):
                    neutralized[field.fieldname] = value
                    frappe.db.set_single_value("Verenigingen Settings", field.fieldname, None)
        if neutralized:
            frappe.db.commit()
        return neutralized

    def _make_user(self, email, first_name="Test", last_name="User"):
        """Insert and track a real System User fixture.

        Kept as a `_make_` helper so the permission bypass (needed because tests
        run as Administrator without going through the signup flow) stays out of
        test-method bodies, per the test-quality-enforcer contract.
        """
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    def tearDown(self):
        # Explicit cleanup of committed side effects, in dependency-safe order:
        # user first (references role), then the role's Custom DocPerms, then the role.
        try:
            for candidate in _all_creator_user_emails():
                if frappe.db.exists("User", candidate):
                    frappe.delete_doc("User", candidate, force=True, ignore_permissions=True)
        except Exception:
            pass

        try:
            # Remove every Custom DocPerm the test caused on the managed doctypes
            # (both the PUBLIC_CREATOR_ROLE rows and any copy_perms clones), so a
            # doctype that had zero Custom DocPerm before reverts to standard perms.
            for dt, before in getattr(self, "_custom_docperm_snapshot", {}).items():
                for name in frappe.get_all("Custom DocPerm", filters={"parent": dt}, pluck="name"):
                    if name not in before:
                        frappe.delete_doc("Custom DocPerm", name, force=True, ignore_permissions=True)
            # Any stragglers for the role on other doctypes.
            for perm in frappe.get_all(
                "Custom DocPerm", filters={"role": PUBLIC_CREATOR_ROLE}, pluck="name"
            ):
                frappe.delete_doc("Custom DocPerm", perm, force=True, ignore_permissions=True)
            if frappe.db.exists("Role", PUBLIC_CREATOR_ROLE):
                frappe.delete_doc("Role", PUBLIC_CREATOR_ROLE, force=True, ignore_permissions=True)
            frappe.clear_cache()
        except Exception:
            pass

        # Restore the Verenigingen Settings Single values the test/module mutated.
        try:
            frappe.db.set_single_value(
                "Verenigingen Settings", "creation_user", self._original_creation_user
            )
            for fieldname, value in getattr(self, "_neutralized_links", {}).items():
                frappe.db.set_single_value("Verenigingen Settings", fieldname, value)
            frappe.db.commit()
        except Exception:
            pass

        super().tearDown()

    # ------------------------------------------------------------------ #
    # generate_secure_password
    # ------------------------------------------------------------------ #
    def test_generate_secure_password_default_length(self):
        pwd = generate_secure_password()
        self.assertEqual(len(pwd), 16)

    def test_generate_secure_password_custom_length(self):
        pwd = generate_secure_password(24)
        self.assertEqual(len(pwd), 24)

    def test_generate_secure_password_uses_expected_alphabet(self):
        allowed = set(string.ascii_letters + string.digits + "!@#$%&*+-=?")
        pwd = generate_secure_password(64)
        self.assertTrue(set(pwd).issubset(allowed))

    def test_generate_secure_password_is_random(self):
        # Two independent draws should not collide (cryptographic randomness).
        self.assertNotEqual(generate_secure_password(), generate_secure_password())

    # ------------------------------------------------------------------ #
    # generate_public_creator_email
    # ------------------------------------------------------------------ #
    def test_generate_email_shape(self):
        email = generate_public_creator_email()
        self.assertTrue(email.startswith("public-creator@"))
        domain = email.split("@", 1)[1]
        # Underscores (illegal in a hostname) are sanitised; dots are preserved so
        # the FQDN remains a valid email domain.
        self.assertNotIn("_", domain)
        # The generated email must actually validate as an email address, otherwise
        # User creation downstream fails.
        from frappe.utils import validate_email_address

        self.assertEqual(validate_email_address(email), email)

    def test_generate_email_uniqueness_on_collision(self):
        base_email = generate_public_creator_email()
        # Create a User occupying the base email; next call must suffix -1.
        self._make_user(base_email, first_name="Collision", last_name="Holder")

        next_email = generate_public_creator_email()
        self.assertNotEqual(next_email, base_email)
        self.assertTrue(next_email.startswith("public-creator-1@"))

    # ------------------------------------------------------------------ #
    # ensure_public_creator_role_exists
    # ------------------------------------------------------------------ #
    def test_ensure_role_creates_role_and_permissions(self):
        result = ensure_public_creator_role_exists()
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(frappe.db.exists("Role", PUBLIC_CREATOR_ROLE))

        role = frappe.get_doc("Role", PUBLIC_CREATOR_ROLE)
        self.assertEqual(role.desk_access, 0)
        self.assertEqual(role.disabled, 0)

        # Every managed doctype gets a Custom DocPerm with read/write/create.
        for doctype in MANAGED_DOCTYPES:
            perm = frappe.db.get_value(
                "Custom DocPerm",
                {"parent": doctype, "role": PUBLIC_CREATOR_ROLE, "permlevel": 0},
                ["read", "write", "create", "delete"],
                as_dict=True,
            )
            self.assertIsNotNone(perm, msg=f"missing Custom DocPerm for {doctype}")
            self.assertEqual(perm.read, 1)
            self.assertEqual(perm.write, 1)
            self.assertEqual(perm.create, 1)
            self.assertEqual(perm.delete, 0)

    def test_ensure_role_preserves_other_roles_permissions_on_member(self):
        """Granting the public-creator role must NOT strip other roles' perms.

        Frappe treats a doctype's Custom DocPerm set as authoritative once ANY
        Custom DocPerm row exists, so a raw insert (without copy_perms) would drop
        every standard role's permission on Member/Donor/Donation. The fix routes
        through frappe.permissions.add_permission (which copies standard perms
        first). This asserts every standard create-role on Member survives.
        """
        standard_create_roles = {
            r.role
            for r in frappe.get_all(
                "DocPerm", filters={"parent": "Member", "create": 1}, fields=["role"]
            )
        }
        self.assertTrue(standard_create_roles, "expected Member to ship standard create perms")

        ensure_public_creator_role_exists()

        custom_create_roles = {
            r.role
            for r in frappe.get_all(
                "Custom DocPerm", filters={"parent": "Member", "create": 1}, fields=["role"]
            )
        }
        missing = standard_create_roles - custom_create_roles
        self.assertFalse(missing, msg=f"standard create-roles were dropped: {missing}")
        self.assertIn(PUBLIC_CREATOR_ROLE, custom_create_roles)

    def test_ensure_role_idempotent(self):
        first = ensure_public_creator_role_exists()
        self.assertTrue(first["success"])
        second = ensure_public_creator_role_exists()
        self.assertTrue(second["success"])
        self.assertEqual(second["message"], "Role already exists")
        # Idempotent: still exactly one role, one perm row per managed doctype.
        for doctype in MANAGED_DOCTYPES:
            count = frappe.db.count(
                "Custom DocPerm", {"parent": doctype, "role": PUBLIC_CREATOR_ROLE}
            )
            self.assertEqual(count, 1, msg=f"duplicate perms for {doctype}")

    # ------------------------------------------------------------------ #
    # create_public_creator_account
    # ------------------------------------------------------------------ #
    def test_create_account_creates_user(self):
        ensure_public_creator_role_exists()
        email = generate_public_creator_email()
        result = create_public_creator_account(email, generate_secure_password())
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(frappe.db.exists("User", email))

        user = frappe.get_doc("User", email)
        self.assertEqual(user.enabled, 1)
        self.assertTrue(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))
        # NOTE (reported finding): the module requests user_type="System User", but
        # Frappe downgrades the account to "Website User" because its only role
        # (PUBLIC_CREATOR_ROLE) has desk_access=0. We assert the account is a real,
        # enabled user with the role rather than the requested type to document the
        # divergence without hard-coding the buggy value.

    def test_create_account_idempotent(self):
        ensure_public_creator_role_exists()
        email = generate_public_creator_email()
        first = create_public_creator_account(email, generate_secure_password())
        self.assertTrue(first["success"])
        second = create_public_creator_account(email, generate_secure_password())
        self.assertTrue(second["success"])
        self.assertEqual(second["message"], "User already exists")

    # ------------------------------------------------------------------ #
    # assign_public_creator_roles
    # ------------------------------------------------------------------ #
    def test_assign_roles_adds_missing_role(self):
        ensure_public_creator_role_exists()
        email = generate_public_creator_email()
        # Create the user WITHOUT the role, then assign it.
        user = self._make_user(email, first_name="No", last_name="Role")
        self.assertFalse(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))

        result = assign_public_creator_roles(email)
        self.assertTrue(result["success"], msg=result)

        user.reload()
        self.assertTrue(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))

    def test_assign_roles_idempotent(self):
        ensure_public_creator_role_exists()
        email = generate_public_creator_email()
        create_public_creator_account(email, generate_secure_password())
        result = assign_public_creator_roles(email)
        self.assertTrue(result["success"])
        # Role appears exactly once, not duplicated.
        user = frappe.get_doc("User", email)
        count = sum(1 for r in user.roles if r.role == PUBLIC_CREATOR_ROLE)
        self.assertEqual(count, 1)

    # ------------------------------------------------------------------ #
    # configure_creation_user_in_settings
    # ------------------------------------------------------------------ #
    def test_configure_creation_user_in_settings(self):
        # creation_user is a Link to User, so it must reference a real account.
        user = self._make_user(
            "config-target@example.invalid", first_name="Config", last_name="Target"
        )

        result = configure_creation_user_in_settings(user.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "creation_user"),
            user.name,
        )

    # ------------------------------------------------------------------ #
    # verify_role_permissions
    # ------------------------------------------------------------------ #
    def test_verify_role_permissions_reports_missing_when_no_role(self):
        # Role/perms do not exist yet -> everything missing, not valid.
        results = verify_role_permissions()
        self.assertFalse(results["all_permissions_valid"])
        self.assertTrue(len(results["missing_permissions"]) > 0)

    def test_verify_role_permissions_valid_after_setup(self):
        ensure_public_creator_role_exists()
        results = verify_role_permissions()
        self.assertTrue(results["all_permissions_valid"], msg=results["missing_permissions"])
        self.assertEqual(results["missing_permissions"], [])
        for doctype in MANAGED_DOCTYPES:
            detail = results["permissions"][doctype]
            self.assertTrue(detail["exists"])
            self.assertEqual(sorted(detail["granted"]), sorted(["read", "write", "create"]))
            self.assertEqual(detail["missing"], [])

    # ------------------------------------------------------------------ #
    # setup_public_document_creator (end to end + idempotency)
    # ------------------------------------------------------------------ #
    def test_setup_end_to_end(self):
        result = setup_public_document_creator()
        self.assertTrue(result["success"], msg=result)
        email = result["user_email"]
        self.assertTrue(email.startswith("public-creator@"))
        self.assertEqual(len(result["user_password"]), 16)

        # Role, user, role assignment, and settings all wired up.
        self.assertTrue(frappe.db.exists("Role", PUBLIC_CREATOR_ROLE))
        self.assertTrue(frappe.db.exists("User", email))
        user = frappe.get_doc("User", email)
        self.assertTrue(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "creation_user"), email
        )

    def test_setup_rerun_reconfigures_without_duplicating_role(self):
        # Documents the ACTUAL re-run contract (reported finding: setup is NOT
        # email-idempotent). generate_public_creator_email() always returns a
        # not-yet-existing address, so a second full run spawns a *second* user
        # (public-creator-1@...) rather than reusing the first. What is stable:
        # the role is created once, and creation_user is repointed to the latest
        # user, which carries the role.
        first = setup_public_document_creator()
        self.assertTrue(first["success"], msg=first)
        second = setup_public_document_creator()
        self.assertTrue(second["success"], msg=second)

        # A fresh account is provisioned on the re-run (non-idempotent behavior).
        self.assertNotEqual(first["user_email"], second["user_email"])

        # Role is created exactly once (not duplicated) across both runs.
        self.assertEqual(frappe.db.count("Role", {"name": PUBLIC_CREATOR_ROLE}), 1)

        # Settings point at the most recent creation user, which has the role.
        configured = frappe.db.get_single_value("Verenigingen Settings", "creation_user")
        self.assertEqual(configured, second["user_email"])
        user = frappe.get_doc("User", configured)
        self.assertTrue(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))

    # ------------------------------------------------------------------ #
    # verify_public_document_creator_setup
    # ------------------------------------------------------------------ #
    def test_verify_setup_incomplete_before_setup(self):
        result = verify_public_document_creator_setup()
        self.assertTrue(result["success"], msg=result)
        self.assertFalse(result["verification"]["role_exists"])
        self.assertFalse(result["setup_complete"])
        self.assertFalse(result["full_setup_complete"])

    def test_verify_setup_complete_after_setup(self):
        setup_public_document_creator()
        result = verify_public_document_creator_setup()
        self.assertTrue(result["success"], msg=result)
        v = result["verification"]
        self.assertTrue(v["role_exists"])
        self.assertTrue(v["settings_exist"])
        self.assertTrue(v["creation_user_configured"])
        self.assertTrue(v["creation_user_exists"])
        self.assertTrue(v["creation_user_has_role"])
        self.assertTrue(v["permissions_valid"])
        self.assertTrue(result["setup_complete"])
        self.assertTrue(result["full_setup_complete"])

    # ------------------------------------------------------------------ #
    # Whitelisted manual API endpoints (security-decorated)
    # ------------------------------------------------------------------ #
    def test_setup_manual_endpoint(self):
        result = setup_public_document_creator_manual()
        # Plain dict passes through the security decorator unchanged.
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(frappe.db.exists("Role", PUBLIC_CREATOR_ROLE))

    def test_verify_manual_endpoint(self):
        setup_public_document_creator()
        result = verify_public_document_creator_manual()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["setup_complete"])


# ---------------------------------------------------------------------- #
# module-level cleanup helpers (kept out of the TestCase for reuse)
# ---------------------------------------------------------------------- #
def _all_creator_user_emails():
    """All possible creator emails this test suite may have created."""
    return frappe.get_all(
        "User", filters={"email": ["like", "public-creator%"]}, pluck="email"
    )
