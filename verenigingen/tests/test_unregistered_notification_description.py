"""A notification key missing from the registry gets an admin-facing description (#1648).

Discovery used to hand the "New Notification Keys" dialog, and then
``add_notification_types``, the text "(Not documented - add to notification_registry.py)",
which was stored as the notification type's description. The flow below is real: a
registered key is removed from the registry for the duration of the test, discovered,
and added through ``add_notification_types``.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.verenigingen.doctype.verenigingen_email_configuration import (
    verenigingen_email_configuration as vec,
)

DOCTYPE = "Verenigingen Email Configuration"


class TestUnregisteredNotificationDescription(FrappeTestCase):
    def _discover_as_unregistered(self):
        from verenigingen import notification_registry

        found = vec._discover_notification_keys()["found"]
        key = next(k["notification_key"] for k in found if k["in_registry"])
        with patch.dict(notification_registry.NOTIFICATION_KEYS):
            notification_registry.NOTIFICATION_KEYS.pop(key)
            entry = next(
                k for k in vec._discover_notification_keys()["found"] if k["notification_key"] == key
            )
        return key, entry

    def test_discovery_description_has_no_code_reference(self):
        key, entry = self._discover_as_unregistered()
        self.assertFalse(entry["in_registry"], "control: the key must really be unregistered")
        self.assertNotIn(".py", entry["description"])

    def test_stored_description_has_no_code_reference(self):
        key, entry = self._discover_as_unregistered()
        with singleton_backup(DOCTYPE):
            config = frappe.get_single(DOCTYPE)
            config.notification_types = []
            config.save()
            result = vec.add_notification_types(json.dumps([entry]))
            self.assertEqual(result["added"], 1)
            row = next(
                r
                for r in frappe.get_single(DOCTYPE).notification_types
                if r.notification_key == key
            )
            self.assertTrue(row.description)
            self.assertNotIn(".py", row.description)
            self.assertNotIn("notification_registry", row.description)
