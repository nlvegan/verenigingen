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


class TestRunSyncCallsCorrelator(EnhancedTestCase):
    """Verify run_sync invokes the application-approval correlator after polling."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()

    @patch("verenigingen.mijnrood_sync.services.polling_service.ApplicationApprovalCorrelator")
    @patch.object(MijnRoodPollingService, "_poll_division_contacts", return_value=0)
    @patch.object(MijnRoodPollingService, "_poll_table")
    @patch("verenigingen.mijnrood_sync.services.polling_service.MijnRoodDatabaseClient")
    @patch("verenigingen.mijnrood_sync.services.polling_service.frappe")
    def test_run_sync_invokes_correlator_with_sync_run_id(
        self, mock_frappe, mock_client_cls, mock_poll_table, mock_poll_dc, mock_correlator_cls
    ):
        """run_sync calls correlator.correlate(sync_run_id) once all tables are polled,
        and the returned count is reflected in totals."""
        # Arrange settings
        settings = MagicMock()
        settings.tables_to_sync = '["admin_member"]'
        mock_frappe.get_single.return_value = settings
        mock_frappe.db.count.return_value = 0

        # run_sync now guards with acquire_sync_lock(), which reads
        # frappe.cache().get_value(); the mocked frappe would otherwise return a
        # truthy MagicMock and make run_sync short-circuit as "lock_held". Force
        # the lock to be free so the real sync body (and correlator) runs.
        mock_frappe.cache.return_value.get_value.return_value = None

        # Log + client stubs
        log_doc = MagicMock()
        mock_frappe.new_doc.return_value = log_doc
        mock_client_cls.return_value.__enter__.return_value = mock_client_cls.return_value

        mock_poll_table.return_value = {
            "new": 1, "changed": 0, "deleted": 1, "unchanged": 0, "rows_scanned": 1,
        }
        mock_correlator = MagicMock()
        mock_correlator.correlate.return_value = 1
        mock_correlator_cls.return_value = mock_correlator

        # Act
        totals = self.service.run_sync()

        # Assert
        mock_correlator.correlate.assert_called_once()
        # sync_run_id is a positional str argument
        call_args = mock_correlator.correlate.call_args
        self.assertEqual(len(call_args.args[0]), 12)  # uuid4().hex[:12]
        self.assertEqual(totals.get("approved"), 1)


class TestComputeChangeTagsFull(EnhancedTestCase):
    """Exhaustive coverage of compute_change_tags() — pure function."""

    def test_new_known_tables(self):
        self.assertEqual(compute_change_tags("New", "admin_member", None), "New Member")
        self.assertEqual(
            compute_change_tags("New", "admin_membership_application", None), "New Application"
        )
        self.assertEqual(compute_change_tags("New", "admin_division", None), "New Division")

    def test_new_unknown_table_falls_back_to_new(self):
        self.assertEqual(compute_change_tags("New", "admin_support_member", None), "New")

    def test_deleted(self):
        self.assertEqual(compute_change_tags("Deleted", "admin_member", None), "Deleted")

    def test_changed_no_fields_returns_empty(self):
        self.assertEqual(compute_change_tags("Changed", "admin_member", None), "")
        self.assertEqual(compute_change_tags("Changed", "admin_member", []), "")

    def test_changed_unmapped_fields_returns_other(self):
        tags = compute_change_tags("Changed", "admin_member", [{"field": "registration_time"}])
        self.assertEqual(tags, "Other")

    def test_changed_single_mapped_field(self):
        tags = compute_change_tags("Changed", "admin_member", [{"field": "iban"}])
        self.assertEqual(tags, "Financial")

    def test_changed_respects_tag_priority_order(self):
        # email=Contact, current_membership_status_id=Status, iban=Financial.
        # TAG_ORDER puts Status before Financial before Contact.
        tags = compute_change_tags(
            "Changed",
            "admin_member",
            [{"field": "email"}, {"field": "current_membership_status_id"}, {"field": "iban"}],
        )
        self.assertEqual(tags, "Status,Financial,Contact")

    def test_changed_dedups_same_tag(self):
        # first_name, last_name, date_of_birth all map to Personal → one tag
        tags = compute_change_tags(
            "Changed",
            "admin_member",
            [{"field": "first_name"}, {"field": "last_name"}, {"field": "date_of_birth"}],
        )
        self.assertEqual(tags, "Personal")

    def test_changed_accepts_plain_string_fields(self):
        # changed_fields entries may be bare strings, not dicts
        tags = compute_change_tags("Changed", "admin_member", ["division_id"])
        self.assertEqual(tags, "Chapter")


class TestSyncLock(EnhancedTestCase):
    """acquire_sync_lock / release_sync_lock against the REAL Frappe cache."""

    def setUp(self):
        super().setUp()
        from verenigingen.mijnrood_sync.services.polling_service import release_sync_lock

        release_sync_lock()  # ensure clean slate

    def tearDown(self):
        from verenigingen.mijnrood_sync.services.polling_service import release_sync_lock

        release_sync_lock()
        super().tearDown()

    def test_acquire_then_second_acquire_blocked(self):
        from verenigingen.mijnrood_sync.services.polling_service import acquire_sync_lock

        self.assertTrue(acquire_sync_lock("run-A"))
        # Second run cannot claim while first holds it
        self.assertFalse(acquire_sync_lock("run-B"))

    def test_release_allows_reacquire(self):
        from verenigingen.mijnrood_sync.services.polling_service import (
            acquire_sync_lock,
            release_sync_lock,
        )

        self.assertTrue(acquire_sync_lock("run-A"))
        release_sync_lock()
        self.assertTrue(acquire_sync_lock("run-B"))

    def test_release_when_not_held_is_safe(self):
        from verenigingen.mijnrood_sync.services.polling_service import release_sync_lock

        release_sync_lock()  # no exception
        release_sync_lock()

    def test_lock_stores_run_id(self):
        from verenigingen.mijnrood_sync.services.polling_service import (
            _SYNC_LOCK_KEY,
            acquire_sync_lock,
        )

        acquire_sync_lock("run-XYZ")
        self.assertEqual(frappe.cache().get_value(_SYNC_LOCK_KEY), "run-XYZ")


class TestComputeChangedFields(EnhancedTestCase):
    """_compute_changed_fields — diff logic, real DB for display resolution."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()
        self._created_states = []

    def tearDown(self):
        for k in self._created_states:
            if frappe.db.exists("MijnRood Sync State", k):
                frappe.delete_doc("MijnRood Sync State", k, force=True, ignore_permissions=True)
        super().tearDown()

    def test_detects_changed_value(self):
        changed = self.service._compute_changed_fields(
            {"first_name": "Alice"}, {"first_name": "Alicia"}
        )
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["field"], "first_name")
        self.assertEqual(changed[0]["old"], "Alice")
        self.assertEqual(changed[0]["new"], "Alicia")
        self.assertEqual(changed[0]["label"], "First Name")

    def test_none_and_empty_string_are_equal(self):
        changed = self.service._compute_changed_fields({"phone": None}, {"phone": ""})
        self.assertEqual(changed, [])

    def test_int_vs_str_compared_as_strings(self):
        # "5" vs 5 should NOT count as a change (str() normalization)
        changed = self.service._compute_changed_fields({"id": 5}, {"id": "5"})
        self.assertEqual(changed, [])

    def test_new_key_appears_as_change(self):
        changed = self.service._compute_changed_fields({}, {"city": "Amsterdam"})
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["new"], "Amsterdam")

    def test_removed_key_appears_as_change(self):
        changed = self.service._compute_changed_fields({"city": "Amsterdam"}, {})
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["old"], "Amsterdam")

    def test_status_id_resolves_display_label(self):
        # Uses default status labels (no settings child table needed)
        changed = self.service._compute_changed_fields(
            {"current_membership_status_id": 1}, {"current_membership_status_id": 3}
        )
        self.assertEqual(len(changed), 1)
        entry = changed[0]
        self.assertIn("old_display", entry)
        self.assertIn("new_display", entry)
        # Default label map: 1 -> "Active (lid)", 3 -> "Resigned (opgezegd)"
        self.assertEqual(entry["old_display"], "Active (lid)")
        self.assertEqual(entry["new_display"], "Resigned (opgezegd)")

    def test_division_id_resolves_via_sync_state(self):
        # Seed an admin_division sync state so _resolve_division_name finds it
        self._make_division_state(7, "Amsterdam Chapter")
        changed = self.service._compute_changed_fields(
            {"division_id": 7}, {"division_id": None}
        )
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["old_display"], "Amsterdam Chapter")
        # new=None is normalized to "" before resolution; safe_int("")->None,
        # so display falls back to str(new_val) which is "".
        self.assertEqual(changed[0]["new_display"], "")

    def _make_division_state(self, div_id, name):
        key = f"admin_division-{div_id}"
        if frappe.db.exists("MijnRood Sync State", key):
            frappe.delete_doc("MijnRood Sync State", key, force=True, ignore_permissions=True)
        state = frappe.new_doc("MijnRood Sync State")
        state.state_key = key
        state.mijnrood_table = "admin_division"
        state.mijnrood_row_id = div_id
        state.row_checksum = "x"
        state.raw_data = json.dumps({"id": div_id, "name": name})
        state.insert(ignore_permissions=True)
        self._created_states = getattr(self, "_created_states", [])
        self._created_states.append(key)


