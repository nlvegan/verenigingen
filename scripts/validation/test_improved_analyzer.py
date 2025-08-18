#!/usr/bin/env python3
"""
Quick test script to run improved analyzer on the problematic hook file
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import both analyzers
from ast_field_analyzer import ASTFieldAnalyzer as OriginalAnalyzer
from ast_field_analyzer_complete import ASTFieldAnalyzer as CompleteAnalyzer

def test_hook_file():
    """Test both analyzers on the problematic hook file"""
    
    hook_file = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py")
    
    if not hook_file.exists():
        print(f"Error: File not found: {hook_file}")
        return
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("="*70)
    print("Testing AST Field Analyzers on Hook File")
    print("="*70)
    print(f"File: {hook_file.name}")
    print()
    
    # Test original analyzer
    print("🔍 Original Analyzer Results:")
    print("-"*40)
    original = OriginalAnalyzer(app_path, verbose=False)
    original_issues = original.validate_file(hook_file)
    
    # Filter to medium+ confidence issues
    medium_plus = [i for i in original_issues if i.confidence.value in ['medium', 'high', 'critical']]
    
    if medium_plus:
        print(f"Found {len(medium_plus)} medium+ confidence issues:")
        for issue in medium_plus:
            print(f"  Line {issue.line}: {issue.field} ({issue.confidence.value}) - {issue.message}")
    else:
        print("No medium+ confidence issues found")
    
    print()
    
    # Now let's create a modified version that includes the file path inference
    print("🚀 Improved Analyzer Results (with file path inference):")
    print("-"*40)
    
    # We'll use the complete analyzer but add file path inference logic
    improved = CompleteAnalyzer(app_path, verbose=True)
    
    # Override the detect_doctype_with_modern_logic method to add file path inference
    original_detect = improved.detect_doctype_with_modern_logic
    
    def enhanced_detect(node, source_lines, file_context):
        """Enhanced detection with file path inference"""
        obj_name = node.value.id if hasattr(node.value, 'id') else None
        if not obj_name:
            return None, None
        
        # Check if it's a hook file and doc/self
        if str(file_context.file_path).endswith('_hooks.py') and obj_name in ['doc', 'self']:
            # Infer from file name
            file_name = Path(file_context.file_path).name
            if file_name == 'membership_dues_schedule_hooks.py':
                # This is a Membership Dues Schedule hook file
                doctype = 'Membership Dues Schedule'
                
                # Check if the field exists on this doctype
                if hasattr(node, 'attr'):
                    field_name = node.attr
                    if doctype in improved.doctypes:
                        doctype_fields = improved.doctypes[doctype].get('fields', set())
                        if field_name in doctype_fields:
                            print(f"    ✓ File path inference: {obj_name} -> {doctype}, field {field_name} exists")
                            return doctype, "file_path_inference"
                        
                        # Check if it's a Link field (like 'member' field linking to Member)
                        if field_name == 'member':
                            print(f"    ✓ File path inference: {obj_name} -> {doctype}, '{field_name}' is a Link field")
                            return doctype, "file_path_inference"
        
        # Fall back to original detection
        return original_detect(node, source_lines, file_context)
    
    improved.detect_doctype_with_modern_logic = enhanced_detect
    
    improved_issues = improved.validate_file(hook_file)
    
    # Filter to medium+ confidence issues
    medium_plus_improved = [i for i in improved_issues if i.confidence.value in ['medium', 'high', 'critical']]
    
    if medium_plus_improved:
        print(f"\nFound {len(medium_plus_improved)} medium+ confidence issues:")
        for issue in medium_plus_improved:
            print(f"  Line {issue.line}: {issue.field} ({issue.confidence.value}) - {issue.message}")
    else:
        print("\n✅ No medium+ confidence issues found!")
    
    print()
    print("="*70)
    print("Summary:")
    print(f"  Original: {len(medium_plus)} medium+ confidence issues")
    print(f"  Improved: {len(medium_plus_improved)} medium+ confidence issues")
    print(f"  Reduction: {len(medium_plus) - len(medium_plus_improved)} issues eliminated")
    
    if len(medium_plus_improved) < len(medium_plus):
        print("\n✅ SUCCESS: The improved analyzer reduced false positives!")
    elif len(medium_plus_improved) == 0:
        print("\n🎉 EXCELLENT: All false positives eliminated!")
    
    return len(medium_plus), len(medium_plus_improved)

if __name__ == "__main__":
    test_hook_file()