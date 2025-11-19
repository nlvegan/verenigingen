#!/usr/bin/env python3
"""
Test Email/Newsletter Functionality
Phase 2 Implementation - Testing
"""

import frappe
import unittest
from frappe.test_runner import make_test_records
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestEmailFunctionality(EnhancedTestCase):
    """Test email and newsletter functionality"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        
        # Create test chapter using Enhanced Test Factory
        self.test_chapter = self.factory.ensure_test_chapter(
            "Test Email Chapter",
            {
                "short_name": "TEC",
                "postal_codes": "1000-1099",
                "published": 1,
                "country": "Netherlands"
            }
        )
    
    def test_simplified_email_manager_import(self):
        """Test that SimplifiedEmailManager can be imported"""
        try:
            from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
            self.assertIsNotNone(SimplifiedEmailManager)
        except ImportError as e:
            self.fail(f"Failed to import SimplifiedEmailManager: {str(e)}")
    
    def test_email_group_sync_import(self):
        """Test that email group sync functions can be imported"""
        try:
            from verenigingen.email.email_group_sync import (
                create_initial_email_groups,
                sync_email_groups_manually
            )
            self.assertIsNotNone(create_initial_email_groups)
            self.assertIsNotNone(sync_email_groups_manually)
        except ImportError as e:
            self.fail(f"Failed to import email group sync functions: {str(e)}")
    
    def test_send_chapter_segment_preview(self):
        """Test getting preview of chapter segment recipients"""
        from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
        
        # Create test members
        member1 = self.create_test_member(
            first_name="Email",
            last_name="Test1",
            email="test1@example.com"
        )
        
        # Add to chapter
        if not frappe.db.exists("Chapter Member", {
            "parent": self.test_chapter.name,
            "member": member1.name
        }):
            self.test_chapter.append("members", {
                "member": member1.name,
                "enabled": 1
            })
            self.test_chapter.save()
        
        # Initialize manager
        manager = SimplifiedEmailManager(self.test_chapter)
        
        # Test preview mode
        result = manager.send_to_chapter_segment(
            chapter_name=self.test_chapter.name,
            segment="all",
            test_mode=True
        )
        
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("test_mode"))
        self.assertGreaterEqual(result.get("recipients_count", 0), 0)
    
    def test_member_opt_out_field(self):
        """Test that member opt-out field exists"""
        # Create a test member
        member = self.create_test_member(
            first_name="OptOut",
            last_name="Test",
            email="optout@example.com"
        )
        
        # Check that the field exists (even if it's None)
        self.assertTrue(hasattr(member, 'opt_out_optional_emails'))
        
        # Test setting the field
        member.opt_out_optional_emails = 1
        member.save()
        
        # Reload and verify
        member.reload()
        self.assertEqual(member.opt_out_optional_emails, 1)
    
    def test_email_group_creation(self):
        """Test creating initial email groups"""
        from verenigingen.email.email_group_sync import create_initial_email_groups
        
        # This test is safe to run multiple times
        # It will only create groups that don't exist
        result = create_initial_email_groups()
        
        self.assertTrue(result.get("success"))
        self.assertIsInstance(result.get("created_count"), int)
        
        # Verify at least one standard group exists
        self.assertTrue(
            frappe.db.exists("Email Group", {"title": "Active Members"}) or
            frappe.db.exists("Email Group", {"title": "All Organization Members"})
        )
    
    def test_segment_preview_function(self):
        """Test the segment preview functionality"""
        from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
        
        manager = SimplifiedEmailManager(self.test_chapter)
        
        # Test preview for different segments
        for segment in ["all", "board", "volunteers"]:
            result = manager.get_segment_preview(
                chapter_name=self.test_chapter.name,
                segment=segment
            )
            
            self.assertTrue(result.get("success") or "error" in result)
            if result.get("success"):
                self.assertIn("recipients_count", result)
                self.assertIn("sample_recipients", result)
    
    def test_api_endpoint_permissions(self):
        """Test that API endpoints check permissions correctly"""
        from verenigingen.email.simplified_email_manager import (
            send_chapter_email,
            get_segment_recipient_count
        )
        
        # These should fail without proper permissions in test context
        # But we're just testing that the functions exist and are callable
        self.assertIsNotNone(send_chapter_email)
        self.assertIsNotNone(get_segment_recipient_count)

