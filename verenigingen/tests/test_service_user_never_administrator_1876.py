"""
#1876: ``get_service_user`` NEVER falls back to Administrator, and the gateway paths that
need a user refuse (with an Error Log row and no message_log entry) when there is none.

Real settings, real User rows, the real helpers. The "raising lookup" case names a settings
doctype that does not exist, so the helper's own lookup raises DoesNotExistError.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.test_service_user_never_administrator_1876
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_user import (
    ServiceUserUnavailable,
    get_service_user,
    require_service_user,
)

SETTINGS = "Verenigingen Payments Settings"
EMAIL = "service-user-1876@example.com"
GHOST = "nobody-1876@example.com"
MISSING_DOCTYPE = "No Such Settings Doctype 1876"


class TestGetServiceUserNeverAdministrator(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("User", EMAIL):
            user = frappe.new_doc("User")
            user.email = EMAIL
            user.first_name = "SvcUser"
            user.send_welcome_email = 0
            user.insert(ignore_permissions=True)
        frappe.db.set_value("User", EMAIL, "enabled", 1)
        self._configure(EMAIL)

    def _configure(self, value):
        frappe.db.set_single_value(SETTINGS, "webhook_user", value)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

    def _resolve_user_1876(self, settings_doctype=SETTINGS, **kwargs):
        return get_service_user(
            settings_doctype=settings_doctype,
            user_field="webhook_user",
            service_name="Svc Test 1876",
            **kwargs,
        )

    def _unusable_states(self):
        """Each arrangement leaves NO usable webhook user; Administrator exists in all."""
        return {
            "unset": lambda: self._configure(None),
            "nonexistent": lambda: self._configure(GHOST),
            "disabled": lambda: frappe.db.set_value("User", EMAIL, "enabled", 0),
            # an operator (or a stale value) naming Administrator IS an elevation: refused too
            "administrator": lambda: self._configure("Administrator"),
        }

    def test_configured_and_enabled_user_is_returned(self):
        self.assertEqual(self._resolve_user_1876(), EMAIL)

    def test_no_usable_user_returns_none_never_administrator(self):
        self.assertTrue(frappe.db.exists("User", "Administrator"), "control: the old fallback target exists")
        for name, arrange in self._unusable_states().items():
            with self.subTest(state=name):
                arrange()
                self.assertIsNone(self._resolve_user_1876())

    def test_a_raising_lookup_returns_none_never_administrator(self):
        self.assertIsNone(self._resolve_user_1876(settings_doctype=MISSING_DOCTYPE))

    def test_an_explicit_administrator_fallback_is_refused(self):
        with self.assertRaises(ValueError):
            self._resolve_user_1876(fallback_user="Administrator")

    def test_require_returns_the_configured_user_without_an_error_log_row(self):
        before = frappe.db.count("Error Log")
        self.assertEqual(self._require(), EMAIL)
        self.assertEqual(frappe.db.count("Error Log"), before)

    def _require(self, settings_doctype=SETTINGS):
        return require_service_user(
            settings_doctype=settings_doctype, user_field="webhook_user", service_name="Svc Test 1876"
        )

    def test_require_refuses_every_unusable_state_with_a_row_and_no_message(self):
        self.expectErrorLog("Svc Test 1876")
        states = dict(self._unusable_states())
        states["lookup raises"] = lambda: None
        for name, arrange in states.items():
            with self.subTest(state=name):
                arrange()
                doctype = MISSING_DOCTYPE if name == "lookup raises" else SETTINGS
                rows, messages = frappe.db.count("Error Log"), len(frappe.local.message_log or [])
                with self.assertRaises(ServiceUserUnavailable) as ctx:
                    self._require(doctype)
                self.assertEqual(frappe.db.count("Error Log"), rows + 1)
                # a frappe.throw would put the reason in message_log, i.e. in an anonymous
                # caller's _server_messages
                self.assertEqual(len(frappe.local.message_log or []), messages)
                self.assertNotIsInstance(ctx.exception, frappe.ValidationError)
                self._configure(EMAIL)
                frappe.db.set_value("User", EMAIL, "enabled", 1)


class TestPontoJobsFailClosedWithoutAWebhookUser(EnhancedTestCase):
    """The Ponto background jobs set their own identity (frappe.enqueue has no `user`
    parameter). With no usable webhook user they must not run as anyone else, must leave an
    Error Log row, and must not reach their business function."""

    HANDLERS = "verenigingen.verenigingen_payments.ponto.api.webhook_handlers"

    def setUp(self):
        super().setUp()
        self._previous = frappe.db.get_single_value(SETTINGS, "webhook_user")
        frappe.db.set_single_value(SETTINGS, "webhook_user", None)
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        self.addCleanup(self._put_back_webhook_user_1876)

    def _put_back_webhook_user_1876(self):
        frappe.db.set_single_value(SETTINGS, "webhook_user", self._previous)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

    def _assert_job_refused_1876(self, job, business_function, **kwargs):
        from unittest.mock import patch

        self.expectErrorLog("Ponto Webhook")
        rows, user = frappe.db.count("Error Log"), frappe.session.user
        # Mock justified: proves the business function is never reached; its own behaviour
        # is covered by the Ponto suites.
        with patch(business_function) as business:
            with self.assertRaises(ServiceUserUnavailable):
                job(**kwargs)
        business.assert_not_called()
        self.assertEqual(frappe.db.count("Error Log"), rows + 1)
        self.assertEqual(frappe.session.user, user, "the job must not have changed identity")

    def test_import_transactions_job_refuses(self):
        from verenigingen.verenigingen_payments.ponto.api import webhook_handlers as wh

        self._assert_job_refused_1876(
            wh.import_transactions_job,
            "verenigingen.verenigingen_payments.ponto.services.transaction_import_service."
            "import_new_transactions",
            account_id="acc-1876",
        )

    def test_process_executed_payment_job_refuses(self):
        from verenigingen.verenigingen_payments.ponto.api import webhook_handlers as wh

        self._assert_job_refused_1876(
            wh.process_executed_payment_job, f"{self.HANDLERS}._process_executed_payment", payment_link_name="PL-1876"
        )


class TestWebhookUserSetupGuarantee(EnhancedTestCase):
    """A migrated site ends with an enabled webhook user that holds its profile's roles.

    The repair tests run on a THROWAWAY webhook user, never on the site's own: the
    captured-insert drain deletes every row inserted during a test, so a Has Role row that
    setup re-inserts for the shared user would be deleted again at teardown (and committed),
    leaving it without Accounts User for every later module in the process."""

    THROWAWAY = "wh-guarantee-1876@example.com"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site_user = frappe.db.get_single_value(SETTINGS, "webhook_user")

    @classmethod
    def tearDownClass(cls):
        try:
            profile_roles = {r.role for r in frappe.get_doc("Role Profile", "Verenigingen Webhook User").roles}
            held = {r.role for r in frappe.get_doc("User", cls.site_user).roles}
            missing = profile_roles - held
        finally:
            super().tearDownClass()
        if missing:
            raise AssertionError(f"this class left the site webhook user without {sorted(missing)}")

    def setUp(self):
        super().setUp()
        from verenigingen.setup.webhook_user_setup import setup_webhook_user

        self.assertTrue(setup_webhook_user()["success"])
        self.assertTrue(self.site_user)
        self.profile_roles = {
            r.role for r in frappe.get_doc("Role Profile", "Verenigingen Webhook User").roles
        }
        self.addCleanup(self._back_to_the_site_user)

    def _back_to_the_site_user(self):
        # commits internally when the value differs, which is what a restore after setup's own
        # commits needs (a bare commit here would grow the order-dependence census)
        from verenigingen.setup.webhook_user_setup import configure_webhook_user_in_settings

        self.assertTrue(configure_webhook_user_in_settings(self.site_user)["success"])
        frappe.clear_document_cache(SETTINGS, SETTINGS)

    def _use_throwaway_user(self):
        """setup_webhook_user converges whatever the setting names, so point it at an address
        that does not exist yet; setup then creates it, with the profile's roles."""
        from verenigingen.setup.webhook_user_setup import setup_webhook_user

        frappe.db.set_single_value(SETTINGS, "webhook_user", self.THROWAWAY)
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        self.assertTrue(setup_webhook_user()["success"])
        self.track_doc("User", self.THROWAWAY)
        return self.THROWAWAY

    def test_a_profile_role_missing_from_the_user_is_repaired(self):
        """The user keeps the webhook role AND the profile row, but lost another profile role
        (Role Profile fan-out is a background job). Setup used to see nothing to do."""
        from verenigingen.setup.webhook_user_setup import setup_webhook_user

        user = self._use_throwaway_user()
        lost = sorted(self.profile_roles - {"Verenigingen Webhook User"})[0]
        frappe.db.delete("Has Role", {"parent": user, "role": lost, "parenttype": "User"})
        frappe.clear_cache(user=user)
        self.assertNotIn(lost, frappe.get_roles(user), "control: the role is really gone")

        self.assertTrue(setup_webhook_user()["success"])
        frappe.clear_cache(user=user)
        self.assertTrue(self.profile_roles <= set(frappe.get_roles(user)))

    def test_a_failed_setup_leaves_an_error_log_row(self):
        from unittest.mock import patch

        from verenigingen.setup import webhook_user_setup as w

        self.expectErrorLog("Webhook user setup failed")
        rows = frappe.db.count("Error Log")
        # Mock justified: forces the failure shape setup_webhook_user returns.
        with patch.object(w, "setup_webhook_user", return_value={"success": False, "message": "boom"}):
            result = w.ensure_webhook_user()
        self.assertFalse(result["success"])
        self.assertEqual(frappe.db.count("Error Log"), rows + 1)

    def test_autosetup_disabled_with_no_usable_user_still_leaves_one_error_log_row(self):
        """Opting out of autosetup is not opting out of the consequence (webhooks refuse)."""
        from verenigingen.setup import webhook_user_setup as w

        self.expectErrorLog("Webhook user missing and autosetup disabled")
        # uncommitted: the per-test rollback restores both Single values
        frappe.db.set_single_value(SETTINGS, "disable_webhook_user_autosetup", 1)
        frappe.db.set_single_value(SETTINGS, "webhook_user", None)
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        rows = frappe.db.count("Error Log")
        result = w.ensure_webhook_user()
        self.assertTrue(result.get("skipped"), "control: the opt-out path was taken")
        self.assertEqual(frappe.db.count("Error Log"), rows + 1)

    def test_autosetup_disabled_with_a_usable_user_is_silent(self):
        from verenigingen.setup import webhook_user_setup as w

        frappe.db.set_single_value(SETTINGS, "disable_webhook_user_autosetup", 1)
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        rows = frappe.db.count("Error Log")
        self.assertTrue(w.ensure_webhook_user().get("skipped"))
        self.assertEqual(frappe.db.count("Error Log"), rows)

    def test_a_successful_setup_leaves_no_row(self):
        from verenigingen.setup import webhook_user_setup as w

        rows = frappe.db.count("Error Log")
        self.assertTrue(w.ensure_webhook_user()["success"])
        self.assertEqual(frappe.db.count("Error Log"), rows)

    def test_a_setting_that_names_administrator_is_repaired_to_the_webhook_user(self):
        """Ruling: never Administrator. A setting naming it is refused by get_service_user
        (unit tests above) AND converged by setup, which would otherwise keep honouring it."""
        from verenigingen.setup.webhook_user_setup import generate_webhook_user_email, setup_webhook_user

        canonical = self.site_user
        frappe.db.set_single_value(SETTINGS, "webhook_user", "Administrator")
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        self.assertNotEqual(generate_webhook_user_email(), "Administrator")

        self.assertTrue(setup_webhook_user()["success"])
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        repaired = frappe.db.get_single_value(SETTINGS, "webhook_user")
        self.assertNotEqual(repaired, "Administrator")
        self.assertEqual(repaired, canonical)
        self.assertEqual(get_service_user(SETTINGS, "webhook_user", "Svc Test 1876"), canonical)

    def test_the_migrate_hook_runs_the_non_silent_entry_point(self):
        self.assertIn(
            "verenigingen.setup.webhook_user_setup.ensure_webhook_user", frappe.get_hooks("after_migrate")
        )
