"""#2406: the patch gives an EXISTING site the row for the new staff-alert key.

Existing-site state is built by rewriting ``notification_types`` inside ``singleton_backup``; the
patch's ``execute`` is called directly (probe shortcut, stated; no real ``bench migrate``). The
alert path is then driven through ``notify_administrators``: unregistered it is skipped, after the
patch it is not. A pre-existing (disabled) row is left alone.
"""

import importlib

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.utils.notification_helpers import notify_administrators

DOCTYPE = "Verenigingen Email Configuration"
KEY = "mollie_forward_payment_staff_cancelled"
PATCH = "verenigingen.patches.v2_2.add_mollie_forward_payment_staff_cancelled_notification"


def _key_rows():
    return {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}


def _set_key_rows(rows):
    config = frappe.get_single(DOCTYPE)
    config.notification_types = []
    for row in rows:
        config.append("notification_types", row)
    config.save()


class TestAddMollieForwardPaymentStaffCancelledNotification(FrappeTestCase):
    def test_existing_site_gets_an_enabled_row_and_the_alert_stops_being_skipped(self):
        with singleton_backup(DOCTYPE):
            _set_key_rows([])
            before = notify_administrators(subject="s", message="m", notification_key=KEY)
            self.assertTrue(before.get("skipped"), "control: a key without a row is skipped")
            importlib.import_module(PATCH).execute()
            self.assertEqual(cint(_key_rows()[KEY].enabled), 1)
            after = notify_administrators(subject="s", message="m", notification_key=KEY)
            self.assertFalse(after.get("skipped"), after)

    def test_an_existing_row_is_left_alone(self):
        with singleton_backup(DOCTYPE):
            _set_key_rows(
                [
                    {
                        "notification_key": KEY,
                        "label": "Admin's own",
                        "category": "Payment",
                        "recipient_policy": "Role-Based",
                        "recipient_roles": "System Manager",
                        "cooldown_minutes": 7,
                        "enabled": 0,
                    }
                ]
            )
            importlib.import_module(PATCH).execute()
            row = _key_rows()[KEY]
            self.assertEqual((cint(row.enabled), row.label, cint(row.cooldown_minutes)), (0, "Admin's own", 7))
