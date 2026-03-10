"""
Integration Tests for Field Synchronization Service
===================================================

Full integration tests for bidirectional field sync between Member and User records.
Tests use actual database operations and real document saves to verify end-to-end behavior.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFieldSyncServiceIntegration(EnhancedTestCase):
    """Integration tests for field synchronization service with real database operations."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        # Use unique email for each test to avoid conflicts
        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        self.test_email = f"field.sync.{unique_suffix}@test.local"

        # Create a test member with a linked user
        self.member = self.create_test_member(
            first_name="Field",
            last_name="Sync",
            email=self.test_email,
            birth_date="1990-01-01"
        )

        # Ensure member has a user linked
        if not self.member.user:
            # Check if user already exists
            existing_user = frappe.db.exists("User", self.test_email)
            if existing_user:
                self.member.user = existing_user
            else:
                self.member.user = frappe.get_doc({
                    "doctype": "User",
                    "email": self.test_email,
                    "first_name": self.member.first_name,
                    "last_name": self.member.last_name,
                    "send_welcome_email": 0
                }).insert(ignore_permissions=True).name
            self.member.save(ignore_permissions=True)
            frappe.db.commit()

    def test_member_image_syncs_to_user(self):
        """Test that updating Member image syncs to User."""
        test_image = "/files/test_image.jpg"

        # Update member image with proper permissions
        self.member.image = test_image
        self.member.save()
        frappe.db.commit()

        # Verify user_image is updated
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.user_image, test_image,
                        "User image should sync from Member image")

    def test_user_image_syncs_to_member(self):
        """Test that updating User image syncs to Member."""
        test_image = "/files/user_test_image.jpg"

        # Create admin user for User update permissions
        admin = self.create_test_user(
            "admin.field.sync@test.local",
            roles=["System Manager"]
        )

        # Update user image with admin permissions (users can't edit other users)
        with self.as_user(admin.email):
            user = frappe.get_doc("User", self.member.user)
            user.user_image = test_image
            user.save()

        # Commit after context manager to ensure sync completes
        frappe.db.commit()

        # Reload member and verify image is updated
        self.member.reload()
        self.assertEqual(self.member.image, test_image,
                        "Member image should sync from User image")

    def test_member_email_does_not_sync_to_user(self):
        """Test that Member email does NOT sync to User (by design).

        User.email is immutable as it's the username/primary key.
        Email changes should be managed through User administration.
        """
        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        new_email = f"new.email.{unique_suffix}@test.local"

        # Store original user email
        original_user_email = frappe.get_doc("User", self.member.user).email

        # Update member email
        self.member.email = new_email
        self.member.save()
        frappe.db.commit()

        # Verify user email is NOT updated (by design)
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.email, original_user_email,
                        "User email should NOT sync from Member email (immutable field)")

    def test_member_name_syncs_to_user(self):
        """Test that updating Member name syncs to User."""
        new_first_name = "Updated"
        new_last_name = "Name"

        # Update member name
        self.member.first_name = new_first_name
        self.member.last_name = new_last_name
        self.member.save()
        frappe.db.commit()

        # Verify user name is updated
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.first_name, new_first_name,
                        "User first_name should sync from Member first_name")
        self.assertEqual(user.last_name, new_last_name,
                        "User last_name should sync from Member last_name")

    def test_user_name_syncs_to_member(self):
        """Test that updating User name syncs to Member."""
        new_first_name = "UserUpdated"
        new_last_name = "UserName"

        # Create admin user for User update permissions
        admin = self.create_test_user(
            "admin.name.sync@test.local",
            roles=["System Manager"]
        )

        # Update user name with admin permissions
        with self.as_user(admin.email):
            user = frappe.get_doc("User", self.member.user)
            user.first_name = new_first_name
            user.last_name = new_last_name
            user.save()

        # Commit after context manager
        frappe.db.commit()

        # Reload member and verify name is updated
        self.member.reload()
        self.assertEqual(self.member.first_name, new_first_name,
                        "Member first_name should sync from User first_name")
        self.assertEqual(self.member.last_name, new_last_name,
                        "Member last_name should sync from User last_name")

    def test_sync_prevents_infinite_loop(self):
        """Test that sync flag prevents infinite loops."""
        test_image = "/files/loop_test.jpg"

        # Set the sync flag manually
        frappe.flags.syncing_member_user_fields = True

        try:
            # Update member image - should not sync due to flag
            self.member.image = test_image
            self.member.save()
            frappe.db.commit()

            # User image should NOT be updated
            user = frappe.get_doc("User", self.member.user)
            self.assertNotEqual(user.user_image, test_image,
                              "Sync should be prevented when flag is set")
        finally:
            # Clean up flag
            frappe.flags.syncing_member_user_fields = False

    def test_sync_handles_missing_user(self):
        """Test that sync gracefully handles members without users."""
        # Create member without user
        member = self.create_test_member(
            first_name="No",
            last_name="User",
            email="no.user.sync@test.local",
            birth_date="1995-05-05"
        )
        member.user = None
        member.save()

        # Update fields - should not error
        member.image = "/files/no_user.jpg"
        member.email = "updated.no.user@test.local"
        member.save()

        # Should complete without error
        self.assertTrue(True, "Member save should succeed even without linked user")

    def test_sync_handles_missing_member(self):
        """Test that sync gracefully handles users without members."""
        # Create user without member - use unique email
        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        test_email = f"no.member.sync.{unique_suffix}@test.local"

        # Create user with proper permission context
        admin_user = self.create_test_user(
            "admin.no.member.sync@test.local",
            roles=["System Manager"]
        )

        with self.as_user(admin_user.email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": test_email,
                "first_name": "No",
                "last_name": "Member",
                "send_welcome_email": 0
            }).insert()

            # Update user fields - should not error
            user.user_image = "/files/no_member.jpg"
            user.first_name = "Updated"
            user.save()

        # Should complete without error
        self.assertTrue(True, "User save should succeed even without linked member")

    def test_sync_only_on_change(self):
        """Test that sync only happens when fields actually change."""
        test_image = "/files/initial.jpg"

        # Set initial image
        self.member.image = test_image
        self.member.save()
        frappe.db.commit()

        # Get initial user image
        user = frappe.get_doc("User", self.member.user)
        initial_user_image = user.user_image

        # Save member again without changing image
        self.member.first_name = "Changed"
        self.member.save()
        frappe.db.commit()

        # User image should remain unchanged
        user.reload()
        self.assertEqual(user.user_image, initial_user_image,
                        "User image should not update when Member image hasn't changed")

    def test_multiple_fields_sync_together(self):
        """Test that multiple field changes sync in one operation."""
        new_first_name = "Multi"
        new_last_name = "Field"
        new_image = "/files/multi_field.jpg"

        # Update multiple fields at once (excluding email - not synced by design)
        self.member.first_name = new_first_name
        self.member.last_name = new_last_name
        self.member.image = new_image
        self.member.save()
        frappe.db.commit()

        # Verify all fields synced to user
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.first_name, new_first_name, "User first_name should sync")
        self.assertEqual(user.last_name, new_last_name, "User last_name should sync")
        self.assertEqual(user.user_image, new_image, "User image should sync")


