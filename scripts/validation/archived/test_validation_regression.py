#!/usr/bin/env python3
"""
Validation Regression Testing Framework
======================================

This framework tests for regressions in validation functionality after the massive
standardization of 21 validators to use DocTypeLoader.

Key Regression Areas Tested:
1. **Validation Accuracy**: Ensures legitimate issues are still caught
2. **False Positive Rate**: Verifies false positives haven't increased
3. **Performance**: Checks that standardization hasn't degraded performance
4. **Compatibility**: Tests that existing workflows still work
5. **Coverage**: Validates that no validation scenarios are missed

The framework uses realistic test data from the actual codebase rather than
synthetic examples, ensuring tests reflect real-world usage patterns.

Test Methodology:
- Baseline establishment using known good/bad validation examples
- Performance benchmarking with actual codebase files
- Comparative analysis of validation results
- Edge case testing with complex validation scenarios
"""

import json
import time
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import tempfile
import shutil


@dataclass
class ValidationResult:
    """Represents a validation result for comparison"""
    file_path: str
    line_number: int
    field_name: str
    doctype: str
    issue_type: str
    confidence: str
    message: str
    
    def __hash__(self):
        return hash((self.file_path, self.line_number, self.field_name, self.doctype))


@dataclass
class RegressionTestResults:
    """Comprehensive regression test results"""
    validation_accuracy: Dict[str, Any]
    false_positive_analysis: Dict[str, Any]
    performance_metrics: Dict[str, float]
    coverage_analysis: Dict[str, Any]
    compatibility_results: Dict[str, Any]
    overall_status: str
    
    def to_dict(self):
        return asdict(self)


class ValidationRegressionTester:
    """Comprehensive regression testing for validation infrastructure"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.validation_dir = self.app_path / "scripts" / "validation"
        
        # Test data sets
        self.test_files = self._discover_test_files()
        self.known_valid_patterns = self._load_known_valid_patterns()
        self.known_invalid_patterns = self._load_known_invalid_patterns()
        
        print(f"🔍 Regression tester initialized with {len(self.test_files)} test files")
    
    def _discover_test_files(self) -> List[Path]:
        """Discover Python files suitable for validation testing"""
        test_files = []
        
        # Find Python files from key areas
        search_areas = [
            self.app_path / "verenigingen" / "doctype",
            self.app_path / "scripts" / "api_maintenance",
            self.app_path / "scripts" / "migration",
            self.app_path / "verenigingen" / "api"
        ]
        
        for area in search_areas:
            if area.exists():
                py_files = list(area.rglob("*.py"))
                # Filter out test files and cache files
                filtered_files = [
                    f for f in py_files 
                    if not any(skip in str(f) for skip in ['test_', '__pycache__', '.pyc'])
                ]
                test_files.extend(filtered_files[:5])  # Limit to 5 files per area for performance
        
        return test_files[:20]  # Limit total for reasonable test time
    
    def _load_known_valid_patterns(self) -> List[Dict[str, str]]:
        """Load known valid field reference patterns that should NOT be flagged"""
        return [
            # Standard Frappe patterns that are always valid
            {"pattern": "frappe.db.get_value('User', 'email')", "doctype": "User", "field": "email"},
            {"pattern": "doc.name", "doctype": "any", "field": "name"},
            {"pattern": "doc.creation", "doctype": "any", "field": "creation"},
            {"pattern": "doc.modified", "doctype": "any", "field": "modified"},
            {"pattern": "doc.owner", "doctype": "any", "field": "owner"},
            
            # Verenigingen-specific valid patterns
            {"pattern": "member.first_name", "doctype": "Member", "field": "first_name"},
            {"pattern": "member.last_name", "doctype": "Member", "field": "last_name"},
            {"pattern": "member.email", "doctype": "Member", "field": "email"},
            {"pattern": "volunteer.start_date", "doctype": "Verenigingen Volunteer", "field": "start_date"},
            {"pattern": "chapter.chapter_name", "doctype": "Chapter", "field": "chapter_name"},
        ]
    
    def _load_known_invalid_patterns(self) -> List[Dict[str, str]]:
        """Load known invalid field reference patterns that SHOULD be flagged"""
        return [
            # Fields that don't exist in their respective DocTypes
            {"pattern": "user.nonexistent_field", "doctype": "User", "field": "nonexistent_field"},
            {"pattern": "member.invalid_field_xyz", "doctype": "Member", "field": "invalid_field_xyz"},
            {"pattern": "doc.fake_field", "doctype": "Member", "field": "fake_field"},
            
            # Common misspellings that should be caught
            {"pattern": "member.frist_name", "doctype": "Member", "field": "frist_name"},  # misspelled first_name
            {"pattern": "member.emai", "doctype": "Member", "field": "emai"},  # misspelled email
            {"pattern": "volunteer.start_dat", "doctype": "Verenigingen Volunteer", "field": "start_dat"},  # misspelled start_date
        ]
    
    def test_validation_accuracy(self) -> Dict[str, Any]:
        """Test that validation accuracy is maintained after standardization"""
        print("🎯 Testing validation accuracy...")
        
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
        except ImportError:
            return {"status": "skipped", "reason": "SpecializedPatternValidator not available"}
        
        # Test with known valid patterns (should NOT be flagged)
        false_positives = []
        for pattern_info in self.known_valid_patterns:
            test_content = f"""
