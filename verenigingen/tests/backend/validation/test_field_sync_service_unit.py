"""
Unit Tests for Field Synchronization Service
============================================

Pure unit tests for testing individual service functions in isolation.
Uses mocking to avoid database dependencies.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import Mock, patch, MagicMock, call
from verenigingen.services.field_sync_service import (
    _find_target_document,
    _get_changed_fields,
    get_sync_config,
    is_sync_configured,
    add_sync_config,
    FIELD_SYNC_CONFIG,
)


class TestFieldSyncServiceUnit(FrappeTestCase):
    """Unit tests for field sync service helper functions."""

    def test_get_sync_config_returns_config(self):
        """Test getting sync config for configured DocType pair."""
        config = get_sync_config("Member", "User")

        self.assertIsNotNone(config)
        self.assertIn("field_mappings", config)
        self.assertIn("sync_flag", config)

    def test_get_sync_config_returns_none_for_unconfigured(self):
        """Test getting sync config for unconfigured DocType pair."""
        config = get_sync_config("NonExistent", "AlsoNotReal")

        self.assertIsNone(config)

    def test_is_sync_configured_true_for_configured_pair(self):
        """Test sync configuration check returns True for configured pair."""
        result = is_sync_configured("Member", "User")

        self.assertTrue(result)

    def test_is_sync_configured_false_for_unconfigured_pair(self):
        """Test sync configuration check returns False for unconfigured pair."""
        result = is_sync_configured("NonExistent", "AlsoNotReal")

        self.assertFalse(result)

    def test_add_sync_config_adds_new_config(self):
        """Test dynamically adding sync configuration."""
        test_config = {
            "field_mappings": {"test_field": "target_field"},
            "sync_flag": "test_sync_flag"
        }

        add_sync_config("TestDocType", "TargetDocType", test_config)

        # Verify config was added
        self.assertTrue(is_sync_configured("TestDocType", "TargetDocType"))
        config = get_sync_config("TestDocType", "TargetDocType")
        self.assertEqual(config["field_mappings"]["test_field"], "target_field")

        # Cleanup
        if "TestDocType" in FIELD_SYNC_CONFIG:
            del FIELD_SYNC_CONFIG["TestDocType"]

    def test_find_target_document_with_link_field(self):
        """Test finding target document using direct link field."""
        # Create mock source document
        source_doc = Mock()
        source_doc.name = "TEST-001"
        source_doc.linked_field = "USER-001"

        config = {
            "link_field": "linked_field"
        }

        result = _find_target_document(source_doc, "User", config)

        self.assertEqual(result, "USER-001")

    def test_find_target_document_with_reverse_lookup(self):
        """Test finding target document using reverse lookup."""
        source_doc = Mock()
        source_doc.name = "TEST-001"

        config = {
            "reverse_lookup": {"source_field": "{source_name}"}
        }

        with patch("frappe.db.get_value") as mock_get_value:
            mock_get_value.return_value = "TARGET-001"

            result = _find_target_document(source_doc, "TargetDocType", config)

            # Verify db call was made with correct filters
            mock_get_value.assert_called_once_with(
                "TargetDocType",
                {"source_field": "TEST-001"},
                "name"
            )
            self.assertEqual(result, "TARGET-001")

    def test_find_target_document_with_lookup_method(self):
        """Test finding target document using custom lookup method."""
        source_doc = Mock()
        source_doc.name = "TEST-001"

        lookup_fn = Mock(return_value="CUSTOM-LOOKUP-001")
        config = {
            "lookup_method": lookup_fn
        }

        result = _find_target_document(source_doc, "TargetDocType", config)

        # Verify lookup function was called
        lookup_fn.assert_called_once_with(source_doc)
        self.assertEqual(result, "CUSTOM-LOOKUP-001")

    def test_find_target_document_returns_none_when_not_found(self):
        """Test finding target document returns None when no relationship exists."""
        source_doc = Mock()
        source_doc.name = "TEST-001"

        config = {
            "reverse_lookup": {"source_field": "TEST-001"}
        }

        with patch("frappe.db.get_value") as mock_get_value:
            mock_get_value.return_value = None

            result = _find_target_document(source_doc, "TargetDocType", config)

            self.assertIsNone(result)

    def test_get_changed_fields_returns_only_changed_fields(self):
        """Test that only changed fields are returned."""
        doc = Mock()
        doc.field1 = "value1"
        doc.field2 = "value2"
        doc.field3 = "value3"

        # Mock has_value_changed to return True for field1 and field2 only
        def mock_has_changed(field_name):
            return field_name in ["field1", "field2"]

        doc.has_value_changed = mock_has_changed

        field_mappings = {
            "field1": "target1",
            "field2": "target2",
            "field3": "target3"
        }

        result = _get_changed_fields(doc, field_mappings)

        # _get_changed_fields returns {"mappings": {...}, "transforms": {...}}
        mappings = result.get("mappings", {})
        self.assertEqual(len(mappings), 2)
        self.assertIn("field1", mappings)
        self.assertIn("field2", mappings)
        self.assertNotIn("field3", mappings)
        self.assertEqual(mappings["field1"], "target1")
        self.assertEqual(mappings["field2"], "target2")

    def test_get_changed_fields_handles_missing_fields(self):
        """Test that missing fields on document are skipped."""
        doc = Mock(spec=["field1", "has_value_changed"])
        doc.field1 = "value1"
        doc.has_value_changed = Mock(return_value=True)

        field_mappings = {
            "field1": "target1",
            "field2": "target2",  # This field doesn't exist on doc
            "field3": "target3"   # This field doesn't exist on doc
        }

        result = _get_changed_fields(doc, field_mappings)

        # Only field1 should be in the mappings subset
        mappings = result.get("mappings", {})
        self.assertEqual(len(mappings), 1)
        self.assertIn("field1", mappings)

    def test_get_changed_fields_returns_empty_when_no_changes(self):
        """Test that empty dict is returned when no fields changed."""
        doc = Mock()
        doc.field1 = "value1"
        doc.has_value_changed = Mock(return_value=False)

        field_mappings = {
            "field1": "target1"
        }

        result = _get_changed_fields(doc, field_mappings)

        self.assertEqual(len(result), 0)
        self.assertEqual(result, {})


class TestSyncFlagsAndLoopPrevention(VereningingenTestCase):
    """Test sync flag behavior and infinite loop prevention."""

    def test_sync_flag_prevents_recursive_sync(self):
        """Test that sync flag prevents recursive synchronization."""
        from verenigingen.services.field_sync_service import _sync_to_target

        # Create real member with a linked user account
        member = self.create_test_member(
            first_name="SyncFlag",
            last_name="Test",
            email="syncflag.test@example.com"
        )
        user = self.create_test_user(member.email)
        member.user = user.name
        member.save(ignore_permissions=True)
        original_user_image = user.user_image

        # Update member image (this would normally trigger sync)
        member.image = "/files/new_test_image.jpg"

        config = {
            "link_field": "user",
            "field_mappings": {"image": "user_image"},
            "sync_flag": "syncing_member_user_fields"
        }

        # Set sync flag to prevent recursion
        frappe.flags.syncing_member_user_fields = True

        try:
            # Call _sync_to_target - should exit early due to flag
            _sync_to_target(member, "User", config)

            # Reload user and verify it was NOT updated (early exit)
            user.reload()
            self.assertEqual(user.user_image, original_user_image,
                           "User image should not change when sync flag is set")

        finally:
            frappe.flags.syncing_member_user_fields = False

    def test_sync_flag_is_cleared_on_exception(self):
        """Test that sync flag is cleared even when exception occurs."""
        from verenigingen.services.field_sync_service import _sync_to_target

        # Create member with invalid user reference to trigger exception
        member = self.create_test_member(
            first_name="ExceptionTest",
            last_name="Member",
            email="exception.test@example.com"
        )

        # Manually set member.user to non-existent user (will cause exception in get_doc)
        member.user = "NONEXISTENT-USER-123"
        member.image = "/files/test.jpg"  # Changed field to trigger sync

        config = {
            "link_field": "user",
            "field_mappings": {"image": "user_image"},
            "sync_flag": "test_sync_flag"
        }

        # Attempt sync with invalid user reference - should raise exception
        with self.assertRaises(Exception):
            frappe.flags.test_sync_flag = False
            _sync_to_target(member, "User", config)

        # Flag should be cleared even after exception
        self.assertFalse(frappe.flags.get("test_sync_flag"),
                       "Sync flag should be cleared even when exception occurs")


class TestConfigurationValidation(FrappeTestCase):
    """Test configuration validation and error handling."""

    def test_sync_with_unconfigured_doctype_exits_early(self):
        """Test that sync exits early for unconfigured DocTypes."""
        from verenigingen.services.field_sync_service import sync_fields

        doc = Mock()
        doc.doctype = "UnconfiguredDocType"

        with patch("verenigingen.services.field_sync_service._sync_to_target") as mock_sync:
            sync_fields(doc)

            # Should not attempt sync for unconfigured DocType
            mock_sync.assert_not_called()

    def test_field_mappings_configuration_structure(self):
        """Test that field mappings have correct structure."""
        config = get_sync_config("Member", "User")

        self.assertIsNotNone(config)
        self.assertIn("field_mappings", config)
        self.assertIsInstance(config["field_mappings"], dict)

        # Verify mappings are string -> string
        for source_field, target_field in config["field_mappings"].items():
            self.assertIsInstance(source_field, str)
            self.assertIsInstance(target_field, str)

    def test_bidirectional_config_consistency(self):
        """Test that bidirectional configs are properly configured."""
        # Member -> User config
        member_to_user = get_sync_config("Member", "User")
        # User -> Member config
        user_to_member = get_sync_config("User", "Member")

        self.assertIsNotNone(member_to_user)
        self.assertIsNotNone(user_to_member)

        # Both should use same sync flag
        self.assertEqual(
            member_to_user.get("sync_flag"),
            user_to_member.get("sync_flag")
        )


class TestErrorHandling(FrappeTestCase):
    """Test error handling and logging."""

    def test_sync_logs_error_on_exception(self):
        """Test that errors are logged but don't block source document save.

        sync_fields iterates over every target DocType configured for the
        source (Member has multiple: User, Volunteer, Customer, Donor, ...),
        and logs one error per failing target so a single broken relationship
        doesn't silently swallow the others. We therefore assert that each
        configured target produced an error log carrying the exception text,
        rather than asserting a single call.
        """
        from verenigingen.services.field_sync_service import FIELD_SYNC_CONFIG, sync_fields

        doc = Mock()
        doc.doctype = "Member"
        doc.name = "TEST-001"

        expected_targets = list(FIELD_SYNC_CONFIG["Member"].keys())
        self.assertGreater(len(expected_targets), 0, "Member should have sync targets configured")

        # Mock _sync_to_target to raise exception
        with patch("verenigingen.services.field_sync_service._sync_to_target") as mock_sync:
            mock_sync.side_effect = Exception("Test sync error")

            # sync_fields logs via the module logger, not frappe.log_error
            with patch("verenigingen.services.field_sync_service.logger") as mock_logger:
                # Call sync_fields - should catch exception and log
                sync_fields(doc)

                # One error per configured target, each carrying the exception text.
                self.assertEqual(mock_logger.error.call_count, len(expected_targets))
                logged_messages = [c.args[0] for c in mock_logger.error.call_args_list]
                for target in expected_targets:
                    self.assertTrue(
                        any(
                            f"Member -> {target}" in msg and "Test sync error" in msg
                            for msg in logged_messages
                        ),
                        f"Expected an error log for Member -> {target} with the exception text; "
                        f"got: {logged_messages}",
                    )

    def test_find_target_handles_database_errors_gracefully(self):
        """Test that database errors in lookup don't crash sync."""
        source_doc = Mock()
        source_doc.name = "TEST-001"

        config = {
            "reverse_lookup": {"field": "value"}
        }

        with patch("frappe.db.get_value") as mock_get_value:
            # Simulate database error
            mock_get_value.side_effect = Exception("Database connection error")

            # Should raise exception (caller will handle logging)
            with self.assertRaises(Exception):
                _find_target_document(source_doc, "TargetDocType", config)


