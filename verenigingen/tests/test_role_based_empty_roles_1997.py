"""A Role-Based notification row with no ``recipient_roles`` must not crash (#1997).

Writers that leave such a row: "Sync Registry" (``add_notification_types``), and the form itself
(switching a row to Role-Based leaves the roles empty). The reader then called ``.split`` on None.

Real flows: the whitelisted ``add_notification_types`` and ``notify_administrators``. Probe
shortcut: the "empty roles" row for the reader tests is appended directly (the form UI path was
not driven in a browser); the Sync Registry writer test uses the real endpoint.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.services.communication.email_configuration_service import (
    get_email_configuration_service,
)
from verenigingen.utils.constants import Roles
from verenigingen.utils.notification_helpers import notify_administrators
from verenigingen.verenigingen.doctype.verenigingen_email_configuration.verenigingen_email_configuration import (
    add_notification_types,
)

DOCTYPE = "Verenigingen Email Configuration"


def _registry_key_with_policy_1997(policy):
    return next(k for k, m in sorted(NOTIFICATION_KEYS.items()) if m["recipient_policy"] == policy)


def _config_row_1997(key):
    return next(r for r in frappe.get_single(DOCTYPE).notification_types if r.notification_key == key)


def _drop_config_row_1997(key):
    config = frappe.get_single(DOCTYPE)
    config.set("notification_types", [r for r in config.notification_types if r.notification_key != key])
    config.save()


def _set_empty_role_row_1997(key):
    _drop_config_row_1997(key)
    config = frappe.get_single(DOCTYPE)
    config.append(
        "notification_types",
        {
            "notification_key": key,
            "label": key,
            "category": "Admin",
            "recipient_policy": "Role-Based",
            "enabled": 1,
        },
    )
    config.save()
    assert not _config_row_1997(key).recipient_roles, "control: the row has no roles"


def _snapshot_rows_1997():
    """Plain copy of the child rows; ``singleton_backup`` does not restore child tables (#2029)."""
    fields = [f.fieldname for f in frappe.get_meta("Email Notification Type").fields if f.fieldtype != "Section Break"]
    return [{f: r.get(f) for f in fields} for r in frappe.get_single(DOCTYPE).notification_types]


def _restore_rows_1997(rows):
    config = frappe.get_single(DOCTYPE)
    config.set("notification_types", rows)
    config.save()


class TestRoleBasedEmptyRoles(FrappeTestCase):
    def setUp(self):
        # Own the child rows (#2029: singleton_backup does not restore them, and it commits, so it would
        # make a leak permanent). Uncommitted here, so the class-level rollback also undoes it.
        rows = _snapshot_rows_1997()
        self.addCleanup(_restore_rows_1997, rows)
        self.role_key = _registry_key_with_policy_1997("Role-Based")

    def test_reader_returns_empty_list_instead_of_raising(self):
        _set_empty_role_row_1997(self.role_key)
        self.assertEqual(
            get_email_configuration_service().get_recipients_for_notification(self.role_key), []
        )

    def test_notify_administrators_falls_back_to_admin_roles_for_empty_roles(self):
        """The alert is not dropped: the caller falls back to the admin roles (as for Fixed/Custom)."""
        _set_empty_role_row_1997(self.role_key)
        result = notify_administrators(subject="s", message="m", notification_key=self.role_key)
        self.assertFalse(result.get("skipped"), result)
        self.assertTrue(result.get("success"), result)
        self.assertGreater(result.get("notifications_created", 0), 0, result)

    def test_sync_registry_writes_admin_roles_for_a_role_based_key(self):
        _drop_config_row_1997(self.role_key)
        out = add_notification_types(json.dumps([{"notification_key": self.role_key}]))
        self.assertEqual(out["added"], 1, out)
        self.assertEqual(set(_config_row_1997(self.role_key).recipient_roles.split(", ")), set(Roles.ADMIN_PAIR))

    def test_sync_registry_leaves_other_policies_without_roles(self):
        """Control: only Role-Based rows get roles; a Document-Field row must stay without."""
        key = _registry_key_with_policy_1997("Document-Field")
        _drop_config_row_1997(key)
        out = add_notification_types(json.dumps([{"notification_key": key}]))
        self.assertEqual(out["added"], 1, out)
        self.assertFalse(_config_row_1997(key).recipient_roles)
