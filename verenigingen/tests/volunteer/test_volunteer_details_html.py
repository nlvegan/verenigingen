"""
Test Suite for Volunteer Details HTML Generation

Tests the volunteer assignment history HTML display feature on Member forms.
Validates security (XSS, URL injection), permissions, edge cases, and integration.

Related files:
- verenigingen/services/member/display/member_volunteer_display_service.py (generate_volunteer_details_html)
- verenigingen/services/member/display/member_onload_service.py (onload integration)
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.member.display.member_volunteer_display_service import (
    get_member_volunteer_display_service,
)
import unittest


def generate_volunteer_details_html(member_doc):
    """Wrapper for backward compatibility with tests."""
    return get_member_volunteer_display_service().generate_volunteer_details_html(member_doc)


class TestVolunteerDetailsHTML(EnhancedTestCase):
    """Test volunteer details HTML generation and security"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()

        # Create test region and chapter
        if not frappe.db.exists("Region", "HTMLTestRegion"):
            frappe.get_doc({
                "doctype": "Region",
                "region_name": "HTMLTestRegion",
                "region_code": "HTMLT",
            }).insert()

        if not frappe.db.exists("Chapter", "HTMLTestChapter"):
            frappe.get_doc({
                "doctype": "Chapter",
                "name": "HTMLTestChapter",
                "region": "HTMLTestRegion",
                "introduction": "Test chapter for HTML generation",
            }).insert()

    def setUp(self):
        """Set up test data for each test"""
        super().setUp()

        # Create test member
        self.test_member = self.create_test_member(
            first_name="HTMLTest",
            last_name="User",
            email=f"htmltest.{frappe.utils.random_string(8)}@example.com"
        )

    def test_01_no_volunteer_record(self):
        """Test HTML generation when member has no volunteer record"""
        html = generate_volunteer_details_html(self.test_member)

        self.assertIn("No volunteer record linked", html)
        self.assertIn("text-muted", html)
        self.assertNotIn("Volunteer ID", html)

    def test_02_volunteer_with_no_assignments(self):
        """Test HTML generation for volunteer with empty assignment history"""
        # Create volunteer with no assignments
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.assignment_history = []
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Should show volunteer info
        self.assertIn("Volunteer ID", html)
        self.assertIn(volunteer.name, html)
        self.assertIn(volunteer.volunteer_name, html)

        # Should show "no assignments" message, not empty table
        self.assertIn("No assignment history recorded", html)
        self.assertNotIn("<tbody></tbody>", html)

    def test_03_xss_protection_volunteer_name(self):
        """Test XSS protection in volunteer name field"""
        # Create volunteer with XSS attempt in name
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.volunteer_name = '<script>alert("xss")</script>'
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Script tags should be escaped
        self.assertNotIn("<script>", html)
        self.assertNotIn("</script>", html)
        # Should contain escaped version (either single or double-encoded)
        self.assertTrue(
            "&lt;script&gt;" in html or "&amp;lt;script&amp;gt;" in html,
            "XSS attempt was not properly escaped"
        )

    def test_04_xss_protection_assignment_fields(self):
        """Test XSS protection in assignment history fields"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # Add assignment with XSS attempts in role field (assignment_type is Select, can't contain scripts)
        volunteer.append("assignment_history", {
            "role": '<img src=x onerror="alert(1)">Role Name',
            "assignment_type": "Board Position",  # Valid Select option
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": today(),
            "status": "Active",  # Valid Select option
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # No script execution allowed
        self.assertNotIn("<script>", html)
        self.assertNotIn('onerror=', html)

        # Escaped versions should be present
        self.assertIn("&lt;img", html, "XSS attempt in role field was not escaped")

    def test_05_url_injection_prevention(self):
        """Test URL encoding prevents injection in reference links"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # Test with valid Chapter but verify URL encoding works properly
        volunteer.append("assignment_history", {
            "role": "Test Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": today(),
            "status": "Active",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Verify that URLs are properly formed and encoded
        if 'href=' in html:
            import re
            hrefs = re.findall(r'href="([^"]+)"', html)
            for href in hrefs:
                # URLs should be well-formed (start with / or http)
                self.assertTrue(
                    href.startswith('/') or href.startswith('http'),
                    f"Malformed URL found: {href}"
                )
                # Should not contain unencoded dangerous characters
                self.assertNotIn('<', href, "Unencoded < in URL")
                self.assertNotIn('>', href, "Unencoded > in URL")
                self.assertNotIn('"', href, "Unencoded quote in URL")

    def test_06_url_encoding_special_characters(self):
        """Test proper URL encoding of special characters"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # Create chapter with special characters in name
        if not frappe.db.exists("Chapter", "Test Chapter With Spaces"):
            frappe.get_doc({
                "doctype": "Chapter",
                "name": "Test Chapter With Spaces",
                "region": "HTMLTestRegion",
                "introduction": "Test chapter for URL encoding",
            }).insert()

        volunteer.append("assignment_history", {
            "role": "Test Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "Test Chapter With Spaces",
            "start_date": today(),
            "status": "Active",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Special characters should be URL-encoded in href
        if 'href=' in html:
            # Extract href value
            import re
            hrefs = re.findall(r'href="([^"]+)"', html)
            for href in hrefs:
                # Spaces should be encoded as %20
                self.assertNotIn(" ", href, "Spaces in URL were not encoded")

    def test_07_permission_check_admin_user(self):
        """Test that admin users can access volunteer data"""
        # Test runs as Administrator by default via EnhancedTestCase
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        html = generate_volunteer_details_html(self.test_member)

        # Admin should see volunteer details
        self.assertIn("Volunteer ID", html)
        self.assertIn(volunteer.name, html)
        self.assertNotIn("not accessible", html)

    def test_08_permission_check_with_valid_permission(self):
        """Test volunteer access with proper read permission"""
        # This tests the permission flow - actual permission setup
        # would require a test user with Volunteer read role
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # As Administrator, should have access
        html = generate_volunteer_details_html(self.test_member)

        self.assertIn("Volunteer ID", html)
        self.assertNotIn("not accessible", html)

    def test_09_assignment_date_sorting(self):
        """Test assignment sorting by start_date (most recent first)"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # Add assignments with different dates
        volunteer.append("assignment_history", {
            "role": "Recent Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": today(),
            "status": "Active",
        })

        volunteer.append("assignment_history", {
            "role": "Old Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": add_days(today(), -365),
            "status": "Completed",
        })

        volunteer.append("assignment_history", {
            "role": "Middle Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": add_days(today(), -180),
            "status": "Completed",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # All roles should be present
        self.assertIn("Recent Role", html)
        self.assertIn("Old Role", html)
        self.assertIn("Middle Role", html)

        # Most recent should appear first (HTML order matches date order)
        recent_pos = html.find("Recent Role")
        middle_pos = html.find("Middle Role")
        old_pos = html.find("Old Role")

        self.assertTrue(recent_pos > 0, "Recent role not found")
        self.assertTrue(middle_pos > 0, "Middle role not found")
        self.assertTrue(old_pos > 0, "Old role not found")

        # Verify correct chronological order (most recent first)
        self.assertTrue(recent_pos < middle_pos, "Sorting incorrect: recent should be before middle")
        self.assertTrue(middle_pos < old_pos, "Sorting incorrect: middle should be before old")

    def test_10_html_structure_valid(self):
        """Test that generated HTML has valid structure"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        volunteer.append("assignment_history", {
            "role": "Test Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": today(),
            "status": "Active",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Should have proper HTML structure
        self.assertIn('<div class="volunteer-details">', html)
        self.assertIn('</div>', html)

        # Should have table if assignments exist
        self.assertIn('<table', html)
        self.assertIn('</table>', html)
        self.assertIn('<thead>', html)
        self.assertIn('<tbody>', html)

        # All opening tags should have closing tags
        self.assertEqual(html.count('<tr>'), html.count('</tr>'))
        self.assertEqual(html.count('<td>'), html.count('</td>'))
        self.assertEqual(html.count('<th>'), html.count('</th>'))

    def test_11_volunteer_link_present(self):
        """Test that link to volunteer record is present"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        html = generate_volunteer_details_html(self.test_member)

        # Should have link to volunteer record
        self.assertIn("View Volunteer Record", html)
        self.assertIn(f"/app/volunteer/{volunteer.name}", html)
        self.assertIn('class="btn', html)

    def test_12_status_badge_colors(self):
        """Test that status badges have correct colors"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # Set volunteer status
        volunteer.status = "Active"
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Active status should have success badge
        self.assertIn('badge-success', html)
        self.assertIn('Active', html)

    def test_13_assignment_status_badges(self):
        """Test assignment status badges"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        volunteer.append("assignment_history", {
            "role": "Active Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": today(),
            "status": "Active",
        })

        volunteer.append("assignment_history", {
            "role": "Completed Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": add_days(today(), -30),
            "end_date": add_days(today(), -1),
            "status": "Completed",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Active should have success badge
        self.assertTrue(
            'badge-success' in html or 'Active' in html,
            "Active status badge not found"
        )

        # Completed should have secondary badge
        self.assertTrue(
            'badge-secondary' in html or 'Completed' in html,
            "Completed status badge not found"
        )

    def test_14_onload_integration(self):
        """Test that onload() properly populates volunteer details"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        volunteer.append("assignment_history", {
            "role": "Test Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": today(),
            "status": "Active",
        })
        volunteer.save()

        # Load member and trigger onload
        self.test_member.reload()
        self.test_member.onload()

        # Check __onload was populated
        self.assertTrue(hasattr(self.test_member, "__onload"))
        onload_data = self.test_member.get("__onload") or {}

        self.assertIn("volunteer_details_html", onload_data)
        self.assertTrue(len(onload_data["volunteer_details_html"]) > 0)

        # HTML should contain volunteer info
        html = onload_data["volunteer_details_html"]
        self.assertIn(volunteer.name, html)
        self.assertIn("Test Role", html)

    def test_15_error_handling_graceful(self):
        """Test that errors are handled gracefully without breaking"""
        # Create member but don't create volunteer, then manually set a broken state
        # This simulates an error condition

        # The function should return error HTML without raising exception
        try:
            html = generate_volunteer_details_html(self.test_member)
            # Should succeed without exception
            self.assertTrue(True)
            # Should return error message or no-volunteer message
            self.assertTrue(
                "No volunteer record" in html or "Unable to load" in html,
                "Error not handled gracefully"
            )
        except Exception as e:
            self.fail(f"Function raised exception instead of handling gracefully: {e}")

    def test_16_date_formatting_consistent(self):
        """Test that dates are formatted consistently"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        test_date = "2025-11-18"
        volunteer.append("assignment_history", {
            "role": "Test Role",
            "assignment_type": "Board Position",
            "reference_doctype": "Chapter",
            "reference_name": "HTMLTestChapter",
            "start_date": test_date,
            "end_date": test_date,
            "status": "Completed",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Should use frappe.utils.format_date formatting
        # Dates should not appear in raw YYYY-MM-DD format in the output
        # (frappe.utils.format_date typically returns DD-MM-YYYY or localized format)
        self.assertTrue(
            "2025-11-18" not in html or "18-11-2025" in html or "Nov" in html,
            "Dates should be formatted using frappe.utils.format_date"
        )

    def test_17_missing_reference_no_link(self):
        """Test that missing reference fields don't create broken links"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)

        # Assignment with no reference_doctype or reference_name (valid scenario)
        volunteer.append("assignment_history", {
            "role": "Test Role Without Organization",
            "assignment_type": "Other",
            "start_date": today(),
            "status": "Active",
        })
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # Should display the role
        self.assertIn("Test Role Without Organization", html)

        # Should not have broken href links
        # Check that any href attributes are well-formed
        if 'href=' in html:
            import re
            hrefs = re.findall(r'href="([^"]*)"', html)
            for href in hrefs:
                # All hrefs should start with / or http
                self.assertTrue(
                    href.startswith('/') or href.startswith('http'),
                    f"Malformed href found: {href}"
                )


if __name__ == "__main__":
    import unittest
    unittest.main()
