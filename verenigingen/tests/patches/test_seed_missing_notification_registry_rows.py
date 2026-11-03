"""#1959: the patch gives an EXISTING site a row for each registry key that has none.

Existing-site state is built the way #1998's tests build theirs (``singleton_backup`` plus a
rewritten ``notification_types``): some keys have rows, one deliberately DISABLED and one with
custom recipients, and the rest have none. Probe shortcut, stated: this is not a real
``bench migrate``; the patch's ``execute`` is called directly and its listing in patches.txt
is pinned by a separate test.
"""

import importlib
import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.tests.fixtures.singleton_backup import singleton_backup

DOCTYPE = "Verenigingen Email Configuration"
PATCH = "verenigingen.patches.v2_2.seed_missing_notification_registry_rows"
DISABLED_KEY = "member_activated"
CUSTOM_KEY = "system_alert"
CUSTOM_ROLES = "Chapter Board Member"
SNAPSHOT_FIELDS = (
    "notification_key",
    "label",
    "category",
    "recipient_policy",
    "recipient_roles",
    "fixed_recipients",
    "cooldown_minutes",
    "enabled",
    "description",
)


def _config_rows():
    return {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}


def _row_fields(row):
    return {f: row.get(f) for f in SNAPSHOT_FIELDS}


def _run_seed_patch():
    return importlib.import_module(PATCH).execute()


class TestSeedMissingNotificationRegistryRows(FrappeTestCase):
    def _existing_site_state(self):
        config = frappe.get_single(DOCTYPE)
        config.notification_types = []
        config.append(
            "notification_types",
            {
                "notification_key": DISABLED_KEY,
                "label": "Custom label",
                "category": "Member",
                "recipient_policy": "Document-Field",
                "cooldown_minutes": 15,
                "enabled": 0,
            },
        )
        config.append(
            "notification_types",
            {
                "notification_key": CUSTOM_KEY,
                "label": "Custom alert",
                "category": "System",
                "recipient_policy": "Role-Based",
                "recipient_roles": CUSTOM_ROLES,
                "cooldown_minutes": 5,
                "enabled": 1,
            },
        )
        config.save()
        self.assertEqual(set(_config_rows()), {DISABLED_KEY, CUSTOM_KEY}, "control: most keys have no row")

    def test_missing_rows_are_added_enabled_and_existing_rows_are_untouched(self):
        with singleton_backup(DOCTYPE):
            self._existing_site_state()
            before = {k: _row_fields(r) for k, r in _config_rows().items()}

            _run_seed_patch()

            rows = _config_rows()
            self.assertEqual(set(rows), set(NOTIFICATION_KEYS))
            for key in (DISABLED_KEY, CUSTOM_KEY):
                self.assertEqual(_row_fields(rows[key]), before[key], key)
            self.assertEqual(cint(rows[DISABLED_KEY].enabled), 0, "an admin's off switch must survive")
            added = set(NOTIFICATION_KEYS) - {DISABLED_KEY, CUSTOM_KEY}
            self.assertTrue(added, "control: there were rows to add")
            for key in added:
                self.assertEqual(cint(rows[key].enabled), 1, key)

    def test_a_second_run_changes_nothing(self):
        with singleton_backup(DOCTYPE):
            self._existing_site_state()
            _run_seed_patch()
            first = [(r.name, r.notification_key, r.modified) for r in _config_rows().values()]

            _run_seed_patch()

            self.assertEqual([(r.name, r.notification_key, r.modified) for r in _config_rows().values()], first)

    def test_the_patch_is_listed_in_post_model_sync(self):
        text = (Path(frappe.get_app_path("verenigingen")) / "patches.txt").read_text()
        sections = re.split(r"^\[(\w+)\]\s*$", text, flags=re.M)
        listed = dict(zip(sections[1::2], sections[2::2]))
        lines = [ln.strip() for ln in listed["post_model_sync"].splitlines()]
        self.assertIn(PATCH, lines)
        self.assertNotIn(PATCH, [ln.strip() for ln in listed["pre_model_sync"].splitlines()])