class TestFieldSyncPerformance(EnhancedTestCase):
    """Performance and query optimization tests."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        self.test_email = f"perf.test.{unique_suffix}@test.local"

        self.member = self.create_test_member(
            first_name="Performance",
            last_name="Test",
            email=self.test_email,
            birth_date="1990-01-01"
        )

        # Ensure member has a user linked
        if not self.member.user:
            self.member.user = frappe.get_doc({
                "doctype": "User",
                "email": self.test_email,
                "first_name": self.member.first_name,
                "last_name": self.member.last_name,
                "send_welcome_email": 0
            }).insert(ignore_permissions=True).name
            self.member.save(ignore_permissions=True)
            frappe.db.commit()

    def test_sync_does_not_cause_nplus1_queries(self):
        """Test that sync doesn't cause N+1 query problems."""
        # Update multiple fields
        self.member.first_name = "NewFirst"
        self.member.last_name = "NewLast"
        self.member.image = "/files/new_image.jpg"

        # Monitor query count - Member save has many operations, but should be bounded
        # Note: Member save triggers many related operations (validation, hooks, etc.)
        with self.assertQueryCount(200):  # Reasonable upper bound for Member+User sync
            self.member.save()
            frappe.db.commit()

    def test_sync_with_no_changes_is_fast(self):
        """Test that sync exits early when no fields changed."""
        # Save without changes - should be very fast
        import time
        start = time.time()

        self.member.save()
        frappe.db.commit()

        duration = time.time() - start

        # Should complete quickly (under 2 seconds)
        self.assertLess(duration, 2.0,
                       "Sync with no changes should exit early and be fast")

    def test_sync_only_updates_changed_fields(self):
        """Test that only changed fields trigger database updates."""
        # Update only image
        self.member.image = "/files/only_image.jpg"
        self.member.save()
        frappe.db.commit()

        # Verify image synced but other fields unchanged
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.user_image, "/files/only_image.jpg")
        self.assertEqual(user.first_name, self.member.first_name)


