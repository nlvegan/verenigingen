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
from verenigingen.tests.harness_logger import get_harness_logger
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
        # ...but the sweep deletes the site's CANONICAL webhook user too -- this
        # suite mints it by design, since generate_webhook_user_email() is
        # deterministic per site -- while the last tearDown restored the Single to
        # the captured value that named it. Re-run the guarded restore afterwards
        # so the sweep cannot leave a dangling Link behind it (#513).
        cls._restore_settings_webhook_user(
            frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        )
        super().tearDownClass()

    def tearDown(self):
        # Restore the Single before base cleanup runs.
        self._restore_settings_webhook_user(self._original_webhook_user)
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

    @classmethod
    def _set_settings_webhook_user(cls, value):
        """Directly persist the Single's webhook_user field (bypasses hooks).

        Deliberately unguarded: three tests below plant an address whose User does
        not exist, because that is the state they are about (a configured user that
        was deleted). Use ``_restore_settings_webhook_user`` for cleanup.
        """
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "webhook_user", value)
        frappe.db.commit()

    @classmethod
    def _restore_settings_webhook_user(cls, value):
        """Put back a captured webhook_user -- but only if its User still exists.

        #513: this suite deletes every webhook User it creates, including the
        site's canonical one, and then restored the Single to the value captured
        in setUp -- which named exactly that user. The result was a dangling Link
        that survived the run, and every later `Verenigingen Payments Settings`
        `.save()` on that site then threw "Could not find Webhook User". Measured
        on test_site_4: 21 green tests here took the Single from
        referent_exists=True to referent_exists=False, and the next module's
        setUpClass swallowed the resulting failure 12 times in 14 tests.

        Clearing is the correct fallback, not a workaround: an unset webhook_user
        is a state production handles (`get_service_user` falls back to
        Administrator, `verify_webhook_user_setup` reports incomplete). A dangling
        one is invalid state that breaks an unrelated Single's every save.
        """
        if value and not frappe.db.exists("User", value):
            value = None
        cls._set_settings_webhook_user(value)

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
        # REFUSE to sweep on a non-test site. This deletes every webhook-user% User
        # on whatever site the suite runs against, and the webhook service user is
        # now a real dependency: gateway services fall back to Administrator without
        # it (get_service_user), silently, until the next migrate re-creates it.
        # The comment above notes this suite has been pointed at the live site before.
        site = getattr(frappe.local, "site", "") or ""
        if not (site.startswith("test_site") or site.endswith(".localhost") or frappe.conf.get("developer_mode")):
            # get_harness_logger, NOT frappe.logger(): this is the only record that
            # the sweep was skipped entirely, and a bare logger drops .warning() on
            # level under bench run-tests.
            get_harness_logger("webhook-user-setup").warning(
                "Refusing to sweep webhook users on non-test site %r", site
            )
            return
        for email in frappe.get_all("User", filters={"email": ["like", "webhook-user%"]}, pluck="name"):
            cls._delete_webhook_user(email)

    def _track_if_exists(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    # ---- the Single this suite must not corrupt ---------------------------

    def test_restore_never_reinstates_a_webhook_user_that_no_longer_exists(self):
        """#513: this suite left the Single naming a User it had just deleted.

        `Verenigingen Payments Settings.webhook_user` is a Link, so a dangling
        value makes EVERY later save() of that Single throw "Could not find Webhook
        User" -- which is what defeated the SEPA setup in four other test classes
        and was swallowed there. The restore must not put back a value whose
        referent is gone.
        """
        ghost = "webhook-user-513-restore-pin@example.invalid"
        self.assertFalse(frappe.db.exists("User", ghost), "precondition: no such User")

        self._restore_settings_webhook_user(ghost)
        self.assertFalse(
            frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user"),
            "a captured value whose User is gone must be cleared, not reinstated",
        )

        # ...and a value that IS still valid is genuinely restored, so the guard
        # has not been turned into "always clear".
        live = w.generate_webhook_user_email()
        self.assertTrue(w.create_webhook_user_account(live, w.generate_secure_password())["success"])
        self._track_if_exists(live)
        self._restore_settings_webhook_user(live)
        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user"), live)

    def test_the_single_is_left_consistent_after_a_users_deletion(self):
        """The end-to-end shape of the leak, without waiting for tearDownClass.

        Configure the canonical user, delete it the way the class-level sweep
        does, then run the restore the teardown runs. What must NOT survive is a
        setting naming a deleted User.
        """
        email = w.generate_webhook_user_email()
        self.assertTrue(w.create_webhook_user_account(email, w.generate_secure_password())["success"])
        w.configure_webhook_user_in_settings(email)
        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user"), email)

        self._delete_webhook_user(email)
        self.assertFalse(frappe.db.exists("User", email), "precondition: the sweep removed it")

        self._restore_settings_webhook_user(email)

        configured = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self.assertFalse(
            configured and not frappe.db.exists("User", configured),
            f"the Single still names a deleted User: {configured!r}",
        )
        # And the Single can be saved again -- the property the other four test
        # classes actually depend on. Saved as the acting user, without
        # ignore_permissions: a bypass here would also bypass _validate_links,
        # which is the exact check being asserted.
        settings = frappe.get_single(SETTINGS_DOCTYPE)
        settings.save()

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

    def test_generate_webhook_user_email_is_deterministic(self):
        """The same site must always resolve to the same address.

        This previously asserted the OPPOSITE -- that an existing user causes a
        numbered suffix -- which pinned the bug: the generator walked a counter
        *while the user existed*, so it deliberately returned an address that did
        not exist yet. create_webhook_user_account's existence check could never
        fire, every run minted a new user, and setup could therefore never be made
        to converge (which is why it could only live in after_install).
        """
        base = w.generate_webhook_user_email()
        result = w.create_webhook_user_account(base, w.generate_secure_password())
        self.assertTrue(result["success"], result)
        self._track_if_exists(base)

        # Pin the precondition: the old generator's counter only fired when the user
        # actually existed, so without this the test would pass against a no-op
        # create and prove nothing.
        self.assertTrue(frappe.db.exists("User", base), "precondition: the user must exist")

        # Now that the user exists, the generator must still resolve to it.
        self.assertEqual(w.generate_webhook_user_email(), base)

    def test_generate_webhook_user_email_prefers_the_configured_user(self):
        """A configured address wins, so a deleted user is recreated in place.

        On a real site the configured user had been deleted, leaving the setting
        pointing at a nonexistent account. get_service_user() treats that exactly
        like an unset one (frappe.db.get_value returns None for a missing user) and
        silently falls back to Administrator -- while the setting still reads as
        configured. Resolving to the configured address means setup recreates it
        rather than creating a second user beside it.
        """
        configured = "webhook-user-preexisting@example.test"
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "webhook_user", configured)
        frappe.db.commit()

        self.assertEqual(w.generate_webhook_user_email(), configured)
        self.assertFalse(frappe.db.exists("User", configured), "precondition: user must not exist")

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

    def test_setup_webhook_user_is_idempotent(self):
        """Running setup twice must CONVERGE on one user, not create a second.

        This is what lets setup_webhook_user live in after_migrate. It previously
        asserted that both runs produced different users and called that "observed
        behaviour"; running that version on every migrate would have minted a
        webhook user per migration.
        """
        first = w.setup_webhook_user()
        first_email = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self._track_if_exists(first_email)
        self.assertTrue(first["success"], first)

        second = w.setup_webhook_user()
        second_email = frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user")
        self.assertTrue(second["success"], second)

        self.assertEqual(second_email, first_email, "second run must reuse the same webhook user")
        self.assertTrue(frappe.db.exists("User", first_email))

        # And exactly one webhook user exists for this site.
        domain = first_email.split("@", 1)[1]
        matches = frappe.get_all("User", filters={"name": ["like", f"webhook-user%@{domain}"]}, pluck="name")
        self.assertEqual(len(matches), 1, f"expected exactly one webhook user, found {matches}")

    def test_setup_recreates_a_configured_non_canonical_user_that_was_deleted(self):
        """The exact state found on test_site_1: a NON-canonical configured address
        whose User has been deleted.

        The address must be non-canonical, otherwise the configured-preference
        branch is indistinguishable from the canonical fallback and the test proves
        nothing about it. `webhook-user-1@<site>` is the real-world value -- the
        fingerprint of the old counter bug, left behind after test-data cleanup
        removed the User.
        """
        canonical = w.generate_webhook_user_email()
        domain = canonical.split("@", 1)[1]
        stale = f"webhook-user-7@{domain}"

        # Configure the stale address AND create the account, so the normalisation
        # branch (which only rewrites when the suffixed user is absent) does not fire.
        self._set_settings_webhook_user(stale)
        self.assertTrue(w.create_webhook_user_account(stale, w.generate_secure_password())["success"])
        self._track_if_exists(stale)
        self.assertNotEqual(stale, canonical)

        # The configured, existing, non-canonical address wins over the canonical one.
        self.assertEqual(w.generate_webhook_user_email(), stale)

        again = w.setup_webhook_user()
        self.assertTrue(again["success"], again)
        self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user"), stale)
        # Converged on the stale address rather than creating the canonical one beside it.
        self.assertFalse(frappe.db.exists("User", canonical))

    def test_a_deleted_suffixed_user_is_normalised_back_to_canonical(self):
        """A `webhook-user-<n>@` setting with no such User is the counter bug's
        artefact; keep it and every future reader re-diagnoses the old bug."""
        canonical = w.generate_webhook_user_email()
        domain = canonical.split("@", 1)[1]
        stale = f"webhook-user-9@{domain}"

        self._set_settings_webhook_user(stale)
        self.assertFalse(frappe.db.exists("User", stale), "precondition: the stale user is gone")

        self.assertEqual(w.generate_webhook_user_email(), canonical)

    def test_create_account_re_enables_a_disabled_user(self):
        """A disabled service user is equivalent to no user: get_service_user reads
        `enabled` and falls back to Administrator, so setup must converge on it."""
        email = w.generate_webhook_user_email()
        self.assertTrue(w.create_webhook_user_account(email, w.generate_secure_password())["success"])
        self._track_if_exists(email)

        user = frappe.get_doc("User", email)
        user.enabled = 0
        user.save(ignore_permissions=True)
        frappe.db.commit()
        self.assertFalse(frappe.db.get_value("User", email, "enabled"))

        result = w.create_webhook_user_account(email, None)
        self.assertTrue(result["success"], result)
        self.assertIn("re-enabled", result["message"])
        self.assertTrue(frappe.db.get_value("User", email, "enabled"))

    def test_autosetup_can_be_disabled(self):
        """Without an opt-out there is no supported way to stop after_migrate
        recreating the account -- clearing webhook_user does not help."""
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "disable_webhook_user_autosetup", 1)
        frappe.db.commit()
        try:
            result = w.setup_webhook_user()
            self.assertTrue(result["success"], result)
            self.assertTrue(result.get("skipped"), result)
            # setUp clears the field, which persists as "" rather than None.
            self.assertFalse(frappe.db.get_single_value(SETTINGS_DOCTYPE, "webhook_user"))
            self.assertFalse(frappe.db.exists("User", w.generate_webhook_user_email()))
        finally:
            frappe.db.set_single_value(SETTINGS_DOCTYPE, "disable_webhook_user_autosetup", 0)
            frappe.db.commit()

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
