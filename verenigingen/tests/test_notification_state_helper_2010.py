"""``own_notification_keys`` really gives a test the notification state it claims (#2010).

Control for the helper the "email was sent" tests rely on: a helper that silently seeded nothing
would leave all of them passing by skipping again.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.tests.utils.notification_state import own_notification_keys

DOCTYPE = "Verenigingen Email Configuration"
KEY = "payment_reminder_friendly"


def _config_rows_2010():
    config = frappe.get_single(DOCTYPE)
    return {r.notification_key: (r.enabled, r.cooldown_minutes) for r in config.notification_types}


def _send_with_key():
    return get_email_service()._send_email_internal(
        recipients=[f"owned.{frappe.generate_hash(length=8)}@example.com"],
        subject="Subject",
        content="<p>Body</p>",
        notification_key=KEY,
    )


class TestOwnNotificationKeys(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.owner = unittest.TestCase()  # stands in for a test: carries addCleanup/doCleanups
        config = frappe.get_single(DOCTYPE)
        self.original_rows = _config_rows_2010()
        self.original_master = config.master_email_enabled
        self.addCleanup(self._put_state_back)

    def _put_state_back(self):
        from verenigingen.tests.utils.notification_state import _restore_notification_rows

        _restore_notification_rows(
            [
                {"notification_key": k, "label": k, "category": "Admin", "enabled": e, "cooldown_minutes": c}
                for k, (e, c) in self.original_rows.items()
            ],
            self.original_master,
        )

    def _set_row(self, enabled, cooldown):
        config = frappe.get_single(DOCTYPE)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key != KEY])
        config.append(
            "notification_types",
            {
                "notification_key": KEY,
                "label": KEY,
                "category": "Payment",
                "enabled": enabled,
                "cooldown_minutes": cooldown,
            },
        )
        config.master_email_enabled = 0
        config.save()

    def test_a_missing_key_is_enabled_without_cooldown_and_gone_again(self):
        config = frappe.get_single(DOCTYPE)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key != KEY])
        config.save()
        self.assertTrue((_send_with_key().data or {}).get("skipped"), "control: an unseeded key skips")

        own_notification_keys(self.owner, KEY)
        self.assertEqual(_config_rows_2010()[KEY], (1, 0))
        self.assertFalse((_send_with_key().data or {}).get("skipped"))

        self.owner.doCleanups()
        self.assertNotIn(KEY, _config_rows_2010())

    def test_a_disabled_key_in_cooldown_is_enabled_and_put_back_as_it_was(self):
        self._set_row(enabled=0, cooldown=1440)
        self.assertTrue((_send_with_key().data or {}).get("skipped"), "control: a disabled key skips")

        own_notification_keys(self.owner, KEY)
        self.assertEqual(_config_rows_2010()[KEY], (1, 0))
        self.assertEqual(frappe.get_single(DOCTYPE).master_email_enabled, 1)
        self.assertFalse((_send_with_key().data or {}).get("skipped"))

        self.owner.doCleanups()
        self.assertEqual(_config_rows_2010()[KEY], (0, 1440))
        self.assertEqual(frappe.get_single(DOCTYPE).master_email_enabled, 0)

    def test_a_commit_while_the_keys_are_owned_fails_the_cleanup_loudly(self):
        """A commit makes the seed permanent (the restore is uncommitted), so it must not pass silently."""
        own_notification_keys(self.owner, KEY)
        frappe.db.commit()  # Probe: stands in for production code under test that commits

        self.assertFalse(self.owner.doCleanups(), "the cleanup must report the leak")
        # What the commit persisted is undone here, by hand, as this test is the one that committed it
        self._put_state_back()
        frappe.db.commit()
