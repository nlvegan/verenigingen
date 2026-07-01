# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for verenigingen/setup/webhook_user_setup.py

These are REAL integration tests: real User docs are created in the test DB and
the Verenigingen Payments Settings Single is really mutated. Because the module
under test commits internally (frappe.db.commit()), created docs survive the
per-test rollback, so:
  - every created webhook User is registered via self.track_doc() for deletion
  - the Payments Settings Single's webhook_user field is captured in setUp and
    restored (and re-committed) in tearDown to prevent leakage across tests.

No business logic is mocked.
"""

import string

import frappe

from verenigingen.setup import webhook_user_setup as w
from verenigingen.tests.utils.base import VereningingenTestCase

SETTINGS_DOCTYPE = "Verenigingen Payments Settings"
SETTINGS_NAME = "Verenigingen Payments Settings"
WEBHOOK_ROLE = "Verenigingen Webhook User"
PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%&*+-=?"


class TestWebhookUserSetup(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Capture the original webhook_user so tearDown can restore the Single.
        self._original_webhook_user = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        # Start each test from a clean, unconfigured state so verify_* is deterministic.
        self._set_settings_webhook_user(None)

    @classmethod
    def tearDownClass(cls):
        # Final best-effort sweep of any webhook users left behind by lock
        # contention during a run (the live veg11 site's scheduler/workers can
        # hold row locks). Harmless on an isolated CI DB where nothing leaks.
        cls._sweep_webhook_users()
        super().tearDownClass()

    def tearDown(self):
        # Restore the Single before base cleanup runs.
        self._set_settings_webhook_user(self._original_webhook_user)
        # Take ownership of webhook-User cleanup: delete them here (best-effort,
        # tolerating lock deadlocks/timeouts) and drop them from the tracked-doc
        # list so the base tearDown does not re-attempt a delete. The base cleanup
        # only retries lock *timeouts*, not deadlocks (which would propagate and
        # fail the test); deleting a User unlinks tabContact in on_trash, which can
        # deadlock/time-out against the site's live worker transactions.
        for doc_info in list(self._test_docs):
            if doc_info.get("doctype") == "User":
                self._delete_webhook_user(doc_info["name"])
        self._test_docs = [d for d in self._test_docs if d.get("doctype") != "User"]
        super().tearDown()

    # ---- helpers -----------------------------------------------------------

    def _set_settings_webhook_user(self, value):
        """Directly persist the Single's webhook_user field (bypasses hooks)."""
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "webhook_user", value)
        frappe.db.commit()

    @staticmethod
    def _delete_webhook_user(email, retries=6):
        """Best-effort delete of a webhook User + linked Contact, tolerating locks.

        Never raises: a transient lock on the contended dev site must not fail an
        otherwise-passing test. Leftovers are swept in tearDownClass.
        """
        import time

        for attempt in range(retries):
            try:
                frappe.db.rollback()
                for contact in frappe.get_all("Contact", filters={"user": email}, pluck="name"):
                    frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
                if frappe.db.exists("User", email):
                    frappe.delete_doc("User", email, force=True, ignore_permissions=True)
                frappe.db.commit()
                return
            except Exception:
                frappe.db.rollback()
                if attempt == retries - 1:
                    return  # best-effort; leave for the class-level sweep
                time.sleep(0.5)

    @classmethod
    def _sweep_webhook_users(cls):
        for email in frappe.get_all("User", filters={"email": ["like", "webhook-user%"]}, pluck="name"):
            cls._delete_webhook_user(email)

    def _track_if_exists(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    # ---- generate_webhook_user_email --------------------------------------

    def test_generate_webhook_user_email_is_valid_and_dotted(self):
        """Email must be a Frappe-valid address (dotted domain), not dot-stripped."""
        email = w.generate_webhook_user_email()
        self.assertTrue(email.startswith("webhook-user"))
        self.assertIn("@", email)
        domain = email.split("@", 1)[1]
        # Regression guard for the dot-stripping bug: the domain MUST contain a dot,
        # otherwise User creation fails "not a valid Email Address".
        self.assertIn(".", domain, f"Domain {domain!r} has no dot; would be an invalid email")
        self.assertNotIn("_", domain, "Underscores are invalid in email domains")
        # Frappe must accept it as a real email address.
        frappe.utils.validate_email_address(email, throw=True)

    def test_generate_webhook_user_email_increments_on_collision(self):
        """When the base email already exists, a numbered suffix is used."""
        base = w.generate_webhook_user_email()
        result = w.create_webhook_user_account(base, w.generate_secure_password())
        self.assertTrue(result["success"], result)
        self._track_if_exists(base)

        # Now the base exists -> generator must return a different, incremented email.
        second = w.generate_webhook_user_email()
        self.assertNotEqual(second, base)
        self.assertFalse(frappe.db.exists("User", second))

    # ---- generate_secure_password -----------------------------------------

    def test_generate_secure_password_default_length_and_charset(self):
        pw = w.generate_secure_password()
        self.assertEqual(len(pw), 16)
        for ch in pw:
            self.assertIn(ch, PASSWORD_ALPHABET, f"Unexpected char {ch!r} in password")

    def test_generate_secure_password_custom_length(self):
        pw = w.generate_secure_password(length=32)
        self.assertEqual(len(pw), 32)
        pw0 = w.generate_secure_password(length=0)
        self.assertEqual(pw0, "")

    def test_generate_secure_password_is_unique(self):
        passwords = {w.generate_secure_password() for _ in range(50)}
        # 50 cryptographically random 16-char passwords must not collide.
        self.assertEqual(len(passwords), 50)

    # ---- create_webhook_user_account --------------------------------------

    def test_create_webhook_user_account_creates_real_user(self):
        email = w.generate_webhook_user_email()
        result = w.create_webhook_user_account(email, w.generate_secure_password())
        self.assertTrue(result["success"], result)
        self._track_if_exists(email)

        self.assert_doc_exists("User", email)
        user = frappe.get_doc("User", email)
        self.assertEqual(user.enabled, 1)
        # NOTE: the module requests user_type "System User", but Frappe normalises
        # this based on the roles' desk access. The "Verenigingen Webhook User" role
        # has no desk access, so Frappe stores it as "Website User". Assert it is a
        # valid user type rather than the requested value.
        self.assertIn(user.user_type, ("System User", "Website User"))
        self.assertEqual(user.first_name, "Webhook")
        self.assertTrue(any(r.role == WEBHOOK_ROLE for r in user.roles))

    def test_create_webhook_user_account_idempotent_same_email(self):
        """Re-creating with an existing email is a no-op, not a duplicate/error."""
        email = w.generate_webhook_user_email()
        first = w.create_webhook_user_account(email, w.generate_secure_password())
        self.assertTrue(first["success"], first)
        self._track_if_exists(email)

        second = w.create_webhook_user_account(email, w.generate_secure_password())
        self.assertTrue(second["success"], second)
        self.assertIn("already exists", second["message"])
        # Still exactly one such user.
        self.assertEqual(frappe.db.count("User", {"email": email}), 1)

    # ---- assign_webhook_roles ---------------------------------------------

    def test_assign_webhook_roles_sets_role_and_profiles(self):
        email = w.generate_webhook_user_email()
        w.create_webhook_user_account(email, w.generate_secure_password())
        self._track_if_exists(email)

        result = w.assign_webhook_roles(email)
        self.assertTrue(result["success"], result)

        user = frappe.get_doc("User", email)
        self.assertTrue(any(r.role == WEBHOOK_ROLE for r in user.roles))
        self.assertEqual(user.role_profile_name, WEBHOOK_ROLE)
        self.assertEqual(user.module_profile, WEBHOOK_ROLE)

    def test_assign_webhook_roles_does_not_duplicate_role(self):
        email = w.generate_webhook_user_email()
        w.create_webhook_user_account(email, w.generate_secure_password())
        self._track_if_exists(email)

        w.assign_webhook_roles(email)
        w.assign_webhook_roles(email)  # run twice

        user = frappe.get_doc("User", email)
        webhook_roles = [r for r in user.roles if r.role == WEBHOOK_ROLE]
        self.assertEqual(len(webhook_roles), 1, "Webhook role must not be duplicated")

    # ---- configure_webhook_user_in_settings -------------------------------

    def test_configure_webhook_user_in_settings(self):
        email = w.generate_webhook_user_email()
        w.create_webhook_user_account(email, w.generate_secure_password())
        self._track_if_exists(email)

        result = w.configure_webhook_user_in_settings(email)
        self.assertTrue(result["success"], result)

        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user"), email)

    # ---- verify_webhook_user_setup ----------------------------------------

    def test_verify_reports_incomplete_when_unconfigured(self):
        self._set_settings_webhook_user(None)
        result = w.verify_webhook_user_setup()
        self.assertTrue(result["success"], result)
        self.assertFalse(result["setup_complete"])
        v = result["verification"]
        self.assertTrue(v["settings_exist"])  # the Single exists
        self.assertFalse(v["webhook_user_configured"])

    def test_verify_reports_complete_after_full_setup(self):
        email = w.generate_webhook_user_email()
        w.create_webhook_user_account(email, w.generate_secure_password())
        self._track_if_exists(email)
        w.assign_webhook_roles(email)
        w.configure_webhook_user_in_settings(email)

        result = w.verify_webhook_user_setup()
        self.assertTrue(result["success"], result)
        self.assertTrue(result["setup_complete"], result)
        v = result["verification"]
        self.assertTrue(v["webhook_user_exists"])
        self.assertTrue(v["webhook_user_has_role"])
        self.assertTrue(v["webhook_user_has_profile"])
        self.assertEqual(v["webhook_user_email"], email)

    # ---- setup_webhook_user (main entrypoint) -----------------------------

    def test_setup_webhook_user_end_to_end(self):
        result = w.setup_webhook_user()
        # Track whatever user got configured so tearDown deletes it.
        configured = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self._track_if_exists(configured)

        self.assertTrue(result["success"], result)
        self.assertTrue(result["webhook_user_email"])
        self.assertTrue(result["webhook_password"])
        self.assertEqual(result["webhook_user_email"], configured)

        # Full verification must report complete after the entrypoint runs.
        verify = w.verify_webhook_user_setup()
        self.assertTrue(verify["setup_complete"], verify)

    def test_setup_webhook_user_run_twice_does_not_error(self):
        """Running setup twice must not error. NOTE: because the email generator
        always produces a fresh unique email, the second run creates a SECOND
        webhook user rather than reusing the first (see reported design issue).
        This test documents that observed behaviour."""
        first = w.setup_webhook_user()
        first_email = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self._track_if_exists(first_email)
        self.assertTrue(first["success"], first)

        second = w.setup_webhook_user()
        second_email = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self._track_if_exists(second_email)
        self.assertTrue(second["success"], second)

        # Neither run errored. Both users exist.
        self.assertTrue(frappe.db.exists("User", first_email))
        self.assertTrue(frappe.db.exists("User", second_email))

    # ---- get_webhook_credentials_for_display ------------------------------

    def test_get_webhook_credentials_for_display(self):
        # Unconfigured -> failure with message.
        self._set_settings_webhook_user(None)
        unconfigured = w.get_webhook_credentials_for_display()
        self.assertFalse(unconfigured["success"])

        # Configured -> returns email but never a password.
        email = w.generate_webhook_user_email()
        w.create_webhook_user_account(email, w.generate_secure_password())
        self._track_if_exists(email)
        w.configure_webhook_user_in_settings(email)

        result = w.get_webhook_credentials_for_display()
        self.assertTrue(result["success"], result)
        self.assertEqual(result["webhook_user_email"], email)
        self.assertNotIn("webhook_password", result)

    # ---- whitelisted / security-decorated manual endpoints ----------------

    def test_manual_endpoints_return_dicts(self):
        """The @high_security_api endpoints must return plain dicts (as Admin)."""
        setup_result = w.setup_webhook_user_manual()
        configured = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self._track_if_exists(configured)
        self.assertIsInstance(setup_result, dict)
        self.assertTrue(setup_result["success"], setup_result)

        verify_result = w.verify_webhook_user_setup_manual()
        self.assertIsInstance(verify_result, dict)
        self.assertTrue(verify_result["success"], verify_result)
        self.assertTrue(verify_result["setup_complete"], verify_result)

        creds_result = w.get_webhook_credentials_manual()
        self.assertIsInstance(creds_result, dict)
        self.assertTrue(creds_result["success"], creds_result)
        self.assertEqual(creds_result["webhook_user_email"], configured)