class TestResolveDivisionName(EnhancedTestCase):
    """_resolve_division_name — DB lookup of admin_division sync state."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()
        self._keys = []

    def tearDown(self):
        for k in self._keys:
            if frappe.db.exists("MijnRood Sync State", k):
                frappe.delete_doc("MijnRood Sync State", k, force=True, ignore_permissions=True)
        super().tearDown()

    def _make_division(self, div_id, name):
        key = f"admin_division-{div_id}"
        if frappe.db.exists("MijnRood Sync State", key):
            frappe.delete_doc("MijnRood Sync State", key, force=True, ignore_permissions=True)
        state = frappe.new_doc("MijnRood Sync State")
        state.state_key = key
        state.mijnrood_table = "admin_division"
        state.mijnrood_row_id = div_id
        state.row_checksum = "x"
        state.raw_data = json.dumps({"id": div_id, "name": name})
        state.insert(ignore_permissions=True)
        self._keys.append(key)

    def test_resolves_name(self):
        self._make_division(42, "Utrecht")
        self.assertEqual(self.service._resolve_division_name(42), "Utrecht")
        # String form of the id also resolves (safe_int)
        self.assertEqual(self.service._resolve_division_name("42"), "Utrecht")

    def test_unknown_division_returns_none(self):
        self.assertIsNone(self.service._resolve_division_name(99999))

    def test_non_int_returns_none(self):
        self.assertIsNone(self.service._resolve_division_name(None))
        self.assertIsNone(self.service._resolve_division_name(""))
        self.assertIsNone(self.service._resolve_division_name("not-a-number"))


class TestChangeSummary(EnhancedTestCase):
    """_compute_change_summary / _summary_for_new / _summary_for_changed."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()

    def test_new_member_summary_includes_name_and_details(self):
        summary = self.service._compute_change_summary(
            "New",
            "admin_member",
            None,
            {"first_name": "Jan", "last_name": "Jansen", "email": "jan@example.org", "city": "Amsterdam"},
            None,
        )
        self.assertIn("Jan Jansen", summary)
        self.assertIn("jan@example.org", summary)
        self.assertIn("Amsterdam", summary)

    def test_new_no_data(self):
        summary = self.service._compute_change_summary("New", "admin_member", None, None, None)
        self.assertEqual(summary, "New admin_member record")

    def test_new_no_name_falls_back_to_row_id(self):
        summary = self.service._summary_for_new("admin_member", {"id": 55})
        self.assertIn("row 55", summary)

    def test_deleted_summary_uses_name(self):
        summary = self.service._compute_change_summary(
            "Deleted",
            "admin_member",
            {"first_name": "Piet", "last_name": "Pietersen"},
            None,
            None,
        )
        self.assertIn("Piet Pietersen", summary)
        self.assertIn("Deleted admin_member", summary)

    def test_deleted_unknown_name(self):
        summary = self.service._compute_change_summary("Deleted", "admin_member", {}, None, None)
        self.assertIn("unknown", summary)

    def test_changed_summary_lists_fields(self):
        changed_fields = [
            {"field": "first_name", "old": "A", "new": "B", "label": "First Name"},
        ]
        summary = self.service._compute_change_summary(
            "Changed", "admin_member", {"first_name": "A"}, {"first_name": "B"}, changed_fields
        )
        self.assertIn("First Name: A → B", summary)

    def test_changed_summary_empty_to_value(self):
        changed_fields = [{"field": "email", "old": "", "new": "x@y.z", "label": "Email"}]
        summary = MijnRoodPollingService._summary_for_changed(changed_fields)
        self.assertIn("(empty) → x@y.z", summary)

    def test_changed_summary_value_to_empty(self):
        changed_fields = [{"field": "email", "old": "x@y.z", "new": "", "label": "Email"}]
        summary = MijnRoodPollingService._summary_for_changed(changed_fields)
        self.assertIn("x@y.z → (empty)", summary)

    def test_changed_summary_truncates_at_five_fields(self):
        changed_fields = [
            {"field": f"f{i}", "old": f"o{i}", "new": f"n{i}", "label": f"L{i}"} for i in range(8)
        ]
        summary = MijnRoodPollingService._summary_for_changed(changed_fields)
        self.assertIn("(+3 more)", summary)

    def test_changed_summary_prefers_display_values(self):
        changed_fields = [
            {
                "field": "current_membership_status_id",
                "old": 1,
                "new": 3,
                "label": "Status",
                "old_display": "Active",
                "new_display": "Resigned",
            }
        ]
        summary = MijnRoodPollingService._summary_for_changed(changed_fields)
        self.assertIn("Active → Resigned", summary)

    def test_new_division_summary(self):
        summary = self.service._summary_for_new(
            "admin_division", {"name": "Den Haag", "city": "Den Haag", "email_id": "info@dh.org"}
        )
        self.assertIn("Den Haag", summary)
        self.assertIn("info@dh.org", summary)

    def test_fallthrough_summary(self):
        # Changed with no changed_fields hits the final return branch
        summary = self.service._compute_change_summary("Changed", "admin_member", {}, {}, None)
        self.assertEqual(summary, "Changed event for admin_member")


