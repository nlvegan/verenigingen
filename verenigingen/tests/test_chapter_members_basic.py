"""Basic chapter member tests without assignment history"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today
from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterMemberBasic(EnhancedTestCase):
    """Basic chapter member tests"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Clean up any existing test chapters first
        self.cleanup_test_chapters()
        
        # Create minimal test data
        self.member1 = self.create_test_member(
            first_name="BasicTest1",
            last_name="Member"
        )
        
        # Create a fresh test chapter
        self.chapter = self.factory.ensure_test_chapter("Basic Test Chapter", {
            "short_name": "BTC",
            "published": 1
        })
        
        # Ensure chapter starts with no members
        if self.chapter.members:
            self.chapter.members = []
            self.chapter.save()
    
    def cleanup_test_chapters(self):
        """Clean up any existing test chapters and their members"""
        # Delete test chapters directly via SQL to avoid validation issues
        frappe.db.sql("""
            DELETE FROM `tabChapter` 
            WHERE name LIKE 'Basic Test Chapter%'
        """)
        
        # Also clean up any orphaned chapter members
        frappe.db.sql("""
            DELETE FROM `tabChapter Member` 
            WHERE parent LIKE 'Basic Test Chapter%'
        """)
        
        # Clean up test members created by this test class
        frappe.db.sql("""
            DELETE FROM `tabMember` 
            WHERE first_name LIKE 'BasicTest%'
        """)
        
        # Note: No commit needed in test context
    
    def tearDown(self):
        """Clean up"""
        self.cleanup_test_chapters()
        super().tearDown()
    
    @patch('verenigingen.utils.chapter_membership_history_manager.ChapterMembershipHistoryManager.add_membership_history')
    def test_add_member_basic(self, mock_history):
        """Test basic member addition without history tracking"""
        # Mock the history tracking to avoid validation issues
        mock_history.return_value = True
        
        # Add member
        result = self.chapter.add_member(self.member1.name)
        
        # Reload chapter
        self.chapter.reload()
        
        # Check member was added
        member_found = any(m.member == self.member1.name for m in self.chapter.members)
        self.assertTrue(member_found, "Member should be added to chapter")
        self.assertTrue(result, "add_member should return True")
    
    @patch('verenigingen.utils.chapter_membership_history_manager.ChapterMembershipHistoryManager.add_membership_history')
    def test_no_duplicate_members_basic(self, mock_history):
        """Test that members cannot be added twice"""
        # Mock the history tracking
        mock_history.return_value = True
        
        # Add member twice
        self.chapter.add_member(self.member1.name)
        result = self.chapter.add_member(self.member1.name)
        
        # Reload chapter
        self.chapter.reload()
        
        # Count occurrences
        count = sum(1 for m in self.chapter.members if m.member == self.member1.name)
        
        self.assertEqual(count, 1, "Member should appear only once")
        self.assertFalse(result, "Second add should return False")
    
    @patch('verenigingen.utils.chapter_membership_history_manager.ChapterMembershipHistoryManager.add_membership_history')
    @patch('verenigingen.utils.chapter_membership_history_manager.ChapterMembershipHistoryManager.end_chapter_membership')
    def test_remove_member_basic(self, mock_end_history, mock_add_history):
        """Test member removal"""
        # Mock the history tracking
        mock_add_history.return_value = True
        mock_end_history.return_value = True
        
        # Add member first
        self.chapter.add_member(self.member1.name)
        
        # Create second member
        member2 = self.create_test_member(
            first_name="BasicTest2",
            last_name="Member"
        )
        self.chapter.add_member(member2.name)
        
        # Reload and check both are there
        self.chapter.reload()
        self.assertEqual(len(self.chapter.members), 2)
        
        # Remove first member (will disable by default)
        result = self.chapter.remove_member(self.member1.name)
        
        # Reload and verify
        self.chapter.reload()
        
        # Check that we still have 2 members but one is disabled
        self.assertEqual(len(self.chapter.members), 2)
        self.assertTrue(result, "remove_member should return True")
        
        # Find the disabled member
        disabled_member = None
        enabled_member = None
        for member in self.chapter.members:
            if member.member == self.member1.name:
                disabled_member = member
            elif member.member == member2.name:
                enabled_member = member
        
        # Verify the first member is disabled and second is enabled
        self.assertIsNotNone(disabled_member)
        self.assertFalse(disabled_member.enabled, "First member should be disabled")
        self.assertIsNotNone(enabled_member)
        self.assertTrue(enabled_member.enabled, "Second member should be enabled")
    
    def test_member_status_fields(self):
        """Test that member entries have correct fields"""
        # Manually add a member entry
        self.chapter.append("members", {
            "member": self.member1.name,
            "enabled": 1,
            "status": "Active",
            "chapter_join_date": today()
        })
        self.chapter.save()
        
        # Reload and verify
        self.chapter.reload()
        
        member_entry = self.chapter.members[0]
        self.assertEqual(member_entry.member, self.member1.name)
        self.assertTrue(member_entry.enabled)
        self.assertEqual(member_entry.status, "Active")
        self.assertEqual(str(member_entry.chapter_join_date), today())


if __name__ == '__main__':
    import unittest
    unittest.main()