"""Real-DB integration tests for MijnRoodApplicationSyncService.

set_application_fields and locate_application_member are private but
tested directly via the service instance. The four public methods are
tested with real MijnRood Sync Event rows and a _FakeOrchestrator stub
for the not-yet-extracted cross-cutting helpers.
"""

import json
from unittest.mock import MagicMock

import frappe

from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _FakeOrchestrator:
    """Stand-in for MijnRoodEventApplicationService.

    Records calls to cross-cutting helpers that have not yet been
    extracted (PR #6 for related records, unassigned chapter helpers).
    """

    def __init__(self):
        self._create_related_records = MagicMock(return_value=[])
        self._assign_chapter_from_division = MagicMock(return_value=None)
        self._handle_division_field_change = MagicMock(return_value=None)
        self._apply_new_member = MagicMock(
            return_value={"success": True, "message": "fallback from stub"}
        )


class TestSetApplicationFields(EnhancedTestCase):
    """Pure-logic field-by-field update of a Member doc."""

    def test_applies_mapped_fields_to_member(self):
        member = self.factory.create_member(
            first_name="OldFirst",
            last_name="OldLast",
            email="set-fields-1@example.org",
        )

        service = get_application_sync_service()
        changed = service._set_application_fields(
            member,
            row_data={"first_name": "NewFirst", "last_name": "NewLast"},
            is_new=False,
        )

        self.assertTrue(changed)
        self.assertEqual(member.first_name, "NewFirst")
        self.assertEqual(member.last_name, "NewLast")

    def test_returns_false_when_no_field_changes(self):
        member = self.factory.create_member(
            first_name="Same",
            last_name="Person",
            email="set-fields-2@example.org",
        )

        service = get_application_sync_service()
        # EnhancedTestDataFactory uniquifies last_name (e.g. "Person123"),
        # so use the stored value to confirm the no-change path.
        changed = service._set_application_fields(
            member,
            row_data={"first_name": "Same", "last_name": member.last_name},
            is_new=False,
        )

        self.assertFalse(changed)

    def test_is_new_infers_bank_transfer_when_iban_present(self):
        member = self.factory.create_member(
            first_name="Iban",
            last_name="Test",
            email="set-fields-3@example.org",
        )
        member.iban = "NL91ABNA0417164300"
        member.payment_method = None

        service = get_application_sync_service()
        service._set_application_fields(
            member, row_data={"first_name": "Iban"}, is_new=True
        )

        self.assertEqual(member.payment_method, "Bank Transfer")

    def test_mollie_customer_id_overrides_payment_method(self):
        member = self.factory.create_member(
            first_name="Mollie",
            last_name="Test",
            email="set-fields-4@example.org",
        )
        member.mollie_customer_id = None
        member.payment_method = "Bank Transfer"

        service = get_application_sync_service()
        changed = service._set_application_fields(
            member,
            row_data={"custom_mollie_customer_id": "cst_test123"},
            is_new=False,
        )

        self.assertTrue(changed)
        self.assertEqual(member.mollie_customer_id, "cst_test123")
        self.assertEqual(member.payment_method, "Mollie")

    def test_skips_empty_string_and_none_values(self):
        member = self.factory.create_member(
            first_name="Keep",
            last_name="Original",
            email="set-fields-5@example.org",
        )
        # EnhancedTestDataFactory uniquifies last_name (e.g. "Original123");
        # capture the stored values so we can assert they were not overwritten.
        original_first_name = member.first_name
        original_last_name = member.last_name

        service = get_application_sync_service()
        service._set_application_fields(
            member,
            row_data={"first_name": "", "last_name": None, "iban": "NL91ABNA0417164300"},
            is_new=False,
        )

        self.assertEqual(member.first_name, original_first_name)
        self.assertEqual(member.last_name, original_last_name)
        self.assertEqual(member.iban, "NL91ABNA0417164300")
