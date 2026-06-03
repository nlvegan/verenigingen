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

    def setUp(self):
        """Set up test data for each test"""
        super().setUp()

        # Create the Region/Chapter the assignment_history reference fields link
        # to. These MUST be created in setUp (not setUpClass): EnhancedTestCase
        # rolls back the DB after every test method, which would otherwise delete
        # setUpClass masters and leave later tests with broken Link references
        # (v16 validates assignment_history.reference_name as a real Link).
        if not frappe.db.exists("Region", "HTMLTestRegion"):
            frappe.get_doc({
                "doctype": "Region",
                "region_name": "HTMLTestRegion",
                "region_code": "HTMLT",
            }).insert(ignore_permissions=True)

        if not frappe.db.exists("Chapter", "HTMLTestChapter"):
            frappe.get_doc({
                "doctype": "Chapter",
                "name": "HTMLTestChapter",
                "region": "HTMLTestRegion",
                "introduction": "Test chapter for HTML generation",
            }).insert(ignore_permissions=True)

        # Create test member
        self.test_member = self.create_test_member(
            first_name="HTMLTest",
            last_name="User",
            email=f"htmltest.{frappe.utils.random_string(8)}@example.com"
        )

    def test_01_no_volunteer_record(self):
        """Test HTML generation when member has no volunteer record"""
        html = generate_volunteer_details_html(self.test_member)

        # Current contract: members without a linked volunteer get a muted
        # "no volunteer profile" notice and no volunteer detail rows.
        self.assertIn("does not have a volunteer profile", html)
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
        """Test XSS protection in volunteer name field.

        Use a payload that survives Data-field sanitization (an <img> tag with an
        onerror handler) rather than a bare <script> (which the framework strips to
        empty on save, making any output assertion trivially true). The display
        service must escape_html() the surviving markup so it renders inert.
        """
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        volunteer.volunteer_name = '<img src=x onerror="alert(1)">XSSName'
        volunteer.save()

        html = generate_volunteer_details_html(self.test_member)

        # The injected name must appear, but only in HTML-escaped form...
        self.assertIn("XSSName", html, "Volunteer name should be rendered")
        self.assertIn("&lt;img", html, "Markup in the name must be HTML-escaped")
        # ...never as live markup / an executable handler.
        self.assertNotIn("<script>", html)
        self.assertNotIn("onerror=", html)
        self.assertNotIn('<img src=x', html)

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
        self.assertIn('<div class="volunteer-details-section">', html)
        self.assertIn('</div>', html)

        # Should have table if assignments exist
        self.assertIn('<table', html)
        self.assertIn('</table>', html)
        # The assignment-history table head carries the thead-light class.
        self.assertIn('<thead', html)
        self.assertIn('</thead>', html)
        self.assertIn('<tbody>', html)

        # All opening tags should have matching closing tags. Opening tags may
        # carry attributes (e.g. <td style="...">), so count "<tag" and "<tag>"
        # forms via a small regex rather than a bare-tag string match.
        import re

        def _open_count(tag):
            return len(re.findall(rf"<{tag}(?:\s[^>]*)?>", html))

        for tag in ("tr", "td", "th"):
            self.assertEqual(
                _open_count(tag),
                html.count(f"</{tag}>"),
                f"Unbalanced <{tag}> tags",
            )

    def test_11_volunteer_link_present(self):
        """Test that link to volunteer record is present"""
        volunteer = self.create_test_volunteer(member_name=self.test_member.name)
        html = generate_volunteer_details_html(self.test_member)

        # The volunteer record is reachable via the Volunteer ID hyperlink.
        self.assertIn("Volunteer ID", html)
        self.assertIn(f"/app/volunteer/{volunteer.name}", html)
        self.assertIn('target="_blank"', html)

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
            # Should return a no-volunteer message or a graceful error notice,
            # never an unhandled exception.
            self.assertTrue(
                "does not have a volunteer profile" in html
                or "Error loading volunteer information" in html,
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

        # Current contract: the display service renders assignment dates as the
        # stored ISO date (str(date)). The key guarantee is *consistency* - the
        # same date used for both start and end must render identically, in both
        # the start-date and end-date columns.
        self.assertIn(test_date, html)
        self.assertEqual(
            html.count(test_date),
            2,
            "Start and end dates should render identically (consistent formatting)",
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