class TestFieldSyncEdgeCases(EnhancedTestCase):
    """Edge case and error scenario tests."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        self.test_email = f"edge.case.{unique_suffix}@test.local"

        self.member = self.create_test_member(
            first_name="Edge",
            last_name="Case",
            email=self.test_email,
            birth_date="1990-01-01"
        )

        if not self.member.user:
            self.member.user = frappe.get_doc({
                "doctype": "User",
                "email": self.test_email,
                "first_name": self.member.first_name,
                "last_name": self.member.last_name,
                "send_welcome_email": 0
            }).insert(ignore_permissions=True).name
            self.member.save(ignore_permissions=True)
            frappe.db.commit()

    def test_sync_handles_null_field_values(self):
        """Test that sync handles None/null field values for optional fields."""
        # Set optional field (image) to None
        # Note: Cannot set mandatory fields like first_name to None
        self.member.image = None
        self.member.save()
        frappe.db.commit()

        # Verify sync completed without error
        user = frappe.get_doc("User", self.member.user)
        self.assertIsNone(user.user_image)

    def test_sync_handles_empty_string_values(self):
        """Test that sync handles empty string values for optional fields."""
        # Set optional field (image) to empty string
        # Note: Cannot set mandatory fields like last_name to empty
        self.member.image = ""
        self.member.save()
        frappe.db.commit()

        # Verify sync completed without error
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.user_image, "")

    def test_sync_with_special_characters_in_name(self):
        """Test sync with special characters in names."""
        # Dutch names with special characters
        self.member.first_name = "François"
        self.member.last_name = "van 't Hof"
        self.member.save()
        frappe.db.commit()

        # Verify sync handled special characters
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.first_name, "François")
        self.assertEqual(user.last_name, "van 't Hof")

    def test_sync_with_long_field_values(self):
        """Test sync with reasonably long field values."""
        # Long name within validation limits (50 char limit for Member name)
        long_name = "A" * 40  # Within 50 char limit
        self.member.first_name = long_name
        self.member.save()
        frappe.db.commit()

        # Verify sync handled long value
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.first_name, long_name)

    def test_concurrent_updates_dont_conflict(self):
        """Test that concurrent updates to Member and User don't cause conflicts."""
        # Update member
        self.member.first_name = "ConcurrentMember"
        self.member.save()
        frappe.db.commit()

        # Immediately update user (simulating concurrent modification)
        admin = self.create_test_user(
            "admin.concurrent@test.local",
            roles=["System Manager"]
        )

        with self.as_user(admin.email):
            user = frappe.get_doc("User", self.member.user)
            user.last_name = "ConcurrentUser"
            user.save()

        frappe.db.commit()

        # Reload and verify both updates persisted
        self.member.reload()
        user.reload()

        self.assertEqual(self.member.first_name, "ConcurrentMember")
        self.assertEqual(user.last_name, "ConcurrentUser")
        self.assertEqual(self.member.last_name, "ConcurrentUser")  # Should have synced back

    def test_sync_with_unlinked_target_document(self):
        """Test sync behavior when Member has no linked User."""
        # Create member without user link
        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]

        unlinked_member = self.create_test_member(
            first_name="Unlinked",
            last_name="Member",
            email=f"unlinked.{unique_suffix}@test.local",
            birth_date="1990-01-01"
        )

        # Remove user link
        unlinked_member.user = None
        unlinked_member.save(ignore_permissions=True)
        frappe.db.commit()

        # Update member - should handle missing user link gracefully
        unlinked_member.image = "/files/no_user.jpg"
        unlinked_member.save()
        frappe.db.commit()

        # Should complete without raising exception
        self.assertTrue(True, "Sync should handle unlinked target gracefully")

    def test_bidirectional_sync_preserves_data_integrity(self):
        """Test that bidirectional sync maintains data consistency."""
        # Set initial values
        initial_first = "Initial"
        initial_last = "Name"
        initial_image = "/files/initial.jpg"

        self.member.first_name = initial_first
        self.member.last_name = initial_last
        self.member.image = initial_image
        self.member.save()
        frappe.db.commit()

        # Verify sync to user
        user = frappe.get_doc("User", self.member.user)
        self.assertEqual(user.first_name, initial_first)
        self.assertEqual(user.last_name, initial_last)
        self.assertEqual(user.user_image, initial_image)

        # Update from user side
        admin = self.create_test_user(
            "admin.bidirectional@test.local",
            roles=["System Manager"]
        )

        with self.as_user(admin.email):
            user.first_name = "UserUpdated"
            user.save()

        frappe.db.commit()

        # Verify sync back to member
        self.member.reload()
        self.assertEqual(self.member.first_name, "UserUpdated")

        # Original values should still be intact
        self.assertEqual(self.member.last_name, initial_last)
        self.assertEqual(self.member.image, initial_image)
