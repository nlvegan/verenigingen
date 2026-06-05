"""
Test User-Member Image Synchronization
======================================

Tests for bidirectional image sync between User and Member records.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestUserMemberImageSync(EnhancedTestCase):
    """Test bidirectional synchronization of profile pictures."""

    def setUp(self):
        """Set up test data."""
        super().setUp()

        # Use unique email for each test to avoid conflicts
        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        self.test_email = f"image.sync.{unique_suffix}@test.local"

        # Create a test member with a linked user
        self.member = self.create_test_member(
            first_name="Image",
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
            "admin.user.sync@test.local",
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

    def test_sync_prevents_infinite_loop(self):
        """Test that sync flag prevents infinite loops."""
        test_image = "/files/loop_test.jpg"

        # Image sync runs through the generic field_sync_service, which guards
        # against recursion with the "syncing_member_user_fields" flag. Setting
        # it here must suppress the Member -> User image sync.
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
            email="no.user@test.local",
            birth_date="1995-05-05"
        )
        member.user = None
        member.save()

        # Update image - should not error
        member.image = "/files/no_user.jpg"
        member.save()

        # Should complete without error
        self.assertTrue(True, "Member save should succeed even without linked user")

    def test_sync_handles_missing_member(self):
        """Test that sync gracefully handles users without members."""
        # Create user without member - use unique email
        import time
        unique_suffix = str(int(time.time() * 1000))[-6:]
        test_email = f"no.member.{unique_suffix}@test.local"

        # Create user with proper permission context
        admin_user = self.create_test_user(
            "admin.image.sync@test.local",
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

            # Update user image - should not error
            user.user_image = "/files/no_member.jpg"
            user.save()

        # Should complete without error
        self.assertTrue(True, "User save should succeed even without linked member")

    def test_sync_only_on_change(self):
        """Test that sync only happens when image actually changes."""
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
