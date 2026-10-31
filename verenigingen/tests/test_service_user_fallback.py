"""
#1834: ``get_service_user(fallback_user=None)`` is the form the guest-reachable Ponto
callbacks use. It must return a usable user or None, never elevate, never write an Error Log
row, never raise. The default (Administrator fallback) must be unchanged for the other callers.

Real settings, real User rows, the real helper. The "raising lookup" case names a settings
doctype that does not exist, so the helper's own lookup raises DoesNotExistError.

Usage:
    bench --site test_site_10 run-tests --app verenigingen \
        --module verenigingen.tests.test_service_user_fallback
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_user import get_service_user

SETTINGS = "Verenigingen Payments Settings"
EMAIL = "service-user-1834@example.com"


class TestGetServiceUserFallback(EnhancedTestCase):
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
        self._n = 0

    def _configure(self, value):
        frappe.db.set_single_value(SETTINGS, "webhook_user", value)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

    def _resolve_svc_user(self, fallback_user="__default__", settings_doctype=SETTINGS):
        # a distinct service_name per call: the fallback audit row is once per name per request
        self._n += 1
        kwargs = {} if fallback_user == "__default__" else {"fallback_user": fallback_user}
        before = frappe.db.count("Error Log")
        user = get_service_user(
            settings_doctype=settings_doctype,
            user_field="webhook_user",
            service_name=f"Svc Test {self._n}",
            **kwargs,
        )
        return user, frappe.db.count("Error Log") - before

    def test_configured_and_enabled_user_is_returned_either_way(self):
        self.assertEqual(self._resolve_svc_user(None), (EMAIL, 0))
        self.assertEqual(self._resolve_svc_user(), (EMAIL, 0))

    def test_unset_returns_none_without_an_error_log_row(self):
        self._configure(None)
        self.assertEqual(self._resolve_svc_user(None), (None, 0))

    def test_nonexistent_configured_user_returns_none(self):
        self._configure("nobody-1834@example.com")
        self.assertEqual(self._resolve_svc_user(None), (None, 0))

    def test_disabled_configured_user_returns_none(self):
        frappe.db.set_value("User", EMAIL, "enabled", 0)
        self.assertEqual(self._resolve_svc_user(None), (None, 0))

    def test_a_raising_lookup_returns_none_and_does_not_raise(self):
        self.assertEqual(self._resolve_svc_user(None, settings_doctype="No Such Settings Doctype 1834"), (None, 0))

    def test_default_still_falls_back_to_administrator_with_its_error_log_row(self):
        """Control: the other callers keep the elevation and its audit row, so the None cases
        above are not just a helper that always returns None."""
        for arrange in (
            lambda: self._configure(None),
            lambda: self._configure("nobody-1834@example.com"),
            lambda: (self._configure(EMAIL), frappe.db.set_value("User", EMAIL, "enabled", 0)),
        ):
            arrange()
            with self.assertErrorLog("Using Administrator Fallback"):
                user, rows = self._resolve_svc_user()
            self.assertEqual(user, "Administrator")
            self.assertEqual(rows, 1)
