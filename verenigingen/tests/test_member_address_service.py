"""
Member Address Service Tests

Tests for the MemberAddressService class that handles address normalization,
fingerprinting, co-located member discovery, and address display generation.

This service extracts address management logic from the Member controller
to enable better testing, performance optimization, and reusability.
"""

import unittest
from unittest.mock import patch, MagicMock

import frappe
from frappe.test_runner import make_test_records

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.services.member.core.member_address_service import member_address_service


class TestMemberAddressService(VereningingenTestCase):
    """Test Member Address Service functionality"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()

        # Create test member for address operations
        self.test_member = self.create_test_member(
            first_name="Jan",
            last_name="de Vries",
            birth_date="1985-03-15"
        )

        # Create test address using frappe.get_doc
        self.test_address = frappe.get_doc({
            "doctype": "Address",
            "address_title": "Test Address",
            "address_line1": "Kalverstraat 123",
            "city": "Amsterdam",
            "pincode": "1012 NX",
            "country": "Netherlands",
            "address_type": "Personal"
        })
        self.test_address.insert()

        # Link address to member with proper reload to avoid timestamp mismatch
        self.test_member.reload()
        self.test_member.primary_address = self.test_address.name
        self.test_member.save(ignore_version=True)

    def test_update_member_address_fields_success(self):
        """Test successful address field updates"""

        # Clear existing address fields
        self.test_member.address_fingerprint = None
        self.test_member.normalized_address_line = None
        self.test_member.normalized_city = None
        self.test_member.address_last_updated = None

        # Call service method
        result = member_address_service.update_member_address_fields(self.test_member)

        # Verify success
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["fingerprint"])
        self.assertEqual(len(result["errors"]), 0)

        # Verify updated fields
        updated_fields = result["updated_fields"]
        self.assertIn("address_fingerprint", updated_fields)
        self.assertIn("normalized_address_line", updated_fields)
        self.assertIn("normalized_city", updated_fields)
        self.assertIn("address_last_updated", updated_fields)

        # Verify member fields were updated
        self.assertIsNotNone(self.test_member.address_fingerprint)
        self.assertIsNotNone(self.test_member.normalized_address_line)
        self.assertIsNotNone(self.test_member.normalized_city)
        self.assertIsNotNone(self.test_member.address_last_updated)

    def test_update_member_address_fields_no_address(self):
        """Test address field updates when member has no primary address"""

        # Remove primary address
        self.test_member.primary_address = None

        # Call service method
        result = member_address_service.update_member_address_fields(self.test_member)

        # Verify success but fields are cleared
        self.assertTrue(result["success"])
        self.assertIsNone(result["fingerprint"])

        # Verify member fields were cleared
        self.assertIsNone(self.test_member.address_fingerprint)
        self.assertIsNone(self.test_member.normalized_address_line)
        self.assertIsNone(self.test_member.normalized_city)
        self.assertIsNone(self.test_member.address_last_updated)

    def test_update_member_address_fields_no_update_needed(self):
        """Test that address fields are not updated when not needed"""

        # Set existing fingerprint
        self.test_member.address_fingerprint = "existing_fingerprint"

        # Mock the change detection to return False
        with patch.object(self.test_member, 'is_new', return_value=False), \
             patch.object(self.test_member, 'has_value_changed', return_value=False):

            result = member_address_service.update_member_address_fields(self.test_member)

            # Verify success with existing fingerprint
            self.assertTrue(result["success"])
            self.assertEqual(result["fingerprint"], "existing_fingerprint")
            self.assertEqual(len(result["updated_fields"]), 0)

    def test_update_member_address_fields_error_handling(self):
        """Test error handling in address field updates"""

        # Create member with invalid address reference
        self.test_member.primary_address = "INVALID_ADDRESS"

        # Call service method
        result = member_address_service.update_member_address_fields(self.test_member)

        # Verify failure
        self.assertFalse(result["success"])
        self.assertGreater(len(result["errors"]), 0)
        self.assertIsNone(result["fingerprint"])

        # Verify fields were cleared on error
        self.assertIsNone(self.test_member.address_fingerprint)
        self.assertIsNone(self.test_member.normalized_address_line)
        self.assertIsNone(self.test_member.normalized_city)
        self.assertIsNone(self.test_member.address_last_updated)

    def test_get_colocated_members_success(self):
        """Test successful co-located member discovery"""

        # Create additional member at same address
        other_member = self.create_test_member(
            first_name="Maria",
            last_name="de Vries",
            birth_date="1987-05-20"
        )
        other_member.reload()
        other_member.primary_address = self.test_address.name
        other_member.save(ignore_version=True)

        # Update address fields for both members
        member_address_service.update_member_address_fields(self.test_member)
        member_address_service.update_member_address_fields(other_member)

        # Call service method
        result = member_address_service.get_colocated_members(self.test_member)

        # Verify success
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["count"], 1)
        self.assertIsInstance(result["members"], list)
        self.assertEqual(len(result["errors"]), 0)

        # Verify member data structure
        if result["members"]:
            member_data = result["members"][0]
            required_fields = ["name", "full_name", "email", "status", "age_text"]
            for field in required_fields:
                self.assertIn(field, member_data)

    def test_get_colocated_members_no_address(self):
        """Test co-located member discovery when member has no address"""

        # Remove primary address
        self.test_member.primary_address = None

        # Call service method
        result = member_address_service.get_colocated_members(self.test_member)

        # Verify success but no members found
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(len(result["members"]), 0)

    def test_get_colocated_members_error_handling(self):
        """Test error handling in co-located member discovery"""

        # Mock the address matcher to raise an exception
        with patch('verenigingen.utils.address_matching.simple_optimized_matcher.SimpleOptimizedAddressMatcher.get_other_members_at_address_simple',
                   side_effect=Exception("Address matching error")):

            result = member_address_service.get_colocated_members(self.test_member)

            # Verify failure
            self.assertFalse(result["success"])
            self.assertGreater(len(result["errors"]), 0)
            self.assertEqual(result["count"], 0)
            self.assertEqual(len(result["members"]), 0)

    def test_generate_address_display_html_success(self):
        """Test successful HTML display generation"""

        # Create additional member at same address
        other_member = self.create_test_member(
            first_name="Maria",
            last_name="de Vries",
            birth_date="1987-05-20"
        )
        other_member.reload()
        other_member.primary_address = self.test_address.name
        other_member.save(ignore_version=True)

        # Update address fields
        member_address_service.update_member_address_fields(self.test_member)
        member_address_service.update_member_address_fields(other_member)

        # Call service method
        result = member_address_service.generate_address_display_html(self.test_member)

        # Verify success
        self.assertTrue(result["success"])
        self.assertIsInstance(result["html_content"], str)
        self.assertGreaterEqual(result["member_count"], 1)
        self.assertEqual(len(result["errors"]), 0)

        # Verify HTML contains expected elements
        if result["member_count"] > 0:
            html = result["html_content"]
            self.assertIn("other-members-container", html)
            self.assertIn("Other Members at Same Address", html)
            self.assertIn(other_member.full_name, html)

    def test_generate_address_display_html_no_members(self):
        """Test HTML display generation when no co-located members exist"""

        # Call service method (only this member at address)
        result = member_address_service.generate_address_display_html(self.test_member)

        # Verify success but empty content
        self.assertTrue(result["success"])
        self.assertEqual(result["html_content"], "")
        self.assertEqual(result["member_count"], 0)

    def test_generate_address_display_html_save_to_db(self):
        """Test HTML display generation with database save"""

        # Create additional member at same address
        other_member = self.create_test_member(
            first_name="Maria",
            last_name="de Vries",
            birth_date="1987-05-20"
        )
        other_member.reload()
        other_member.primary_address = self.test_address.name
        other_member.save(ignore_version=True)

        # Update address fields
        member_address_service.update_member_address_fields(self.test_member)
        member_address_service.update_member_address_fields(other_member)

        # Clear existing HTML field
        self.test_member.other_members_at_address = ""

        # Call service method with save_to_db=True
        result = member_address_service.generate_address_display_html(self.test_member, save_to_db=True)

        # Verify success
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["member_count"], 1)

        # Verify member field was updated
        self.assertEqual(self.test_member.other_members_at_address, result["html_content"])

    def test_generate_address_display_html_error_handling(self):
        """Test error handling in HTML display generation"""

        # Mock the colocated members method to fail
        with patch.object(member_address_service, 'get_colocated_members',
                         return_value={"success": False, "errors": ["Test error"], "members": [], "count": 0}):

            result = member_address_service.generate_address_display_html(self.test_member)

            # Verify failure
            self.assertFalse(result["success"])
            self.assertGreater(len(result["errors"]), 0)
            self.assertEqual(result["html_content"], "")
            self.assertEqual(result["member_count"], 0)

    def test_service_integration_workflow(self):
        """Test complete workflow using all service methods"""

        # Create additional member at same address
        other_member = self.create_test_member(
            first_name="Maria",
            last_name="de Vries",
            birth_date="1987-05-20"
        )
        other_member.reload()
        other_member.primary_address = self.test_address.name
        other_member.save(ignore_version=True)

        # Step 1: Update address fields for both members
        result1 = member_address_service.update_member_address_fields(self.test_member)
        result2 = member_address_service.update_member_address_fields(other_member)

        self.assertTrue(result1["success"])
        self.assertTrue(result2["success"])

        # Step 2: Find co-located members
        colocated_result = member_address_service.get_colocated_members(self.test_member)

        self.assertTrue(colocated_result["success"])
        self.assertGreaterEqual(colocated_result["count"], 1)

        # Step 3: Generate HTML display
        display_result = member_address_service.generate_address_display_html(self.test_member, save_to_db=True)

        self.assertTrue(display_result["success"])
        self.assertGreaterEqual(display_result["member_count"], 1)
        self.assertIn("other-members-container", display_result["html_content"])

        # Verify member field was updated
        self.assertEqual(self.test_member.other_members_at_address, display_result["html_content"])

    def test_service_performance_with_multiple_members(self):
        """Test service performance with multiple members"""

        # Create multiple members at same address
        members = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Test{i}",
                last_name="User",
                birth_date=f"198{i}-01-01"
            )
            member.reload()
            member.primary_address = self.test_address.name
            member.save(ignore_version=True)
            members.append(member)

        # Update address fields for all members
        import time
        start_time = time.time()

        for member in members:
            result = member_address_service.update_member_address_fields(member)
            self.assertTrue(result["success"])

        # Test co-located member discovery performance
        colocated_result = member_address_service.get_colocated_members(self.test_member)

        processing_time = time.time() - start_time

        # Should complete quickly
        self.assertLess(processing_time, 2.0)  # Less than 2 seconds
        self.assertTrue(colocated_result["success"])
        self.assertGreaterEqual(colocated_result["count"], 3)

    def test_dutch_address_normalization_integration(self):
        """Test Dutch address normalization integration"""

        # Create address with Dutch street patterns
        dutch_address = frappe.get_doc({
            "doctype": "Address",
            "address_title": "Dutch Test Address",
            "address_line1": "Nieuwe Prinsengracht 123",
            "city": "Amsterdam",
            "pincode": "1018 VZ",
            "country": "Netherlands",
            "address_type": "Personal"
        })
        dutch_address.insert()

        self.test_member.primary_address = dutch_address.name
        self.test_member.save(ignore_version=True)

        # Update address fields
        result = member_address_service.update_member_address_fields(self.test_member)

        # Verify success
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["fingerprint"])

        # Verify normalized fields contain Dutch-specific patterns
        self.assertIsNotNone(self.test_member.normalized_address_line)
        self.assertIsNotNone(self.test_member.normalized_city)

        # Address should be normalized to lowercase, consistent format
        self.assertTrue(self.test_member.normalized_address_line.islower())
        self.assertTrue(self.test_member.normalized_city.islower())

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()


if __name__ == "__main__":
    unittest.main()