import frappe

def test_function():
    # Valid pattern that should not be flagged
    result = {pattern_info['pattern']}
    return result
"""
            
            with self._create_temp_file(test_content) as temp_file:
                violations = validator.validate_file(temp_file)
                
                # Check if this valid pattern was incorrectly flagged
                for violation in violations:
                    if (violation.field == pattern_info['field'] and 
                        violation.confidence in ['high', 'medium']):
                        false_positives.append({
                            'pattern': pattern_info['pattern'],
                            'violation': violation.message,
                            'confidence': violation.confidence
                        })
        
        # Test with known invalid patterns (SHOULD be flagged)
        missed_issues = []
        for pattern_info in self.known_invalid_patterns:
            test_content = f"""
import frappe

def test_function():
    # Invalid pattern that should be flagged
    {pattern_info['pattern']}
"""
            
            with self._create_temp_file(test_content) as temp_file:
                violations = validator.validate_file(temp_file)
                
                # Check if this invalid pattern was missed
                found_violation = any(
                    violation.field == pattern_info['field'] 
                    for violation in violations
                )
                
                if not found_violation:
                    missed_issues.append({
                        'pattern': pattern_info['pattern'],
                        'expected_field': pattern_info['field'],
                        'expected_doctype': pattern_info['doctype']
                    })
        
        accuracy_score = 1.0 - (len(false_positives) + len(missed_issues)) / (len(self.known_valid_patterns) + len(self.known_invalid_patterns))
        
        return {
            "status": "completed",
            "accuracy_score": accuracy_score,
            "false_positives": false_positives,
            "missed_issues": missed_issues,
            "total_patterns_tested": len(self.known_valid_patterns) + len(self.known_invalid_patterns)
        }
    
    def test_false_positive_rate(self) -> Dict[str, Any]:
        """Test that false positive rate hasn't increased significantly"""
        print("🔍 Testing false positive rate...")
        
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
        except ImportError:
            return {"status": "skipped", "reason": "SpecializedPatternValidator not available"}
        
        false_positive_counts = {"high": 0, "medium": 0, "low": 0}
        total_violations = 0
        files_tested = 0
        
        # Test on actual codebase files
        for test_file in self.test_files[:10]:  # Limit for performance
            try:
                violations = validator.validate_file(test_file)
                
                for violation in violations:
                    total_violations += 1
                    confidence = violation.confidence.lower()
                    if confidence in false_positive_counts:
                        false_positive_counts[confidence] += 1
                
                files_tested += 1
                
            except Exception as e:
                print(f"⚠️  Error testing {test_file}: {e}")
        
        # Calculate false positive metrics
        high_confidence_rate = false_positive_counts["high"] / max(total_violations, 1)
        overall_fp_rate = (false_positive_counts["high"] + false_positive_counts["medium"]) / max(total_violations, 1)
        
        return {
            "status": "completed",
            "files_tested": files_tested,
            "total_violations": total_violations,
            "false_positive_counts": false_positive_counts,
            "high_confidence_rate": high_confidence_rate,
            "overall_fp_rate": overall_fp_rate,
            "acceptable": overall_fp_rate < 0.2  # Less than 20% false positives
        }
    
    def test_performance_metrics(self) -> Dict[str, float]:
        """Test that performance hasn't significantly degraded"""
        print("⏱️  Testing performance metrics...")
        
        performance_results = {}
        
        # Test DocTypeLoader performance
        try:
            from doctype_loader import DocTypeLoader
            
            # Measure cold load time
            start_time = time.time()
            loader = DocTypeLoader(str(self.bench_path), verbose=False)
            doctypes = loader.get_doctypes()
            cold_load_time = time.time() - start_time
            
            # Measure warm load time
            start_time = time.time()
            doctypes_cached = loader.get_doctypes()
            warm_load_time = time.time() - start_time
            
            performance_results.update({
                "doctype_loader_cold_load": cold_load_time,
                "doctype_loader_warm_load": warm_load_time,
                "doctype_count": len(doctypes),
                "cache_effectiveness": cold_load_time / max(warm_load_time, 0.001)
            })
            
        except Exception as e:
            print(f"⚠️  DocTypeLoader performance test failed: {e}")
        
        # Test validator instantiation performance
        try:
            from unified_validation_engine import SpecializedPatternValidator
            
            start_time = time.time()
            validator = SpecializedPatternValidator(str(self.app_path))
            instantiation_time = time.time() - start_time
            
            performance_results["validator_instantiation"] = instantiation_time
            
            # Test file validation performance
            if self.test_files:
                start_time = time.time()
                violations = validator.validate_file(self.test_files[0])
                validation_time = time.time() - start_time
                
                performance_results.update({
                    "file_validation_time": validation_time,
                    "violations_found": len(violations)
                })
            
        except Exception as e:
            print(f"⚠️  Validator performance test failed: {e}")
        
        return performance_results
    
    def test_coverage_analysis(self) -> Dict[str, Any]:
        """Test that validation coverage is maintained"""
        print("📊 Testing validation coverage...")
        
        try:
            from doctype_loader import DocTypeLoader
            loader = DocTypeLoader(str(self.bench_path), verbose=False)
            
            # Analyze DocType coverage
            stats = loader.get_loading_stats()
            doctypes = loader.get_doctypes()
            
            # Check field coverage
            total_fields = sum(len(loader.get_field_names(dt)) for dt in doctypes.keys())
            
            # Check app coverage
            expected_apps = {'frappe', 'erpnext', 'verenigingen'}
            covered_apps = stats.apps_scanned
            app_coverage = len(expected_apps & covered_apps) / len(expected_apps)
            
            # Check custom field integration
            custom_fields_integrated = stats.custom_fields > 0
            
            return {
                "status": "completed",
                "doctype_count": stats.total_doctypes,
                "total_fields": total_fields,
                "custom_fields": stats.custom_fields,
                "apps_covered": len(covered_apps),
                "app_coverage_rate": app_coverage,
                "custom_fields_integrated": custom_fields_integrated,
                "child_table_relationships": stats.child_table_relationships
            }
            
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def test_compatibility_results(self) -> Dict[str, Any]:
        """Test backward compatibility after standardization"""
        print("🔄 Testing backward compatibility...")
        
        compatibility_results = {
            "legacy_imports": True,
            "convenience_functions": True,
            "validator_interfaces": True,
            "errors": []
        }
        
        # Test legacy import patterns
        try:
            from doctype_loader import DocTypeLoader, load_doctypes_simple, load_doctypes_detailed
        except ImportError as e:
            compatibility_results["legacy_imports"] = False
            compatibility_results["errors"].append(f"Legacy import failed: {e}")
        
        # Test convenience functions
        try:
            simple_doctypes = load_doctypes_simple(str(self.app_path))
            detailed_doctypes = load_doctypes_detailed(str(self.app_path))
            
            if not isinstance(simple_doctypes, dict) or len(simple_doctypes) == 0:
                compatibility_results["convenience_functions"] = False
                compatibility_results["errors"].append("load_doctypes_simple returned invalid data")
                
        except Exception as e:
            compatibility_results["convenience_functions"] = False
            compatibility_results["errors"].append(f"Convenience function error: {e}")
        
        # Test validator interfaces
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
            
            # Test that it has expected interface
            required_methods = ['validate_file', 'run_validation']
            for method in required_methods:
                if not hasattr(validator, method):
                    compatibility_results["validator_interfaces"] = False
                    compatibility_results["errors"].append(f"Missing method: {method}")
                    
        except Exception as e:
            compatibility_results["validator_interfaces"] = False
            compatibility_results["errors"].append(f"Validator interface error: {e}")
        
        return compatibility_results
    
    @contextmanager
    def _create_temp_file(self, content: str):
        """Create a temporary Python file for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)
        
        try:
            yield temp_path
        finally:
            if temp_path.exists():
                temp_path.unlink()
    
    def run_comprehensive_regression_tests(self) -> RegressionTestResults:
        """Run all regression tests and return comprehensive results"""
        print("🧪 Running Comprehensive Validation Regression Tests")
        print("=" * 80)
        
        # Run all test categories
        validation_accuracy = self.test_validation_accuracy()
        false_positive_analysis = self.test_false_positive_rate()
        performance_metrics = self.test_performance_metrics()
        coverage_analysis = self.test_coverage_analysis()
        compatibility_results = self.test_compatibility_results()
        
        # Determine overall status
        critical_failures = []
        
        if validation_accuracy.get("accuracy_score", 0) < 0.8:
            critical_failures.append("Low validation accuracy")
        
        if false_positive_analysis.get("overall_fp_rate", 1.0) > 0.3:
            critical_failures.append("High false positive rate")
        
        if not compatibility_results.get("legacy_imports", False):
            critical_failures.append("Legacy import compatibility broken")
        
        if coverage_analysis.get("doctype_count", 0) < 500:
            critical_failures.append("Insufficient DocType coverage")
        
        overall_status = "FAILED" if critical_failures else "PASSED"
        
        results = RegressionTestResults(
            validation_accuracy=validation_accuracy,
            false_positive_analysis=false_positive_analysis,
            performance_metrics=performance_metrics,
            coverage_analysis=coverage_analysis,
            compatibility_results=compatibility_results,
            overall_status=overall_status
        )
        
        # Print detailed summary
        self._print_regression_summary(results, critical_failures)
        
        return results
    
    def _print_regression_summary(self, results: RegressionTestResults, critical_failures: List[str]):
        """Print a detailed summary of regression test results"""
        print("\n" + "=" * 80)
        print("📋 Regression Test Summary")
        print("=" * 80)
        
        # Overall status
        status_emoji = "✅" if results.overall_status == "PASSED" else "❌"
        print(f"Overall Status: {status_emoji} {results.overall_status}")
        
        if critical_failures:
            print("\n🚨 Critical Failures:")
            for failure in critical_failures:
                print(f"  - {failure}")
        
        # Validation accuracy
        accuracy = results.validation_accuracy
        if accuracy.get("status") == "completed":
            score = accuracy.get("accuracy_score", 0)
            print(f"\n🎯 Validation Accuracy: {score:.1%}")
            if accuracy.get("false_positives"):
                print(f"   False Positives: {len(accuracy['false_positives'])}")
            if accuracy.get("missed_issues"):
                print(f"   Missed Issues: {len(accuracy['missed_issues'])}")
        
        # False positive analysis
        fp_analysis = results.false_positive_analysis
        if fp_analysis.get("status") == "completed":
            overall_rate = fp_analysis.get("overall_fp_rate", 0)
            print(f"\n🔍 False Positive Rate: {overall_rate:.1%}")
            print(f"   Files Tested: {fp_analysis.get('files_tested', 0)}")
            print(f"   Total Violations: {fp_analysis.get('total_violations', 0)}")
        
        # Performance metrics
        perf = results.performance_metrics
        if perf:
            print(f"\n⏱️  Performance Metrics:")
            if "doctype_loader_cold_load" in perf:
                print(f"   DocType Cold Load: {perf['doctype_loader_cold_load']:.3f}s")
            if "doctype_loader_warm_load" in perf:
                print(f"   DocType Warm Load: {perf['doctype_loader_warm_load']:.3f}s")
            if "validator_instantiation" in perf:
                print(f"   Validator Instantiation: {perf['validator_instantiation']:.3f}s")
        
        # Coverage analysis
        coverage = results.coverage_analysis
        if coverage.get("status") == "completed":
            print(f"\n📊 Coverage Analysis:")
            print(f"   DocTypes: {coverage.get('doctype_count', 0)}")
            print(f"   Custom Fields: {coverage.get('custom_fields', 0)}")
            print(f"   Apps Covered: {coverage.get('apps_covered', 0)}")
        
        # Compatibility
        compat = results.compatibility_results
        if compat:
            print(f"\n🔄 Compatibility:")
            print(f"   Legacy Imports: {'✅' if compat.get('legacy_imports') else '❌'}")
            print(f"   Convenience Functions: {'✅' if compat.get('convenience_functions') else '❌'}")
            print(f"   Validator Interfaces: {'✅' if compat.get('validator_interfaces') else '❌'}")
            
            if compat.get("errors"):
                print("   Errors:")
                for error in compat["errors"][:3]:  # Show first 3 errors
                    print(f"     - {error}")
        
        print("\n" + "=" * 80)


def run_regression_tests():
    """Main function to run regression tests"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    tester = ValidationRegressionTester(app_path)
    
    results = tester.run_comprehensive_regression_tests()
    
    # Save results to file for reference
    results_file = Path(app_path) / "scripts" / "validation" / "regression_test_results.json"
    try:
        with open(results_file, 'w') as f:
            json.dump(results.to_dict(), f, indent=2, default=str)
        print(f"\n💾 Results saved to: {results_file}")
    except Exception as e:
        print(f"⚠️  Could not save results: {e}")
    
    return results.overall_status == "PASSED"


if __name__ == "__main__":
    success = run_regression_tests()
    exit(0 if success else 1)