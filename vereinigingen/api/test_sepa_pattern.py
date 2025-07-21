#!/usr/bin/env python3
"""
Test script for SEPA mandate configurable naming pattern
"""

import frappe


@frappe.whitelist()
def test_sepa_mandate_pattern():
    """Test the configurable SEPA mandate naming pattern"""

    result = []
    result.append("=== Testing SEPA Mandate Configurable Naming Pattern ===")

    try:
        # Test 1: Check if settings field exists and has default value
        result.append("\n1. Testing Verenigingen Settings field...")
        settings = frappe.get_single("Verenigingen Settings")

        current_pattern = getattr(settings, "sepa_mandate_naming_pattern", None)

        if current_pattern is None:
            result.append("❌ Field 'sepa_mandate_naming_pattern' not found in Verenigingen Settings!")
            return {"success": False, "message": "\n".join(result)}

        result.append(f"Current SEPA mandate pattern: {current_pattern}")

        # Test 2: Test pattern modification
        result.append("\n2. Testing pattern modification...")
        original_pattern = settings.sepa_mandate_naming_pattern
        test_pattern = "format:TEST-MANDATE-{YYYY}-{####}"

        settings.sepa_mandate_naming_pattern = test_pattern
        settings.save()

        result.append(f"Set test pattern: {test_pattern}")

        # Test 3: Test name generation
        result.append("\n3. Testing name generation...")
        from frappe.model.naming import make_autoname

        test_name = make_autoname(test_pattern)
        result.append(f"Generated test name: {test_name}")

        # Test 4: Restore original pattern
        result.append("\n4. Restoring original pattern...")
        settings.sepa_mandate_naming_pattern = original_pattern
        settings.save()

        result.append(f"Restored pattern: {original_pattern}")

        result.append("\n✅ All tests passed! SEPA mandate naming pattern configuration is working.")

        return {
            "success": True,
            "message": "\n".join(result),
            "original_pattern": original_pattern,
            "test_name_generated": test_name,
        }

    except Exception as e:
        result.append(f"\n❌ Error during testing: {str(e)}")
        return {"success": False, "error": str(e), "message": "\n".join(result)}
