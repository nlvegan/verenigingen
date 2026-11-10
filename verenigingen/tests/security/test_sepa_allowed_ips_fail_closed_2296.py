"""#2296: an unreadable SEPA IP allowlist must not read as "no allowlist".

``SEPAAuthorizationManager._get_allowed_ips`` caught every exception and returned ``[]``,
which ``_check_ip_restrictions`` reads as "no restrictions configured". The only realistic
trigger is the Settings read (``frappe.db.get_single_value``) failing: the site-config read
cannot raise. The failure is injected BELOW the swallowing layer, at that DB read, and the
IP-restricted operation is driven through ``_check_contextual_permissions``.

Not configured (empty/absent) must stay permissive; only a failed read denies.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import QueryDeadlockError

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.authorization import SEPAAuthorizationManager, SEPAOperation

SETTINGS = "Verenigingen Payments Settings"
ALLOWED_IP = "203.0.113.5"
OTHER_IP = "198.51.100.9"
RESTRICTED = SEPAOperation.SETTINGS_MODIFY  # a member of IP_RESTRICTED_OPERATIONS


class TestSepaAllowedIpsFailClosed(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._request = getattr(frappe.local, "request", None)
        self._conf_had = "sepa_allowed_ips" in frappe.conf
        self._conf_value = frappe.conf.get("sepa_allowed_ips")
        frappe.conf.pop("sepa_allowed_ips", None)

    def tearDown(self):
        frappe.local.request = self._request  # Mock justified: Infrastructure - restore
        if self._conf_had:
            frappe.conf["sepa_allowed_ips"] = self._conf_value
        else:
            frappe.conf.pop("sepa_allowed_ips", None)
        super().tearDown()

    def _http_from(self, ip):
        frappe.local.request = SimpleNamespace(method="POST", environ={"REMOTE_ADDR": ip})  # Mock justified: Infrastructure - simulated HTTP request

    def _settings_read(self, value=None, raises=None):
        """Replace ONLY the Settings read. Mock justified: Infrastructure - a DB error cannot be
        provoked on demand; every other get_single_value call is passed through."""
        real = frappe.db.get_single_value

        def fake(doctype, field, *args, **kwargs):
            if doctype == SETTINGS and field == "sepa_allowed_ips":
                if raises:
                    raise raises
                return value
            return real(doctype, field, *args, **kwargs)

        return patch.object(frappe.db, "get_single_value", side_effect=fake)

    def _allowed(self, manager):
        return manager._check_contextual_permissions(RESTRICTED, "Administrator")

    def test_control_configured_allowlist_admits_listed_and_refuses_foreign_ip(self):
        with self._settings_read(value=ALLOWED_IP):
            manager = SEPAAuthorizationManager()
        self.assertEqual(manager.allowed_ips, [ALLOWED_IP])
        self._http_from(ALLOWED_IP)
        self.assertTrue(self._allowed(manager))
        self._http_from(OTHER_IP)
        self.assertFalse(self._allowed(manager))

    def test_not_configured_stays_unrestricted(self):
        """Opposite-harm control: an absent allowlist must not refuse everything."""
        with self._settings_read(value=None):
            manager = SEPAAuthorizationManager()
        self._http_from(OTHER_IP)
        self.assertTrue(self._allowed(manager))

    def test_failed_read_denies_http_request(self):
        self.expectErrorLog("SEPA allowed IPs could not be read")
        with self._settings_read(raises=frappe.db.OperationalError(2013, "Lost connection")):
            manager = SEPAAuthorizationManager()
            self._http_from(ALLOWED_IP)
            self.assertFalse(self._allowed(manager), "unreadable allowlist was treated as 'no restriction'")

    def test_failed_read_does_not_affect_non_http_context(self):
        self.expectErrorLog("SEPA allowed IPs could not be read")
        with self._settings_read(raises=frappe.db.OperationalError(2013, "Lost connection")):
            manager = SEPAAuthorizationManager()
            frappe.local.request = None  # Mock justified: Infrastructure - simulate non-HTTP context
            self.assertTrue(self._allowed(manager))

    def test_manager_built_during_failure_recovers_when_the_read_works_again(self):
        """__init__ must not freeze 'no allowlist' (the manager is a process-wide singleton)."""
        self.expectErrorLog("SEPA allowed IPs could not be read")
        with self._settings_read(raises=frappe.db.OperationalError(2013, "Lost connection")):
            manager = SEPAAuthorizationManager()
        with self._settings_read(value=ALLOWED_IP):
            self._http_from(ALLOWED_IP)
            self.assertTrue(self._allowed(manager))
            self._http_from(OTHER_IP)
            self.assertFalse(self._allowed(manager), "allowlist stayed off after the read recovered")

    def test_deadlock_propagates_instead_of_being_swallowed(self):
        with self._settings_read(raises=QueryDeadlockError()):
            with self.assertRaises(QueryDeadlockError):
                SEPAAuthorizationManager()

    def test_site_config_list_is_not_mutated_by_settings_merge(self):
        frappe.conf["sepa_allowed_ips"] = ["192.0.2.1"]
        with self._settings_read(value=ALLOWED_IP):
            manager = SEPAAuthorizationManager()
        self.assertCountEqual(manager.allowed_ips, ["192.0.2.1", ALLOWED_IP])
        self.assertEqual(frappe.conf["sepa_allowed_ips"], ["192.0.2.1"])

    def test_string_site_config_is_split_and_merged_with_settings(self):
        """A comma-separated string in site config used to hit str.extend (AttributeError),
        be swallowed to [] and switch the allowlist OFF."""
        listed, second, settings_ip = "192.0.2.1", "192.0.2.2", ALLOWED_IP
        frappe.conf["sepa_allowed_ips"] = f"{listed}, {second}"  # tearDown restores frappe.conf
        with self._settings_read(value=settings_ip):
            manager = SEPAAuthorizationManager()
        self.assertCountEqual(manager.allowed_ips, [listed, second, settings_ip])
        self._http_from(listed)
        self.assertTrue(self._allowed(manager))
        self._http_from(OTHER_IP)
        self.assertFalse(self._allowed(manager))
