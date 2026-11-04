"""Per-key cooldowns come from the registry, on both ways of creating rows (#1999).

The seeder (#1998) wrote a constant 60 for every key, so the dunning keys could re-send to the same
member every hour instead of once a day or week. The maintainer's values (minutes) are pinned here
by hand, NOT derived from the registry, so a wrong registry value is caught. Keys outside these
rulings keep 60, except those #2012 moved to their v15 value.

Probe shortcut: the "fresh install" state is built by emptying ``notification_types`` inside
``singleton_backup`` (as in the #1959 test); a real ``install-app`` was not run. Existing rows are
never touched by either path (maintainer ruling), and a test below keeps that honest.
"""

import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.hooks.lifecycle import after_install
from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.utils.v15_cooldowns import ruled_v15_cooldowns
from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
    add_notification_types,
)

DOCTYPE = "Verenigingen Email Configuration"
RULED = {
    "payment_failure_first": 1440,
    "payment_failure_second": 1440,
    "payment_reminder_friendly": 10080,
    "payment_reminder_urgent": 4320,
    "payment_failure_final": 0,
    "subscription_cancelled": 0,
    "subscription_suspended": 0,
}


def _cooldown_rows_by_key():
    return {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}


def _empty_notification_config_for_cooldowns():
    config = frappe.get_single(DOCTYPE)
    config.notification_types = []
    config.save()


def _run_install_seed_for_cooldowns():
    handler = next(h for h in after_install if h.endswith("ensure_notification_registry_rows"))
    frappe.get_attr(handler)()


class TestSeededCooldowns(FrappeTestCase):
    def test_each_ruled_key_is_seeded_with_its_cooldown(self):
        with singleton_backup(DOCTYPE):
            _empty_notification_config_for_cooldowns()
            _run_install_seed_for_cooldowns()
            rows = _cooldown_rows_by_key()
            for key, minutes in RULED.items():
                self.assertEqual(cint(rows[key].cooldown_minutes), minutes, key)

    def test_every_key_outside_the_rulings_keeps_the_default_of_60(self):
        # #2012 moved the keys the v15 patches hard-code (see test_notification_cooldown_v15_parity_2012),
        # so "every other key is 60" now excludes them. The control below keeps the 60 set non-empty.
        with singleton_backup(DOCTYPE):
            _empty_notification_config_for_cooldowns()
            _run_install_seed_for_cooldowns()
            rows = _cooldown_rows_by_key()
            v15 = ruled_v15_cooldowns(NOTIFICATION_KEYS)
            others = [k for k in NOTIFICATION_KEYS if k not in RULED and v15.get(k, 60) == 60]
            self.assertIn("member_activated", others, "control: an ordinary key is in the sample")
            self.assertGreater(len(others), 20)
            self.assertTrue([k for k in v15 if v15[k] != 60], "control: some keys are excluded")
            for key in others:
                self.assertEqual(cint(rows[key].cooldown_minutes), 60, key)

    def test_seeding_does_not_touch_a_row_an_admin_already_set(self):
        with singleton_backup(DOCTYPE):
            _empty_notification_config_for_cooldowns()
            config = frappe.get_single(DOCTYPE)
            config.append(
                "notification_types",
                {
                    "notification_key": "payment_failure_first",
                    "label": "Mine",
                    "category": "Payment",
                    "recipient_policy": "Document-Field",
                    "cooldown_minutes": 5,
                    "enabled": 1,
                },
            )
            config.save()
            _run_install_seed_for_cooldowns()
            self.assertEqual(cint(_cooldown_rows_by_key()["payment_failure_first"].cooldown_minutes), 5)


class TestSyncRegistryUsesTheRegistryCooldown(FrappeTestCase):
    def _sync(self, **entry):
        entry.setdefault("notification_key", "payment_failure_first")
        return add_notification_types(json.dumps([entry]))

    def test_sync_registry_row_takes_the_registry_cooldown(self):
        with singleton_backup(DOCTYPE):
            _empty_notification_config_for_cooldowns()
            self.assertEqual(self._sync()["added"], 1)
            self.assertEqual(cint(_cooldown_rows_by_key()["payment_failure_first"].cooldown_minutes), 1440)

    def test_sync_registry_keeps_zero_and_an_explicit_value(self):
        with singleton_backup(DOCTYPE):
            _empty_notification_config_for_cooldowns()
            self._sync(notification_key="subscription_cancelled")
            self.assertEqual(cint(_cooldown_rows_by_key()["subscription_cancelled"].cooldown_minutes), 0)
            self._sync(notification_key="payment_failure_second", cooldown_minutes=7)
            self.assertEqual(cint(_cooldown_rows_by_key()["payment_failure_second"].cooldown_minutes), 7)
            self._sync(notification_key="member_activated")
            self.assertEqual(cint(_cooldown_rows_by_key()["member_activated"].cooldown_minutes), 60)


class TestZeroMeansNoCooldown(FrappeTestCase):
    def test_a_zero_cooldown_key_can_be_resent_at_once_and_a_1440_key_cannot(self):
        service = EmailService()._get_config_service()
        recipient = f"cooldown-{uuid.uuid4().hex[:8]}@example.com"
        with singleton_backup(DOCTYPE):
            _empty_notification_config_for_cooldowns()
            _run_install_seed_for_cooldowns()
            for key in ("payment_failure_final", "payment_failure_first"):
                service.clear_cooldown(key, recipient)
                self.addCleanup(service.clear_cooldown, key, recipient)
                service.record_send(key, recipient)
            self.assertTrue(service.check_cooldown("payment_failure_final", recipient), "0 = no cooldown")
            self.assertFalse(service.check_cooldown("payment_failure_first", recipient), "control: 1440 blocks")
