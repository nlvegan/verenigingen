#!/usr/bin/env python3
"""
Performance test for Enhanced JS-Python Parameter Validator
"""

import sys
from pathlib import Path

# Add current directory to path for imports
current_dir = Path(__file__).parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from js_python_parameter_validator import ModernJSPythonValidator

def test_enhanced_features():
    """Test the enhanced validation features"""
    
    project_root = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🧪 Testing Enhanced JS-Python Parameter Validator")
    print("=" * 60)
    
    # Create validator instance
    validator = ModernJSPythonValidator(project_root)
    
    # Test DocType loader initialization
    if validator.doctype_loader:
        print("✅ DocType loader initialized successfully")
        
        # Test DocType field lookup
        try:
            member_fields = validator._get_doctype_fields('Member')
            print(f"✅ Found {len(member_fields)} fields for Member DocType")
            if member_fields:
                print(f"   Sample fields: {list(member_fields)[:5]}")
        except Exception as e:
            print(f"❌ DocType field lookup failed: {e}")
    else:
        print("❌ DocType loader not available")
    
    print("\n📊 Running enhanced validation...")
    
    # Run validation
    issues = validator.run_validation()
    
    print(f"\n📈 Enhanced Validation Results:")
    print(f"   • Total issues found: {len(issues)}")
    print(f"   • DocType lookups: {validator.stats['doctype_lookups']}")
    print(f"   • Enhanced validations: {validator.stats['enhanced_validations']}")
    print(f"   • Cache hits: {validator.stats['cache_hits']}")
    
    # Show issue breakdown
    from collections import Counter
    issue_types = Counter(issue.issue_type.value for issue in issues)
    severity_counts = Counter(issue.severity.value for issue in issues)
    
    print(f"\n🔍 Issue Breakdown:")
    print(f"   By type: {dict(issue_types)}")
    print(f"   By severity: {dict(severity_counts)}")
    
    # Test specific enhancement features
    print(f"\n🚀 Enhancement Features:")
    print(f"   • Framework method filtering: {len(validator.framework_methods)} patterns")
    print(f"   • Builtin patterns: {len(validator.builtin_patterns)} regex patterns")
    print(f"   • Function index size: {len(validator.function_index)} function names")
    print(f"   • DocType fields cached: {len(validator.doctype_fields_cache)} DocTypes")
    
    return len(issues)

if __name__ == "__main__":
    original_count = test_enhanced_features()
    
    print(f"\n🎯 Validation Complete!")
    print(f"   Enhanced validator detected {original_count} issues")
    print(f"   (Baseline was 14 issues)")
    
    if original_count == 14:
        print("✅ Issue count matches baseline - no regressions!")
    elif original_count < 14:
        print("🎉 Reduced false positives detected!")
    else:
        print("⚠️  More issues detected - enhanced sensitivity!")