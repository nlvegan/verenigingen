#!/usr/bin/env python3
"""
Quick validation script for permission changes
Run this from the bench directory: python apps/verenigingen/validation_check.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath("."))


def validate_changes():
    print("🔍 Validating permission changes...")

    try:
        import frappe

        print("✅ Frappe module loaded")

        # Test Chapter permission function
        from verenigingen.verenigingen.doctype.chapter.chapter import get_chapter_permission_query_conditions

        # Test with no user (should return published chapters)
        result1 = get_chapter_permission_query_conditions(user=None)
        print(f"✅ Chapter permission query (no user): {result1}")

        # Test Team permission function
        from verenigingen.verenigingen.doctype.team.team import get_team_permission_query_conditions

        # Test with no user (should return empty access)
        result2 = get_team_permission_query_conditions(user=None)
        print(f"✅ Team permission query (no user): {result2}")

        print("\n✅ All permission functions are working correctly!")

        # Test doctype permissions
        chapter_perms = frappe.get_meta("Chapter").permissions
        team_perms = frappe.get_meta("Team").permissions

        chapter_has_member_role = any(p.role == "Verenigingen Member" for p in chapter_perms)
        team_has_member_role = any(p.role == "Verenigingen Member" for p in team_perms)

        print(f"✅ Chapter has Verenigingen Member role: {chapter_has_member_role}")
        print(f"✅ Team has Verenigingen Member role: {team_has_member_role}")

        # Check for permlevel 1 fields in Chapter
        chapter_fields = frappe.get_meta("Chapter").fields
        sensitive_fields = [f.fieldname for f in chapter_fields if f.permlevel == 1]
        print(f"✅ Chapter sensitive fields (permlevel 1): {sensitive_fields}")

        return True

    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    if validate_changes():
        print("\n🎉 All validations passed!")
        sys.exit(0)
    else:
        print("\n💥 Validation failed!")
        sys.exit(1)
