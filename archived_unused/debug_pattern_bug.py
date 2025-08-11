#!/usr/bin/env python3
"""
Debug the specific pattern matching bug
"""

import sys
from pathlib import Path
import re

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from schema_aware_validator import SchemaAwareValidator, FrappePatternHandler

def debug_pattern_bug():
    """Debug the pattern matching bug"""
    
    print("🔍 DEBUGGING PATTERN MATCHING BUG")
    print("=" * 50)
    
    # Create pattern handler
    pattern_handler = FrappePatternHandler()
    
    # Test cases
    test_cases = [
        ("member.email_address_nonexistent", "member = frappe.get_doc('Member', 'test')"),
        ("member.save", "member.save()"),
        ("member.get", "member.get('field')"),
        ("member.completely_fake_field", "test = member.completely_fake_field"),
    ]
    
    print("🧪 Testing pattern matching:")
    
    for field_access, context in test_cases:
        is_valid, pattern_type = pattern_handler.is_valid_frappe_pattern(field_access, context)
        print(f"\n   Field: {field_access}")
        print(f"   Context: {context}")
        print(f"   Result: {is_valid} ({pattern_type})")
        
        # Let's manually check the frappe_document_methods logic
        if pattern_type == 'frappe_document_methods':
            print(f"   🔍 Manual check for frappe_document_methods:")
            
            frappe_methods = pattern_handler.valid_patterns['frappe_document_methods']
            field_name = field_access.split('.')[-1]
            
            print(f"      Field name: '{field_name}'")
            print(f"      Is in methods list: {field_name in frappe_methods}")
            
            # Test each method pattern
            for method in frappe_methods:
                if re.search(method, context, re.IGNORECASE):
                    print(f"      ❌ BUG: '{method}' matches context '{context}'")
                    break
    
    print("\n🔍 Root cause analysis:")
    print("   The is_valid_frappe_pattern method uses re.search() on method names")
    print("   This means 'get' matches any context containing 'get' like 'get_doc'")
    print("   This is why ALL field accesses are being classified as valid patterns")
    
    # Test the fix approach
    print("\n🔧 Testing fix approach:")
    
    # The fix should be to check if the field name itself is a method, not search in context
    for field_access, context in test_cases:
        field_name = field_access.split('.')[-1]  # Get just the field name part
        frappe_methods = pattern_handler.valid_patterns['frappe_document_methods']
        
        is_method = field_name in frappe_methods
        print(f"   {field_access:<30} -> Field '{field_name}' is method: {is_method}")

if __name__ == "__main__":
    debug_pattern_bug()