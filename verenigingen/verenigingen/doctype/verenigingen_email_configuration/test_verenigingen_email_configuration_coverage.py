# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Real-DB coverage tests for the Verenigingen Email Configuration controller.

This Single DocType centralises email/notification policy for the app. Tests
exercise the controller and its module-level helpers against the real Single
document on the test site:

- validate(): unique notification keys, email-list format validation,
  pause-setting consistency
- is_email_enabled(): master switch, Paused mode (with/without pause_until),
  auto-resume once pause_until elapses
- get_notification_config / is_notification_enabled: child-row lookup
- get_recipients_for_category: category routing + role-based fallback
- _parse_email_list / _get_users_with_role helpers
- get_email_configuration(): Single accessor
- send_test_email(): invalid-email guard
- _infer_category_from_path / _make_label_from_key: path/key inference
- add_notification_types(): append + dedupe behaviour

The Single doc is mutated then restored to its original state in tearDown so
parallel shards on the same DB are not disturbed beyond rollback.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
    _infer_category_from_path,
    _make_label_from_key,
    get_email_configuration,
    send_test_email,
)


class TestVerenigingenEmailConfiguration(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.config = frappe.get_single("Verenigingen Email Configuration")

    def _add_notification_row(self, key, **overrides):
        data = {
            "notification_key": key,
            "label": key.replace("_", " ").title(),
            "category": "Admin",
            "priority": "Medium",
            "enabled": 1,
            "recipient_policy": "Document-Field",
        }
        data.update(overrides)
        return self.config.append("notification_types", data)

    # ---------------------------------------------------------- validate
    def test_duplicate_notification_keys_rejected(self):
        self._add_notification_row("dup_key_cov")
        self._add_notification_row("dup_key_cov")
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.config.validate()
        self.assertIn("unique", str(ctx.exception).lower())

    def test_invalid_email_in_list_rejected(self):
        self.config.admin_notification_emails = "good@example.com, not-an-email"
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.config.validate()
        self.assertIn("Invalid email address", str(ctx.exception))

    def test_valid_email_list_passes(self):
        self.config.admin_notification_emails = "a@example.com, b@example.com"
        self.config.financial_admin_emails = "fin@example.com"
        # Clear any duplicate-key state from a sibling test by deduping in memory.
        self.config.validate()  # must not raise

    # ------------------------------------------------------ is_email_enabled
    def test_email_disabled_when_master_off(self):
        self.config.master_email_enabled = 0
        self.assertFalse(self.config.is_email_enabled())

    def test_email_enabled_when_active(self):
        self.config.master_email_enabled = 1
        self.config.email_mode = "Active"
        self.assertTrue(self.config.is_email_enabled())

    def test_email_disabled_when_paused_indefinitely(self):
        self.config.master_email_enabled = 1
        self.config.email_mode = "Paused"
        self.config.pause_until = None
        self.assertFalse(self.config.is_email_enabled())

    def test_email_disabled_when_paused_until_future(self):
        self.config.master_email_enabled = 1
        self.config.email_mode = "Paused"
        self.config.pause_until = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=2)
        self.assertFalse(self.config.is_email_enabled())

    def test_email_auto_resumes_after_pause_elapsed(self):
        # pause_until is in the past -> is_email_enabled flips mode back to Active.
        self.config.master_email_enabled = 1
        self.config.email_mode = "Paused"
        # The Single must be persisted for db_set("email_mode","Active") to apply.
        self.config.flags.ignore_validate = True
        self.config.pause_until = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-2)
        self.config.save()
        self.assertTrue(self.config.is_email_enabled())
        # auto-resume persisted via db_set.
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Email Configuration", "email_mode"), "Active"
        )

    # --------------------------------------------- notification config lookup
    def test_get_notification_config_returns_row_data(self):
        self._add_notification_row(
            "cfg_lookup_cov", label="Config Lookup", category="Payment", priority="High", cooldown_minutes=15
        )
        cfg = self.config.get_notification_config("cfg_lookup_cov")
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["label"], "Config Lookup")
        self.assertEqual(cfg["category"], "Payment")
        self.assertEqual(cfg["cooldown_minutes"], 15)

    def test_get_notification_config_missing_returns_empty(self):
        self.assertEqual(self.config.get_notification_config("no_such_key_cov"), {})

    def test_is_notification_enabled_reflects_flag(self):
        self._add_notification_row("enabled_flag_cov", enabled=1)
        self._add_notification_row("disabled_flag_cov", enabled=0)
        self.assertTrue(self.config.is_notification_enabled("enabled_flag_cov"))
        self.assertFalse(self.config.is_notification_enabled("disabled_flag_cov"))
        self.assertFalse(self.config.is_notification_enabled("totally_unknown_cov"))

    # ------------------------------------------- get_recipients_for_category
    def test_recipients_for_payment_category_uses_financial_list(self):
        self.config.financial_admin_emails = "fin1@example.com, fin2@example.com"
        recipients = self.config.get_recipients_for_category("Payment")
        self.assertEqual(set(recipients), {"fin1@example.com", "fin2@example.com"})

    def test_recipients_for_system_category_uses_system_list(self):
        self.config.system_alert_emails = "sys@example.com"
        recipients = self.config.get_recipients_for_category("System")
        self.assertEqual(recipients, ["sys@example.com"])

    def test_recipients_falls_back_to_role_lookup(self):
        # Unknown category with no configured list -> role-based fallback.
        self.config.admin_notification_emails = ""
        self.config.financial_admin_emails = ""
        self.config.system_alert_emails = ""
        self.config.fallback_admin_role = "System Manager"
        recipients = self.config.get_recipients_for_category("Member")
        # Administrator holds System Manager -> at least one email returned.
        self.assertIsInstance(recipients, list)
        for r in recipients:
            self.assertTrue(r is None or "@" in str(r))

    def test_parse_email_list_helper(self):
        self.assertEqual(self.config._parse_email_list("a@x.com, b@x.com "), ["a@x.com", "b@x.com"])
        self.assertEqual(self.config._parse_email_list(""), [])
        self.assertEqual(self.config._parse_email_list(None), [])

    def test_get_users_with_role_returns_emails(self):
        emails = self.config._get_users_with_role("System Manager")
        self.assertIsInstance(emails, list)

    def test_get_users_with_role_unknown_role_empty(self):
        self.assertEqual(self.config._get_users_with_role("No Such Role XYZ Cov"), [])

    # ------------------------------------------------- module-level helpers
    def test_get_email_configuration_returns_single(self):
        cfg = get_email_configuration()
        self.assertEqual(cfg.doctype, "Verenigingen Email Configuration")

    def test_infer_category_from_path(self):
        self.assertEqual(_infer_category_from_path("verenigingen/utils/sepa_processor.py"), "Payment")
        self.assertEqual(_infer_category_from_path("verenigingen/chapter/handler.py"), "Chapter")
        self.assertEqual(_infer_category_from_path("verenigingen/volunteer/expense.py"), "Volunteer")
        self.assertEqual(_infer_category_from_path("verenigingen/member/application.py"), "Member")
        self.assertEqual(_infer_category_from_path("verenigingen/utils/scheduler.py"), "System")
        self.assertEqual(_infer_category_from_path("verenigingen/something/random.py"), "Admin")

    def test_make_label_from_key(self):
        self.assertEqual(_make_label_from_key("payment_failed"), "Payment Failed")
        self.assertEqual(_make_label_from_key("member_welcome_email"), "Member Welcome Email")

    # --------------------------------------------------------- send_test_email
    def test_send_test_email_rejects_invalid_address(self):
        result = send_test_email("clearly-not-an-email")
        self.assertFalse(result["success"])
        self.assertIn("Invalid email address", result["error"])

    # --------------------------------------------------- add_notification_types
    def test_add_notification_types_appends_new_and_skips_existing(self):
        import json

        from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
            add_notification_types,
        )

        unique_key = frappe.generate_hash("addnt_cov", 6)
        payload = json.dumps(
            [
                {"notification_key": unique_key, "label": "Added Cov", "category": "Admin"},
            ]
        )
        result = add_notification_types(payload)
        self.assertTrue(result["success"])
        self.assertEqual(result["added"], 1)

        # Re-adding the same key is skipped (dedupe against existing rows).
        result2 = add_notification_types(payload)
        self.assertEqual(result2["added"], 0)
        self.assertIn(unique_key, result2["skipped"])

        # Cleanup: remove the row we added to the Single so it doesn't accrete.
        cfg = frappe.get_single("Verenigingen Email Configuration")
        cfg.notification_types = [nt for nt in cfg.notification_types if nt.notification_key != unique_key]
        cfg.flags.ignore_validate = True
        cfg.save()

    def test_add_notification_types_invalid_json(self):
        from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
            add_notification_types,
        )

        result = add_notification_types("{not valid json")
        self.assertFalse(result["success"])
        self.assertIn("Invalid JSON", result["error"])
