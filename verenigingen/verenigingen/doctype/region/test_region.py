# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import random

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestRegion(EnhancedTestCase):
    """Focused test suite for Region doctype - tests actual functionality, not implementation details"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

    @staticmethod
    def get_unique_suffix():
        """Generate unique suffix using timestamp + random to avoid collisions"""
        import time

        timestamp = str(int(time.time() * 1000000) % 1000000)
        rand_suffix = random.randint(100, 999)
        return f"{timestamp}-{rand_suffix}"

    def test_region_creation(self):
        """Test basic region creation with required fields"""
        unique_suffix = self.get_unique_suffix()

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Test Region {unique_suffix}",
                "region_code": f"TR{unique_suffix[:3]}",
                "country": "Netherlands",
            }
        )
        # EnhancedTestCase runs with frappe.flags.in_import=True, which suppresses
        # JSON field defaults (so is_active would be None). Temporarily clear the
        # flag for this insert to verify the real production default (is_active=1).
        prev_in_import = frappe.flags.in_import
        frappe.flags.in_import = False
        try:
            region.save()
        finally:
            frappe.flags.in_import = prev_in_import

        # Verify region was created
        self.assertIsNotNone(region.name)
        self.assertTrue(region.is_active)
        self.assertEqual(region.country, "Netherlands")

    def test_region_code_uniqueness(self):
        """Test that duplicate region codes are prevented"""
        unique_suffix = self.get_unique_suffix()
        # Region code must be 2-5 chars, use first 2 digits of timestamp
        code = f"D{unique_suffix[:1]}"

        # Create first region
        region1 = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Region One {unique_suffix}",
                "region_code": code,
            }
        )
        region1.save()

        # Try to create second region with same code
        region2 = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Region Two {unique_suffix}",
                "region_code": code,
            }
        )

        # Should fail due to duplicate code
        with self.assertRaises(frappe.ValidationError):
            region2.save()

    def test_postal_code_patterns(self):
        """Test postal code pattern matching functionality"""
        unique_suffix = self.get_unique_suffix()

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Postal Test Region {unique_suffix}",
                "region_code": f"PT{unique_suffix[:3]}",
                "postal_code_patterns": "1000-1999, 2500, 3000-3099",
            }
        )
        region.save()

        # Verify patterns are stored
        self.assertEqual(region.postal_code_patterns, "1000-1999, 2500, 3000-3099")

    def test_region_coordinator_assignment(self):
        """Test assigning regional coordinator (Member link)"""
        unique_suffix = self.get_unique_suffix()

        # Create a member to be coordinator
        coordinator = self.create_test_member()

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Coordinator Region {unique_suffix}",
                "region_code": f"CR{unique_suffix[:3]}",
                "regional_coordinator": coordinator.name,
            }
        )
        region.save()

        # Verify coordinator assignment
        self.assertEqual(region.regional_coordinator, coordinator.name)
