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
            "state_key": f"admin_division:{row_id}",
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
