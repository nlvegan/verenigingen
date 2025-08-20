"""
Debug critical authentication security issues
"""

import frappe

from verenigingen import auth_hooks


def debug_critical_auth_issues():
    """Debug method to test critical authentication security issues"""

    print("🔍 DEBUGGING CRITICAL AUTH ISSUES")
    print("=" * 50)

    print("\n1. Testing frappe.get_roles(None):")
    try:
        result = frappe.get_roles(None)
        print(f"   Result: {result}")
        print(f"   Type: {type(result)}")
        if result:
            print(f"   Contains 'System Manager': {'System Manager' in result}")
            print(f"   Contains 'Administrator': {'Administrator' in result}")
    except Exception as e:
        print(f"   Exception: {e}")

    print("\n2. Testing has_system_access(None):")
    try:
        result = auth_hooks.has_system_access(None)
        print(f"   Result: {result}")
        if result:
            print(f"   🚨 CRITICAL: None user has system access!")
    except Exception as e:
        print(f"   Exception: {e}")

    print("\n3. Testing edge cases that could cause 'User None is disabled':")
    test_cases = [None, "", "None", "null", False, 0]

    for case in test_cases:
        print(f"\n   Testing user: {repr(case)}")
        try:
            # Test the exact functions used in auth_hooks
            roles = frappe.get_roles(case)
            member_role = auth_hooks.has_member_role(case)
            volunteer_role = auth_hooks.has_volunteer_role(case)
            system_access = auth_hooks.has_system_access(case)

            print(f"     get_roles: {roles}")
            print(f"     has_member_role: {member_role}")
            print(f"     has_volunteer_role: {volunteer_role}")
            print(f"     has_system_access: {system_access}")

            if system_access:
                print(f"     🚨 CRITICAL: {repr(case)} has system access!")

        except Exception as e:
            print(f"     Exception: {e}")

    print("\n4. Testing on_session_creation with problematic users:")
    for case in [None, "", "None"]:
        print(f"\n   Testing session creation with user: {repr(case)}")
        try:
            # Mock frappe.session.user
            original_user = getattr(frappe.session, "user", None)
            frappe.session.user = case

            # Create a mock login manager
            class MockLoginManager:
                pass

            login_manager = MockLoginManager()

            # Test the function
            auth_hooks.on_session_creation(login_manager)
            print(f"     Session creation completed without error")

            # Restore original user
            frappe.session.user = original_user

        except Exception as e:
            print(f"     Exception during session creation: {e}")
            # Restore original user
            if "original_user" in locals():
                frappe.session.user = original_user

    print("\n" + "=" * 50)
    print("Debug complete. Check for any CRITICAL issues above.")

    return "Debug completed"