class TestPerformanceOptimizations(VereningingenTestCase):
    """Test performance-related behaviors."""

    def test_sync_skips_when_no_fields_changed(self):
        """Test that sync is skipped when no configured fields changed."""
        from verenigingen.services.field_sync_service import _sync_to_target

        # Create member with a linked user account
        member = self.create_test_member(
            first_name="NoChange",
            last_name="Test",
            email="nochange.test@example.com"
        )
        user = self.create_test_user(member.email)
        member.user = user.name
        member.save(ignore_permissions=True)
        # Read modified directly from DB to compare against a post-reload value
        original_modified = frappe.db.get_value("User", user.name, "modified")

        # Don't change the synced field (image)
        # Just save member without changes to trigger potential sync
        config = {
            "link_field": "user",
            "field_mappings": {"image": "user_image"},
            "sync_flag": "test_flag"
        }

        # Call sync - should exit early since no fields changed
        _sync_to_target(member, "User", config)

        # Verify user was not updated (modified time unchanged)
        current_modified = frappe.db.get_value("User", user.name, "modified")
        self.assertEqual(current_modified, original_modified,
                       "User should not be updated when no fields changed")

    def test_sync_exits_early_when_no_target_found(self):
        """Test that sync exits early when target document doesn't exist."""
        from verenigingen.services.field_sync_service import _sync_to_target

        # Create member with user, then unlink it
        member = self.create_test_member(
            first_name="NoTarget",
            last_name="Test",
            email="notarget.test@example.com"
        )

        # Manually unlink user to simulate no target
        member.user = None
        member.image = "/files/test.jpg"  # Change field to trigger sync

        config = {
            "link_field": "user",
            "field_mappings": {"image": "user_image"},
            "sync_flag": "test_flag"
        }

        # Call sync - should exit early without errors since no target
        try:
            _sync_to_target(member, "User", config)
            # Success - early exit worked gracefully
        except Exception as e:
            self.fail(f"Sync should exit gracefully when no target found, but raised: {e}")
