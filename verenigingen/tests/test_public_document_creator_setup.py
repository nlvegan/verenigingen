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

import frappe

from verenigingen.setup.public_document_creator_setup import (
    PUBLIC_CREATOR_ROLE,
    assign_public_creator_roles,
    configure_creation_user_in_settings,
    create_public_creator_account,
    ensure_public_creator_role_exists,
    generate_public_creator_email,
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
        # Users a test inserted that setup's own commit would otherwise leave behind.
        self._control_users = []
        self._original_user = frappe.session.user
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
        frappe.set_user(self._original_user)
        # Explicit cleanup of committed side effects, in dependency-safe order:
        # user first (references role), then the role's Custom DocPerms, then the role.
        for candidate in [*self._control_users, *_all_creator_user_emails()]:
            try:
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
        result = create_public_creator_account(email)
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
        first = create_public_creator_account(email)
        self.assertTrue(first["success"])
        second = create_public_creator_account(email)
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
        create_public_creator_account(email)
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

        # Role, user, role assignment, and settings all wired up.
        self.assertTrue(frappe.db.exists("Role", PUBLIC_CREATOR_ROLE))
        self.assertTrue(frappe.db.exists("User", email))
        user = frappe.get_doc("User", email)
        self.assertTrue(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "creation_user"), email
        )

    def test_setup_rerun_reuses_the_existing_creator(self):
        # Setup runs on every fresh install and via the manual endpoint, so it must be
        # idempotent: a re-run reuses the creator instead of minting public-creator-N (#1645).
        first = setup_public_document_creator()
        self.assertTrue(first["success"], msg=first)
        users_before = set(_all_creator_user_emails())
        second = setup_public_document_creator()
        self.assertTrue(second["success"], msg=second)

        self.assertEqual(first["user_email"], second["user_email"])
        self.assertEqual(set(_all_creator_user_emails()), users_before, "a re-run created a user")

        self.assertEqual(frappe.db.count("Role", {"name": PUBLIC_CREATOR_ROLE}), 1)
        configured = frappe.db.get_single_value("Verenigingen Settings", "creation_user")
        self.assertEqual(configured, first["user_email"])

    # ------------------------------------------------------------------ #
    # #1670: the creator account must not be usable as a login
    #
    # The public flows only ever `frappe.set_user(creator)` in-process; nothing
    # needs a session, a password or an API key for it. Each test below tries one
    # way in, and each has a control (an ordinary user passes the same path) so a
    # refusal that is really "everyone is refused" cannot pass.
    # ------------------------------------------------------------------ #
    def _creator_after_setup(self):
        result = setup_public_document_creator()
        self.assertTrue(result["success"], msg=result)
        return result["user_email"]

    def _make_login_user(self, email):
        """An ordinary Website User with a known password (the control)."""
        from frappe.utils.password import update_password

        self._control_users.append(email)
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Control",
                "user_type": "Website User",
                "enabled": 1,
                "send_welcome_email": 0,
            }
        ).insert(ignore_permissions=True)
        update_password(user.name, "Zq9!control-pass-1670")
        return user.name

    def _password_login(self, user, password):
        """Real LoginManager authenticate + the on_login trigger, no HTTP request."""
        from frappe.auth import LoginManager

        manager = LoginManager.__new__(LoginManager)
        manager.user = manager.info = manager.full_name = manager.user_type = None
        # No HTTP request here, and the login-attempt tracker is keyed on the request IP.
        previous_ip = getattr(frappe.local, "request_ip", None)
        frappe.local.request_ip = "127.0.0.1"
        try:
            manager.authenticate(user=user, pwd=password)
            manager.run_trigger("on_login")
        finally:
            frappe.local.request_ip = previous_ip
        return manager.user

    def test_setup_leaves_the_creator_without_any_password(self):
        email = self._creator_after_setup()
        rows = frappe.db.sql("select fieldname from __Auth where doctype='User' and name=%s", email)
        self.assertEqual(rows, (), msg="the creator must hold no stored credential at all")

    def test_a_password_set_later_still_cannot_log_the_creator_in(self):
        from frappe.utils.password import update_password

        email = self._creator_after_setup()
        control = self._make_login_user("control-login-1670@example.invalid")
        self.assertEqual(self._password_login(control, "Zq9!control-pass-1670"), control)

        update_password(email, "Zq9!set-by-an-admin-1670")
        frappe.clear_cache()
        with self.assertRaises(frappe.AuthenticationError):
            self._password_login(email, "Zq9!set-by-an-admin-1670")

    def _authenticate_with_api_key(self, user):
        from frappe.auth import validate_api_key_secret, validate_auth_via_hooks
        from frappe.core.doctype.user.user import generate_keys

        secret = generate_keys(user)["api_secret"]
        key = frappe.db.get_value("User", user, "api_key")
        previous_manager = getattr(frappe.local, "login_manager", None)
        frappe.local.login_manager = frappe._dict(user="Guest")
        try:
            validate_api_key_secret(key, secret)
            self.assertEqual(frappe.session.user, user, "control: the key authenticated")
            validate_auth_via_hooks()
        finally:
            frappe.local.login_manager = previous_manager
            frappe.set_user(self._original_user)

    def test_an_api_key_cannot_authenticate_the_creator(self):
        email = self._creator_after_setup()
        control = self._make_login_user("control-key-1670@example.invalid")
        self._authenticate_with_api_key(control)

        frappe.clear_cache()
        with self.assertRaises(frappe.AuthenticationError):
            self._authenticate_with_api_key(email)

    def test_an_existing_session_of_the_creator_is_refused(self):
        from frappe.auth import validate_auth_via_hooks

        email = self._creator_after_setup()
        control = self._make_login_user("control-session-1670@example.invalid")
        frappe.clear_cache()
        try:
            frappe.set_user(control)
            validate_auth_via_hooks()
            frappe.set_user(email)
            with self.assertRaises(frappe.AuthenticationError):
                validate_auth_via_hooks()
        finally:
            frappe.set_user(self._original_user)

    def test_the_refusal_is_the_same_as_a_wrong_password(self):
        """Same exception, same response message, same Activity Log row as a bad password."""
        from frappe.utils.password import update_password

        email = self._creator_after_setup()
        update_password(email, "Zq9!set-by-an-admin-1670")
        frappe.clear_cache()
        control = self._make_login_user("control-oracle-1670@example.invalid")

        def attempt(user, password):
            frappe.local.response.pop("message", None)
            before = frappe.db.count("Activity Log", {"operation": "Login", "status": "Failed"})
            with self.assertRaises(frappe.AuthenticationError):
                self._password_login(user, password)
            after = frappe.db.count("Activity Log", {"operation": "Login", "status": "Failed"})
            return frappe.local.response.get("message"), after - before

        wrong = attempt(control, "not-the-password")
        refused = attempt(email, "Zq9!set-by-an-admin-1670")
        self.assertEqual(refused, wrong)
        self.assertEqual(wrong, ("Invalid login credentials", 1))

    @staticmethod
    def _session_count(user):
        return frappe.db.sql("select count(*) from tabSessions where user=%s", user)[0][0]

    def _open_session_for(self, user):
        """A real session row, written by Frappe's own Session.insert_session_record.

        Session() itself needs an HTTP request (cookies), which a test does not have, so the
        record it would have built is populated by hand and inserted the way a login does.
        """
        from frappe.sessions import Session, get_expiry_period

        session = Session.__new__(Session)
        session.sid = frappe.generate_hash()
        session.user = user
        session.data = frappe._dict(
            user=user,
            sid=session.sid,
            data=frappe._dict(
                user=user,
                session_ip="127.0.0.1",
                last_updated=frappe.utils.now(),
                creation=frappe.utils.now(),
                session_expiry=get_expiry_period(),
                full_name="Public Document Creator",
                user_type="Website User",
            ),
        )
        session.insert_session_record()

    def test_hardening_strips_a_creator_that_already_has_credentials(self):
        """A site set up before #1670 has a password, an API key, a session and a reset key."""
        from frappe.core.doctype.user.user import generate_keys
        from frappe.utils.password import update_password

        from verenigingen.setup.public_document_creator_setup import harden_public_document_creator

        email = self._creator_after_setup()
        update_password(email, "Zq9!legacy-password-1670")
        generate_keys(email)
        frappe.db.set_value("User", email, "reset_password_key", "legacy-reset-key")
        self.assertTrue(frappe.db.get_value("User", email, "api_key"), "precondition")
        self._open_session_for(email)
        self.assertEqual(self._session_count(email), 1, "precondition: a live session exists")

        harden_public_document_creator()

        self.assertEqual(
            frappe.db.sql("select fieldname from __Auth where doctype='User' and name=%s", email), ()
        )
        self.assertFalse(frappe.db.get_value("User", email, "api_key"))
        self.assertFalse(frappe.db.get_value("User", email, "reset_password_key"))
        self.assertEqual(self._session_count(email), 0)
        # What the public flows need is untouched.
        user = frappe.get_doc("User", email)
        self.assertEqual(user.enabled, 1)
        self.assertTrue(any(r.role == PUBLIC_CREATOR_ROLE for r in user.roles))
        self.assertEqual(frappe.db.get_single_value("Verenigingen Settings", "creation_user"), email)

    def test_hardening_leaves_a_staff_user_that_merely_matches_the_prefix_alone(self):
        from frappe.utils.password import check_password, update_password

        from verenigingen.setup.public_document_creator_setup import harden_public_document_creator

        self._creator_after_setup()
        staff = self._make_user("public-creator-staff-1670@example.invalid")
        update_password(staff.name, "Zq9!staff-password-1670")
        harden_public_document_creator()
        self.assertEqual(check_password(staff.name, "Zq9!staff-password-1670"), staff.name)

    def test_the_hardening_hook_is_wired_into_migrate(self):
        from frappe import get_hooks

        frappe.clear_cache()
        self.assertIn(
            "verenigingen.setup.public_document_creator_setup.harden_public_document_creator",
            get_hooks("after_migrate"),
        )

    # ------------------------------------------------------------------ #
    # #1670: the public flows impersonate the creator IN-PROCESS and must keep doing so.
    # (They are exercised end to end, as Guest, by test_guest_donation_flow and
    # test_application_submission_validation; neither goes through an auth hook.)
    # ------------------------------------------------------------------ #
    def test_in_process_impersonation_of_the_creator_still_works(self):
        from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

        creator = self._creator_after_setup()
        frappe.clear_cache()
        try:
            frappe.set_user("Guest")
            system_user = get_system_user_for_operation("public creator lockdown test")
            self.assertEqual(system_user, creator)
            with secure_user_context(system_user, "public creator lockdown test"):
                self.assertEqual(frappe.session.user, creator)
                contact = frappe.get_doc({"doctype": "Contact", "first_name": "Lockdown1670"}).insert()
        finally:
            frappe.set_user(self._original_user)
        self.track_doc("Contact", contact.name)
        self.assertEqual(contact.owner, creator)

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
