# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for MijnRoodPollingService._poll_division_contacts().

Tests cover:
- No changes detected when current matches previous
- Synthetic Changed events created for new/changed/removed contacts
- Malformed JSON in last_division_contacts_hash handled gracefully
- State persisted after poll
- Empty current data with non-empty previous creates events
"""

import json
from unittest.mock import MagicMock, call, patch

import frappe

from verenigingen.mijnrood_sync.services.polling_service import (
    MijnRoodPollingService,
    compute_change_tags,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPollDivisionContacts(EnhancedTestCase):
    """Tests for _poll_division_contacts()."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()

    def _make_settings(self, last_hash=None):
        """Create a mock settings object."""
        settings = MagicMock()
        settings.last_division_contacts_hash = last_hash
        return settings

    def _make_client(self, current_data):
        """Create a mock client returning given division contact data."""
        client = MagicMock()
        client.fetch_division_contacts.return_value = current_data
        return client

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_no_changes_creates_no_events(self, mock_frappe, mock_create_event, mock_find):
        """No events created when current state matches previous."""
        current = {100: [1, 2], 200: [3]}
        previous = json.dumps({"100": [1, 2], "200": [3]})

        client = self._make_client(current)
        settings = self._make_settings(last_hash=previous)

        count = self.service._poll_division_contacts(client, settings, "run-001")

        self.assertEqual(count, 0)
        mock_create_event.assert_not_called()
        # State still persisted (idempotent)
        settings.db_set.assert_called_once()

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_new_contact_creates_changed_event(self, mock_frappe, mock_create_event, mock_find):
        """A newly appearing member creates a synthetic Changed event."""
        current = {100: [1, 2]}
        # No previous state
        client = self._make_client(current)
        settings = self._make_settings(last_hash=None)

        count = self.service._poll_division_contacts(client, settings, "run-001")

        self.assertEqual(count, 1)
        mock_create_event.assert_called_once()
        call_kwargs = mock_create_event.call_args
        self.assertEqual(call_kwargs.kwargs.get("event_type") or call_kwargs[1].get("event_type", call_kwargs[0][0] if call_kwargs[0] else None), "Changed")

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_changed_divisions_creates_event(self, mock_frappe, mock_create_event, mock_find):
        """Changed division assignments create a synthetic Changed event."""
        current = {100: [1, 2, 3]}  # gained division 3
        previous = json.dumps({"100": [1, 2]})

        client = self._make_client(current)
        settings = self._make_settings(last_hash=previous)

        count = self.service._poll_division_contacts(client, settings, "run-001")

        self.assertEqual(count, 1)
        # Verify the event contains correct old/new data
        args, kwargs = mock_create_event.call_args
        # _create_sync_event is called with keyword args
        self.assertEqual(kwargs.get("old_data"), {"managed_division_ids": [1, 2]})
        self.assertEqual(kwargs.get("new_data"), {"managed_division_ids": [1, 2, 3]})

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_removed_contact_creates_event(self, mock_frappe, mock_create_event, mock_find):
        """A member removed from all divisions creates a synthetic Changed event."""
        current = {}  # member 100 gone
        previous = json.dumps({"100": [1, 2]})

        client = self._make_client(current)
        settings = self._make_settings(last_hash=previous)

        count = self.service._poll_division_contacts(client, settings, "run-001")

        self.assertEqual(count, 1)
        args, kwargs = mock_create_event.call_args
        self.assertEqual(kwargs.get("old_data"), {"managed_division_ids": [1, 2]})
        self.assertEqual(kwargs.get("new_data"), {"managed_division_ids": []})

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_malformed_json_treated_as_empty(self, mock_frappe, mock_create_event, mock_find):
        """Malformed last_division_contacts_hash treated as empty (all contacts are 'new')."""
        current = {100: [1], 200: [2]}

        client = self._make_client(current)
        settings = self._make_settings(last_hash="not valid json{{{")

        count = self.service._poll_division_contacts(client, settings, "run-001")

        # Both members appear new
        self.assertEqual(count, 2)

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_state_persisted_as_json(self, mock_frappe, mock_create_event, mock_find):
        """Current state is persisted to settings as sorted JSON with string keys."""
        current = {200: [3, 4], 100: [1, 2]}

        client = self._make_client(current)
        settings = self._make_settings(last_hash=None)

        self.service._poll_division_contacts(client, settings, "run-001")

        persisted = settings.db_set.call_args[0]
        self.assertEqual(persisted[0], "last_division_contacts_hash")
        parsed = json.loads(persisted[1])
        # Keys should be strings (JSON requirement)
        self.assertIn("100", parsed)
        self.assertIn("200", parsed)
        self.assertEqual(parsed["100"], [1, 2])

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value="MEM-001")
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_linked_member_passed_to_event(self, mock_frappe, mock_create_event, mock_find):
        """linked_member from _find_linked_member is passed to _create_sync_event."""
        current = {100: [1]}

        client = self._make_client(current)
        settings = self._make_settings(last_hash=None)

        self.service._poll_division_contacts(client, settings, "run-001")

        args, kwargs = mock_create_event.call_args
        self.assertEqual(kwargs.get("linked_member"), "MEM-001")
        mock_find.assert_called_once_with("admin_member", 100)

    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_fetch_exception_returns_zero(self, mock_frappe):
        """Exception from fetch_division_contacts returns 0, does not propagate."""
        client = MagicMock()
        client.fetch_division_contacts.side_effect = Exception("table not found")

        settings = self._make_settings(last_hash=None)

        count = self.service._poll_division_contacts(client, settings, "run-001")

        self.assertEqual(count, 0)

    @patch.object(MijnRoodPollingService, "_find_linked_member", return_value=None)
    @patch.object(MijnRoodPollingService, "_create_sync_event")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_multiple_changes_creates_multiple_events(self, mock_frappe, mock_create_event, mock_find):
        """Multiple changed members each get their own event."""
        current = {100: [1, 2], 200: [3, 4], 300: [5]}
        previous = json.dumps({"100": [1], "200": [3, 4]})  # 100 changed, 200 same, 300 new

        client = self._make_client(current)
        settings = self._make_settings(last_hash=previous)

        count = self.service._poll_division_contacts(client, settings, "run-001")

        # 100 changed (gained div 2), 300 new → 2 events; 200 unchanged
        self.assertEqual(count, 2)
        self.assertEqual(mock_create_event.call_count, 2)


class TestComputeChangeTags(EnhancedTestCase):
    """Tests for compute_change_tags()."""

    def test_approved_event_returns_approved_tag(self):
        """Approved events produce an 'Approved' tag regardless of table or fields."""
        self.assertEqual(
            compute_change_tags("Approved", "admin_member", None),
            "Approved",
        )

    def test_approved_event_ignores_changed_fields(self):
        """Changed fields (which shouldn't normally exist on Approved) don't leak into the tag."""
        self.assertEqual(
            compute_change_tags("Approved", "admin_member", [{"field": "email"}]),
            "Approved",
        )
