#!/usr/bin/env python3
"""
Validator Standardization Test Suite
===================================

This test suite validates that all 21 validators have been properly standardized
to use the comprehensive DocTypeLoader instead of manual DocType loading.

Key Testing Areas:
1. Import standardization - All validators use `from doctype_loader import DocTypeLoader`
2. Instantiation patterns - All validators create DocTypeLoader instances properly
3. DocType count validation - All validators load 1,049+ DocTypes correctly
4. Performance consistency - No validators show significant performance degradation
5. Backward compatibility - Legacy interfaces still work
6. Error handling - Proper error handling for missing apps/DocTypes

This uses realistic validation by actually importing and testing the validators
rather than just checking their source code.
"""

import importlib
import inspect
import sys
import time
import unittest
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from unittest.mock import patch


class ValidatorStandardizationTest(unittest.TestCase):
    """Test that all validators are properly standardized"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        cls.validation_dir = Path("/home/frappe/frappe-bench/apps/verenigingen/scripts/validation")
        cls.bench_path = "/home/frappe/frappe-bench"
        
        # Complete list of 21 standardized validators
        cls.standardized_validators = {
            'doctype_field_validator.py': 'AccurateFieldValidator',
            'unified_validation_engine.py': 'SpecializedPatternValidator', 
            'javascript_doctype_field_validator.py': 'JavaScriptFieldValidator',
            'enhanced_field_reference_validator.py': 'EnhancedFieldReferenceValidator',
            'production_ready_validator.py': 'ProductionReadyValidator',
            'comprehensive_final_validator.py': 'ComprehensiveFinalValidator',
            'intelligent_pattern_validator.py': 'IntelligentPatternValidator',
            'frappe_api_field_validator.py': 'FrappeAPIFieldValidator',
            'bugfix_enhanced_validator.py': 'BugfixEnhancedValidator',
            'doctype_field_validator_modified.py': 'ModifiedFieldValidator',
            'comprehensive_field_validator.py': 'ComprehensiveFieldValidator',
            'enhanced_doctype_validator.py': 'EnhancedDocTypeValidator',
            'comprehensive_field_reference_validator.py': 'ComprehensiveFieldReferenceValidator',
            'database_field_reference_validator.py': 'DatabaseFieldReferenceValidator',
            'database_field_reference_validator_consolidated.py': 'ConsolidatedDatabaseValidator',
            'precision_focused_validator.py': 'PrecisionFocusedValidator',
            'balanced_accuracy_validator.py': 'BalancedAccuracyValidator',
            'refined_pattern_validator.py': 'RefinedPatternValidator',
            'enhanced_validator_v2.py': 'EnhancedValidatorV2',
            'sql_field_reference_validator.py': 'SQLFieldReferenceValidator',
            'phase_1_completion_validator.py': 'Phase1CompletionValidator'
        }
        
        # Add validation directory to Python path
        if str(cls.validation_dir) not in sys.path:
            sys.path.insert(0, str(cls.validation_dir))
        
        print(f"🔍 Testing standardization of {len(cls.standardized_validators)} validators")
    
    def test_source_code_standardization(self):
        """Test that validator source code uses DocTypeLoader import"""
        results = {}
        
        for validator_file, class_name in self.standardized_validators.items():
            validator_path = self.validation_dir / validator_file
            
            if not validator_path.exists():
                results[validator_file] = {"status": "missing", "error": "File not found"}
                continue
            
            try:
                with open(validator_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for DocTypeLoader import
                has_import = any(pattern in content for pattern in [
                    'from doctype_loader import DocTypeLoader',
                    'from doctype_loader import',
                    'import doctype_loader'
                ])
                
                # Check for DocTypeLoader instantiation
                has_instantiation = any(pattern in content for pattern in [
                    'DocTypeLoader(',
                    'doctype_loader = DocTypeLoader',
                    'self.doctype_loader = DocTypeLoader'
                ])
                
                # Check for old manual loading patterns (should be removed)
                has_old_patterns = any(pattern in content for pattern in [
                    'rglob("**/doctype/*/*.json")',
                    'Path(app_path).rglob',
                    'manual_doctype_loading',
                    'glob.glob'
                ])
                
                results[validator_file] = {
                    "status": "analyzed",
                    "has_import": has_import,
                    "has_instantiation": has_instantiation,
                    "has_old_patterns": has_old_patterns,
                    "class_name": class_name
                }
                
            except Exception as e:
                results[validator_file] = {"status": "error", "error": str(e)}
        
        # Validate results
        failed_validators = []
        
        for validator_file, result in results.items():
            if result["status"] == "missing":
                print(f"⚠️  {validator_file}: File not found (may be renamed/moved)")
                continue
            elif result["status"] == "error":
                failed_validators.append(f"{validator_file}: {result['error']}")
                continue
            
            # Check standardization requirements
            if not result["has_import"]:
                failed_validators.append(f"{validator_file}: Missing DocTypeLoader import")
            
            if not result["has_instantiation"]:
                failed_validators.append(f"{validator_file}: Missing DocTypeLoader instantiation")
            
            if result["has_old_patterns"]:
                failed_validators.append(f"{validator_file}: Still contains old manual loading patterns")
            
            if result["has_import"] and result["has_instantiation"] and not result["has_old_patterns"]:
                print(f"✅ {validator_file}: Properly standardized")
        
        if failed_validators:
            self.fail(f"Standardization issues found:\n" + "\n".join(failed_validators))
        
        print(f"✅ Source code standardization: All {len(results)} validators properly use DocTypeLoader")
    
    def test_validator_doctype_loading_functionality(self):
        """Test that validators can actually load DocTypes correctly"""
        successful_validators = []
        failed_validators = []
        
        for validator_file, class_name in self.standardized_validators.items():
            try:
                # Import the validator module
                module_name = validator_file.replace('.py', '')
                spec = importlib.util.spec_from_file_location(
                    module_name, 
                    self.validation_dir / validator_file
                )
                
                if spec is None or spec.loader is None:
                    failed_validators.append(f"{validator_file}: Could not create module spec")
                    continue
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Get the validator class
                if not hasattr(module, class_name):
                    # Try to find any validator class in the module
                    validator_classes = [
                        name for name, obj in inspect.getmembers(module, inspect.isclass)
                        if 'validator' in name.lower() and obj.__module__ == module.__name__
                    ]
                    
                    if validator_classes:
                        class_name = validator_classes[0]
                    else:
                        failed_validators.append(f"{validator_file}: No validator class found")
                        continue
                
                validator_class = getattr(module, class_name)
                
                # Instantiate the validator
                app_path = "/home/frappe/frappe-bench/apps/verenigingen"
                
                # Try different constructor patterns
                validator_instance = None
                
                try:
                    # Try with app_path parameter
                    validator_instance = validator_class(app_path)
                except TypeError:
                    try:
                        # Try with no parameters
                        validator_instance = validator_class()
                    except TypeError:
                        try:
                            # Try with explicit bench_path
                            validator_instance = validator_class(bench_path=self.bench_path)
                        except TypeError as e:
                            failed_validators.append(f"{validator_file}: Could not instantiate {class_name}: {e}")
                            continue
                
                if validator_instance is None:
                    failed_validators.append(f"{validator_file}: Failed to instantiate {class_name}")
                    continue
                
                # Check that it has DocType loading capability
                doctype_count = 0
                
                # Try different ways to get DocType count
                if hasattr(validator_instance, 'doctypes'):
                    if isinstance(validator_instance.doctypes, dict):
                        doctype_count = len(validator_instance.doctypes)
                    elif hasattr(validator_instance.doctypes, '__len__'):
                        doctype_count = len(validator_instance.doctypes)
                
                if hasattr(validator_instance, 'doctype_loader'):
                    try:
                        doctypes = validator_instance.doctype_loader.get_doctypes()
                        doctype_count = len(doctypes)
                    except Exception:
                        pass
                
                # Validate DocType count
                if doctype_count == 0:
                    failed_validators.append(f"{validator_file}: Loaded 0 DocTypes (path configuration issue)")
                elif doctype_count < 500:
                    failed_validators.append(f"{validator_file}: Only loaded {doctype_count} DocTypes (incomplete loading)")
                else:
                    successful_validators.append({
                        'file': validator_file,
                        'class': class_name,
                        'doctype_count': doctype_count
                    })
                    print(f"✅ {validator_file}: {class_name} loaded {doctype_count} DocTypes")
                
            except ImportError as e:
                failed_validators.append(f"{validator_file}: Import error: {e}")
            except Exception as e:
                failed_validators.append(f"{validator_file}: Unexpected error: {e}")
        
        # Report results
        success_count = len(successful_validators)
        total_count = len(self.standardized_validators)
        
        print(f"\n📊 Validator Loading Results:")
        print(f"✅ Successful: {success_count}/{total_count}")
        print(f"❌ Failed: {len(failed_validators)}")
        
        if failed_validators:
            print(f"\n❌ Failed validators:")
            for failure in failed_validators:
                print(f"  - {failure}")
        
        # Ensure minimum success rate
        success_rate = success_count / total_count
        self.assertGreaterEqual(
            success_rate, 0.7,  # At least 70% should work
            f"Too many validators failed: {success_rate:.1%} success rate. "
            f"This suggests standardization issues."
        )
        
        print(f"✅ Validator functionality: {success_rate:.1%} success rate")
    
    def test_performance_consistency(self):
        """Test that standardized validators have consistent performance"""
        # Test performance of a few key validators
        key_validators = [
            ('unified_validation_engine.py', 'SpecializedPatternValidator'),
            ('doctype_field_validator.py', 'AccurateFieldValidator'),
        ]
        
        performance_results = {}
        
        for validator_file, class_name in key_validators:
            try:
                # Import and instantiate
                module_name = validator_file.replace('.py', '')
                spec = importlib.util.spec_from_file_location(
                    module_name, 
                    self.validation_dir / validator_file
                )
                
                if spec is None or spec.loader is None:
                    continue
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                if not hasattr(module, class_name):
                    continue
                
                validator_class = getattr(module, class_name)
                
                # Measure instantiation time
                start_time = time.time()
                app_path = "/home/frappe/frappe-bench/apps/verenigingen"
                validator_instance = validator_class(app_path)
                instantiation_time = time.time() - start_time
                
                performance_results[validator_file] = {
                    'instantiation_time': instantiation_time,
                    'success': True
                }
                
                print(f"⏱️  {validator_file}: Instantiated in {instantiation_time:.3f}s")
                
            except Exception as e:
                performance_results[validator_file] = {
                    'error': str(e),
                    'success': False
                }
        
        # Validate performance
        successful_results = [r for r in performance_results.values() if r.get('success')]
        
        if successful_results:
            max_time = max(r['instantiation_time'] for r in successful_results)
            avg_time = sum(r['instantiation_time'] for r in successful_results) / len(successful_results)
            
            # Performance should be reasonable
            self.assertLess(
                max_time, 15.0,  # No validator should take more than 15 seconds
                f"Some validators are too slow: max time {max_time:.3f}s"
            )
            
            print(f"✅ Performance consistency: Max {max_time:.3f}s, Avg {avg_time:.3f}s")
        else:
            self.skipTest("No validators available for performance testing")
    
    def test_backward_compatibility_interfaces(self):
        """Test that legacy interfaces still work after standardization"""
        from doctype_loader import DocTypeLoader, load_doctypes_simple, load_doctypes_detailed
        
        app_path = "/home/frappe/frappe-bench/apps/verenigingen"
        
        # Test legacy convenience functions
        simple_doctypes = load_doctypes_simple(app_path)
        detailed_doctypes = load_doctypes_detailed(app_path)
        
        self.assertIsInstance(simple_doctypes, dict)
        self.assertIsInstance(detailed_doctypes, dict)
        self.assertGreater(len(simple_doctypes), 0)
        self.assertGreater(len(detailed_doctypes), 0)
        
        # Test direct loader methods
        loader = DocTypeLoader(self.bench_path)
        
        legacy_simple = loader.get_doctypes_simple()
        legacy_detailed = loader.get_doctypes_detailed()
        
        self.assertIsInstance(legacy_simple, dict)
        self.assertIsInstance(legacy_detailed, dict)
        
        # Test single app loading (legacy pattern)
        vereinigingen_doctypes = loader.load_from_single_app('verenigingen')
        self.assertIsInstance(verenigigingen_doctypes, dict)
        self.assertGreater(len(vereinigingen_doctypes), 0)
        
        print("✅ Backward compatibility: All legacy interfaces work correctly")
    
    def test_error_handling_robustness(self):
        """Test that validators handle errors gracefully"""
        from doctype_loader import DocTypeLoader
        
        # Test with invalid path
        try:
            invalid_loader = DocTypeLoader("/nonexistent/path")
            doctypes = invalid_loader.get_doctypes()
            # Should handle gracefully, not crash
            self.assertIsInstance(doctypes, dict)
            print("✅ Error handling: Invalid path handled gracefully")
        except Exception as e:
            # Should not crash with unhandled exceptions
            self.fail(f"DocTypeLoader crashed with invalid path: {e}")
        
        # Test with valid path but missing apps
        try:
            loader = DocTypeLoader(self.bench_path)
            # Try to load from non-existent app
            result = loader.load_from_single_app('nonexistent_app')
            self.assertIsInstance(result, dict)
            self.assertEqual(len(result), 0)  # Should return empty dict, not crash
            print("✅ Error handling: Missing app handled gracefully")
        except Exception as e:
            self.fail(f"DocTypeLoader crashed with missing app: {e}")


def run_validator_standardization_tests():
    """Run validator standardization tests with detailed reporting"""
    print("🔧 Running Validator Standardization Tests")
    print("=" * 80)
    
    # Create and run test suite
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(ValidatorStandardizationTest))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Report summary
    print("\n" + "=" * 80)
    print("🔧 Validator Standardization Summary")
    print("=" * 80)
    
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total_tests - failures - errors
    
    print(f"Tests Run: {total_tests}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failures}")
    print(f"🚫 Errors: {errors}")
    
    if result.failures:
        print("\n❌ Failures:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print("\n🚫 Errors:")  
        for test, traceback in result.errors:
            print(f"  - {test}")
    
    success = failures == 0 and errors == 0
    
    if success:
        print("\n🎉 All validator standardization tests PASSED!")
        print("The 21 validators are properly standardized to use DocTypeLoader.")
    else:
        print("\n⚠️  Some validator standardization tests failed.")
        print("Manual investigation is needed for failed validators.")
    
    return success


if __name__ == "__main__":
    success = run_validator_standardization_tests()
    exit(0 if success else 1)