"""Real-DB integration tests for MijnRoodMappingService.

extract_email() is tested as a pure helper; map_member_fields() and
resolve_division_id() require Chapter / MijnRood Sync State fixtures.
"""

import frappe

from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
    get_mapping_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExtractEmail(EnhancedTestCase):
    """extract_email is a pure helper — no DB needed but kept here for cohesion."""

    def test_returns_value_for_valid_email_string(self):
        self.assertEqual(extract_email("alice@example.org"), "alice@example.org")

    def test_returns_none_for_numeric_string(self):
        # MijnRood's email_id column sometimes contains a numeric FK
        self.assertIsNone(extract_email("12345"))

    def test_returns_none_for_string_without_at_sign(self):
        self.assertIsNone(extract_email("not-an-email"))

    def test_returns_none_for_none(self):
        self.assertIsNone(extract_email(None))

    def test_returns_none_for_integer(self):
        self.assertIsNone(extract_email(12345))

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(extract_email(""))


class TestResolveDivisionId(EnhancedTestCase):
    """resolve_division_id checks Chapter.mijnrood_division_id, then
    falls back to MijnRood Sync State raw_data for chapters that predate
    the ID field.
    """

    def test_returns_chapter_name_via_direct_id_field(self):
        # Create a chapter with mijnrood_division_id set. create_chapter
        # accepts arbitrary kwargs and forwards them to the doc.
        chapter = self.factory.create_chapter(mijnrood_division_id=42)

        service = get_mapping_service()
        result = service.resolve_division_id(42)

        self.assertEqual(result, chapter.name)

    def _insert_sync_state(self, row_id: int, name_value: str):
        """Test fixture helper — creates a MijnRood Sync State row and
        registers cleanup. raw_data is the JSON blob the service decodes.
        """
        state = frappe.get_doc({
            "doctype": "MijnRood Sync State",
            "mijnrood_table": "admin_division",
            "mijnrood_row_id": row_id,
            "state_key": f"admin_division-{row_id}",
            "raw_data": f'{{"name": "{name_value}"}}',
            "row_checksum": "0" * 32,
        }).insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.delete_doc(
            "MijnRood Sync State", state.name, ignore_permissions=True, force=True
        ))
        return state

    def test_falls_back_to_sync_state_when_id_field_unset(self):
        # Create a sync state row for a division that's NOT linked to a
        # Chapter via the direct field. raw_data must include "name".
        self._insert_sync_state(999, "Sync-State-Chapter")

        service = get_mapping_service()
        result = service.resolve_division_id(999)

        self.assertEqual(result, "Sync-State-Chapter")

    def test_returns_none_when_neither_source_has_match(self):
        service = get_mapping_service()
        result = service.resolve_division_id(987654)  # nonexistent

        self.assertIsNone(result)


class TestMapMemberFields(EnhancedTestCase):
    """map_member_fields translates MijnRood row dicts via the configured
    status / role / period mappings. Status_id with no mapping must raise
    ValueError (Tier A audit guarantee — event remains visible to operator).
    """

    def setUp(self):
        super().setUp()
        # Ensure a known status mapping exists. Use mijnrood_status_id=999
        # to avoid collision with seed data.
        settings = frappe.get_single("MijnRood Sync Settings")
        original = list(settings.status_mapping or [])
        # Pick a Membership Type that already exists in the test fixture
        # set, or create one if not.
        membership_type = self.factory.ensure_membership_type("Mapping Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 999,
            "label": "Test Status",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        def _cleanup():
            settings = frappe.get_single("MijnRood Sync Settings")
            settings.status_mapping = original
            settings.save(ignore_permissions=True)
            frappe.db.commit()
        self.addCleanup(_cleanup)
        # Force the field_mapping cache to refresh
        frappe.cache().delete_value("mijnrood_status_mapping")

    def test_maps_basic_field_translations(self):
        # MIJNROOD_TO_MEMBER_FIELD_MAP is the source of truth. Pick a few
        # well-known mappings to assert the loop runs.
        result = get_mapping_service().map_member_fields({
            "first_name": "Alice",
            "last_name": "Example",
            "current_membership_status_id": 999,
        })
        self.assertEqual(result["first_name"], "Alice")
        self.assertEqual(result["last_name"], "Example")

    def test_filters_empty_string_and_none_values(self):
        result = get_mapping_service().map_member_fields({
            "first_name": "",
            "last_name": None,
            "city": "Amsterdam",
            "current_membership_status_id": 999,
        })
        self.assertNotIn("first_name", result)
        self.assertNotIn("last_name", result)
        self.assertEqual(result["city"], "Amsterdam")

    def test_status_id_with_explicit_mapping_sets_membership_type(self):
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
        })
        self.assertIn("membership_type", result)
        self.assertEqual(result["membership_type"], "Mapping Test Type")

    def test_unmapped_status_id_raises_valueerror(self):
        # Tier A guarantee: silent skip → ValueError → event surfaces in queue
        with self.assertRaises(ValueError) as cm:
            get_mapping_service().map_member_fields({
                "id": 12345,
                "current_membership_status_id": 99999,  # not in mapping
            })
        self.assertIn("99999", str(cm.exception))
        self.assertIn("Lidmaatschapstypes", str(cm.exception))

    def test_converts_cents_to_euros(self):
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_per_period_in_cents": 1250,
        })
        self.assertEqual(result["dues_rate"], 12.5)

    def test_zero_cents_leaves_dues_rate_unset(self):
        """MijnRood 0 cents means "no custom amount", not "a €0 dues rate".

        Regression for MR-SYNC-2026-00087: MIJNROOD_TO_MEMBER_FIELD_MAP used to
        map contribution_per_period_in_cents → dues_rate raw, and the cents→euros
        conversion below it is guarded by `if cents:`. So the raw value only ever
        won when it was exactly 0 — and applying an address-only Changed event
        zeroed the member's real dues rate (observed: €9.00 → €0.00). Leaving the
        key unset lets the membership type / template default stand.
        """
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_per_period_in_cents": 0,
        })
        self.assertNotIn("dues_rate", result)

    def test_maps_known_contribution_period(self):
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_period": 1,  # Quarterly in MijnRood
        })
        self.assertEqual(result["payment_period"], "Per kwartaal")

    def test_unknown_contribution_period_is_logged_and_omitted(self):
        # logger.warning, key not set — should not raise
        result = get_mapping_service().map_member_fields({
            "current_membership_status_id": 999,
            "contribution_period": 99,
        })
        self.assertNotIn("payment_period", result)
