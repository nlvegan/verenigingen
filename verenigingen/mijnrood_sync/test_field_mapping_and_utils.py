# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for the pure MijnRood field-mapping helpers and JSON utils.

field_mapping.py exposes get_* reader functions that fall back to the
module-level _DEFAULT_* maps when the MijnRood Sync Settings status_mapping
child table is empty, and read from the cached child table when populated.
These tests exercise BOTH branches (empty -> defaults, populated -> config)
and the pure utils.safe_json_load / safe_int helpers directly.

No business logic is mocked. The settings doctype is a Single; tests that
populate its status_mapping snapshot + restore the table to avoid leaking.
"""

import frappe

from verenigingen.mijnrood_sync.field_mapping import (
    _DEFAULT_STATUS_ID_LABELS,
    _DEFAULT_STATUS_ID_MAP,
    _DEFAULT_TERMINATED_STATUS_IDS,
    MIJNROOD_FIELD_LABELS,
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    TABLE_COLUMNS,
    TABLE_PRIMARY_KEY,
    get_active_status_ids,
    get_status_id_map,
    get_status_labels,
    get_terminated_status_ids,
    get_termination_type_map,
    get_verenigingen_membership_type_for_status_id,
)
from verenigingen.mijnrood_sync.utils import safe_int, safe_json_load
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _clear_mapping_cache():
    frappe.cache.delete_value("mijnrood_status_mapping")


class TestMijnRoodUtils(EnhancedTestCase):
    """Pure helpers — no DB, no mocking."""

    # ---- safe_int -------------------------------------------------------

    def test_safe_int_parses_numeric_string(self):
        self.assertEqual(safe_int("42"), 42)

    def test_safe_int_passes_through_int(self):
        self.assertEqual(safe_int(7), 7)

    def test_safe_int_none_returns_none(self):
        self.assertIsNone(safe_int(None))

    def test_safe_int_empty_string_returns_none(self):
        self.assertIsNone(safe_int(""))

    def test_safe_int_garbage_returns_none(self):
        self.assertIsNone(safe_int("abc"))

    def test_safe_int_list_returns_none(self):
        # TypeError path
        self.assertIsNone(safe_int([1, 2]))

    # ---- safe_json_load -------------------------------------------------

    def test_safe_json_load_parses_object(self):
        self.assertEqual(safe_json_load('{"a": 1}'), {"a": 1})

    def test_safe_json_load_parses_list(self):
        self.assertEqual(safe_json_load("[1, 2, 3]"), [1, 2, 3])

    def test_safe_json_load_none_returns_default_dict(self):
        # Default default is {}
        self.assertEqual(safe_json_load(None), {})

    def test_safe_json_load_empty_string_returns_default(self):
        self.assertEqual(safe_json_load(""), {})

    def test_safe_json_load_falsy_returns_explicit_default(self):
        # An explicit list default is honored on falsy input
        self.assertEqual(safe_json_load(None, default=[]), [])

    def test_safe_json_load_explicit_default_ignored_when_input_present(self):
        # default only applies on falsy input — valid JSON wins
        self.assertEqual(safe_json_load('{"x": 9}', default=[]), {"x": 9})

    def test_safe_json_load_invalid_json_raises(self):
        # Documents that safe_json_load does NOT swallow malformed JSON —
        # it guards None/empty only, and lets json.JSONDecodeError propagate.
        import json

        with self.assertRaises(json.JSONDecodeError):
            safe_json_load("{not valid json")


class TestFieldMappingDefaults(EnhancedTestCase):
    """get_* readers fall back to defaults when status_mapping is empty."""

    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("MijnRood Sync Settings")
        self._snapshot = [row.as_dict() for row in (self.settings.status_mapping or [])]
        # Force the empty-table / defaults branch.
        self.settings.set("status_mapping", [])
        self.settings.flags.ignore_validate = True
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()
        _clear_mapping_cache()

    def tearDown(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("status_mapping", [])
        for row in self._snapshot:
            settings.append("status_mapping", row)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        _clear_mapping_cache()
        super().tearDown()

    def test_status_id_map_falls_back_to_defaults(self):
        result = get_status_id_map()
        self.assertEqual(result, dict(_DEFAULT_STATUS_ID_MAP))
        self.assertEqual(result[1], "lid")
        self.assertEqual(result[3], "opgezegd")

    def test_status_id_map_returns_a_copy(self):
        # Mutating the result must not corrupt the module-level default.
        result = get_status_id_map()
        result[99] = "mutant"
        self.assertNotIn(99, _DEFAULT_STATUS_ID_MAP)

    def test_active_status_ids_default(self):
        self.assertEqual(get_active_status_ids(), frozenset([1, 2]))

    def test_terminated_status_ids_default(self):
        self.assertEqual(get_terminated_status_ids(), _DEFAULT_TERMINATED_STATUS_IDS)
        self.assertEqual(get_terminated_status_ids(), frozenset([3, 4, 5, 6]))

    def test_termination_type_map_default(self):
        result = get_termination_type_map()
        self.assertEqual(result[3], "Voluntary")
        self.assertEqual(result[5], "Deceased")
        # Active statuses (1, 2) are not in the termination-type map.
        self.assertNotIn(1, result)
        self.assertNotIn(2, result)

    def test_status_labels_default(self):
        result = get_status_labels()
        self.assertEqual(result, dict(_DEFAULT_STATUS_ID_LABELS))
        self.assertEqual(result[1], "Active (lid)")
        self.assertEqual(result[4], "Expelled (geroyeerd)")

    def test_verenigingen_membership_type_none_when_no_mapping(self):
        # No config -> None for any status id.
        self.assertIsNone(get_verenigingen_membership_type_for_status_id(1))


class TestFieldMappingConfigured(EnhancedTestCase):
    """get_* readers read from the configured status_mapping child table."""

    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("MijnRood Sync Settings")
        self._snapshot = [row.as_dict() for row in (self.settings.status_mapping or [])]
        self.settings.set("status_mapping", [])
        # Two configured rows: one active, one terminated with a vereniging MT.
        self.settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": 1,
                "label": "Custom Active",
                "membership_type_string": "active_custom",
                "is_active": 1,
            },
        )
        self.settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": 9,
                "label": "Custom Gone",
                "membership_type_string": "gone_custom",
                "is_active": 0,
                "termination_type": "Voluntary",
            },
        )
        self.settings.flags.ignore_validate = True
        self.settings.save(ignore_permissions=True)
        frappe.db.commit()
        _clear_mapping_cache()

    def tearDown(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("status_mapping", [])
        for row in self._snapshot:
            settings.append("status_mapping", row)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        _clear_mapping_cache()
        super().tearDown()

    def test_status_id_map_reads_config(self):
        result = get_status_id_map()
        self.assertEqual(result[1], "active_custom")
        self.assertEqual(result[9], "gone_custom")
        # The default id 3 must NOT leak in once config is present.
        self.assertNotIn(3, result)

    def test_active_status_ids_reads_config(self):
        self.assertEqual(get_active_status_ids(), frozenset([1]))

    def test_terminated_status_ids_reads_config(self):
        self.assertEqual(get_terminated_status_ids(), frozenset([9]))

    def test_termination_type_map_reads_config(self):
        result = get_termination_type_map()
        self.assertEqual(result, {9: "Voluntary"})

    def test_status_labels_reads_config(self):
        result = get_status_labels()
        self.assertEqual(result[1], "Custom Active")
        self.assertEqual(result[9], "Custom Gone")


class TestStaticMappingConstants(EnhancedTestCase):
    """Sanity checks on the static constant maps (used app-wide)."""

    def test_table_columns_keys_match_primary_key_keys(self):
        # Every table with a column list must have a registered primary key.
        self.assertEqual(set(TABLE_COLUMNS.keys()), set(TABLE_PRIMARY_KEY.keys()))

    def test_all_primary_keys_are_id(self):
        self.assertTrue(all(pk == "id" for pk in TABLE_PRIMARY_KEY.values()))

    def test_member_field_map_status_target(self):
        self.assertEqual(MIJNROOD_TO_MEMBER_FIELD_MAP["current_membership_status_id"], "membership_type")
        self.assertEqual(MIJNROOD_TO_MEMBER_FIELD_MAP["division_id"], "chapter")

    def test_contribution_cents_is_not_mapped_raw(self):
        """Re-adding this key would silently reintroduce the shadowing bug.

        The column needs a cents→euros conversion, done in
        mapping_service.map_member_fields(). Mapping it here as well meant the raw
        cents value won whenever the conversion was skipped — i.e. exactly when
        cents == 0 — which zeroed the member's real dues rate (MR-SYNC-2026-00087:
        €9.00 → €0.00 via DuesScheduleRepository.update_schedule_rate, whose gate
        is `if new_rate is not None` and therefore admits 0).
        """
        self.assertNotIn("contribution_per_period_in_cents", MIJNROOD_TO_MEMBER_FIELD_MAP)

    def test_field_labels_cover_status_column(self):
        self.assertEqual(MIJNROOD_FIELD_LABELS["current_membership_status_id"], "Membership Status")