class TestFindLinkedMember(EnhancedTestCase):
    """_find_linked_member — member_id then email fallback, real Member DB."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()
        self._members = []

    def tearDown(self):
        for name in self._members:
            if frappe.db.exists("Member", name):
                frappe.delete_doc("Member", name, force=True, ignore_permissions=True)
        super().tearDown()

    def _make_member(self, member_id=None, email=None):
        doc = frappe.new_doc("Member")
        doc.first_name = "Link"
        doc.last_name = "Target"
        if member_id is not None:
            doc.member_id = str(member_id)
        if email:
            doc.email = email
        doc.insert(ignore_permissions=True)
        self._members.append(doc.name)
        return doc

    def test_non_linkable_table_returns_none(self):
        self.assertIsNone(self.service._find_linked_member("admin_division", 1))

    def test_matches_by_member_id(self):
        m = self._make_member(member_id="900111")
        found = self.service._find_linked_member("admin_member", "900111")
        self.assertEqual(found, m.name)

    def test_falls_back_to_email(self):
        m = self._make_member(email="fallback-link@example.org")
        # member_id mismatch but email matches via row_data
        found = self.service._find_linked_member(
            "admin_member", 555000, row_data={"email": "fallback-link@example.org"}
        )
        self.assertEqual(found, m.name)

    def test_no_match_returns_none(self):
        found = self.service._find_linked_member(
            "admin_membership_application", 888777, row_data={"email": "nobody@nowhere.invalid"}
        )
        self.assertIsNone(found)


class TestUpsertSyncStateAndCreateEvent(EnhancedTestCase):
    """_upsert_sync_state + _create_sync_event against real DocTypes."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()
        self._state_keys = []
        self._event_names = []

    def tearDown(self):
        for k in self._state_keys:
            if frappe.db.exists("MijnRood Sync State", k):
                frappe.delete_doc("MijnRood Sync State", k, force=True, ignore_permissions=True)
        for n in self._event_names:
            if frappe.db.exists("MijnRood Sync Event", n):
                frappe.delete_doc("MijnRood Sync Event", n, force=True, ignore_permissions=True)
        super().tearDown()

    def test_upsert_inserts_then_updates(self):
        from frappe.utils import now_datetime

        key = "admin_member-700001"
        self._state_keys.append(key)
        if frappe.db.exists("MijnRood Sync State", key):
            frappe.delete_doc("MijnRood Sync State", key, force=True, ignore_permissions=True)

        self.service._upsert_sync_state(
            table="admin_member",
            row_id=700001,
            checksum="sum-1",
            raw_data={"id": 700001, "first_name": "A"},
            linked_member=None,
            last_seen=now_datetime(),
        )
        self.assertTrue(frappe.db.exists("MijnRood Sync State", key))
        self.assertEqual(frappe.db.get_value("MijnRood Sync State", key, "row_checksum"), "sum-1")

        # Second call updates the existing record
        self.service._upsert_sync_state(
            table="admin_member",
            row_id=700001,
            checksum="sum-2",
            raw_data={"id": 700001, "first_name": "B"},
            linked_member=None,
            last_seen=now_datetime(),
        )
        self.assertEqual(frappe.db.get_value("MijnRood Sync State", key, "row_checksum"), "sum-2")
        raw = frappe.db.get_value("MijnRood Sync State", key, "raw_data")
        self.assertEqual(json.loads(raw)["first_name"], "B")

    def test_create_sync_event_persists_with_tags(self):
        from frappe.utils import now_datetime

        before = set(frappe.get_all("MijnRood Sync Event", pluck="name"))
        self.service._create_sync_event(
            event_type="Changed",
            table="admin_member",
            row_id=700002,
            old_data={"iban": "OLD"},
            new_data={"iban": "NEW"},
            changed_fields=[{"field": "iban", "old": "OLD", "new": "NEW", "label": "IBAN"}],
            linked_member=None,
            sync_run_id="run-evt",
            detected_at=now_datetime(),
        )
        after = set(frappe.get_all("MijnRood Sync Event", pluck="name"))
        new_names = after - before
        self.assertEqual(len(new_names), 1)
        name = new_names.pop()
        self._event_names.append(name)
        doc = frappe.get_doc("MijnRood Sync Event", name)
        self.assertEqual(doc.event_type, "Changed")
        self.assertEqual(doc.change_tags, "Financial")
        self.assertEqual(doc.status, "Pending")
        self.assertEqual(json.loads(doc.new_data), {"iban": "NEW"})


