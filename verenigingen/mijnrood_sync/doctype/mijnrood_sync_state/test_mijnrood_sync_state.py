# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for the MijnRood Sync State doctype.

MijnRood Sync State is per-row sync bookkeeping (one record per MijnRood source
row) with no controller logic — the controller is a bare ``Document`` subclass.
Coverage is therefore inherently shallow: there is no ``validate``/hook branch.
These tests pin the framework-level contracts the doctype JSON declares and that
``polling_service`` relies on: autoname-from-fieldname (``name`` ==
``state_key``), the mandatory fields (``state_key``, ``mijnrood_table``,
``mijnrood_row_id``), the unique ``state_key`` constraint, and a JSON
``raw_data`` create+persist+reload roundtrip (read back by
``polling_service._resolve_division_name``).
"""

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMijnRoodSyncState(EnhancedTestCase):
    def _make_state(self, **overrides):
        data = {
            "doctype": "MijnRood Sync State",
            "state_key": overrides.pop("state_key", "admin_member-900001"),
            "mijnrood_table": "admin_member",
            "mijnrood_row_id": 900001,
            "row_checksum": "abc123",
            "raw_data": json.dumps({"division_name": "Amsterdam", "id": 900001}),
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        self.factory.track_document("MijnRood Sync State", doc.name)
        return doc

    def _make_raw(self, data):
        """Insert an arbitrary (possibly invalid) doc for negative-path tests."""
        return frappe.get_doc(data).insert(ignore_permissions=True)

    def test_autoname_from_state_key_and_json_roundtrip(self):
        """name comes from state_key and the raw_data JSON survives reload intact."""
        doc = self._make_state(state_key="admin_member-roundtrip")

        # autoname: "field:state_key" -> document name equals the state key
        self.assertEqual(doc.name, "admin_member-roundtrip")

        reloaded = frappe.get_doc("MijnRood Sync State", doc.name)
        self.assertEqual(reloaded.mijnrood_table, "admin_member")
        self.assertEqual(reloaded.mijnrood_row_id, 900001)
        self.assertEqual(reloaded.row_checksum, "abc123")

        # raw_data is a JSON field; parsing it back yields the original payload
        payload = json.loads(reloaded.raw_data)
        self.assertEqual(payload["division_name"], "Amsterdam")
        self.assertEqual(payload["id"], 900001)

    def test_missing_mandatory_fields_rejected(self):
        """state_key / mijnrood_table / mijnrood_row_id are mandatory."""
        # Missing mijnrood_table and mijnrood_row_id
        with self.assertRaises(frappe.MandatoryError):
            self._make_raw({"doctype": "MijnRood Sync State", "state_key": "incomplete-key"})

    def test_state_key_is_unique(self):
        """Two states with the same state_key collide (unique constraint)."""
        self._make_state(state_key="admin_member-dup")
        with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
            self._make_state(state_key="admin_member-dup")
