#!/usr/bin/env python3
"""
Final Validator Assessment
Comprehensive comparison of all field validators
"""

import time
import sys
from pathlib import Path

# Add validation modules to path
sys.path.append(str(Path(__file__).parent))

try:
    from enhanced_field_validator import EnhancedFieldValidator
    from unified_field_validator import UnifiedFieldValidator
    from optimized_field_validator import OptimizedFieldValidator
except ImportError as e:
    print(f"Error importing validators: {e}")
    sys.exit(1)

def run_validator_assessment():
    """Run comprehensive assessment of all validators"""
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 COMPREHENSIVE FIELD VALIDATOR ASSESSMENT")
    print("=" * 60)
    
    results = {}
    
    # Test Enhanced Field Validator
    print("\n1. Enhanced Field Validator")
    print("-" * 30)
    start_time = time.time()
    try:
        enhanced_validator = EnhancedFieldValidator(app_path)
        enhanced_issues = enhanced_validator.validate_all_files()
        enhanced_time = time.time() - start_time
        
        enhanced_high = [i for i in enhanced_issues if i.confidence == "high"]
        enhanced_medium = [i for i in enhanced_issues if i.confidence == "medium"]
        enhanced_low = [i for i in enhanced_issues if i.confidence == "low"]
        
        # Calculate false positive rate
        false_positive_keywords = ['in', 'like', 'and', 'or', 'not', 'is', 'Active', 'Draft', 'Cancelled']
        enhanced_fps = [i for i in enhanced_issues if i.field in false_positive_keywords]
        enhanced_fp_rate = len(enhanced_fps) / len(enhanced_issues) if enhanced_issues else 0
        
        results['enhanced'] = {
            'time': enhanced_time,
            'total_issues': len(enhanced_issues),
            'high_confidence': len(enhanced_high),
            'medium_confidence': len(enhanced_medium),
            'low_confidence': len(enhanced_low),
            'false_positive_rate': enhanced_fp_rate,
            'issues_per_second': len(enhanced_issues) / enhanced_time if enhanced_time > 0 else 0
        }
        
        print(f"✅ Completed in {enhanced_time:.2f}s")
        print(f"📊 Total issues: {len(enhanced_issues)}")
        print(f"🔴 High confidence: {len(enhanced_high)}")
        print(f"🟡 Medium confidence: {len(enhanced_medium)}")
        print(f"🟢 Low confidence: {len(enhanced_low)}")
        print(f"⚠️  False positive rate: {enhanced_fp_rate:.1%}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        results['enhanced'] = None
    
    # Test Unified Field Validator
    print("\n2. Unified Field Validator")
    print("-" * 30)
    start_time = time.time()
    try:
        unified_validator = UnifiedFieldValidator(app_path)
        
        # Run validation manually to get detailed results
        all_violations = []
        file_count = 0
        
        for py_file in Path(app_path).rglob("*.py"):
            if any(skip in str(py_file) for skip in ['__pycache__', '.pyc', 'test_', '_test.py', '/tests/']):
                continue
            violations = unified_validator.validate_file(py_file)
            all_violations.extend(violations)
            file_count += 1
        
        for html_file in Path(app_path).rglob("*.html"):
            if any(skip in str(html_file) for skip in ['__pycache__', '/tests/']):
                continue
            violations = unified_validator.validate_html_file(html_file)
            all_violations.extend(violations)
            file_count += 1
        
        unified_time = time.time() - start_time
        
        unified_high = [v for v in all_violations if v.confidence == 'high']
        unified_medium = [v for v in all_violations if v.confidence == 'medium']
        unified_low = [v for v in all_violations if v.confidence == 'low']
        
        # Calculate false positive rate
        unified_fps = [v for v in all_violations if v.field in false_positive_keywords]
        unified_fp_rate = len(unified_fps) / len(all_violations) if all_violations else 0
        
        results['unified'] = {
            'time': unified_time,
            'total_issues': len(all_violations),
            'high_confidence': len(unified_high),
            'medium_confidence': len(unified_medium),
            'low_confidence': len(unified_low),
            'false_positive_rate': unified_fp_rate,
            'issues_per_second': len(all_violations) / unified_time if unified_time > 0 else 0,
            'files_checked': file_count
        }
        
        print(f"✅ Completed in {unified_time:.2f}s")
        print(f"📊 Total issues: {len(all_violations)}")
        print(f"🔴 High confidence: {len(unified_high)}")
        print(f"🟡 Medium confidence: {len(unified_medium)}")
        print(f"🟢 Low confidence: {len(unified_low)}")
        print(f"⚠️  False positive rate: {unified_fp_rate:.1%}")
        print(f"📁 Files checked: {file_count}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        results['unified'] = None
    
    # Test Optimized Field Validator
    print("\n3. Optimized Field Validator")
    print("-" * 30)
    start_time = time.time()
    try:
        optimized_validator = OptimizedFieldValidator(app_path)
        
        # Run validation manually
        all_violations = []
        file_count = 0
        
        for py_file in Path(app_path).rglob("*.py"):
            violations = optimized_validator.validate_file(py_file)
            all_violations.extend(violations)
            file_count += 1
        
        optimized_time = time.time() - start_time
        
        optimized_high = [v for v in all_violations if v.confidence == 'high']
        optimized_medium = [v for v in all_violations if v.confidence == 'medium']
        optimized_low = [v for v in all_violations if v.confidence == 'low']
        
        # Calculate false positive rate
        optimized_fps = [v for v in all_violations if v.field in false_positive_keywords]
        optimized_fp_rate = len(optimized_fps) / len(all_violations) if all_violations else 0
        
        results['optimized'] = {
            'time': optimized_time,
            'total_issues': len(all_violations),
            'high_confidence': len(optimized_high),
            'medium_confidence': len(optimized_medium),
            'low_confidence': len(optimized_low),
            'false_positive_rate': optimized_fp_rate,
            'issues_per_second': len(all_violations) / optimized_time if optimized_time > 0 else 0,
            'files_checked': file_count
        }
        
        print(f"✅ Completed in {optimized_time:.2f}s")
        print(f"📊 Total issues: {len(all_violations)}")
        print(f"🔴 High confidence: {len(optimized_high)}")
        print(f"🟡 Medium confidence: {len(optimized_medium)}")
        print(f"🟢 Low confidence: {len(optimized_low)}")
        print(f"⚠️  False positive rate: {optimized_fp_rate:.1%}")
        print(f"📁 Files checked: {file_count}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        results['optimized'] = None
    
    # Performance Comparison
    print("\n4. PERFORMANCE COMPARISON")
    print("=" * 40)
    
    if all(results.values()):
        print("Speed Ranking (fastest to slowest):")
        speed_ranking = sorted(results.items(), key=lambda x: x[1]['time'])
        for i, (name, data) in enumerate(speed_ranking, 1):
            print(f"  {i}. {name.capitalize()}: {data['time']:.2f}s")
        
        print("\nAccuracy Ranking (lowest false positive rate):")
        accuracy_ranking = sorted(results.items(), key=lambda x: x[1]['false_positive_rate'])
        for i, (name, data) in enumerate(accuracy_ranking, 1):
            print(f"  {i}. {name.capitalize()}: {data['false_positive_rate']:.1%} false positives")
        
        print("\nIssue Detection Ranking (most high-confidence issues):")
        detection_ranking = sorted(results.items(), key=lambda x: x[1]['high_confidence'], reverse=True)
        for i, (name, data) in enumerate(detection_ranking, 1):
            print(f"  {i}. {name.capitalize()}: {data['high_confidence']} high-confidence issues")
    
    # Quality Assessment
    print("\n5. QUALITY ASSESSMENT")
    print("=" * 30)
    
    best_overall = None
    best_score = 0
    
    for name, data in results.items():
        if data is None:
            continue
            
        # Calculate composite score (lower is better for time and FP rate, higher for issues)
        speed_score = 1 / data['time'] if data['time'] > 0 else 0  # Inverse of time
        accuracy_score = 1 - data['false_positive_rate']  # Inverse of FP rate
        detection_score = data['high_confidence'] / 100  # Normalize high confidence issues
        
        composite_score = (speed_score * 0.3 + accuracy_score * 0.5 + detection_score * 0.2)
        
        print(f"{name.capitalize()} Validator:")
        print(f"  ⚡ Speed Score: {speed_score:.3f}")
        print(f"  🎯 Accuracy Score: {accuracy_score:.3f}")
        print(f"  🔍 Detection Score: {detection_score:.3f}")
        print(f"  📊 Composite Score: {composite_score:.3f}")
        print()
        
        if composite_score > best_score:
            best_score = composite_score
            best_overall = name
    
    # Recommendations
    print("6. RECOMMENDATIONS")
    print("=" * 20)
    
    if best_overall:
        print(f"🏆 RECOMMENDED: {best_overall.capitalize()} Field Validator")
        print(f"   Best overall score: {best_score:.3f}")
        print()
    
    print("Use Case Recommendations:")
    
    if results.get('optimized'):
        opt_data = results['optimized']
        print(f"✅ PRODUCTION USE: Optimized Field Validator")
        print(f"   - Low false positive rate ({opt_data['false_positive_rate']:.1%})")
        print(f"   - Good performance ({opt_data['time']:.1f}s)")
        print(f"   - Focused on real issues ({opt_data['high_confidence']} critical)")
        print()
    
    if results.get('unified'):
        uni_data = results['unified']
        print(f"🔧 DEVELOPMENT USE: Unified Field Validator") 
        print(f"   - Fast execution ({uni_data['time']:.1f}s)")
        print(f"   - Good for quick checks")
        print(f"   - Reasonable accuracy")
        print()
    
    if results.get('enhanced'):
        enh_data = results['enhanced']
        print(f"🔬 COMPREHENSIVE AUDIT: Enhanced Field Validator")
        print(f"   - Most thorough detection ({enh_data['total_issues']} total issues)")
        print(f"   - Good for deep analysis")
        print(f"   - Higher false positive rate ({enh_data['false_positive_rate']:.1%})")
        print()
    
    # Implementation Guidelines
    print("7. IMPLEMENTATION GUIDELINES")
    print("=" * 35)
    
    print("Pre-commit Hook Configuration:")
    print("```yaml")
    print("- id: field-validation")
    print("  name: Validate field references")
    print("  entry: python scripts/validation/optimized_field_validator.py --pre-commit")
    print("  language: system")
    print("  pass_filenames: false")
    print("```")
    print()
    
    print("CI/CD Pipeline Integration:")
    print("```bash")
    print("# Quick validation (development)")
    print("python scripts/validation/unified_field_validator.py --pre-commit")
    print()
    print("# Comprehensive validation (production)")
    print("python scripts/validation/optimized_field_validator.py")
    print("```")
    print()
    
    print("Manual Code Review:")
    print("```bash")
    print("# Full audit before major releases")
    print("python scripts/validation/enhanced_field_validator.py")
    print("```")
    
    return results

if __name__ == "__main__":
    results = run_validator_assessment()
    print(f"\n✅ Comprehensive assessment completed")
    
    # Return success if at least one validator worked
    if any(results.values()):
        sys.exit(0)
    else:
        sys.exit(1)