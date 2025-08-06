#!/usr/bin/env python3
"""
Medium Confidence SQL Field Validation

This script specifically validates the "medium confidence" SQL field issues that were 
identified and fixed. These issues involved Chapter Board Member DocType queries that
incorrectly used 'member' field instead of proper JOINs through volunteer to member.
"""

import os
import re
import sys

# Add the app path to sys.path for importing
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.insert(0, app_path)


def validate_chapter_board_member_queries():
    """Validate that Chapter Board Member queries use proper field references"""
    
    print("🎯 Medium Confidence SQL Field Validation")
    print("=" * 60)
    
    permissions_file = os.path.join(app_path, 'verenigingen/permissions.py')
    with open(permissions_file, 'r') as f:
        content = f.read()
    
    print("📁 Analyzing Chapter Board Member SQL queries...")
    
    # Test 1: Ensure no direct 'WHERE member =' on Chapter Board Member table (without proper JOINs)
    bad_patterns = [
        r'FROM\s+`tabChapter Board Member`\s+WHERE\s+member\s*=',  # Direct WHERE without alias
        r'FROM\s+`tabChapter Board Member`\s+cbm\s+WHERE\s+cbm\.member\s*=',  # Direct cbm.member reference
    ]
    
    issues_found = 0
    
    for i, pattern in enumerate(bad_patterns):
        matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
        if matches:
            print(f"❌ Found bad pattern {i+1}: {len(matches)} instances")
            for match in matches[:3]:  # Show first 3 matches
                print(f"   {match[:100]}...")
            issues_found += len(matches)
        else:
            print(f"✅ No instances of bad pattern {i+1}")
    
    # Test 2: Check for proper JOIN patterns
    good_patterns = [
        r'FROM\s+`tabChapter Board Member`\s+cbm\s+JOIN\s+`tabVolunteer`\s+v\s+ON\s+cbm\.volunteer\s*=\s*v\.name',
        r'WHERE\s+v\.member\s*=',
    ]
    
    expected_joins = 0
    for pattern in good_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        expected_joins += len(matches)
        print(f"✅ Found {len(matches)} instances of correct pattern: {pattern[:50]}...")
    
    print(f"\n📊 Validation Results:")
    print(f"Bad patterns found: {issues_found}")
    print(f"Correct JOIN patterns found: {expected_joins}")
    
    # Test 3: Specific query validation
    print(f"\n🔍 Specific Query Pattern Analysis:")
    
    # Extract Chapter Board Member related queries
    cbm_queries = re.findall(
        r'frappe\.db\.sql\(\s*""".*?`tabChapter Board Member`.*?"""\s*,', 
        content, 
        re.DOTALL | re.IGNORECASE
    )
    
    print(f"Found {len(cbm_queries)} Chapter Board Member queries")
    
    for i, query in enumerate(cbm_queries):
        print(f"\n📝 Query {i+1}:")
        
        # Check for proper structure
        if 'JOIN `tabVolunteer`' in query and 'v.member =' in query:
            print("   ✅ Uses proper JOIN through Volunteer to Member")
        elif 'WHERE member =' in query:
            print("   ❌ Uses invalid direct member field reference")
            issues_found += 1
        else:
            print("   ⚠️  Unknown pattern - manual review needed")
    
    return issues_found == 0


def validate_fixed_issues():
    """Validate that the original 18 medium confidence issues are fixed"""
    
    print(f"\n🔧 Original Issue Validation")
    print("-" * 40)
    
    permissions_file = os.path.join(app_path, 'verenigingen/permissions.py')
    with open(permissions_file, 'r') as f:
        content = f.read()
    
    # The medium confidence issues were queries like:
    # SELECT DISTINCT parent as chapter_name FROM `tabChapter Board Member` WHERE member = %s
    
    problematic_patterns = [
        'FROM `tabChapter Board Member`\n                WHERE member =',
        'FROM `tabChapter Board Member`\n                    WHERE member =',
        'FROM `tabChapter Board Member` WHERE member =',
    ]
    
    all_fixed = True
    
    for pattern in problematic_patterns:
        if pattern in content:
            print(f"❌ Still found problematic pattern: {pattern}")
            all_fixed = False
        else:
            print(f"✅ Fixed: No direct Chapter Board Member WHERE member = patterns")
    
    # Check for the correct replacement patterns
    correct_patterns = [
        'FROM `tabChapter Board Member` cbm',
        'JOIN `tabVolunteer` v ON cbm.volunteer = v.name',
        'WHERE v.member = %s AND cbm.is_active = 1',
    ]
    
    print(f"\n✅ Checking for Correct Replacement Patterns:")
    for pattern in correct_patterns:
        count = content.count(pattern)
        if count > 0:
            print(f"✅ Found {count} instances of: {pattern}")
        else:
            print(f"⚠️  Pattern not found: {pattern}")
    
    return all_fixed


def main():
    """Run all medium confidence SQL validation tests"""
    
    print("🚀 Medium Confidence SQL Field Issue Validation")
    print("=" * 80)
    
    # Test 1: Chapter Board Member query validation
    cbm_validation = validate_chapter_board_member_queries()
    
    # Test 2: Original issue validation
    fixes_validation = validate_fixed_issues()
    
    print(f"\n🎯 Final Results")
    print("=" * 30)
    print(f"Chapter Board Member queries: {'✅ PASS' if cbm_validation else '❌ FAIL'}")
    print(f"Original fixes validation: {'✅ PASS' if fixes_validation else '❌ FAIL'}")
    
    if cbm_validation and fixes_validation:
        print(f"\n🎉 All medium confidence SQL field issues RESOLVED!")
        print("The 18 medium confidence issues have been successfully fixed.")
        print("Chapter Board Member queries now use proper JOINs through Volunteer to Member.")
        return True
    else:
        print(f"\n⚠️  Some medium confidence issues may still exist.")
        print("Please review the output above for specific problems.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)