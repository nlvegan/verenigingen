"""Missing notification registry rows are seeded on migrate too (#2037).

A key with no row in Verenigingen Email Configuration counts as DISABLED, so a site installed
before a key existed (veg11, production) silently skipped that key's alerts until someone ran
"Sync Registry". #1998 seeded on install only; the maintainer ruled (2026-11-03) that migrate
seeds too. Only ADDS rows: an existing row (including a disabled one) is never touched.

Real flow: the handler is looked up in ``hooks.lifecycle.after_migrate`` by name. Probe shortcut:
the "old site" state is built by deleting rows from the Single directly; a real ``bench migrate``
was not run. ``singleton_backup`` does not back up child tables (#2029), so the rows are
snapshotted and restored by ``addCleanup``.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.hooks.lifecycle import after_migrate
from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

DOCTYPE = "Verenigingen Email Configuration"
SEED_HANDLER = "ensure_notification_registry_rows"


def _migrate_seed_handler():
    path = next((h for h in after_migrate if h.endswith(SEED_HANDLER)), None)
    if not path:
        raise AssertionError(f"{SEED_HANDLER} is not in hooks.lifecycle.after_migrate")
    return frappe.get_attr(path)


def _rows():
    return {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}


class TestNotificationRegistrySeedOnMigrate(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Snapshot BEFORE seeding: a site may legitimately carry no rows, and must end the same way.
        self.baseline = {k: dict(r.as_dict()) for k, r in _rows().items()}
        self.addCleanup(self._restore_rows)
        ensure_notification_registry_rows()
        self.keys = sorted(NOTIFICATION_KEYS)
        self.assertGreaterEqual(len(self.keys), 4, "control: the registry has keys to play with")

    def _restore_rows(self):
        # Not singleton_backup: it skips child tables (#2029). Put back exactly what was there.
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
        missing_a, missing_b, disabled_key, edited_key = self.keys[:4]
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
            self.assertEqual(
                cint(rows[key].cooldown_minutes),
                NOTIFICATION_KEYS[key].get("cooldown_minutes", cint(rows[key].cooldown_minutes)),
                key,
            )
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
