# verenigingen/verenigingen/tests/test_chapter_matching.py
import unittest

import frappe

from verenigingen.tests.test_base import VereningingenTestCase


class TestChapterMatching(VereningingenTestCase):
    def setUp(self):
        # Create test chapters with different postal code patterns
        self.create_test_chapters()

        # Create a test member
        self.test_member = self.create_test_member()

        # Create test address
        self.test_address = self.create_test_address()

    def tearDown(self):
        # Clean up test data
        for chapter in self.test_chapters:
            try:
                frappe.delete_doc("Chapter", chapter)
            except Exception:
                pass

        try:
            frappe.delete_doc("Member", self.test_member.name)
        except Exception:
            pass

        try:
            frappe.delete_doc("Address", self.test_address.name)
        except Exception:
            pass

    def create_test_chapters(self):
        """Create test chapters with different postal code patterns"""
        self.test_chapters = []

        # Amsterdam chapter (1000-1099)
        amsterdam = self.create_test_chapter("Test Amsterdam", "Noord-Holland", "1000-1099")
        self.test_chapters.append(amsterdam.name)

        # Rotterdam chapter (3000-3099)
        rotterdam = self.create_test_chapter("Test Rotterdam", "Zuid-Holland", "3000-3099")
        self.test_chapters.append(rotterdam.name)

        # Utrecht chapter (specific postal code)
        utrecht = self.create_test_chapter("Test Utrecht", "Utrecht", "3500")
        self.test_chapters.append(utrecht.name)

        # Eindhoven chapter (wildcard pattern)
        eindhoven = self.create_test_chapter("Test Eindhoven", "Noord-Brabant", "56*")
        self.test_chapters.append(eindhoven.name)

    def create_test_chapter(self, name, region, postal_codes=None):
        """Create a test chapter"""
        chapter_data = {
            "doctype": "Chapter",
            "name": name,
            "region": region,
            "introduction": f"Test chapter for {name}",
            "published": 1}

        if postal_codes:
            chapter_data["postal_codes"] = postal_codes

        if frappe.db.exists("Chapter", name):
            return frappe.get_doc("Chapter", name)

        chapter = frappe.get_doc(chapter_data)
        chapter.insert(ignore_permissions=True)
        return chapter

    def create_test_address(self):
        """Create a test address"""
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Test Address for {self.test_member.name}",
                "address_type": "Personal",
                "address_line1": "Test Street 123",
                "city": "Amsterdam",
                "state": "Noord-Holland",
                "country": "Netherlands",
                "pincode": "1001",  # Should match Amsterdam chapter
                "links": [{"link_doctype": "Member", "link_name": self.test_member.name}]}
        )
        address.insert(ignore_permissions=True)
        return address

    def test_postal_code_edge_cases(self):
        """Test edge cases in postal code matching"""
        # Create a chapter with range 1000-1099
        range_chapter = self.create_test_chapter("Range Test", "Test Region", "1000-1099")

        # Test exact boundaries
        self.assertTrue(range_chapter.matches_postal_code("1000"), "Lower boundary should match")
        self.assertTrue(range_chapter.matches_postal_code("1099"), "Upper boundary should match")
        self.assertFalse(range_chapter.matches_postal_code("999"), "Just below range shouldn't match")
        self.assertFalse(range_chapter.matches_postal_code("1100"), "Just above range shouldn't match")

        # Test wildcard patterns
        wildcard_chapter = self.create_test_chapter("Wildcard Test", "Test Region", "5*")
        self.assertTrue(wildcard_chapter.matches_postal_code("5"), "Single digit should match")
        self.assertTrue(wildcard_chapter.matches_postal_code("50"), "Double digit should match")
        self.assertTrue(wildcard_chapter.matches_postal_code("5999"), "Four-digit should match")
        self.assertFalse(wildcard_chapter.matches_postal_code("65"), "Non-matching prefix shouldn't match")

        # Test multiple patterns
        multi_pattern_chapter = self.create_test_chapter(
            "Multi Pattern", "Test Region", "2500, 3000-3100, 4*"
        )
        self.assertTrue(multi_pattern_chapter.matches_postal_code("2500"), "Exact match should work")
        self.assertTrue(multi_pattern_chapter.matches_postal_code("3050"), "Range match should work")
        self.assertTrue(multi_pattern_chapter.matches_postal_code("4123"), "Wildcard match should work")
        self.assertFalse(
            multi_pattern_chapter.matches_postal_code("2600"), "Non-matching code shouldn't match"
        )

    def test_no_chapter_matches(self):
        """Test when no chapters match the member's location"""
        # Create address with postal code that doesn't match any chapter
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": "No Match Address",
                "address_type": "Personal",
                "address_line1": "No Match Street 123",
                "city": "No Match City",
                "state": "No Match Region",
                "country": "Netherlands",
                "pincode": "9999",  # Doesn't match any chapter
                "links": [{"link_doctype": "Member", "link_name": self.test_member.name}]}
        )
        address.insert(ignore_permissions=True)

        # Link to test member
        self.test_member.primary_address = address.name
        self.test_member.save()

        # Call the suggestion function
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code=address.pincode,
            state=address.state,
            city=address.city,
        )

        # Should not have matched by postal code
        self.assertFalse(result["matches_by_postal"])

        # Should not have matched by region (assuming no chapter has this region)
        self.assertFalse(result["matches_by_region"])

        # Should not have matched by city (assuming no chapter has this city)
        self.assertFalse(result["matches_by_city"])

        # But should still return all chapters
        self.assertTrue(result["all_chapters"])

    def test_partial_location_match(self):
        """Test matching with partial location data"""
        # Create a chapter with a specific region
        self.create_test_chapter("Region Test", "Test Region")

        # Create address that matches region but not postal code
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": "Region Match Address",
                "address_type": "Personal",
                "address_line1": "Region Match Street 123",
                "city": "Some City",
                "state": "Test Region",  # Matches the chapter
                "country": "Netherlands",
                "pincode": "9999",  # Doesn't match any chapter
                "links": [{"link_doctype": "Member", "link_name": self.test_member.name}]}
        )
        address.insert(ignore_permissions=True)

        # Link to test member
        self.test_member.primary_address = address.name
        self.test_member.save()

        # Call the suggestion function
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code=address.pincode,
            state=address.state,
            city=address.city,
        )

        # Should not have matched by postal code
        self.assertFalse(result["matches_by_postal"])

        # Should have matched by region
        self.assertTrue(result["matches_by_region"])
        self.assertEqual(result["matches_by_region"][0].name, "Region Test")

    def test_postal_code_matching(self):
        """Test matching chapters based on postal code"""
        # Test matching by postal code range
        amsterdam_chapter = frappe.get_doc("Chapter", "Test Amsterdam")

        # Should match Amsterdam chapter
        self.assertTrue(amsterdam_chapter.matches_postal_code("1001"))
        self.assertTrue(amsterdam_chapter.matches_postal_code("1099"))
        self.assertFalse(amsterdam_chapter.matches_postal_code("1100"))

        # Test matching by exact postal code
        utrecht_chapter = frappe.get_doc("Chapter", "Test Utrecht")
        self.assertTrue(utrecht_chapter.matches_postal_code("3500"))
        self.assertFalse(utrecht_chapter.matches_postal_code("3501"))

        # Test matching by wildcard pattern
        eindhoven_chapter = frappe.get_doc("Chapter", "Test Eindhoven")
        self.assertTrue(eindhoven_chapter.matches_postal_code("5600"))
        self.assertTrue(eindhoven_chapter.matches_postal_code("5699"))
        self.assertFalse(eindhoven_chapter.matches_postal_code("4600"))

    def test_suggest_chapter_for_member(self):
        """Test suggesting chapters based on member address"""
        # Link the test address to the member
        self.test_member.primary_address = self.test_address.name
        self.test_member.save()

        # Call the suggestion function
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code=self.test_address.pincode,
            state=self.test_address.state,
            city=self.test_address.city,
        )

        # Should have matched Amsterdam chapter by postal code
        self.assertTrue(result["matches_by_postal"])
        self.assertEqual(result["matches_by_postal"][0].name, "Test Amsterdam")

        # Test with different postal code
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code="3500",  # Utrecht
            state=self.test_address.state,
            city=self.test_address.city,
        )

        # Should have matched Utrecht chapter by postal code
        self.assertTrue(result["matches_by_postal"])
        self.assertEqual(result["matches_by_postal"][0].name, "Test Utrecht")

        # Test matching by region only
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code="9999",  # No match
            state="Noord-Holland",  # Amsterdam
            city="Unknown",
        )

        # Should have matched Amsterdam chapter by region
        self.assertFalse(result["matches_by_postal"])
        self.assertTrue(result["matches_by_region"])
        self.assertEqual(result["matches_by_region"][0].name, "Test Amsterdam")

        # Test matching by city only
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code=None,
            state=None,
            city="Amsterdam",
        )

        # Should have matched Amsterdam chapter by city
        self.assertFalse(result["matches_by_postal"])
        self.assertFalse(result["matches_by_region"])
        self.assertTrue(result["matches_by_city"])
        self.assertEqual(result["matches_by_city"][0].name, "Test Amsterdam")


if __name__ == "__main__":
    unittest.main()