class TestPollTable(EnhancedTestCase):
    """_poll_table end-to-end with a STUBBED client (external DB boundary only).

    The client's fetch_row_checksums / fetch_rows_by_ids are stubbed with canned
    rows. Everything else — change classification, Sync Event creation, Sync
    State upsert/delete — runs for real and is asserted against the live DB.
    """

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()
        self._state_keys = []
        self._event_run_id = None

    def tearDown(self):
        for k in self._state_keys:
            if frappe.db.exists("MijnRood Sync State", k):
                frappe.delete_doc("MijnRood Sync State", k, force=True, ignore_permissions=True)
        if self._event_run_id:
            for n in frappe.get_all(
                "MijnRood Sync Event", filters={"sync_run_id": self._event_run_id}, pluck="name"
            ):
                frappe.delete_doc("MijnRood Sync Event", n, force=True, ignore_permissions=True)
        super().tearDown()

    def _make_client(self, checksums, rows_by_id):
        client = MagicMock()
        client.fetch_row_checksums.return_value = checksums
        client.fetch_rows_by_ids.return_value = list(rows_by_id.values())
        return client

    def _make_seed_state(self, table, row_id, checksum, raw_data):
        key = f"{table}-{row_id}"
        if frappe.db.exists("MijnRood Sync State", key):
            frappe.delete_doc("MijnRood Sync State", key, force=True, ignore_permissions=True)
        state = frappe.new_doc("MijnRood Sync State")
        state.state_key = key
        state.mijnrood_table = table
        state.mijnrood_row_id = row_id
        state.row_checksum = checksum
        state.raw_data = json.dumps(raw_data)
        state.insert(ignore_permissions=True)
        self._state_keys.append(key)
        return key

    def test_new_row_creates_event_and_state(self):
        run_id = "polltest-new"
        self._event_run_id = run_id
        row_id = 710001
        self._state_keys.append(f"admin_member-{row_id}")
        client = self._make_client(
            checksums={row_id: "cs-new"},
            rows_by_id={row_id: {"id": row_id, "first_name": "New", "last_name": "Person"}},
        )

        stats = self.service._poll_table(client, "admin_member", run_id)

        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["changed"], 0)
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual(stats["rows_scanned"], 1)
        # Sync State created
        self.assertTrue(frappe.db.exists("MijnRood Sync State", f"admin_member-{row_id}"))
        # Sync Event created
        events = frappe.get_all(
            "MijnRood Sync Event",
            filters={"sync_run_id": run_id, "event_type": "New"},
            pluck="name",
        )
        self.assertEqual(len(events), 1)

    def test_changed_row_creates_changed_event(self):
        run_id = "polltest-chg"
        self._event_run_id = run_id
        row_id = 710002
        self._make_seed_state(
            "admin_member", row_id, "cs-old", {"id": row_id, "first_name": "Old", "email": "x@y.z"}
        )
        client = self._make_client(
            checksums={row_id: "cs-new"},  # different checksum → changed
            rows_by_id={row_id: {"id": row_id, "first_name": "New", "email": "x@y.z"}},
        )

        stats = self.service._poll_table(client, "admin_member", run_id)

        self.assertEqual(stats["changed"], 1)
        self.assertEqual(stats["new"], 0)
        # State checksum updated
        self.assertEqual(
            frappe.db.get_value("MijnRood Sync State", f"admin_member-{row_id}", "row_checksum"),
            "cs-new",
        )
        events = frappe.get_all(
            "MijnRood Sync Event",
            filters={"sync_run_id": run_id, "event_type": "Changed"},
            pluck="name",
        )
        self.assertEqual(len(events), 1)

    def test_deleted_row_creates_event_and_removes_state(self):
        run_id = "polltest-del"
        self._event_run_id = run_id
        row_id = 710003
        key = self._make_seed_state(
            "admin_member", row_id, "cs-old", {"id": row_id, "first_name": "Gone"}
        )
        # MijnRood no longer returns this row
        client = self._make_client(checksums={}, rows_by_id={})

        stats = self.service._poll_table(client, "admin_member", run_id)

        self.assertEqual(stats["deleted"], 1)
        # State removed
        self.assertFalse(frappe.db.exists("MijnRood Sync State", key))
        events = frappe.get_all(
            "MijnRood Sync Event",
            filters={"sync_run_id": run_id, "event_type": "Deleted"},
            pluck="name",
        )
        self.assertEqual(len(events), 1)

    def test_unchanged_row_no_event(self):
        run_id = "polltest-unchg"
        self._event_run_id = run_id
        row_id = 710004
        self._make_seed_state(
            "admin_member", row_id, "cs-same", {"id": row_id, "first_name": "Same"}
        )
        client = self._make_client(checksums={row_id: "cs-same"}, rows_by_id={})

        stats = self.service._poll_table(client, "admin_member", run_id)

        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(stats["new"], 0)
        self.assertEqual(stats["changed"], 0)
        self.assertEqual(stats["deleted"], 0)
        # No events created
        events = frappe.get_all("MijnRood Sync Event", filters={"sync_run_id": run_id}, pluck="name")
        self.assertEqual(len(events), 0)
        # fetch_rows_by_ids not called (no new/changed rows)
        client.fetch_rows_by_ids.assert_not_called()


class TestRowSavepoint(EnhancedTestCase):
    """_row_savepoint — isolates per-row failures, increments error stats."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodPollingService()

    def test_successful_block_no_error(self):
        stats = {"errors": 0}
        with self.service._row_savepoint(1, "admin_member", stats):
            pass
        self.assertEqual(stats["errors"], 0)

    def test_exception_caught_and_counted(self):
        stats = {"errors": 0}
        # Exception inside the block must NOT propagate
        with self.service._row_savepoint(2, "admin_member", stats):
            raise ValueError("bad row")
        self.assertEqual(stats["errors"], 1)
