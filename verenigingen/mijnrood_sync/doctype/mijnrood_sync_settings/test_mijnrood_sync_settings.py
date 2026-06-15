# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Integration tests for MijnRood Sync Settings.

Covers validation, default-population, team provisioning, status-mapping
cache helpers, and the get_status_mapping_for_client report endpoint. These
all create/validate real DB records — no business logic is mocked. The remote
SSH/SFTP/DB boundary methods (test_connection, fetch_*) are NOT exercised here
since there are no live MijnRood credentials.

MijnRood Sync Settings is a Single doctype, so the three child tables are
snapshotted in setUp and restored in tearDown to avoid leaking state across
tests.
"""

import frappe

from verenigingen.mijnrood_sync.doctype.mijnrood_sync_settings.mijnrood_sync_settings import (
    get_status_mapping_for_client,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_CHILD_TABLES = ("status_mapping", "role_mapping", "document_folder_mapping")


class TestMijnRoodSyncSettings(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("MijnRood Sync Settings")
        # Snapshot child tables + scalar fields we mutate so we can restore.
        self._snapshot = {
            tbl: [row.as_dict() for row in (self.settings.get(tbl) or [])] for tbl in _CHILD_TABLES
        }
        self._scalar_snapshot = {
            "tables_to_sync": self.settings.tables_to_sync,
            "poll_interval_minutes": self.settings.poll_interval_minutes,
            "ssh_port": self.settings.ssh_port,
            "db_port": self.settings.db_port,
        }
        # Start each test from empty child tables.
        for tbl in _CHILD_TABLES:
            self.settings.set(tbl, [])

    def tearDown(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        for tbl in _CHILD_TABLES:
            settings.set(tbl, [])
            for row in self._snapshot[tbl]:
                settings.append(tbl, row)
        for field, value in self._scalar_snapshot.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def _persist_settings(self):
        self.settings.save(ignore_permissions=True)

    # ---- validate: scalar fields ----------------------------------------

    def test_validate_rejects_non_json_tables_to_sync(self):
        self.settings.tables_to_sync = "not json"
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_validate_rejects_non_list_tables_to_sync(self):
        self.settings.tables_to_sync = '{"a": 1}'
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_validate_accepts_json_list_tables_to_sync(self):
        self.settings.tables_to_sync = '["admin_member"]'
        # Should not raise
        self.settings.validate()

    def test_validate_accepts_normal_poll_interval(self):
        self.settings.poll_interval_minutes = 15
        # Should not raise
        self.settings.validate()

    def test_validate_zero_poll_interval_bypasses_check(self):
        """A 0 poll interval is treated as falsy/unset and bypasses the
        `< 1` guard. Documents the actual behavior — the guard is
        effectively unreachable for an Int field since no positive int is
        < 1. (Product quirk, not a crash.)
        """
        self.settings.poll_interval_minutes = 0
        # No throw — guard short-circuits on the falsy 0
        self.settings.validate()

    def test_validate_rejects_bad_ssh_port(self):
        self.settings.ssh_port = 70000
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_validate_rejects_out_of_range_db_port(self):
        self.settings.db_port = 70000
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    # ---- _validate_status_mapping ---------------------------------------

    def test_status_mapping_duplicate_id_rejected(self):
        self.settings.append(
            "status_mapping",
            {"mijnrood_status_id": 5, "label": "A", "membership_type_string": "A"},
        )
        self.settings.append(
            "status_mapping",
            {"mijnrood_status_id": 5, "label": "B", "membership_type_string": "B"},
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_status_mapping_unique_ids_pass(self):
        self.settings.append(
            "status_mapping",
            {"mijnrood_status_id": 1, "label": "A", "membership_type_string": "A", "is_active": 0},
        )
        self.settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": 2,
                "label": "B",
                "membership_type_string": "B",
                "is_active": 0,
                "termination_type": "Administrative",
            },
        )
        # No duplicate -> validate passes (msgprints are warnings, not throws)
        self.settings.validate()

    # ---- _validate_role_mapping -----------------------------------------

    def test_role_mapping_duplicate_role_rejected(self):
        self.settings.append("role_mapping", {"mijnrood_role": "ROLE_ADMIN", "label": "A"})
        self.settings.append("role_mapping", {"mijnrood_role": "ROLE_ADMIN", "label": "B"})
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_role_mapping_board_without_chapter_role_rejected(self):
        self.settings.append(
            "role_mapping",
            {"mijnrood_role": "ROLE_ADMIN", "label": "A", "add_to_chapter_board": 1, "chapter_role": ""},
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_role_mapping_role_without_create_volunteer_rejected(self):
        role = frappe.get_all("Role", limit=1, pluck="name")[0]
        self.settings.append(
            "role_mapping",
            {
                "mijnrood_role": "ROLE_ADMIN",
                "label": "A",
                "verenigingen_role": role,
                "create_volunteer": 0,
            },
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_role_mapping_nonexistent_role_rejected(self):
        self.settings.append(
            "role_mapping",
            {
                "mijnrood_role": "ROLE_ADMIN",
                "label": "A",
                "verenigingen_role": "Definitely Nonexistent Role ZZZ",
                "create_volunteer": 1,
            },
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_role_mapping_add_to_team_without_team_rejected(self):
        self.settings.append(
            "role_mapping",
            {
                "mijnrood_role": "ROLE_ADMIN",
                "label": "A",
                "add_to_team": 1,
                "default_team": "",
                "create_volunteer": 1,
            },
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_role_mapping_add_to_team_without_volunteer_rejected(self):
        team = self.create_test_team()
        self.settings.append(
            "role_mapping",
            {
                "mijnrood_role": "ROLE_ADMIN",
                "label": "A",
                "add_to_team": 1,
                "default_team": team.name,
                "create_volunteer": 0,
            },
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.validate()

    def test_role_mapping_valid_team_assignment_passes(self):
        team = self.create_test_team()
        self.settings.append(
            "role_mapping",
            {
                "mijnrood_role": "ROLE_ADMIN",
                "label": "A",
                "add_to_team": 1,
                "default_team": team.name,
                "create_volunteer": 1,
            },
        )
        # No throw
        self.settings.validate()

    # ---- populate_default_status_mapping --------------------------------

    def test_populate_default_status_mapping(self):
        result = self.settings.populate_default_status_mapping()
        self.assertTrue(result["success"])
        self.assertGreater(len(self.settings.status_mapping), 0)
        # Verify persisted to DB
        reloaded = frappe.get_single("MijnRood Sync Settings")
        self.assertGreater(len(reloaded.status_mapping), 0)

    def test_populate_default_status_mapping_rejects_when_not_empty(self):
        self.settings.append(
            "status_mapping",
            {"mijnrood_status_id": 1, "label": "A", "membership_type_string": "A"},
        )
        self._persist_settings()
        with self.assertRaises(frappe.ValidationError):
            self.settings.populate_default_status_mapping()

    # ---- populate_default_role_mapping + _ensure_default_teams ----------

    def test_populate_default_role_mapping(self):
        result = self.settings.populate_default_role_mapping()
        self.assertTrue(result["success"])
        roles = [r.mijnrood_role for r in self.settings.role_mapping]
        self.assertIn("ROLE_ADMIN", roles)
        self.assertIn("ROLE_DIVISION_CONTACT", roles)
        # Default teams must exist after population
        self.assertTrue(frappe.db.exists("Team", "Landelijk Beheer"))
        self.assertTrue(frappe.db.exists("Team", "Secretariaat"))

    def test_populate_default_role_mapping_rejects_when_not_empty(self):
        self.settings.append("role_mapping", {"mijnrood_role": "ROLE_ADMIN", "label": "A"})
        self._persist_settings()
        with self.assertRaises(frappe.ValidationError):
            self.settings.populate_default_role_mapping()

    def test_ensure_default_teams_idempotent(self):
        first = self.settings._ensure_default_teams()
        self.assertEqual(first["admin"], "Landelijk Beheer")
        self.assertEqual(first["staff"], "Secretariaat")
        admin_team = frappe.get_doc("Team", "Landelijk Beheer")
        # Re-run should not create duplicates or change existing team
        second = self.settings._ensure_default_teams()
        self.assertEqual(first, second)
        self.assertEqual(frappe.db.count("Team", {"team_name": "Landelijk Beheer"}), 1)
        self.assertEqual(admin_team.name, frappe.get_doc("Team", "Landelijk Beheer").name)

    # ---- first_time_setup -----------------------------------------------

    def test_first_time_setup_populates_both_tables(self):
        result = self.settings.first_time_setup()
        self.assertTrue(result["success"])
        self.assertIn("status_mapping", result["sections_populated"])
        self.assertIn("role_mapping", result["sections_populated"])
        reloaded = frappe.get_single("MijnRood Sync Settings")
        self.assertGreater(len(reloaded.status_mapping), 0)
        self.assertGreater(len(reloaded.role_mapping), 0)

    def test_first_time_setup_idempotent_when_already_populated(self):
        self.settings.first_time_setup()
        # Second run: nothing left to populate
        settings2 = frappe.get_single("MijnRood Sync Settings")
        result = settings2.first_time_setup()
        self.assertTrue(result["success"])
        self.assertNotIn("sections_populated", result)
        self.assertIn("teams", result)

    # ---- get_status_mapping_for_client ----------------------------------

    def test_get_status_mapping_for_client_shape(self):
        result = get_status_mapping_for_client()
        self.assertIsInstance(result, dict)
        for status_id, entry in result.items():
            self.assertIsInstance(status_id, str)
            self.assertIn("label", entry)
            self.assertIn("is_terminated", entry)
            self.assertIsInstance(entry["is_terminated"], bool)

    # ---- on_update cache invalidation -----------------------------------

    def test_on_update_clears_caches(self):
        frappe.cache.set_value("mijnrood_status_mapping", "stale")
        frappe.cache.set_value("mijnrood_role_mapping", "stale")
        self.settings.on_update()
        self.assertIsNone(frappe.cache.get_value("mijnrood_status_mapping"))
        self.assertIsNone(frappe.cache.get_value("mijnrood_role_mapping"))

    # ---- import_documents guard (no SFTP needed) ------------------------

    def test_import_documents_rejects_when_no_mapping_configured(self):
        self.settings.set("document_folder_mapping", [])
        result = self.settings.import_documents()
        self.assertFalse(result["success"])
        self.assertIn("No folder mappings configured", result["message"])
