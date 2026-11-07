"""A fresh install has a row for every registry key (#1959).

A key with no row in Verenigingen Email Configuration counts as DISABLED, so on a fresh
install (every CI site: patches.txt is not run) ``notify_administrators(notification_key=...)``
silently skipped every alert. The install hook must seed a row per registry key.

Real flow: the hook is looked up in ``hooks.lifecycle.after_install`` (not imported by name),
run against a Single emptied the way a fresh install leaves it, and the alert path is driven
through ``notify_administrators``. Probe shortcut: the "fresh install" state is built by
emptying ``notification_types`` inside ``singleton_backup``; a real ``install-app`` was not run.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.hooks.lifecycle import after_install
from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.utils.constants import Roles
from verenigingen.utils.notification_helpers import notify_administrators

DOCTYPE = "Verenigingen Email Configuration"
SEED_HANDLER = "ensure_notification_registry_rows"


def _seed_handler():
    path = next((h for h in after_install if h.endswith(SEED_HANDLER)), None)
    if not path:
        raise AssertionError(f"{SEED_HANDLER} is not in hooks.lifecycle.after_install")
    return frappe.get_attr(path)


def _rows():
    return {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}


class TestNotificationRegistrySeed(FrappeTestCase):
    def _fresh_install_state(self):
        config = frappe.get_single(DOCTYPE)
        config.notification_types = []
        config.save()
        self.assertEqual(_rows(), {}, "control: the fresh-install state has no rows")

    def test_install_hook_seeds_every_registry_key_enabled(self):
        with singleton_backup(DOCTYPE):
            self._fresh_install_state()
            _seed_handler()()
            rows = _rows()
            self.assertEqual(set(rows), set(NOTIFICATION_KEYS))
            for key, row in rows.items():
                meta = NOTIFICATION_KEYS[key]
                self.assertEqual(cint(row.enabled), 1, key)
                self.assertEqual(row.category, meta["category"], key)
                self.assertEqual(row.recipient_policy, meta["recipient_policy"], key)

    def test_role_based_keys_get_the_admin_roles_so_recipients_resolve(self):
        with singleton_backup(DOCTYPE):
            self._fresh_install_state()
            _seed_handler()()
            role_based = [k for k, m in NOTIFICATION_KEYS.items() if m["recipient_policy"] == "Role-Based"]
            self.assertTrue(role_based, "control: the registry has Role-Based keys")
            for key in role_based:
                # A registry entry may name its own roles (#2093 ruling: the scheduler alert is for
                # Financial Managers); every other Role-Based key gets the admin pair.
                expected = set(NOTIFICATION_KEYS[key].get("recipient_roles", ", ".join(Roles.ADMIN_PAIR)).split(", "))
                self.assertEqual(set(_rows()[key].recipient_roles.split(", ")), expected, key)
            self.assertEqual(_rows()["sepa_batch_scheduler_alert"].recipient_roles, Roles.FINANCIAL_MANAGER)
            self.assertEqual(set(_rows()["sepa_batch_error"].recipient_roles.split(", ")), set(Roles.ADMIN_PAIR))

    def test_alert_is_not_skipped_on_a_seeded_install_and_is_skipped_on_an_unseeded_one(self):
        key = "ponto_executed_on_cancelled_row"
        with singleton_backup(DOCTYPE):
            self._fresh_install_state()
            unseeded = notify_administrators(subject="s", message="m", notification_key=key)
            self.assertTrue(unseeded.get("skipped"), "control: unseeded keys are skipped")
            _seed_handler()()
            seeded = notify_administrators(subject="s", message="m", notification_key=key)
            self.assertFalse(seeded.get("skipped"), seeded)

    def test_seeding_keeps_a_row_an_admin_already_configured(self):
        key = "member_activated"
        with singleton_backup(DOCTYPE):
            self._fresh_install_state()
            config = frappe.get_single(DOCTYPE)
            config.append(
                "notification_types",
                {
                    "notification_key": key,
                    "label": "Custom label",
                    "category": "Member",
                    "recipient_policy": "Document-Field",
                    "enabled": 0,
                },
            )
            config.save()
            _seed_handler()()
            row = _rows()[key]
            self.assertEqual((cint(row.enabled), row.label), (0, "Custom label"))
            self.assertEqual(set(_rows()), set(NOTIFICATION_KEYS))
            # idempotent: a second run adds nothing
            _seed_handler()()
            self.assertEqual(len(frappe.get_single(DOCTYPE).notification_types), len(NOTIFICATION_KEYS))
