#!/usr/bin/env python3
"""Simple test to verify refactored functions work"""


def test_function_imports():
    """Test that all refactored functions can be imported"""
    try:
        from verenigingen.api.membership_application_review import (
            approve_membership_application,
            assign_member_to_chapter,
            create_member_iban_history,
            finalize_member_approval,
            reject_membership_application,
            resolve_membership_type,
        )

        print("✅ SUCCESS: All refactored functions imported successfully")

        # Test function callable
        print(f"approve_membership_application callable: {callable(approve_membership_application)}")
        print(f"reject_membership_application callable: {callable(reject_membership_application)}")
        print(f"assign_member_to_chapter callable: {callable(assign_member_to_chapter)}")
        print(f"resolve_membership_type callable: {callable(resolve_membership_type)}")
        print(f"create_member_iban_history callable: {callable(create_member_iban_history)}")
        print(f"finalize_member_approval callable: {callable(finalize_member_approval)}")

        return True

    except Exception as e:
        print(f"❌ FAILED: Could not import functions: {str(e)}")
        return False


if __name__ == "__main__":
    test_function_imports()
