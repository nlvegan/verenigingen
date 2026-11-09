"""#2174: the patch moves the two contact-request alert rows from the seeded 60 to 0.

Probe shortcut: existing-site state is built by rewriting ``notification_types`` and the patch's
``execute`` is called directly, not through the patch runner.
"""

import importlib

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.tests.fixtures.singleton_backup import singleton_backup

DOCTYPE = "Verenigingen Email Configuration"
PATCH = "verenigingen.patches.v2_2.zero_contact_request_cooldown_2174"
KEYS = ("contact_request_new", "contact_request_urgent")
ROW_META = {"category": "Admin", "recipient_policy": "Role-Based", "enabled": 1}


def _set_rows(cooldowns):
    config = frappe.get_single(DOCTYPE)
    config.notification_types = []
    for key, minutes in cooldowns.items():
        config.append(
            "notification_types", {"notification_key": key, "label": key, "cooldown_minutes": minutes, **ROW_META}
        )
    config.save()


def _rows():
    return {r.notification_key: cint(r.cooldown_minutes) for r in frappe.get_single(DOCTYPE).notification_types}


class TestZeroContactRequestCooldown(FrappeTestCase):
    def test_rows_at_the_seeded_60_move_to_0_and_other_rows_are_untouched(self):
        with singleton_backup(DOCTYPE):
            _set_rows({"contact_request_new": 60, "contact_request_urgent": 60, "member_activated": 60})
            importlib.import_module(PATCH).execute()
            self.assertEqual(
                _rows(), {"contact_request_new": 0, "contact_request_urgent": 0, "member_activated": 60}
            )

    def test_an_admins_own_value_is_left_alone(self):
        with singleton_backup(DOCTYPE):
            _set_rows({"contact_request_new": 15, "contact_request_urgent": 0})
            importlib.import_module(PATCH).execute()
            self.assertEqual(_rows(), {"contact_request_new": 15, "contact_request_urgent": 0})

    def test_the_patch_is_registered(self):
        from pathlib import Path

        import verenigingen

        listed = (Path(verenigingen.__file__).parent / "patches.txt").read_text().splitlines()
        self.assertIn(PATCH, listed)
