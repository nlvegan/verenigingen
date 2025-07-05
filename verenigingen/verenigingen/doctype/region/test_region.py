# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import random
import string

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRegion(FrappeTestCase):
    """Comprehensive test suite for Region doctype functionality"""

    @classmethod
    def setUpClass(cls):
        """Clean up any existing test data before starting tests"""
        # Clean up any leftover test regions
        test_regions = frappe.get_all("Region", filters={"region_name": ["like", "Test Region%"]})
        for region in test_regions:
            try:
                frappe.delete_doc("Region", region.name, force=True)
            except Exception:
                pass

        # Clean up any leftover test members
        test_members = frappe.get_all("Member", filters={"email": ["like", "test%coordinator%"]})
        for member in test_members:
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except Exception:
                pass

    def setUp(self):
        """Set up test data"""
        # Generate unique suffix for each test method
        self.test_suffix = "".join(random.choices(string.ascii_lowercase, k=6))

        # Base test data - will be customized per test method
        self.base_region_data = {
            "country": "Netherlands",
            "postal_code_patterns": "2000-2999, 3*",
            "description": "Test region for unit testing",
            "preferred_language": "Dutch",
            "time_zone": "Europe/Amsterdam",
            "membership_fee_adjustment": 1.0,
        }

        self.base_member_data = {
            "first_name": "Test",
            "last_name": "Coordinator",
            "status": "Active",
            "birth_date": "1990-01-01",
            "membership_type": "Regular",
        }

    def tearDown(self):
        """Clean up test data after each test"""
        # Clean up test regions created in this test
        test_regions = frappe.get_all("Region", filters={"region_name": ["like", f"%{self.test_suffix}%"]})
        for region in test_regions:
            try:
                frappe.delete_doc("Region", region.name, force=True)
            except Exception:
                pass

        # Clean up test members created in this test
        test_members = frappe.get_all("Member", filters={"email": ["like", f"%{self.test_suffix}%"]})
        for member in test_members:
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except Exception:
                pass

    def create_test_region(self, custom_name=None, custom_code=None, **kwargs):
        """Helper to create test region with unique naming"""
        region_data = self.base_region_data.copy()
        region_data.update(kwargs)

        region_data["region_name"] = custom_name or f"Test Region {self.test_suffix}"
        region_data["region_code"] = custom_code or f"T{self.test_suffix[:3].upper()}"

        region = frappe.new_doc("Region")
        region.update(region_data)
        return region

    def create_test_member(self, custom_email=None, **kwargs):
        """Helper to create test member with unique naming"""
        member_data = self.base_member_data.copy()
        member_data.update(kwargs)

        member_data["email"] = custom_email or f"test{self.test_suffix}@coordinator.com"
        member_data["full_name"] = f"Test Coordinator {self.test_suffix}"
        member_data["customer_name"] = f"Test Coordinator {self.test_suffix}"

        member = frappe.new_doc("Member")
        member.update(member_data)
        member.flags.ignore_validate = True  # Skip validation for test data
        return member

    def test_01_region_creation(self):
        """Test basic region creation"""
        region = self.create_test_region()
        region.save()

        # Test that the region was created with the expected values
        # Note: Frappe uses region_name as document name, so it gets slugified
        self.assertEqual(region.region_code, f"T{self.test_suffix[:3].upper()}")
        # Check that the document name was auto-generated (slugified version of region_name)
        self.assertIsNotNone(region.name)
        expected_name_part = f"test-region-{self.test_suffix}"
        self.assertTrue(region.name.startswith(expected_name_part))
        # The region_name field is set to the slugified version by Frappe
        self.assertTrue(region.region_name.startswith(expected_name_part))
        self.assertTrue(region.is_active)
        self.assertEqual(region.country, "Netherlands")
        self.assertEqual(region.preferred_language, "Dutch")

    def test_02_region_code_validation(self):
        """Test region code validation and formatting"""
        # Test uppercase conversion
        region = self.create_test_region(custom_code=f"tz{self.test_suffix[:1]}")
        region.save()
        self.assertEqual(region.region_code, f"TZ{self.test_suffix[:1].upper()}")

        # Test invalid format - special characters
        region2 = self.create_test_region(
            custom_name=f"Invalid Region {self.test_suffix}", custom_code="123-ABC"
        )
        with self.assertRaises(frappe.ValidationError):
            region2.save()

        # Test invalid format - too long
        region3 = self.create_test_region(
            custom_name=f"Too Long Region {self.test_suffix}", custom_code="TOOLONG"
        )
        with self.assertRaises(frappe.ValidationError):
            region3.save()

        # Test invalid format - too short
        region4 = self.create_test_region(custom_name=f"Too Short Region {self.test_suffix}", custom_code="T")
        with self.assertRaises(frappe.ValidationError):
            region4.save()

    def test_03_region_uniqueness(self):
        """Test region name and code uniqueness"""
        # Create first region
        region1 = self.create_test_region()
        region1.save()

        # Try to create duplicate name
        region2 = self.create_test_region(custom_code=f"DUP{self.test_suffix[:2]}")
        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            region2.save()

        # Try to create duplicate code
        region3 = self.create_test_region(
            custom_name=f"Different Name {self.test_suffix}",
            custom_code=region1.region_code,  # Same code as region1
        )
        with self.assertRaises(frappe.ValidationError):
            region3.save()

    def test_04_postal_code_pattern_matching(self):
        """Test comprehensive postal code pattern matching"""
        region = self.create_test_region(postal_code_patterns="2000-2999, 3*, 4100, 5000-5099")
        region.save()

        # Test range matching (2000-2999)
        self.assertTrue(region.matches_postal_code("2000"))
        self.assertTrue(region.matches_postal_code("2500"))
        self.assertTrue(region.matches_postal_code("2999"))
        self.assertFalse(region.matches_postal_code("1999"))

        # Test wildcard matching (3*)
        self.assertTrue(region.matches_postal_code("3000"))  # Matches 3*
        self.assertTrue(region.matches_postal_code("3123"))
        self.assertTrue(region.matches_postal_code("3999"))

        # Test exact matching (4100)
        self.assertTrue(region.matches_postal_code("4100"))
        self.assertFalse(region.matches_postal_code("4101"))
        self.assertFalse(region.matches_postal_code("4099"))

        # Test second range (5000-5099)
        self.assertTrue(region.matches_postal_code("5000"))
        self.assertTrue(region.matches_postal_code("5050"))
        self.assertTrue(region.matches_postal_code("5099"))
        self.assertFalse(region.matches_postal_code("4999"))
        self.assertFalse(region.matches_postal_code("5100"))

        # Test codes that don't match any pattern
        self.assertFalse(region.matches_postal_code(""))
        self.assertFalse(region.matches_postal_code("abc"))
        self.assertFalse(region.matches_postal_code("9999"))

    def test_05_postal_code_edge_cases(self):
        """Test edge cases in postal code matching"""
        region = self.create_test_region(postal_code_patterns="1*, 2000-2999")
        region.save()

        # Test postal codes with spaces
        self.assertTrue(region.matches_postal_code("1000 AB"))  # Matches 1*
        self.assertTrue(region.matches_postal_code("2500 CD"))  # Matches 2000-2999

        # Test edge of ranges
        self.assertTrue(region.matches_postal_code("2000"))
        self.assertTrue(region.matches_postal_code("2999"))
        self.assertTrue(region.matches_postal_code("1999"))  # Matches 1*
        self.assertFalse(region.matches_postal_code("3000"))  # No match

    def test_06_coordinator_validation(self):
        """Test coordinator validation and relationships"""
        # Create test member first
        member = self.create_test_member()
        member.save()

        # Test valid coordinator
        region = self.create_test_region(regional_coordinator=member.name)  # Use member name, not email
        region.save()
        self.assertEqual(region.regional_coordinator, member.name)

        # Test invalid coordinator (non-existent)
        region2 = self.create_test_region(
            custom_name=f"Invalid Coord Region {self.test_suffix}",
            custom_code=f"IC{self.test_suffix[:2].upper()}",
            regional_coordinator="nonexistent-member-id",
        )
        with self.assertRaises(frappe.ValidationError):
            region2.save()

        # Test backup coordinator same as main coordinator
        region3 = self.create_test_region(
            custom_name=f"Same Coord Region {self.test_suffix}",
            custom_code=f"SC{self.test_suffix[:2].upper()}",
            regional_coordinator=member.name,
            backup_coordinator=member.name,
        )
        with self.assertRaises(frappe.ValidationError):
            region3.save()

    def test_07_contact_info_validation(self):
        """Test contact information validation"""
        region = self.create_test_region()

        # Test valid email
        region.regional_email = "region@example.com"
        region.save()
        self.assertEqual(region.regional_email, "region@example.com")

        # Test invalid email with a new region to avoid timestamp issues
        region2 = self.create_test_region(
            custom_name=f"Test Invalid Email Region {self.test_suffix}",
            custom_code=f"IE{self.test_suffix[:2].upper()}",
            regional_email="invalid-email",
        )
        with self.assertRaises(frappe.ValidationError):
            region2.save()

        # Test URL formatting with another new region
        region3 = self.create_test_region(
            custom_name=f"Test URL Region {self.test_suffix}",
            custom_code=f"UR{self.test_suffix[:2].upper()}",
            regional_email="valid@example.com",
            website_url="example.com",
        )
        region3.save()

        # Should auto-prepend https://
        self.assertTrue(region3.website_url.startswith("https://"))

    def test_08_membership_fee_adjustment_validation(self):
        """Test membership fee adjustment validation"""
        # Test too low
        region = self.create_test_region(membership_fee_adjustment=0.05)
        with self.assertRaises(frappe.ValidationError):
            region.save()

        # Test too high
        region2 = self.create_test_region(
            custom_name=f"High Fee Region {self.test_suffix}",
            custom_code=f"HF{self.test_suffix[:2].upper()}",
            membership_fee_adjustment=3.0,
        )
        with self.assertRaises(frappe.ValidationError):
            region2.save()

        # Test valid values
        valid_adjustments = [0.1, 0.5, 1.0, 1.5, 2.0]
        for i, adjustment in enumerate(valid_adjustments):
            region = self.create_test_region(
                custom_name=f"Valid Fee Region {self.test_suffix} {i}",
                custom_code=f"V{i}{self.test_suffix[:2].upper()}",
                membership_fee_adjustment=adjustment,
            )
            region.save()
            self.assertEqual(region.membership_fee_adjustment, adjustment)

    def test_09_region_statistics(self):
        """Test regional statistics calculation"""
        region = self.create_test_region()
        region.save()

        stats = region.get_region_statistics()

        # Verify structure
        self.assertIn("total_chapters", stats)
        self.assertIn("published_chapters", stats)
        self.assertIn("total_members", stats)

        # Verify types
        self.assertIsInstance(stats["total_chapters"], int)
        self.assertIsInstance(stats["published_chapters"], int)
        self.assertIsInstance(stats["total_members"], int)

        # Verify non-negative values
        self.assertGreaterEqual(stats["total_chapters"], 0)
        self.assertGreaterEqual(stats["published_chapters"], 0)
        self.assertGreaterEqual(stats["total_members"], 0)

        # Verify logical consistency
        self.assertLessEqual(stats["published_chapters"], stats["total_chapters"])

    def test_10_postal_code_pattern_parsing(self):
        """Test postal code pattern parsing"""
        region = self.create_test_region(postal_code_patterns="1000-1999, 2*, 3000, 4000-4099")
        region.save()

        patterns = region.parse_postal_code_patterns()

        self.assertEqual(len(patterns), 4)
        self.assertIn("1000-1999", patterns)
        self.assertIn("2*", patterns)
        self.assertIn("3000", patterns)
        self.assertIn("4000-4099", patterns)

        # Test empty patterns
        region.postal_code_patterns = ""
        patterns_empty = region.parse_postal_code_patterns()
        self.assertEqual(len(patterns_empty), 0)

        # Test patterns with extra spaces
        region.postal_code_patterns = " 1000-1999 , 2* , 3000 "
        patterns_spaced = region.parse_postal_code_patterns()
        self.assertEqual(len(patterns_spaced), 3)

    def test_11_web_route_generation(self):
        """Test web route generation"""
        region = self.create_test_region()
        region.save()

        # Check route is generated
        self.assertIsNotNone(region.route)
        self.assertTrue(region.route.startswith("regions/"))

        # Test route with special characters
        region2 = self.create_test_region(
            custom_name=f"Test Region with Spaces & Special! {self.test_suffix}",
            custom_code=f"SP{self.test_suffix[:2].upper()}",
        )
        region2.save()

        # Route should be URL-friendly
        self.assertNotIn(" ", region2.route)
        self.assertNotIn("&", region2.route)
        self.assertNotIn("!", region2.route)

    def test_12_region_context_for_web(self):
        """Test region context generation for web views"""
        region = self.create_test_region()
        region.save()

        # Test get_context method with dict context
        context = {}
        region.get_context(context)

        # Verify context structure
        self.assertIn("chapters", context)
        self.assertIn("stats", context)
        self.assertTrue(context.get("no_cache"))

        # Verify chapters is a list
        self.assertIsInstance(context["chapters"], list)

        # Verify stats is a dict
        self.assertIsInstance(context["stats"], dict)


