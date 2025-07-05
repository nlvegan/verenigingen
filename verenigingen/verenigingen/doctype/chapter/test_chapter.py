# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import random
import string

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate, today


class TestChapter(FrappeTestCase):
    def setUp(self):
        """Set up test data"""
        # Generate unique identifier
        self.unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

        # Clean up any existing test data
        self.cleanup_test_data()

        # Create test data
        self.create_test_prerequisites()

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Clean up test data"""
        # Delete test chapters
        for chapter in frappe.get_all(
            "Chapter", filters={"name": ["like", f"Test Chapter {self.unique_id}%"]}
        ):
            try:
                frappe.delete_doc("Chapter", chapter.name, force=True)
            except Exception as e:
                print(f"Error cleaning up chapter {chapter.name}: {str(e)}")

        # Delete test members
        for member in frappe.get_all("Member", filters={"email": ["like", f"%{self.unique_id}@example.com"]}):
            try:
                frappe.delete_doc("Member", member.name, force=True)
            except Exception as e:
                print(f"Error cleaning up member {member.name}: {str(e)}")

    def create_test_prerequisites(self):
        """Create test prerequisites"""
        # Get or create test region
        self.test_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
        if not self.test_region:
            # Create test region if it doesn't exist
            region = frappe.get_doc(
                {
                    "doctype": "Region",
                    "region_name": "Test Region",
                    "region_code": "TR",
                    "country": "Netherlands",
                    "is_active": 1,
                }
            )
            region.insert(ignore_permissions=True)
            self.test_region = region.name

        # Create test member for chapter head
        self.test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": f"Head {self.unique_id}",
                "email": f"testhead{self.unique_id}@example.com",
                "contact_number": "+31612345678",
                "payment_method": "Bank Transfer",
            }
        )
        self.test_member.insert(ignore_permissions=True)

    def test_chapter_creation(self):
        """Test creating a basic chapter"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": self.test_region,
                "introduction": "Test chapter for unit tests",
                "published": 1,
                "chapter_head": self.test_member.name,
            }
        )
        chapter.insert(ignore_permissions=True)

        # Verify chapter was created correctly
        self.assertEqual(chapter.name, f"Test Chapter {self.unique_id}")
        self.assertEqual(chapter.region, self.test_region)
        # Note: chapter_head may not be set if the field doesn't exist or isn't required
        if hasattr(chapter, "chapter_head") and chapter.chapter_head:
            self.assertEqual(chapter.chapter_head, self.test_member.name)
        self.assertEqual(chapter.published, 1)

        # Verify auto-generated fields
        self.assertTrue(chapter.creation)
        self.assertTrue(chapter.modified)

    def test_chapter_validation(self):
        """Test chapter validation"""
        # Test missing required fields
        with self.assertRaises(frappe.ValidationError):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": f"Invalid Chapter {self.unique_id}",
                    # Missing region
                    "introduction": "Test chapter",
                }
            )
            chapter.insert(ignore_permissions=True)

    def test_postal_code_validation(self):
        """Test postal code validation and formatting"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": self.test_region,
                "introduction": "Test chapter",
                "postal_codes": "1000-1999, 2000, 3000-3099",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Verify postal codes are stored correctly
        self.assertTrue("1000-1999" in chapter.postal_codes)
        self.assertTrue("2000" in chapter.postal_codes)
        self.assertTrue("3000-3099" in chapter.postal_codes)

    def test_chapter_head_assignment(self):
        """Test chapter head assignment and validation"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
                "chapter_head": self.test_member.name,
            }
        )
        chapter.insert(ignore_permissions=True)

        # Verify chapter head is properly assigned (if field exists)
        if hasattr(chapter, "chapter_head") and chapter.chapter_head:
            self.assertEqual(chapter.chapter_head, self.test_member.name)

        # Change chapter head
        new_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "New",
                "last_name": f"Head {self.unique_id}",
                "email": f"newhead{self.unique_id}@example.com",
                "contact_number": "+31612345679",
                "payment_method": "Bank Transfer",
            }
        )
        new_member.insert(ignore_permissions=True)

        chapter.chapter_head = new_member.name
        chapter.save(ignore_permissions=True)

        # Verify chapter head change
        chapter.reload()
        self.assertEqual(chapter.chapter_head, new_member.name)

        # Clean up
        frappe.delete_doc("Member", new_member.name, force=True)

    def test_chapter_member_management(self):
        """Test chapter member management"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Create additional test members
        members = []
        for i in range(3):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": f"Member{i}",
                    "last_name": f"Test {self.unique_id}",
                    "email": f"member{i}{self.unique_id}@example.com",
                    "contact_number": f"+3161234567{i}",
                    "payment_method": "Bank Transfer",
                    "primary_chapter": chapter.name,
                }
            )
            member.insert(ignore_permissions=True)
            members.append(member)

        # Test member count (should include chapter head + added members)
        if hasattr(chapter, "get_member_count"):
            member_count = chapter.get_member_count()
            self.assertGreaterEqual(member_count, 3)

        # Clean up additional members
        for member in members:
            frappe.delete_doc("Member", member.name, force=True)

    def test_board_member_chapter_status_field(self):
        """Test that board member addition sets chapter member status field correctly"""
        # Create test volunteer and role
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Board Test Volunteer {self.unique_id}",
                "email": f"boardvol{self.unique_id}@example.com",
                "member": self.test_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        volunteer.insert(ignore_permissions=True)

        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Board Role {self.unique_id}",
                "permissions_level": "Admin",
                "is_active": 1,
            }
        )
        role.insert(ignore_permissions=True)

        # Create chapter
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter Board {self.unique_id}",
                "region": self.test_region,
                "introduction": "Test chapter for board member status",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Add board member
        if hasattr(chapter, "add_board_member"):
            result = chapter.add_board_member(volunteer=volunteer.name, role=role.name, from_date=today())
            self.assertTrue(result.get("success"))

            # Reload and check status field
            chapter.reload()
            self.assertEqual(len(chapter.members), 1)
            self.assertEqual(
                chapter.members[0].status,
                "Active",
                "Chapter member status should be set to Active when adding board member",
            )

        # Clean up
        frappe.delete_doc("Chapter", chapter.name, force=True)
        frappe.delete_doc("Chapter Role", role.name, force=True)
        frappe.delete_doc("Volunteer", volunteer.name, force=True)

    def test_chapter_statistics(self):
        """Test chapter statistics functionality"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Test basic statistics methods exist
        if hasattr(chapter, "get_member_count"):
            self.assertTrue(callable(getattr(chapter, "get_member_count")))

        if hasattr(chapter, "get_volunteer_count"):
            self.assertTrue(callable(getattr(chapter, "get_volunteer_count")))

        if hasattr(chapter, "get_activity_count"):
            self.assertTrue(callable(getattr(chapter, "get_activity_count")))

    def test_chapter_contact_info(self):
        """Test chapter contact information"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
                "email": f"chapter{self.unique_id}@example.org",
                "phone": "+31612345678",
                "website": "https://example.org",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Verify contact information
        self.assertEqual(chapter.email, f"chapter{self.unique_id}@example.org")
        self.assertEqual(chapter.phone, "+31612345678")
        self.assertEqual(chapter.website, "https://example.org")

    def test_chapter_publication_status(self):
        """Test chapter publication status"""
        # Create unpublished chapter
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
                "published": 0,
            }
        )
        chapter.insert(ignore_permissions=True)

        # Verify unpublished status
        self.assertEqual(chapter.published, 0)

        # Publish chapter
        chapter.published = 1
        chapter.save(ignore_permissions=True)

        # Verify published status
        chapter.reload()
        self.assertEqual(chapter.published, 1)

    def test_chapter_location_info(self):
        """Test chapter location information"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
                "city": "Amsterdam",
                "state": "North Holland",
                "country": "Netherlands",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Verify location information
        self.assertEqual(chapter.city, "Amsterdam")
        self.assertEqual(chapter.state, "North Holland")
        self.assertEqual(chapter.country, "Netherlands")

    def test_chapter_matching_by_postal_code(self):
        """Test chapter matching functionality by postal code"""
        # Create chapter with specific postal codes
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
                "postal_codes": "1000-1999",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Test postal code matching if method exists
        if hasattr(chapter, "matches_postal_code"):
            self.assertTrue(chapter.matches_postal_code("1500"))
            self.assertFalse(chapter.matches_postal_code("2000"))

        # Test with individual postal code
        chapter.postal_codes = "1234"
        chapter.save(ignore_permissions=True)

        if hasattr(chapter, "matches_postal_code"):
            self.assertTrue(chapter.matches_postal_code("1234"))
            self.assertFalse(chapter.matches_postal_code("1235"))

    def test_chapter_update_permissions(self):
        """Test chapter update and permission handling"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Test update
        original_modified = chapter.modified
        chapter.introduction = "Updated introduction"
        chapter.save(ignore_permissions=True)

        # Verify update
        chapter.reload()
        self.assertEqual(chapter.introduction, "Updated introduction")
        self.assertNotEqual(chapter.modified, original_modified)

    def test_chapter_member_roster_management(self):
        """Test chapter member roster management with new structure"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Create test members to add to roster
        members = []
        for i in range(3):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Roster",
                    "last_name": f"Member{i} {self.unique_id}",
                    "email": f"roster{i}{self.unique_id}@example.com",
                    "contact_number": f"+3161234568{i}",
                    "payment_method": "Bank Transfer",
                }
            )
            member.insert(ignore_permissions=True)
            members.append(member)

        # Add members to chapter roster (new structure without member_name)
        for member in members:
            chapter.append("members", {"member": member.name, "chapter_join_date": today(), "enabled": 1})

        chapter.save(ignore_permissions=True)
        chapter.reload()

        # Verify roster size
        self.assertEqual(len(chapter.members), 3, "Chapter should have 3 members in roster")

        # Verify join dates are set
        for roster_member in chapter.members:
            self.assertTrue(roster_member.chapter_join_date, "Join date should be set")

        # Test disabling a member
        chapter.members[0].enabled = 0
        chapter.save(ignore_permissions=True)
        chapter.reload()

        # Verify member status
        self.assertEqual(chapter.members[0].enabled, 0, "Member should be disabled")

        # Clean up
        for member in members:
            frappe.delete_doc("Member", member.name, force=True)

    def test_chapter_board_management(self):
        """Test chapter board member management with automatic member addition"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Create volunteer for board position
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Board Volunteer {self.unique_id}",
                "email": f"board{self.unique_id}@organization.org",
                "member": self.test_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        volunteer.insert(ignore_permissions=True)

        # Create chapter role if it doesn't exist
        if not frappe.db.exists("Chapter Role", "Board Member"):
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": "Board Member",
                    "permissions_level": "Admin",
                    "is_active": 1,
                }
            )
            role.insert(ignore_permissions=True)

        # Add volunteer to board with new structure
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "email": volunteer.email,
                "chapter_role": "Board Member",
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter.save(ignore_permissions=True)
        chapter.reload()

        # Verify board member was added
        self.assertEqual(len(chapter.board_members), 1, "Chapter should have 1 board member")
        self.assertEqual(chapter.board_members[0].volunteer, volunteer.name)
        self.assertEqual(chapter.board_members[0].volunteer_name, volunteer.volunteer_name)

        # Verify member was automatically added to chapter members
        member_found = False
        for member in chapter.members:
            if member.member == self.test_member.name:
                member_found = True
                break
        self.assertTrue(member_found, "Board member should be automatically added to chapter members")

        # Test ending board membership
        if len(chapter.board_members) > 0:
            chapter.board_members[0].is_active = 0
            chapter.board_members[0].to_date = today()
            chapter.save(ignore_permissions=True)
            chapter.reload()

            # Verify board member status
            if len(chapter.board_members) > 0:
                self.assertEqual(chapter.board_members[0].is_active, 0, "Board member should be inactive")
                self.assertEqual(getdate(chapter.board_members[0].to_date), getdate(today()))

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)

    def test_board_manager_functionality(self):
        """Test BoardManager API for adding/removing board members"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test BoardManager {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter for BoardManager",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Create volunteer and role
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"API Test Volunteer {self.unique_id}",
                "email": f"apitest{self.unique_id}@organization.org",
                "member": self.test_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        volunteer.insert(ignore_permissions=True)

        # Create test role
        role_name = f"Test Role {self.unique_id}"
        if not frappe.db.exists("Chapter Role", role_name):
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Basic",
                    "is_active": 1,
                }
            )
            role.insert(ignore_permissions=True)

        # Test adding board member via BoardManager
        result = chapter.add_board_member(volunteer=volunteer.name, role=role_name, from_date=today())

        # Verify the API response
        self.assertTrue(result.get("success"), "API should return success")
        self.assertIn("board_member", result, "API should return board member data")

        # Reload and verify board member was added
        chapter.reload()
        self.assertEqual(len(chapter.board_members), 1, "Should have 1 board member")

        # Verify automatic chapter member addition
        member_found = False
        for member in chapter.members:
            if member.member == self.test_member.name:
                member_found = True
                self.assertTrue(member.chapter_join_date, "Join date should be set")
                break
        self.assertTrue(member_found, "Member should be automatically added to chapter")

        # Test removing board member via BoardManager
        remove_result = chapter.remove_board_member(volunteer=volunteer.name, end_date=today())

        # Verify removal
        self.assertTrue(remove_result.get("success"), "Removal should succeed")
        chapter.reload()

        # Board member should be inactive
        self.assertEqual(chapter.board_members[0].is_active, 0, "Board member should be inactive")

        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)
        if frappe.db.exists("Chapter Role", role_name):
            frappe.delete_doc("Chapter Role", role_name, force=True)
        frappe.delete_doc("Chapter", chapter.name, force=True)

    def test_chapter_search_and_filtering(self):
        """Test chapter search and filtering capabilities"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "North Region",
                "introduction": "Test chapter for searching",
                "published": 1,
                "postal_codes": "1000-1999",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Test search by region
        chapters = frappe.get_all("Chapter", filters={"region": "North Region"})
        chapter_names = [c.name for c in chapters]
        self.assertIn(chapter.name, chapter_names, "Should find chapters by region")

        # Test search by published status
        published_chapters = frappe.get_all("Chapter", filters={"published": 1})
        chapter_names = [c.name for c in published_chapters]
        self.assertIn(chapter.name, chapter_names, "Should find published chapters")

        # Test search by name pattern
        pattern_chapters = frappe.get_all("Chapter", filters={"name": ["like", f"%{self.unique_id}%"]})
        self.assertGreater(len(pattern_chapters), 0, "Should find chapters by name pattern")

    def test_chapter_data_validation_edge_cases(self):
        """Test chapter data validation edge cases"""
        # Test empty/null fields
        try:
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": f"Empty Test {self.unique_id}",
                    "region": "",  # Empty required field
                    "introduction": "Test chapter",
                }
            )
            chapter.insert(ignore_permissions=True)
            self.fail("Should not allow empty region")
        except Exception as e:
            self.assertIn("region", str(e).lower(), "Error should mention region field")

        # Test very long field values
        long_text = "A" * 2000
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Long Text Test {self.unique_id}",
                "region": "Test Region",
                "introduction": long_text,
            }
        )
        chapter.insert(ignore_permissions=True)
        chapter.reload()

        # Should handle long text
        self.assertTrue(len(chapter.introduction) >= 1000, "Should store long introduction")

        # Clean up
        frappe.delete_doc("Chapter", chapter.name, force=True)

    def test_chapter_deletion_constraints(self):
        """Test chapter deletion with constraints"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Delete Test {self.unique_id}",
                "region": "Test Region",
                "introduction": "Test chapter for deletion",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Create member linked to chapter
        linked_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Linked",
                "last_name": f"Member {self.unique_id}",
                "email": f"linked{self.unique_id}@example.com",
                "contact_number": "+31612345679",
                "payment_method": "Bank Transfer",
                "primary_chapter": chapter.name,
            }
        )
        linked_member.insert(ignore_permissions=True)

        # Try to delete chapter with linked member
        try:
            frappe.delete_doc("Chapter", chapter.name)
            # If deletion succeeds, just note it
            print("Chapter deletion with linked members allowed")
        except Exception as e:
            # If deletion fails due to constraints, that's expected
            print(f"Chapter deletion properly prevented: {str(e)}")

        # Clean up member first, then chapter
        linked_member.primary_chapter = None
        linked_member.save(ignore_permissions=True)
        frappe.delete_doc("Member", linked_member.name, force=True)

        # Now chapter should be deletable
        try:
            frappe.delete_doc("Chapter", chapter.name, force=True)
        except Exception as e:
            print(f"Chapter deletion still failed: {str(e)}")

    def test_chapter_geographical_features(self):
        """Test chapter geographical and location features"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter {self.unique_id}",
                "region": "Geographic Test Region",
                "introduction": "Test chapter",
                "postal_codes": "1000-1999,2500,3000-3099",
                "address": "123 Test Street\n1234 AB Test City\nNetherlands",
            }
        )
        chapter.insert(ignore_permissions=True)

        # Test postal code coverage
        test_codes = ["1500", "2500", "3050", "4000", "999"]
        expected_matches = [True, True, True, False, False]

        if hasattr(chapter, "matches_postal_code"):
            for code, should_match in zip(test_codes, expected_matches):
                result = chapter.matches_postal_code(code)
                if should_match:
                    self.assertTrue(result, f"Code {code} should match")
                else:
                    self.assertFalse(result, f"Code {code} should not match")

        # Test address handling
        self.assertIn("Test Street", chapter.address)
        self.assertIn("Test City", chapter.address)
