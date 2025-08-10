#!/usr/bin/env python3
"""
Test script to evaluate validator performance and accuracy
"""

import time
import sys
from pathlib import Path

# Add the validation modules to path
sys.path.append(str(Path(__file__).parent))

try:
    from doctype_field_validator import DocTypeFieldValidator
    from unified_field_validator import UnifiedFieldValidator
except ImportError as e:
    print(f"Error importing validators: {e}")
    sys.exit(1)

def test_validator_performance():
    """Test both validators and compare results"""
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Testing Field Validators Performance and Accuracy")
    print("=" * 60)
    
    # Test DocType Field Validator
    print("\n1. Testing DocType Field Validator...")
    start_time = time.time()
    
    try:
        doctype_validator = DocTypeFieldValidator(app_path)
        doctype_issues = doctype_validator.validate_all_files()
        doctype_time = time.time() - start_time
        
        # Categorize issues
        doctype_high = [i for i in doctype_issues if i.confidence == "high"]
        doctype_medium = [i for i in doctype_issues if i.confidence == "medium"]
        doctype_low = [i for i in doctype_issues if i.confidence == "low"]
        
        print(f"✅ DocType Field Validator completed in {doctype_time:.2f} seconds")
        print(f"   📊 Total issues: {len(doctype_issues)}")
        print(f"   🔴 High confidence: {len(doctype_high)}")
        print(f"   🟡 Medium confidence: {len(doctype_medium)}")
        print(f"   🟢 Low confidence: {len(doctype_low)}")
        
    except Exception as e:
        print(f"❌ DocType Field Validator failed: {e}")
        doctype_issues = []
        doctype_time = 0
    
    # Test Unified Field Validator
    print("\n2. Testing Unified Field Validator...")
    start_time = time.time()
    
    try:
        unified_validator = UnifiedFieldValidator(app_path)
        
        # Manually run validation to get issues
        all_violations = []
        file_count = 0
        
        # Validate Python files
        for py_file in Path(app_path).rglob("*.py"):
            if any(skip in str(py_file) for skip in ['__pycache__', '.pyc', 'test_', '_test.py', '/tests/']):
                continue
            violations = unified_validator.validate_file(py_file)
            all_violations.extend(violations)
            file_count += 1
        
        # Validate HTML files
        for html_file in Path(app_path).rglob("*.html"):
            if any(skip in str(html_file) for skip in ['__pycache__', '/tests/']):
                continue
            violations = unified_validator.validate_html_file(html_file)
            all_violations.extend(violations)
            file_count += 1
        
        unified_time = time.time() - start_time
        
        # Categorize issues
        unified_high = [v for v in all_violations if v.confidence == 'high']
        unified_medium = [v for v in all_violations if v.confidence == 'medium']
        unified_low = [v for v in all_violations if v.confidence == 'low']
        
        print(f"✅ Unified Validator completed in {unified_time:.2f} seconds")
        print(f"   📊 Total issues: {len(all_violations)}")
        print(f"   🔴 High confidence: {len(unified_high)}")
        print(f"   🟡 Medium confidence: {len(unified_medium)}")
        print(f"   🟢 Low confidence: {len(unified_low)}")
        print(f"   📁 Files checked: {file_count}")
        
    except Exception as e:
        print(f"❌ Unified Validator failed: {e}")
        all_violations = []
        unified_time = 0
    
    # Performance Comparison
    print("\n3. Performance Comparison")
    print("-" * 30)
    if doctype_time > 0 and unified_time > 0:
        if unified_time < doctype_time:
            speedup = doctype_time / unified_time
            print(f"🚀 Unified Validator is {speedup:.1f}x faster")
        else:
            slowdown = unified_time / doctype_time
            print(f"⚠️  Unified Validator is {slowdown:.1f}x slower")
    
    # Issue Quality Analysis
    print("\n4. Issue Quality Analysis")
    print("-" * 30)
    
    # Common issue types to check for false positives
    common_false_positives = ['in', 'like', 'and', 'or', 'not', 'is', 'as', 'Active', 'Draft', 'Cancelled']
    
    if doctype_issues:
        doctype_fps = [i for i in doctype_issues if i.field in common_false_positives]
        print(f"DocType Field Validator - Potential false positives: {len(doctype_fps)}/{len(doctype_issues)} ({len(doctype_fps)/len(doctype_issues)*100:.1f}%)")
        
        # Show examples of potential false positives
        if doctype_fps:
            print("   Examples:")
            for fp in doctype_fps[:3]:
                print(f"     - '{fp.field}' in {fp.doctype} ({fp.issue_type})")
    
    if all_violations:
        unified_fps = [v for v in all_violations if v.field in common_false_positives]
        print(f"Unified Validator - Potential false positives: {len(unified_fps)}/{len(all_violations)} ({len(unified_fps)/len(all_violations)*100:.1f}%)")
        
        # Show examples of potential false positives
        if unified_fps:
            print("   Examples:")
            for fp in unified_fps[:3]:
                print(f"     - '{fp.field}' in {fp.doctype} ({fp.issue_type})")
    
    # Specific pattern analysis
    print("\n5. Pattern Analysis")
    print("-" * 20)
    
    if doctype_issues:
        # Group by issue type
        doctype_types = {}
        for issue in doctype_issues:
            issue_type = issue.issue_type
            if issue_type not in doctype_types:
                doctype_types[issue_type] = 0
            doctype_types[issue_type] += 1
        
        print("DocType Field Validator issue types:")
        for issue_type, count in sorted(doctype_types.items(), key=lambda x: x[1], reverse=True):
            print(f"   {issue_type}: {count}")
    
    if all_violations:
        # Group by issue type
        unified_types = {}
        for violation in all_violations:
            issue_type = violation.issue_type
            if issue_type not in unified_types:
                unified_types[issue_type] = 0
            unified_types[issue_type] += 1
        
        print("\nUnified Validator issue types:")
        for issue_type, count in sorted(unified_types.items(), key=lambda x: x[1], reverse=True):
            print(f"   {issue_type}: {count}")
    
    # Recommendations
    print("\n6. Recommendations")
    print("-" * 20)
    
    print("Based on the analysis:")
    
    if doctype_time > 0 and unified_time > 0:
        if unified_time < doctype_time:
            print(f"✅ Unified Validator is more efficient ({unified_time:.1f}s vs {doctype_time:.1f}s)")
        
    if doctype_issues and all_violations:
        doctype_fp_rate = len([i for i in doctype_issues if i.field in common_false_positives]) / len(doctype_issues)
        unified_fp_rate = len([v for v in all_violations if v.field in common_false_positives]) / len(all_violations)
        
        if unified_fp_rate < doctype_fp_rate:
            print(f"✅ Unified Validator has lower false positive rate ({unified_fp_rate:.1%} vs {doctype_fp_rate:.1%})")
        else:
            print(f"⚠️  DocType Field Validator has lower false positive rate ({doctype_fp_rate:.1%} vs {unified_fp_rate:.1%})")
    
    # Suggested optimizations
    print("\n7. Suggested Optimizations")
    print("-" * 30)
    print("To reduce false positives:")
    print("- Add SQL operator filtering: ['in', 'like', 'and', 'or', 'not', 'is']")
    print("- Add status value filtering: ['Active', 'Draft', 'Cancelled', 'Approved']")
    print("- Improve doctype context detection")
    print("- Add field existence validation before flagging")
    print("- Consider field aliases and virtual fields")
    
    return {
        'doctype': {
            'time': doctype_time,
            'issues': len(doctype_issues) if doctype_issues else 0,
            'high_confidence': len(doctype_high) if doctype_issues else 0
        },
        'unified': {
            'time': unified_time,
            'issues': len(all_violations) if all_violations else 0,
            'high_confidence': len(unified_high) if all_violations else 0
        }
    }

if __name__ == "__main__":
    results = test_validator_performance()
    
    # Exit with success
    print(f"\n✅ Validator testing completed successfully")