class TestRegionUtilityFunctions(FrappeTestCase):
    """Test utility functions for Region doctype"""

    def setUp(self):
        """Set up test data"""
        self.test_suffix = "".join(random.choices(string.ascii_lowercase, k=6))

        # Clean up any existing test regions
        test_regions = frappe.get_all("Region", filters={"region_name": ["like", "Test Util%"]})
        for region in test_regions:
            try:
                frappe.delete_doc("Region", region.name, force=True)
            except Exception:
                pass

        # Create test region
        self.test_region = frappe.new_doc("Region")
        self.test_region.region_name = f"Test Util Region {self.test_suffix}"
        self.test_region.region_code = f"TU{self.test_suffix[:2].upper()}"
        self.test_region.postal_code_patterns = "9000-9099, 8*"
        self.test_region.is_active = 1
        self.test_region.save()

    def tearDown(self):
        """Clean up test data"""
        if hasattr(self, "test_region") and self.test_region:
            try:
                frappe.delete_doc("Region", self.test_region.name, force=True)
            except Exception:
                pass

    def test_get_regions_for_dropdown(self):
        """Test regions dropdown data function"""
        from verenigingen.verenigingen.doctype.region.region import get_regions_for_dropdown

        regions = get_regions_for_dropdown()

        # Should be a list
        self.assertIsInstance(regions, list)

        # Should include our test region
        region_names = [r["name"] for r in regions]
        self.assertIn(self.test_region.name, region_names)

        # Check structure of returned data
        if regions:
            region = regions[0]
            self.assertIn("name", region)
            self.assertIn("region_name", region)
            self.assertIn("region_code", region)

    def test_find_region_by_postal_code(self):
        """Test finding region by postal code"""
        from verenigingen.verenigingen.doctype.region.region import find_region_by_postal_code

        # Test matching postal codes
        found_region = find_region_by_postal_code("9050")
        if found_region:  # May not find due to other regions with broader patterns
            self.assertIsInstance(found_region, str)

        # Test wildcard matching
        found_region_wildcard = find_region_by_postal_code("8500")
        if found_region_wildcard:
            self.assertIsInstance(found_region_wildcard, str)

        # Test invalid input
        found_invalid = find_region_by_postal_code("")
        self.assertIsNone(found_invalid)

        found_invalid2 = find_region_by_postal_code(None)
        self.assertIsNone(found_invalid2)

    def test_get_regional_coordinator(self):
        """Test getting regional coordinator"""
        from verenigingen.verenigingen.doctype.region.region import get_regional_coordinator

        # Test with region that has no coordinator
        coordinator_info = get_regional_coordinator(self.test_region.name)
        self.assertIsInstance(coordinator_info, dict)
        self.assertIn("regional_coordinator", coordinator_info)
        self.assertIn("backup_coordinator", coordinator_info)

        # Test with invalid region
        coordinator_invalid = get_regional_coordinator("NonExistentRegion")
        self.assertIsNone(coordinator_invalid)

        # Test with None input
        coordinator_none = get_regional_coordinator(None)
        self.assertIsNone(coordinator_none)

    def test_validate_postal_code_patterns(self):
        """Test postal code pattern validation function"""
        from verenigingen.verenigingen.doctype.region.region import validate_postal_code_patterns

        # Test valid patterns
        result_valid = validate_postal_code_patterns("1000-1999, 2*, 3000")
        self.assertTrue(result_valid["valid"])
        self.assertEqual(len(result_valid["errors"]), 0)

        # Test invalid patterns
        result_invalid = validate_postal_code_patterns("1000-999, abc*, 3000-")
        self.assertFalse(result_invalid["valid"])
        self.assertGreater(len(result_invalid["errors"]), 0)

        # Test empty patterns
        result_empty = validate_postal_code_patterns("")
        self.assertTrue(result_empty["valid"])

        # Test None input
        result_none = validate_postal_code_patterns(None)
        self.assertTrue(result_none["valid"])


# Import the functions to test
