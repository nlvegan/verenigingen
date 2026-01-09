"""
Integration Tests for CSV Import User Linking

Tests that CSV imports properly link existing user accounts to member records,
addressing the systematic user linking failure where 99.8% of members had empty
user fields after import.
"""

import csv
import os
import tempfile

import frappe
from frappe.utils import add_days, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.account_creation_manager import queue_account_creation_for_member


class TestCSVImportUserLinking(EnhancedTestCase):
    """Integration tests for CSV import user account linking"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary CSV files"""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
        super().tearDown()

    def _get_request_name_or_skip(self, result, context="account creation"):
        """Helper to get request_name from result or skip if roles are missing."""
        if not result.get("success"):
            errors = result.get("errors", [])
            error_str = str(errors)
            if "Role" in error_str or "Employee Self Service" in error_str:
                self.skipTest(f"Required role missing in test environment: {errors}")
            self.fail(f"{context} failed: {result.get('error', errors)}")
        return result["request_name"]

    def _create_temp_csv(self, data, suffix='.csv'):
        """Create temporary CSV file with test data"""
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix=suffix,
            delete=False,
            encoding='utf-8'
        )

        if data:
            writer = csv.DictWriter(temp_file, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        temp_file.close()
        self.temp_files.append(temp_file.name)
        return temp_file.name

    def test_csv_import_links_new_users(self):
        """Test that CSV import creates and links new user accounts"""
        # Create member via CSV-like process
        member = self.create_test_member(
            first_name="New",
            last_name="User",
            email="new.user@test.invalid",
            birth_date="1990-01-01"
        )

        # Verify member.user is initially empty
        self.assertFalse(member.user, "Member.user should be empty initially")

        # Queue account creation (simulating post-CSV-import processing)
        result = queue_account_creation_for_member(
            member.name,
            roles=["Verenigingen Member"]
        )

        # Verify request was created and get request name
        request_name = self._get_request_name_or_skip(result, "account creation")

        # Process the account creation request
        from verenigingen.utils.account_creation_manager import (
            process_account_creation_request
        )
        process_result = process_account_creation_request(request_name)

        # Verify success
        self.assertTrue(process_result.get("success"),
                       "Account creation should succeed")

        # Verify user was created and linked
        member.reload()
        self.assertTrue(member.user, "Member.user should be populated")
        self.assertTrue(frappe.db.exists("User", member.user),
                       "User account should exist in database")

    def test_csv_import_links_existing_users(self):
        """Test that CSV import links pre-existing user accounts to members"""
        # Create member via CSV-like process
        member = self.create_test_member(
            first_name="Existing",
            last_name="User",
            email="existing.user.csv@test.invalid",
            birth_date="1990-01-01"
        )

        # Create pre-existing user account (simulating user who registered before import)
        existing_user = frappe.get_doc({
            "doctype": "User",
            "email": member.email,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "enabled": 1,
            "user_type": "System User"
        })
        existing_user.insert()

        # Verify member.user is initially empty
        self.assertFalse(member.user, "Member.user should be empty initially")

        # Create request manually (not via queue_account_creation which checks for existing completed requests)
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()

        # Set status to Queued after insert (status may be set by hooks during insert)
        request.status = "Queued"
        request.save()

        # Process the account creation request directly
        from verenigingen.utils.account_creation_manager import AccountCreationManager
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        # Verify request completed successfully
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertEqual(request.created_user, existing_user.name)

        # CRITICAL: Verify member.user field is now linked to existing user
        member.reload()
        self.assertEqual(member.user, existing_user.name,
                        "Member.user must be linked to existing user")

        # Verify no duplicate user was created
        user_count = frappe.db.count("User", {"email": member.email})
        self.assertEqual(user_count, 1,
                        "Should not create duplicate user account")

    def test_bulk_csv_import_links_mixed_users(self):
        """Test that bulk CSV import handles both new and existing users correctly"""
        # Simulate bulk import with 3 members: 2 with existing users, 1 new
        members = []
        existing_users = []

        # Member 1: with existing user
        member1 = self.create_test_member(
            first_name="Bulk1",
            last_name="ExistingUser",
            email="bulk1.existing@test.invalid",
            birth_date="1990-01-01"
        )
        existing_user1 = frappe.get_doc({
            "doctype": "User",
            "email": member1.email,
            "first_name": member1.first_name,
            "last_name": member1.last_name,
            "enabled": 1,
            "user_type": "System User"
        })
        existing_user1.insert()
        members.append(member1)
        existing_users.append(existing_user1)

        # Member 2: with existing user
        member2 = self.create_test_member(
            first_name="Bulk2",
            last_name="ExistingUser",
            email="bulk2.existing@test.invalid",
            birth_date="1991-01-01"
        )
        existing_user2 = frappe.get_doc({
            "doctype": "User",
            "email": member2.email,
            "first_name": member2.first_name,
            "last_name": member2.last_name,
            "enabled": 1,
            "user_type": "System User"
        })
        existing_user2.insert()
        members.append(member2)
        existing_users.append(existing_user2)

        # Member 3: new user
        member3 = self.create_test_member(
            first_name="Bulk3",
            last_name="NewUser",
            email="bulk3.new@test.invalid",
            birth_date="1992-01-01"
        )
        members.append(member3)

        # Verify all members have empty user fields initially
        for member in members:
            member.reload()
            self.assertFalse(member.user,
                           f"{member.name} should have empty user field initially")

        # Create and process account creation requests for all members
        from verenigingen.utils.account_creation_manager import AccountCreationManager

        for member in members:
            # Create request manually to avoid duplicate checking issues in tests
            request = frappe.get_doc({
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": member.email,
                "full_name": member.full_name,
                "requested_roles": [{"role": "Verenigingen Member"}]
            })
            request.insert()

            # Set status to Queued after insert
            request.status = "Queued"
            request.save()

            # Process the request
            manager = AccountCreationManager(request.name)
            manager.process_complete_pipeline()

            # Verify success
            request.reload()
            self.assertEqual(request.status, "Completed",
                           f"Request should complete for {member.name}")

        # Verify all members now have user field populated
        for i, member in enumerate(members):
            member.reload()
            self.assertTrue(member.user,
                           f"{member.name} should have user field populated")

            if i < 2:  # First two members had existing users
                self.assertEqual(member.user, existing_users[i].name,
                               f"{member.name} should link to existing user")
            else:  # Third member is new
                self.assertTrue(frappe.db.exists("User", member.user),
                               f"{member.name} should have new user created")

        # Verify 100% user linking rate (fixing the 99.8% failure rate)
        linked_count = sum(1 for m in members if m.user)
        total_count = len(members)
        linking_rate = (linked_count / total_count) * 100

        self.assertEqual(linking_rate, 100.0,
                        "All members should have user accounts linked (100% rate)")

    def test_csv_import_preserves_existing_user_data(self):
        """Test that linking existing users preserves their existing data"""
        # Create member
        member = self.create_test_member(
            first_name="Preserve",
            last_name="UserData",
            email="preserve.data@test.invalid",
            birth_date="1990-01-01"
        )

        # Create existing user with specific settings
        existing_user = frappe.get_doc({
            "doctype": "User",
            "email": member.email,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "enabled": 1,
            "user_type": "System User",
            "language": "nl",  # Dutch language preference
            "time_zone": "Europe/Amsterdam"
        })
        existing_user.insert()

        original_language = existing_user.language
        original_timezone = existing_user.time_zone

        # Create and process account creation request
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()

        # Set status to Queued after insert
        request.status = "Queued"
        request.save()

        from verenigingen.utils.account_creation_manager import AccountCreationManager
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        self.assertEqual(request.status, "Completed")

        # Verify member is linked
        member.reload()
        self.assertEqual(member.user, existing_user.name)

        # Verify existing user data was preserved
        existing_user.reload()
        self.assertEqual(existing_user.language, original_language,
                        "User language preference should be preserved")
        self.assertEqual(existing_user.time_zone, original_timezone,
                        "User timezone should be preserved")

    def test_csv_import_adds_roles_to_existing_users(self):
        """Test that existing users get new roles added during linking"""
        # Create member
        member = self.create_test_member(
            first_name="Add",
            last_name="Roles",
            email="add.roles@test.invalid",
            birth_date="1990-01-01"
        )

        # Create existing user without Verenigingen Member role
        existing_user = frappe.get_doc({
            "doctype": "User",
            "email": member.email,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "enabled": 1,
            "user_type": "System User"
        })
        existing_user.insert()

        # Verify user doesn't have Verenigingen Member role
        user_roles = [r.role for r in existing_user.roles]
        self.assertNotIn("Verenigingen Member", user_roles,
                        "User should not have Verenigingen Member role initially")

        # Create and process account creation request
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()

        # Set status to Queued after insert
        request.status = "Queued"
        request.save()

        from verenigingen.utils.account_creation_manager import AccountCreationManager
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        self.assertEqual(request.status, "Completed")

        # Verify member is linked
        member.reload()
        self.assertEqual(member.user, existing_user.name)

        # Verify role was added to existing user
        existing_user.reload()
        user_roles = [r.role for r in existing_user.roles]
        self.assertIn("Verenigingen Member", user_roles,
                     "Verenigingen Member role should be added to existing user")


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
