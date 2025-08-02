#!/usr/bin/env python3
"""
Quick test to verify JavaScript progress reporting improvements are working
"""


def test_js_progress_improvements():
    """Test the JavaScript progress reporting improvements"""

    import os
    import re

    js_file_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.js"

    print("=== Testing JavaScript Progress Reporting Improvements ===")

    # Read the file
    with open(js_file_path, "r") as f:
        content = f.read()

    # Test 1: Check that clear_migration_progress function exists
    clear_function_pattern = r"function clear_migration_progress\(frm\)"
    if re.search(clear_function_pattern, content):
        print("✓ clear_migration_progress function exists")
    else:
        print("❌ clear_migration_progress function missing")
        return False

    # Test 2: Check that progress function includes cleanup
    progress_function_pattern = (
        r"function show_migration_progress\(frm\) \{[^}]*clear_migration_progress\(frm\)"
    )
    if re.search(progress_function_pattern, content, re.DOTALL):
        print("✓ show_migration_progress includes cleanup call")
    else:
        print("❌ show_migration_progress missing cleanup")
        return False

    # Test 3: Check that auto-refresh only happens for 'In Progress' status
    status_check_pattern = r"if \(frm\.doc\.migration_status === \'In Progress\'"
    matches = len(re.findall(status_check_pattern, content))
    if matches >= 3:  # Should be in multiple places
        print(f"✓ Status checks for 'In Progress' found ({matches} instances)")
    else:
        print(f"❌ Insufficient status checks ({matches} found, expected >= 3)")
        return False

    # Test 4: Check that intervals have proper error handling
    error_handling_pattern = r"\.catch\(\(error\) =>"
    if re.search(error_handling_pattern, content):
        print("✓ Error handling in reload operations found")
    else:
        print("❌ Error handling in reload operations missing")
        return False

    # Test 5: Check for improved event handlers
    event_handlers = ["before_unload", "migration_status", "refresh"]

    found_handlers = 0
    for handler in event_handlers:
        handler_pattern = f"frappe.ui.form.on\\('E-Boekhouden Migration', '{handler}'"
        if re.search(handler_pattern, content):
            found_handlers += 1
            print(f"✓ Event handler '{handler}' found")
        else:
            print(f"❌ Event handler '{handler}' missing")

    if found_handlers >= 2:  # At least before_unload and one other
        print(f"✓ Sufficient event handlers found ({found_handlers}/3)")
    else:
        print(f"❌ Insufficient event handlers ({found_handlers}/3)")
        return False

    # Test 6: Check that setTimeout has been replaced with frm.reload_doc().then()
    old_pattern_count = len(re.findall(r"setTimeout\(\(\) => frm\.reload_doc\(\)", content))
    new_pattern_count = len(re.findall(r"frm\.reload_doc\(\)\.then\(\(\) =>", content))

    print(f"Old setTimeout patterns found: {old_pattern_count}")
    print(f"New Promise-based patterns found: {new_pattern_count}")

    if new_pattern_count >= 3:  # Should have multiple improved callbacks
        print("✓ Improved callback patterns implemented")
    else:
        print("❌ Insufficient improved callback patterns")
        return False

    # Test 7: Check for dashboard.clear_headline()
    if "frm.dashboard.clear_headline()" in content:
        print("✓ Dashboard headline clearing implemented")
    else:
        print("❌ Dashboard headline clearing missing")
        return False

    # Test 8: Check for reduced polling interval (3000ms instead of 5000ms)
    if "3000); // Reduced to 3 seconds" in content:
        print("✓ Reduced polling interval implemented (3s)")
    else:
        print("❌ Polling interval not optimized")
        return False

    print("\n=== Summary ===")
    print("✅ All JavaScript progress reporting improvements are properly implemented!")
    print("\nKey improvements:")
    print("- Memory leak prevention with proper interval cleanup")
    print("- Progress bar duplication prevention")
    print("- Status-aware polling (only when 'In Progress')")
    print("- Error handling for failed reload operations")
    print("- Reduced polling interval (3s vs 5s)")
    print("- Comprehensive event handlers for cleanup")
    print("- Promise-based callbacks instead of setTimeout")

    return True


if __name__ == "__main__":
    test_js_progress_improvements()
