"""Missing notification registry rows are seeded on migrate too (#2037).

A key with no row in Verenigingen Email Configuration counts as DISABLED, so a site installed
before a key existed (veg11, production) silently skipped that key's alerts until someone ran
"Sync Registry". #1998 seeded on install only; the maintainer ruled (2026-11-03) that migrate
seeds too. Only ADDS rows: an existing row (including a disabled one) is never touched.

Real flow: the handler is looked up in ``hooks.lifecycle.after_migrate`` by name. Probe shortcut:
the "old site" state is built by deleting rows from the Single directly; a real ``bench migrate``
was not run. the rows are snapshotted and restored by ``addCleanup``
(``singleton_backup`` has restored child tables since #2091, so this is now redundant; see #2159).
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.hooks.lifecycle import after_migrate
from verenigingen.notification_registry import DEFAULT_COOLDOWN_MINUTES, NOTIFICATION_KEYS
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.test_notification_registry_seed_1959 import _rows

DOCTYPE = "Verenigingen Email Configuration"
SEED_HANDLER = "ensure_notification_registry_rows"


def _migrate_seed_handler():
    path = next((h for h in after_migrate if h.endswith(SEED_HANDLER)), None)
    if not path:
        raise AssertionError(f"{SEED_HANDLER} is not in hooks.lifecycle.after_migrate")
    return frappe.get_attr(path)


class TestNotificationRegistrySeedOnMigrate(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Snapshot BEFORE seeding: a site may legitimately carry no rows, and must end the same way.
        self.baseline = {k: dict(r.as_dict()) for k, r in _rows().items()}
        self.addCleanup(self._put_back_snapshot)
        ensure_notification_registry_rows()
        self.keys = sorted(NOTIFICATION_KEYS)
        self.assertGreaterEqual(len(self.keys), 4, "control: the registry has keys to play with")

    def _put_back_snapshot(self):
        # Hand-rolled restore, kept although singleton_backup restores child tables since #2091 (#2159).
        config = frappe.get_single(DOCTYPE)
        config.notification_types = []
        for row in self.baseline.values():
            row = {k: v for k, v in row.items() if k not in ("name", "creation", "modified", "idx")}
            config.append("notification_types", row)
        config.save()

    def _config_without(self, *dropped, edit=None):
        config = frappe.get_single(DOCTYPE)
        config.notification_types = [r for r in config.notification_types if r.notification_key not in dropped]
        for row in config.notification_types:
            if edit and row.notification_key in edit:
                row.update(edit[row.notification_key])
        config.save()

    def test_migrate_adds_missing_rows_and_leaves_existing_ones_alone(self):
        # Pinned: missing_a carries a registry cooldown other than the default, so the seeded value
        # is distinguishable from the default; the rest are the first other keys.
        missing_a = next(
            k for k in self.keys if NOTIFICATION_KEYS[k].get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
            != DEFAULT_COOLDOWN_MINUTES
        )
        others = [k for k in self.keys if k != missing_a]
        missing_b, disabled_key, edited_key = others[:3]
        self._config_without(
            missing_a,
            missing_b,
            edit={disabled_key: {"enabled": 0}, edited_key: {"label": "Custom label", "cooldown_minutes": 7}},
        )
        before = _rows()
        self.assertNotIn(missing_a, before, "control: the rows are really missing")
        self.assertNotIn(missing_b, before)

        _migrate_seed_handler()()

        rows = _rows()
        self.assertEqual(set(rows), set(NOTIFICATION_KEYS))
        for key in (missing_a, missing_b):
            self.assertEqual(cint(rows[key].enabled), 1, key)
            expected = NOTIFICATION_KEYS[key].get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)
            self.assertEqual(cint(rows[key].cooldown_minutes), expected, key)
        self.assertEqual(cint(rows[disabled_key].enabled), 0, "an admin-disabled row stays disabled")
        self.assertEqual(rows[edited_key].label, "Custom label")
        self.assertEqual(cint(rows[edited_key].cooldown_minutes), 7)

    def test_second_run_adds_nothing(self):
        self._config_without(self.keys[0])
        _migrate_seed_handler()()
        count = len(frappe.get_single(DOCTYPE).notification_types)
        modified = frappe.db.get_value(DOCTYPE, DOCTYPE, "modified")

        _migrate_seed_handler()()

        self.assertEqual(len(frappe.get_single(DOCTYPE).notification_types), count)
        self.assertEqual(count, len(NOTIFICATION_KEYS))
        self.assertEqual(
            frappe.db.get_value(DOCTYPE, DOCTYPE, "modified"), modified, "nothing missing: no save at all"
        )
