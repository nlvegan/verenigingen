"""#2012: the patch moves rows still at the seeded default 60 to the ruled v15 cooldown.

Existing-site state is built by rewriting ``notification_types``; the patch's ``execute`` is called
directly (probe shortcut, stated). The real patch runner is exercised separately by a
``bench migrate`` recorded in the PR. ``notification_types`` is not snapshotted: nothing here commits,
so the class-level rollback puts the rows back (#2159).

Known, accepted by the ruling: a row an admin deliberately set to 60 is indistinguishable from the
seeded default, so it is moved too.
"""

import importlib
import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint

from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.tests.utils.v15_cooldowns import ruled_v15_cooldowns

DOCTYPE = "Verenigingen Email Configuration"
PATCH = "verenigingen.patches.v2_2.apply_v15_cooldowns_to_seeded_rows"
ROW_META = {"category": "Member", "recipient_policy": "Document-Field", "enabled": 1}
IGNORED = {"name", "parent", "parentfield", "parenttype", "idx", "creation", "modified", "modified_by", "owner", "docstatus", "doctype"}
KEPT_AT_60 = "payment_success"  # v15 value is 60, so there is nothing to change
ADMIN_CHOICE_KEY = "membership_renewal_reminder"


def _cooldown_rows():
    return {r.notification_key: r for r in frappe.get_single(DOCTYPE).notification_types}


def _run_cooldown_patch():
    return importlib.import_module(PATCH).execute()


def _set_cooldown_rows(cooldowns):
    config = frappe.get_single(DOCTYPE)
    config.notification_types = []
    for key, minutes in cooldowns.items():
        config.append(
            "notification_types",
            {"notification_key": key, "label": key, "cooldown_minutes": minutes, **ROW_META},
        )
    config.save()


class TestApplyV15Cooldowns(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.ruled = ruled_v15_cooldowns(NOTIFICATION_KEYS)
        self.changing = {k: v for k, v in self.ruled.items() if v != 60}

    def test_a_row_at_60_gets_the_ruled_value_for_every_changing_key(self):
        self.assertGreater(len(self.changing), 15, "control: there are keys to move")
        _set_cooldown_rows(dict.fromkeys(self.changing, 60))
        _run_cooldown_patch()
        rows = _cooldown_rows()
        wrong = {k: cint(rows[k].cooldown_minutes) for k, v in self.changing.items() if cint(rows[k].cooldown_minutes) != v}
        self.assertEqual(wrong, {})

    def test_the_patch_table_is_exactly_the_ruled_keys_that_leave_60(self):
        self.assertEqual(importlib.import_module(PATCH).RULED_COOLDOWNS, self.changing)

    def test_a_row_at_another_value_is_an_admins_choice_and_is_left_alone(self):
        self.assertIn(ADMIN_CHOICE_KEY, self.changing, "control: this key would change from 60")
        _set_cooldown_rows({k: 15 for k in self.changing})
        _run_cooldown_patch()
        self.assertEqual({cint(r.cooldown_minutes) for r in _cooldown_rows().values()}, {15})

    def test_a_key_whose_ruled_value_is_60_is_untouched(self):
        self.assertEqual(self.ruled[KEPT_AT_60], 60, "control: v15 value really is 60")
        _set_cooldown_rows({KEPT_AT_60: 60, "member_activated": 60})
        before = {k: r.modified for k, r in _cooldown_rows().items()}
        _run_cooldown_patch()
        rows = _cooldown_rows()
        self.assertEqual({k: cint(r.cooldown_minutes) for k, r in rows.items()}, {KEPT_AT_60: 60, "member_activated": 60})
        self.assertEqual({k: r.modified for k, r in rows.items()}, before)

    def test_a_key_not_in_the_ruling_is_untouched_at_60(self):
        _set_cooldown_rows({"payment_reminder_friendly": 60, "member_activated": 60})
        _run_cooldown_patch()
        self.assertEqual({cint(r.cooldown_minutes) for r in _cooldown_rows().values()}, {60})

    def test_a_second_run_changes_nothing(self):
        _set_cooldown_rows({**dict.fromkeys(self.changing, 60), ADMIN_CHOICE_KEY: 15})
        _run_cooldown_patch()
        first = {k: (cint(r.cooldown_minutes), r.modified) for k, r in _cooldown_rows().items()}
        _run_cooldown_patch()
        self.assertEqual({k: (cint(r.cooldown_minutes), r.modified) for k, r in _cooldown_rows().items()}, first)

    def test_the_cached_config_doc_sees_the_new_value(self):
        # The patch writes by SQL, so without clearing the document cache get_cached_doc keeps the 60.
        _set_cooldown_rows({"termination_overdue": 60})
        primed = frappe.get_cached_doc(DOCTYPE)
        self.assertEqual(cint(primed.notification_types[0].cooldown_minutes), 60, "control: cache primed at 60")
        _run_cooldown_patch()
        cached = frappe.get_cached_doc(DOCTYPE)
        self.assertEqual(cint(cached.notification_types[0].cooldown_minutes), self.changing["termination_overdue"])

    def test_a_missing_row_is_not_created(self):
        _set_cooldown_rows({"member_activated": 60})
        _run_cooldown_patch()
        self.assertEqual(set(_cooldown_rows()), {"member_activated"})

    def test_the_patch_is_listed_in_post_model_sync(self):
        text = (Path(frappe.get_app_path("verenigingen")) / "patches.txt").read_text()
        sections = re.split(r"^\[(\w+)\]\s*$", text, flags=re.M)
        listed = dict(zip(sections[1::2], sections[2::2]))
        self.assertIn(PATCH, [ln.strip() for ln in listed["post_model_sync"].splitlines()])
        self.assertNotIn(PATCH, [ln.strip() for ln in listed["pre_model_sync"].splitlines()])
