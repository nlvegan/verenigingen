#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Email Test Setup Validation
============================

Validates that the email/newsletter test suite can be executed properly.
Checks dependencies, imports, test data creation, and basic functionality.
"""

import os
import sys

# Add the apps directory to Python path
sys.path.insert(0, '/home/frappe/frappe-bench/apps')

# Set up Frappe environment
os.environ['FRAPPE_SITE'] = 'dev.veganisme.net'

try:
    import frappe
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    print("✅ Frappe environment initialized successfully")
except Exception as e:
    print(f"❌ Failed to initialize Frappe environment: {e}")
    sys.exit(1)


def validate_imports():
    """Validate that all required modules can be imported"""
    print("\n🔍 VALIDATING IMPORTS...")
    
    try:
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
        print("✅ Enhanced Test Factory imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Enhanced Test Factory: {e}")
        return False
    
    try:
        from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
        print("✅ Simplified Email Manager imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Simplified Email Manager: {e}")
        return False
    
    try:
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager
        print("✅ Newsletter Template Manager imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Newsletter Template Manager: {e}")
        return False
    
    try:
        from verenigingen.email.advanced_segmentation import AdvancedSegmentationManager
        print("✅ Advanced Segmentation Manager imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Advanced Segmentation Manager: {e}")
        return False
    
    try:
        from verenigingen.tests.test_email_newsletter_system import (
            TestEmailNewsletterSystemSecurity,
            TestEmailNewsletterSystemIntegration,
            TestEmailNewsletterSystemBusinessLogic,
            TestEmailNewsletterSystemPerformance,
            TestEmailNewsletterSystemErrorHandling,
        )
        print("✅ All test classes imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import test classes: {e}")
        return False
    
    return True


def validate_doctypes():
    """Validate that required DocTypes exist"""
    print("\n📊 VALIDATING DOCTYPES...")
    
    required_doctypes = [
        "Member",
        "Chapter",
        "Volunteer", 
        "Chapter Member",
        "Chapter Board Member",
        "Chapter Role"
    ]
    
    for doctype in required_doctypes:
        try:
            if frappe.db.exists("DocType", doctype):
                print(f"✅ {doctype} DocType exists")
            else:
                print(f"❌ {doctype} DocType not found")
                return False
        except Exception as e:
            print(f"❌ Error checking {doctype}: {e}")
            return False
    
    return True


def validate_field_references():
    """Validate critical field references"""
    print("\n🔎 VALIDATING FIELD REFERENCES...")
    
    try:
        # Check Chapter Board Member fields
        cbm_meta = frappe.get_meta("Chapter Board Member")
        cbm_fields = [f.fieldname for f in cbm_meta.fields]
        
        if 'volunteer' in cbm_fields:
            print("✅ Chapter Board Member has 'volunteer' field (correct)")
        else:
            print("❌ Chapter Board Member missing 'volunteer' field")
            return False
        
        if 'chapter_role' in cbm_fields:
            print("✅ Chapter Board Member has 'chapter_role' field")
        else:
            print("❌ Chapter Board Member missing 'chapter_role' field")
            return False
        
        # Check Member fields
        member_meta = frappe.get_meta("Member")
        member_fields = [f.fieldname for f in member_meta.fields]
        
        if 'email' in member_fields:
            print("✅ Member has 'email' field")
        else:
            print("❌ Member missing 'email' field")
            return False
        
        # Check for opt-out field (might not exist)
        if 'opt_out_optional_emails' in member_fields:
            print("✅ Member has 'opt_out_optional_emails' field")
        else:
            print("⚠️  Member missing 'opt_out_optional_emails' field (tests will handle gracefully)")
        
    except Exception as e:
        print(f"❌ Error validating field references: {e}")
        return False
    
    return True


def validate_test_data_creation():
    """Validate that test data can be created"""
    print("\n🧪 VALIDATING TEST DATA CREATION...")
    
    try:
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory
        
        # Create factory instance
        factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
        print("✅ Test data factory created")
        
        # Test member creation
        member = factory.create_member(
            first_name="Validation",
            last_name="Test",
            email="validation@test.invalid",
            birth_date="1990-01-01"
        )
        print(f"✅ Test member created: {member.name}")
        
        # Test chapter creation
        chapter = factory.ensure_test_chapter(
            "Validation Test Chapter",
            {"short_name": "VTC"}
        )
        print(f"✅ Test chapter created: {chapter.name}")
        
        # Test volunteer creation
        volunteer = factory.create_volunteer(
            member_name=member.name,
            volunteer_name="Validation Test Volunteer",
            email="validation-volunteer@test.invalid"
        )
        print(f"✅ Test volunteer created: {volunteer.name}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating test data: {e}")
        import traceback
        traceback.print_exc()
        return False


def validate_email_components():
    """Validate that email components can be instantiated"""
    print("\n📧 VALIDATING EMAIL COMPONENTS...")
    
    try:
        from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager
        from verenigingen.email.advanced_segmentation import AdvancedSegmentationManager
        
        # Test component instantiation
        email_manager = SimplifiedEmailManager()
        print("✅ Simplified Email Manager instantiated")
        
        template_manager = NewsletterTemplateManager()
        print("✅ Newsletter Template Manager instantiated")
        
        segmentation_manager = AdvancedSegmentationManager()
        print("✅ Advanced Segmentation Manager instantiated")
        
        # Test template loading
        templates = template_manager.templates
        if templates and len(templates) > 0:
            print(f"✅ {len(templates)} newsletter templates loaded")
        else:
            print("❌ No newsletter templates loaded")
            return False
        
        # Test segmentation segments
        segments = segmentation_manager.built_in_segments
        if segments and len(segments) > 0:
            print(f"✅ {len(segments)} segmentation options available")
        else:
            print("❌ No segmentation options loaded")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error validating email components: {e}")
        import traceback
        traceback.print_exc()
        return False


def validate_test_runner():
    """Validate that test runner can be executed"""
    print("\n🏃 VALIDATING TEST RUNNER...")
    
    try:
        # Import test runner
        sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen/scripts/testing/runners')
        from run_email_newsletter_tests import EmailNewsletterTestRunner
        
        # Create test runner instance
        runner = EmailNewsletterTestRunner()
        print("✅ Test runner instantiated")
        
        # Check test suites
        if len(runner.test_suites) >= 5:
            print(f"✅ {len(runner.test_suites)} test suites configured")
            
            # List available suites
            for suite_name, suite_info in runner.test_suites.items():
                print(f"   - {suite_name}: {suite_info['name']} ({suite_info['priority']})")
        else:
            print("❌ Insufficient test suites configured")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error validating test runner: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main validation function"""
    print("🚀 EMAIL/NEWSLETTER TEST SETUP VALIDATION")
    print("="*60)
    
    validation_steps = [
        ("Import Validation", validate_imports),
        ("DocType Validation", validate_doctypes), 
        ("Field Reference Validation", validate_field_references),
        ("Test Data Creation", validate_test_data_creation),
        ("Email Components", validate_email_components),
        ("Test Runner", validate_test_runner)
    ]
    
    passed = 0
    failed = 0
    
    for step_name, step_func in validation_steps:
        try:
            if step_func():
                passed += 1
                print(f"\n✅ {step_name}: PASSED")
            else:
                failed += 1
                print(f"\n❌ {step_name}: FAILED")
        except Exception as e:
            failed += 1
            print(f"\n❌ {step_name}: ERROR - {e}")
    
    print("\n" + "="*60)
    print("📋 VALIDATION SUMMARY")
    print("="*60)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total: {passed + failed}")
    
    if failed == 0:
        print("\n🎉 ALL VALIDATIONS PASSED!")
        print("✨ Email/newsletter test suite is ready to run.")
        print("\n🚀 Run tests with:")
        print("python scripts/testing/runners/run_email_newsletter_tests.py --suite all")
    else:
        print("\n🚨 VALIDATION FAILURES DETECTED!")
        print("⚠️  Please fix issues before running tests.")
        
        if failed == 1 and "opt_out_optional_emails" in str(failed):
            print("\n📄 NOTE: Missing 'opt_out_optional_emails' field is handled gracefully by tests.")
    
    print("="*60)
    
    # Clean up
    try:
        frappe.destroy()
    except:
        pass
    
    return failed == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
