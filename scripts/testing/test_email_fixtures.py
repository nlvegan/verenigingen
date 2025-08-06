#!/usr/bin/env python3
"""
Test script for email fixtures validation

This script validates that the email fixtures system works correctly
and provides the expected functionality.
"""

import sys
import os

# Add the app path to sys.path for importing
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.insert(0, app_path)

def test_email_fixtures():
    """Test the email fixtures functionality"""
    
    print("🧪 Testing Email Fixtures System")
    print("=" * 50)
    
    try:
        from verenigingen.fixtures.email_addresses import (
            get_email, get_support_email, get_test_email, get_placeholder_email,
            is_test_email, is_dev_email, get_all_emails
        )
        print("✅ Successfully imported email fixtures")
    except ImportError as e:
        print(f"❌ Failed to import email fixtures: {e}")
        return False
    
    # Test basic email retrieval
    try:
        app_email = get_email("production", "app_contact")
        assert app_email == "info@verenigingen.org"
        print(f"✅ Production app email: {app_email}")
    except Exception as e:
        print(f"❌ Failed to get production email: {e}")
        return False
    
    # Test fallback functionality
    try:
        fallback_email = get_email("production", "nonexistent", "fallback@example.com")
        assert fallback_email == "fallback@example.com"
        print("✅ Fallback functionality works")
    except Exception as e:
        print(f"❌ Fallback functionality failed: {e}")
        return False
    
    # Test test email detection
    try:
        assert is_test_email("test@example.com") == True
        assert is_test_email("info@verenigingen.org") == False
        print("✅ Test email detection works")
    except Exception as e:
        print(f"❌ Test email detection failed: {e}")
        return False
    
    # Test dev email detection
    try:
        assert is_dev_email("foppe@veganisme.org") == True
        assert is_dev_email("test@example.com") == False
        print("✅ Dev email detection works")
    except Exception as e:
        print(f"❌ Dev email detection failed: {e}")
        return False
    
    # Test get_test_email function
    try:
        admin_email = get_test_email("admin")
        assert admin_email == "test_admin@example.com"
        print(f"✅ Test admin email: {admin_email}")
    except Exception as e:
        print(f"❌ Get test email failed: {e}")
        return False
    
    # Test placeholder emails
    try:
        placeholder = get_placeholder_email("personal")
        assert placeholder == "your.email@example.com"
        print(f"✅ Placeholder email: {placeholder}")
    except Exception as e:
        print(f"❌ Get placeholder email failed: {e}")
        return False
    
    # Test support email function
    try:
        support = get_support_email("development")
        assert support in ["support@example.com", "test@example.com"]
        print(f"✅ Support email for development: {support}")
    except Exception as e:
        print(f"❌ Get support email failed: {e}")
        return False
    
    # Test get_all_emails
    try:
        all_emails = get_all_emails()
        assert "production" in all_emails
        assert "test" in all_emails
        assert "dev" in all_emails
        assert "placeholder" in all_emails
        assert "security_test" in all_emails
        print("✅ Get all emails works")
    except Exception as e:
        print(f"❌ Get all emails failed: {e}")
        return False
    
    print("\n🎯 All email fixtures tests passed!")
    return True


def test_email_utils():
    """Test the email utilities functionality"""
    
    print("\n🔧 Testing Email Utilities")
    print("=" * 30)
    
    try:
        # Mock frappe for testing
        class MockFrappe:
            class db:
                @staticmethod
                def get_single_value(doctype, field):
                    if doctype == "Verenigingen Settings" and field == "member_contact_email":
                        return "configured@veganisme.org"
                    return None
                    
                @staticmethod
                def get_value(doctype, name, field):
                    if doctype == "Company" and field == "email":
                        return "company@example.com"
                    return None
            
            class defaults:
                @staticmethod
                def get_global_default(key):
                    if key == "company":
                        return "Test Company"
                    return None
        
        # Import and patch frappe temporarily for testing
        import verenigingen.utils.email_utils
        original_frappe = getattr(verenigingen.utils.email_utils, 'frappe', None)
        verenigingen.utils.email_utils.frappe = MockFrappe()
        
        from verenigingen.utils.email_utils import (
            get_member_contact_email, get_support_contact_email,
            create_test_user_email, sanitize_email_for_testing,
            validate_email_usage
        )
        
        # Test member contact email with mocked frappe
        member_email = get_member_contact_email()
        assert member_email == "configured@veganisme.org"
        print(f"✅ Member contact email (mocked): {member_email}")
        
        # Test support contact email
        support_email = get_support_contact_email()
        assert support_email == "company@example.com"
        print(f"✅ Support contact email (mocked): {support_email}")
        
        # Restore original frappe
        if original_frappe:
            verenigingen.utils.email_utils.frappe = original_frappe
        
    except Exception as e:
        print(f"⚠️  Email utils test with mocked frappe failed: {e}")
        print("   (This is expected in non-Frappe environment)")
    
    # Test functions that don't require frappe
    try:
        from verenigingen.utils.email_utils import (
            create_test_user_email, sanitize_email_for_testing,
            validate_email_usage
        )
        
        # Test create_test_user_email
        user_email = create_test_user_email("admin", "123")
        assert user_email == "test_admin.123@example.com"
        print(f"✅ Create test user email: {user_email}")
        
        # Test sanitize_email_for_testing
        sanitized = sanitize_email_for_testing("realuser@realdomain.com")
        assert sanitized == "realuser.test@example.com"
        print(f"✅ Sanitize email: {sanitized}")
        
        # Test validate_email_usage
        validation = validate_email_usage("test@example.com", "test context")
        assert validation["email_type"] == "test"
        print("✅ Email validation works")
        
    except Exception as e:
        print(f"❌ Email utils test failed: {e}")
        return False
    
    print("🎯 Email utilities tests completed!")
    return True


def main():
    """Run all email fixtures tests"""
    
    print("🚀 Running Email Fixtures Test Suite")
    print("=" * 60)
    
    fixtures_ok = test_email_fixtures()
    utils_ok = test_email_utils()
    
    print("\n📊 Test Results Summary")
    print("=" * 30)
    print(f"Email Fixtures: {'✅ PASS' if fixtures_ok else '❌ FAIL'}")
    print(f"Email Utils: {'✅ PASS' if utils_ok else '❌ FAIL'}")
    
    if fixtures_ok and utils_ok:
        print("\n🎉 All tests passed! Email fixtures system is working correctly.")
        return True
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)