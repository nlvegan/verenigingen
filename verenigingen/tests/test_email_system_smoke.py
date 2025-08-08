#!/usr/bin/env python3
"""
Email System Smoke Tests
=========================

Quick smoke tests to verify the email system test infrastructure and basic functionality.
This validates that tests can run successfully in the Frappe environment.
"""

import frappe
from frappe.utils import now_datetime, getdate, add_days

# Import our enhanced test infrastructure  
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Import email system components
from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
from verenigingen.email.newsletter_templates import NewsletterTemplateManager


class TestEmailSystemSmoke(EnhancedTestCase):
    """
    Smoke tests for email system basic functionality
    """
    
    def setUp(self):
        super().setUp()
        # Create minimal test data
        self.test_chapter = self.factory.ensure_test_chapter(
            "Smoke Test Chapter",
            {
                "region": "Smoke Region",
                "introduction": "Smoke test chapter",
                "contact_email": "smoke@test.invalid"
            }
        )
        
        # Create a test member
        self.test_member = self.create_test_member(
            first_name="Smoke",
            last_name="TestMember", 
            email="smoke.member@test.invalid",
            birth_date="1990-01-01"
        )
        
        # Add member to chapter
        self.test_chapter.append("members", {
            "member": self.test_member.name,
            "enabled": 1,
            "join_date": getdate()
        })
        self.test_chapter.save()
        
    def test_enhanced_test_factory_functionality(self):
        """Test that our enhanced test factory works correctly"""
        # Test member creation
        self.assertIsNotNone(self.test_member)
        self.assertEqual(self.test_member.first_name, "Smoke")
        self.assertIn("@test.invalid", self.test_member.email)
        
        # Test chapter creation
        self.assertIsNotNone(self.test_chapter)
        self.assertEqual(len(self.test_chapter.members), 1)
        
    def test_simplified_email_manager_basic(self):
        """Test basic SimplifiedEmailManager functionality"""
        manager = SimplifiedEmailManager(self.test_chapter)
        
        # Test segment preview (test mode)
        result = manager.send_to_chapter_segment(
            chapter_name=self.test_chapter.name,
            segment="all",
            subject="Smoke test",
            content="Test content",
            test_mode=True
        )
        
        self.assertTrue(result["success"])
        self.assertEqual(result["recipients_count"], 1)
        self.assertEqual(result["segment"], "all")
        
    def test_newsletter_template_manager_basic(self):
        """Test basic NewsletterTemplateManager functionality"""
        template_manager = NewsletterTemplateManager()
        
        # Test template listing
        templates = template_manager.list_templates()
        self.assertIsInstance(templates, list)
        self.assertGreater(len(templates), 0)
        
        # Test template retrieval
        monthly_template = template_manager.get_template("monthly_update")
        self.assertIsNotNone(monthly_template)
        self.assertIn("subject_template", monthly_template)
        self.assertIn("content_template", monthly_template)
        
    def test_template_rendering_basic(self):
        """Test basic template rendering"""
        template_manager = NewsletterTemplateManager()
        
        variables = {
            "chapter_name": "Test Chapter",
            "month_year": "March 2024",
            "highlights": "Test highlights",
            "upcoming_events": "Test events", 
            "volunteer_spotlight": "Test volunteer"
        }
        
        rendered = template_manager.render_template("monthly_update", variables)
        
        self.assertIsNotNone(rendered)
        self.assertIn("subject", rendered)
        self.assertIn("content", rendered)
        self.assertIn("Test Chapter", rendered["content"])
        
    def test_member_opt_out_basic(self):
        """Test basic opt-out functionality"""
        manager = SimplifiedEmailManager(self.test_chapter)
        
        # Initially should include member
        initial_result = manager.send_to_chapter_segment(
            chapter_name=self.test_chapter.name,
            segment="all",
            test_mode=True
        )
        self.assertEqual(initial_result["recipients_count"], 1)
        
        # Opt out member
        self.test_member.opt_out_optional_emails = 1
        self.test_member.save()
        
        # Should now exclude member
        after_optout = manager.send_to_chapter_segment(
            chapter_name=self.test_chapter.name,
            segment="all",
            test_mode=True
        )
        self.assertEqual(after_optout["recipients_count"], 0)
        
    def test_field_validation_basic(self):
        """Test that field validation works"""
        # Test with valid fields
        member = self.create_test_member(
            first_name="Valid",
            last_name="Member",
            email="valid@test.invalid",
            birth_date="1990-01-01"
        )
        self.assertIsNotNone(member)
        
    def test_business_rule_validation_basic(self):
        """Test that business rule validation works"""
        # Test age validation - should fail for too young
        with self.assertRaises(Exception):  # Should raise BusinessRuleError
            self.create_test_member(
                first_name="TooYoung",
                last_name="Member",
                email="tooyoung@test.invalid",
                birth_date="2020-01-01"  # Too young
            )


def run_smoke_tests():
    """Run smoke tests and return results"""
    import unittest
    from io import StringIO
    
    # Load and run smoke tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEmailSystemSmoke)
    stream = StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    
    print("\n" + "="*60)
    print("EMAIL SYSTEM SMOKE TESTS")
    print("="*60)
    
    result = runner.run(suite)
    
    # Print results
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}")
            print(f"  {traceback}")
            
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}")
            print(f"  {traceback}")
    
    success_rate = ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0
    print(f"\nSuccess rate: {success_rate:.1f}%")
    
    if success_rate >= 95:
        print("✅ SMOKE TESTS PASSED - Test infrastructure is working correctly")
        return True
    else:
        print("❌ SMOKE TESTS FAILED - Test infrastructure needs attention") 
        return False


if __name__ == "__main__":
    run_smoke_tests()