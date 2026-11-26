# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
#1680: the webhook service user must not be usable as a login.

Measured on test_site_5 over HTTP (werkzeug Client against frappe.app.application) before the
fix: POST /api/method/login as `webhook-user@<site>` with the password setup stored returned 200
"Logged In", and the session then read Contact, Customer and User through /api/resource.
Every webhook handler (Mollie, ING Checkout, Ponto) only does `frappe.set_user(webhook_user)`
in-process (`require_service_user` / `get_service_user`); nothing logs in as it. So, as for the
public document creator (#1670), the account holds no credential and is refused on every
login and every request.

These tests drive Frappe's own LoginManager / auth hooks IN-PROCESS (no HTTP request), the
way test_public_document_creator_setup does. setup_webhook_user() commits, so tearDown deletes
what the tests created and restores the Payments Settings Single.
"""

import frappe
from frappe.utils.password import update_password

from verenigingen.setup import webhook_user_setup as w
from verenigingen.tests.utils.base import VereningingenTestCase

SETTINGS = "Verenigingen Payments Settings"
WEBHOOK_ROLE = "Verenigingen Webhook User"
# Shaped like generate_webhook_user_email() output (webhook-user[-N]@<domain>) but on a
# domain no real site uses, so the tests never touch the site's canonical webhook user.
WEBHOOK_1680 = "webhook-user-16801@whu-1680.example.invalid"
CONTROL_PASSWORD = "Zq9!control-pass-1680"


class TestWebhookUserCannotAuthenticate1680(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._original_user = frappe.session.user
        self._original_webhook_user = frappe.db.get_single_value(SETTINGS, "webhook_user")
        self._created_1680 = []

    def tearDown(self):
        frappe.set_user(self._original_user)
        frappe.db.rollback()
        for email in self._created_1680:
            if frappe.db.exists("User", email):
                for contact in frappe.get_all("Contact", filters={"user": email}, pluck="name"):
                    frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
                frappe.delete_doc("User", email, force=True, ignore_permissions=True)
        value = self._original_webhook_user
        if value and not frappe.db.exists("User", value):
            value = None
        frappe.db.set_single_value(SETTINGS, "webhook_user", value)
        frappe.db.commit()
        super().tearDown()

    # ---- fixtures ------------------------------------------------------------------

    def _webhook_user_after_setup(self):
        """The REAL setup flow, pointed at a throwaway address through the setting it honours."""
        frappe.db.set_single_value(SETTINGS, "webhook_user", WEBHOOK_1680)
        self._created_1680.append(WEBHOOK_1680)
        result = self._setup_result_1680 = w.setup_webhook_user()
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["webhook_user_email"], WEBHOOK_1680)
        self.assertIn(WEBHOOK_ROLE, frappe.get_roles(WEBHOOK_1680), "precondition: holds the role")
        return WEBHOOK_1680

    def _make_user_1680(self, email, roles=(), password=CONTROL_PASSWORD):
        self._created_1680.append(email)
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Control",
                "user_type": "Website User",
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in roles],
            }
        ).insert(ignore_permissions=True)
        if password:
            update_password(user.name, password)
        return user.name

    @staticmethod
    def _auth_rows_1680(user):
        return frappe.db.sql("select fieldname from __Auth where doctype='User' and name=%s", user)

    @staticmethod
    def _password_login_1680(user, password):
        """Real LoginManager authenticate + the on_login trigger, no HTTP request."""
        from frappe.auth import LoginManager

        manager = LoginManager.__new__(LoginManager)
        manager.user = manager.info = manager.full_name = manager.user_type = None
        previous_ip = getattr(frappe.local, "request_ip", None)
        frappe.local.request_ip = "127.0.0.1"
        try:
            manager.authenticate(user=user, pwd=password)
            manager.run_trigger("on_login")
        finally:
            frappe.local.request_ip = previous_ip
        return manager.user

    def _authenticate_with_api_key_1680(self, user):
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

    # ---- the account holds no credential --------------------------------------------

    def test_setup_leaves_the_webhook_user_without_any_password(self):
        email = self._webhook_user_after_setup()
        self.assertEqual(self._auth_rows_1680(email), (), msg="no stored credential at all")

    def test_setup_does_not_report_a_password(self):
        self._webhook_user_after_setup()
        self.assertNotIn("webhook_password", self._setup_result_1680)

    # ---- every way in is refused, with a control that is let through -----------------

    def test_a_password_set_later_cannot_log_the_webhook_user_in(self):
        email = self._webhook_user_after_setup()
        control = self._make_user_1680("control-login-1680@example.invalid")
        self.assertEqual(self._password_login_1680(control, CONTROL_PASSWORD), control)

        update_password(email, "Zq9!set-by-an-admin-1680")
        frappe.clear_cache()
        with self.assertRaises(frappe.AuthenticationError):
            self._password_login_1680(email, "Zq9!set-by-an-admin-1680")

    def test_an_api_key_cannot_authenticate_the_webhook_user(self):
        email = self._webhook_user_after_setup()
        control = self._make_user_1680("control-key-1680@example.invalid")
        self._authenticate_with_api_key_1680(control)

        frappe.clear_cache()
        with self.assertRaises(frappe.AuthenticationError):
            self._authenticate_with_api_key_1680(email)

    def test_an_existing_session_of_the_webhook_user_is_refused(self):
        from frappe.auth import validate_auth_via_hooks

        email = self._webhook_user_after_setup()
        control = self._make_user_1680("control-session-1680@example.invalid")
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
        """Same exception, response message and Activity Log row as a bad password."""
        email = self._webhook_user_after_setup()
        update_password(email, "Zq9!set-by-an-admin-1680")
        frappe.clear_cache()
        control = self._make_user_1680("control-oracle-1680@example.invalid")

        def attempt(user, password):
            frappe.local.response.pop("message", None)
            before = frappe.db.count("Activity Log", {"operation": "Login", "status": "Failed"})
            with self.assertRaises(frappe.AuthenticationError):
                self._password_login_1680(user, password)
            after = frappe.db.count("Activity Log", {"operation": "Login", "status": "Failed"})
            return frappe.local.response.get("message"), after - before

        wrong = attempt(control, "not-the-password")
        refused = attempt(email, "Zq9!set-by-an-admin-1680")
        self.assertEqual(refused, wrong)
        self.assertEqual(wrong, ("Invalid login credentials", 1))

    # ---- a site set up before the fix converges on migrate -----------------------------

    def test_hardening_strips_a_webhook_user_that_already_has_credentials(self):
        from frappe.core.doctype.user.user import generate_keys

        from verenigingen.setup.webhook_user_setup import harden_webhook_user

        email = self._webhook_user_after_setup()
        update_password(email, "Zq9!legacy-password-1680")
        generate_keys(email)
        frappe.db.set_value("User", email, "reset_password_key", "legacy-reset-key")
        self.assertTrue(frappe.db.get_value("User", email, "api_key"), "precondition")

        harden_webhook_user()

        self.assertEqual(self._auth_rows_1680(email), ())
        self.assertFalse(frappe.db.get_value("User", email, "api_key"))
        self.assertFalse(frappe.db.get_value("User", email, "reset_password_key"))
        # What the gateways need is untouched.
        user = frappe.get_doc("User", email)
        self.assertEqual(user.enabled, 1)
        self.assertTrue(any(r.role == WEBHOOK_ROLE for r in user.roles))
        self.assertEqual(frappe.db.get_single_value(SETTINGS, "webhook_user"), email)

    def test_hardening_leaves_look_alikes_alone(self):
        from verenigingen.setup.webhook_user_setup import harden_webhook_user

        self._webhook_user_after_setup()
        staff = self._make_user_1680("webhook-ops-1680@example.invalid", roles=[WEBHOOK_ROLE])
        no_role = self._make_user_1680("webhook-user-16802@example.invalid")
        harden_webhook_user()
        self.assertTrue(self._auth_rows_1680(staff), "an ordinary holder of the role keeps its password")
        self.assertTrue(self._auth_rows_1680(no_role), "the address alone does not identify the account")

    def test_a_staff_user_holding_the_role_with_another_address_can_still_log_in(self):
        self._webhook_user_after_setup()
        staff = self._make_user_1680("webhook-ops-16803@example.invalid", roles=[WEBHOOK_ROLE])
        self.assertEqual(self._password_login_1680(staff, CONTROL_PASSWORD), staff)

    def test_a_user_with_the_address_but_without_the_role_can_still_log_in(self):
        self._webhook_user_after_setup()
        same_address = self._make_user_1680("webhook-user-16804@example.invalid")
        self.assertEqual(self._password_login_1680(same_address, CONTROL_PASSWORD), same_address)

    # ---- wiring, and what must keep working ---------------------------------------------

    def test_the_refusal_and_hardening_are_wired_in(self):
        from frappe import get_hooks

        frappe.clear_cache()
        refuse = "verenigingen.setup.webhook_user_setup.refuse_webhook_user_authentication"
        self.assertIn(refuse, get_hooks("on_login"))
        self.assertIn(refuse, get_hooks("auth_hooks"))
        self.assertIn(
            "verenigingen.setup.webhook_user_setup.harden_webhook_user", get_hooks("after_migrate")
        )

    def test_the_gateways_can_still_assume_the_webhook_user_in_process(self):
        from verenigingen.utils.service_user import require_service_user

        email = self._webhook_user_after_setup()
        frappe.clear_cache()
        try:
            frappe.set_user("Guest")
            service_user = require_service_user(SETTINGS, "webhook_user", "1680 test")
            self.assertEqual(service_user, email)
            frappe.set_user(service_user)
            self.assertEqual(frappe.session.user, email)
        finally:
            frappe.set_user(self._original_user)
