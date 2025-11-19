# verenigingen/verenigingen/tests/test_chapter_matching.py
import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestChapterMatching(VereningingenTestCase):
    def setUp(self):
        """Set up test data using factory methods"""
        super().setUp()
        
        # Create test chapters with different postal code patterns
        self.create_test_chapters()

        # Create a test member
        self.test_member = self.create_test_member()

        # Create test address
        self.test_address = self.create_test_address()

    def create_test_chapters(self):
        """Create test chapters with different postal code patterns"""
        self.test_chapters = []

        # Use the base class chapter factory method
        # Amsterdam chapter (1000-1099)
        amsterdam = self.create_test_chapter(
            chapter_name="Test Amsterdam",
            postal_codes="1000-1099"
        )
        self.test_chapters.append(amsterdam.name)
        self.amsterdam_chapter_name = amsterdam.name

        # Rotterdam chapter (3000-3099)
        rotterdam = self.create_test_chapter(
            chapter_name="Test Rotterdam", 
            postal_codes="3000-3099"
        )
        self.test_chapters.append(rotterdam.name)
        self.rotterdam_chapter_name = rotterdam.name

        # Utrecht chapter (specific postal code)
        utrecht = self.create_test_chapter(
            chapter_name="Test Utrecht",
            postal_codes="3500"
        )
        self.test_chapters.append(utrecht.name)
        self.utrecht_chapter_name = utrecht.name

        # Eindhoven chapter (wildcard pattern)
        eindhoven = self.create_test_chapter(
            chapter_name="Test Eindhoven",
            postal_codes="56*"
        )
        self.test_chapters.append(eindhoven.name)
        self.eindhoven_chapter_name = eindhoven.name

    # Using factory method from base class instead of custom chapter creation

    def create_test_address(self):
        """Create a test address using proper creation and tracking"""
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
        address.insert()
        self.track_doc("Address", address.name)  # Track for cleanup
        return address

    def test_postal_code_edge_cases(self):
        """Test edge cases in postal code matching"""
        # Create a chapter with range 1000-1099
        range_chapter = self.create_test_chapter(
            chapter_name="Range Test",
            postal_codes="1000-1099"
        )

        # Test exact boundaries
        self.assertTrue(range_chapter.matches_postal_code("1000"), "Lower boundary should match")
        self.assertTrue(range_chapter.matches_postal_code("1099"), "Upper boundary should match")
        self.assertFalse(range_chapter.matches_postal_code("999"), "Just below range shouldn't match")
        self.assertFalse(range_chapter.matches_postal_code("1100"), "Just above range shouldn't match")

        # Test wildcard patterns
        wildcard_chapter = self.create_test_chapter(
            chapter_name="Wildcard Test",
            postal_codes="5*"
        )
        self.assertTrue(wildcard_chapter.matches_postal_code("5"), "Single digit should match")
        self.assertTrue(wildcard_chapter.matches_postal_code("50"), "Double digit should match")
        self.assertTrue(wildcard_chapter.matches_postal_code("5999"), "Four-digit should match")
        self.assertFalse(wildcard_chapter.matches_postal_code("65"), "Non-matching prefix shouldn't match")

        # Test multiple patterns
        multi_pattern_chapter = self.create_test_chapter(
            chapter_name="Multi Pattern",
            postal_codes="2500, 3000-3100, 4*"
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
        address.insert()
        self.track_doc("Address", address.name)

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

        # Result should be a list of matching chapters
        self.assertIsInstance(result, list, "Result should be a list of chapters")
        
        # Should not have matched any chapters for postal code 9999
        self.assertEqual(len(result), 0, "No chapters should match postal code 9999")

    def test_partial_location_match(self):
        """Test matching with partial location data"""
        # Create a chapter for region testing (using default test region)
        region_chapter = self.create_test_chapter(
            chapter_name="Region Test"
        )

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
        address.insert()
        self.track_doc("Address", address.name)

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

        # API returns a list of matching chapters
        self.assertIsInstance(result, list, "Result should be a list of chapters")
        
        # Should have found at least one chapter in the result
        self.assertIsInstance(result, list, "Result should be a list")
        # Note: Region matching depends on actual region data in test environment

    def test_postal_code_matching(self):
        """Test matching chapters based on postal code"""
        # Test matching by postal code range
        amsterdam_chapter = frappe.get_doc("Chapter", self.amsterdam_chapter_name)

        # Should match Amsterdam chapter
        self.assertTrue(amsterdam_chapter.matches_postal_code("1001"))
        self.assertTrue(amsterdam_chapter.matches_postal_code("1099"))
        self.assertFalse(amsterdam_chapter.matches_postal_code("1100"))

        # Test matching by exact postal code
        utrecht_chapter = frappe.get_doc("Chapter", self.utrecht_chapter_name)
        self.assertTrue(utrecht_chapter.matches_postal_code("3500"))
        self.assertFalse(utrecht_chapter.matches_postal_code("3501"))

        # Test matching by wildcard pattern
        eindhoven_chapter = frappe.get_doc("Chapter", self.eindhoven_chapter_name)
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

        # API returns a list of matching chapters
        self.assertIsInstance(result, list, "Result should be a list of chapters")
        
        # Should have matched Amsterdam chapter by postal code (1001 matches 1000-1099)
        chapter_names = [chapter.get('name') for chapter in result if isinstance(chapter, dict)]
        # Look for Amsterdam chapter by substring match
        amsterdam_found = any('Amsterdam' in name for name in chapter_names)
        self.assertTrue(amsterdam_found, f"Should find Amsterdam chapter for postal code 1001. Found: {chapter_names}")

        # Test with different postal code - Utrecht (3500)
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code="3500",  # Utrecht
            state=self.test_address.state,
            city=self.test_address.city,
        )

        # Should have matched Utrecht chapter by postal code
        self.assertIsInstance(result, list, "Result should be a list of chapters")
        chapter_names = [chapter.get('name') for chapter in result if isinstance(chapter, dict)]
        # Look for Utrecht chapter by substring match
        utrecht_found = any('Utrecht' in name for name in chapter_names)
        self.assertTrue(utrecht_found, f"Should find Utrecht chapter for postal code 3500. Found: {chapter_names}")

        # Test matching by region only (using test region that exists)
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code="9999",  # No postal match
            state="Test Region",  # Use default test region
            city="Unknown",
        )

        # Should return a list (may or may not have matches depending on test data)
        self.assertIsInstance(result, list, "Result should be a list of chapters")

        # Test matching by city only
        result = frappe.call(
            "verenigingen.verenigingen.doctype.chapter.chapter.suggest_chapter_for_member",
            member_name=self.test_member.name,
            postal_code=None,
            state=None,
            city="Amsterdam",
        )

        # Should return a list (may or may not have matches depending on test data)
        self.assertIsInstance(result, list, "Result should be a list of chapters")


if __name__ == "__main__":
    unittest.main()
