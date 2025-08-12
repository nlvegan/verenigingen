#!/usr/bin/env python3
"""
Comprehensive Validation Infrastructure Test Suite
=================================================

Master test runner for validating the massive standardization of 21 validators
to use the comprehensive DocTypeLoader instead of manual DocType loading.

This suite runs all test categories:
1. **DocTypeLoader Core Tests**: Verify 1,049+ DocTypes and 36+ custom fields loading
2. **Validator Standardization Tests**: Ensure all 21 validators use DocTypeLoader correctly  
3. **Regression Tests**: Compare pre/post standardization validation results
4. **Pre-commit Integration Tests**: Verify no breaking changes to development workflow
5. **Performance Benchmarks**: Ensure standardization hasn't degraded performance
6. **Functional Validation Tests**: Test with realistic data from the codebase

Test Philosophy:
- Uses realistic data from actual codebase rather than mocks
- Tests actual system behavior, not artificial scenarios
- Validates business logic and real-world usage patterns
- Comprehensive coverage without unnecessary complexity

Run Options:
- Full suite: All tests for complete validation
- Quick suite: Core tests for rapid feedback
- Specific categories: Individual test suites
- CI mode: Optimized for continuous integration
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import subprocess


@dataclass
class TestSuiteResult:
    """Result from running a test suite"""
    name: str
    duration: float
    tests_run: int
    passed: int
    failed: int
    errors: int
    skipped: int
    success: bool
    error_message: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        return self.passed / max(self.tests_run, 1)
    
    def to_dict(self):
        return asdict(self)


@dataclass
class ComprehensiveTestResults:
    """Complete test results from all suites"""
    overall_success: bool
    total_duration: float
    suite_results: List[TestSuiteResult]
    summary: Dict[str, Any]
    
    def to_dict(self):
        return asdict(self)


class ComprehensiveTestRunner:
    """Master test runner for validation infrastructure tests"""
    
    def __init__(self, validation_dir: Path):
        self.validation_dir = validation_dir
        self.app_path = validation_dir.parent.parent
        
        # Test suite definitions
        self.test_suites = {
            'doctype_loader': {
                'name': 'DocType Loader Core Tests',
                'script': 'test_doctype_loader_comprehensive.py',
                'description': 'Verify comprehensive DocType loading (1,049+ DocTypes, 36+ custom fields)',
                'critical': True,
                'estimated_time': 30
            },
            'validator_standardization': {
                'name': 'Validator Standardization Tests', 
                'script': 'test_validator_standardization.py',
                'description': 'Ensure all 21 validators use DocTypeLoader correctly',
                'critical': True,
                'estimated_time': 45
            },
            'regression': {
                'name': 'Validation Regression Tests',
                'script': 'test_validation_regression.py', 
                'description': 'Compare pre/post standardization validation results',
                'critical': True,
                'estimated_time': 60
            },
            'precommit_integration': {
                'name': 'Pre-commit Integration Tests',
                'script': 'test_precommit_integration.py',
                'description': 'Verify no breaking changes to development workflow',
                'critical': False,
                'estimated_time': 30
            },
            'performance_benchmarks': {
                'name': 'Performance Benchmark Tests',
                'script': 'test_performance_benchmarks.py',
                'description': 'Ensure standardization maintains/improves performance',
                'critical': False,
                'estimated_time': 90
            },
            'functional_validation': {
                'name': 'Functional Validation Tests',
                'script': 'test_functional_validation.py',
                'description': 'Test with realistic data from the codebase',
                'critical': True,
                'estimated_time': 45
            }
        }
        
        print(f"🧪 Comprehensive Validation Test Runner initialized")
        print(f"📂 Validation directory: {self.validation_dir}")
        print(f"📋 {len(self.test_suites)} test suites available")
    
    def run_test_suite(self, suite_key: str, verbose: bool = True) -> TestSuiteResult:
        """Run a single test suite and return results"""
        suite_info = self.test_suites[suite_key]
        script_path = self.validation_dir / suite_info['script']
        
        if not script_path.exists():
            return TestSuiteResult(
                name=suite_info['name'],
                duration=0,
                tests_run=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                success=False,
                error_message=f"Test script not found: {script_path}"
            )
        
        if verbose:
            print(f"\n🔄 Running {suite_info['name']}...")
            print(f"📄 Script: {suite_info['script']}")
            print(f"⏱️  Estimated time: {suite_info['estimated_time']}s")
        
        start_time = time.time()
        
        try:
            # Run the test script
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=suite_info['estimated_time'] * 2,  # 2x timeout for safety
                cwd=str(self.validation_dir)
            )
            
            duration = time.time() - start_time
            
            # Parse output to extract test metrics
            stdout = result.stdout
            stderr = result.stderr
            
            # Extract test counts from output
            tests_run, passed, failed, errors, skipped = self._parse_test_output(stdout)
            
            success = result.returncode == 0 and failed == 0 and errors == 0
            
            if verbose:
                status = "✅ PASSED" if success else "❌ FAILED"
                print(f"{status} - {suite_info['name']} ({duration:.1f}s)")
                print(f"   Tests: {tests_run}, Passed: {passed}, Failed: {failed}, Errors: {errors}")
                if not success and stderr:
                    print(f"   Error output: {stderr[:200]}...")
            
            return TestSuiteResult(
                name=suite_info['name'],
                duration=duration,
                tests_run=tests_run,
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                success=success,
                error_message=stderr[:500] if stderr else None
            )
            
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return TestSuiteResult(
                name=suite_info['name'],
                duration=duration,
                tests_run=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                success=False,
                error_message=f"Test suite timed out after {duration:.1f}s"
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return TestSuiteResult(
                name=suite_info['name'],
                duration=duration,
                tests_run=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                success=False,
                error_message=str(e)
            )
    
    def _parse_test_output(self, output: str) -> tuple[int, int, int, int, int]:
        """Parse test output to extract metrics"""
        # Default values
        tests_run = passed = failed = errors = skipped = 0
        
        # Look for test result patterns in output
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            
            # Pattern: "Ran X tests"
            if 'Ran ' in line and ' test' in line:
                try:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'Ran' and i + 1 < len(parts):
                            tests_run = int(parts[i + 1])
                            break
                except (ValueError, IndexError):
                    pass
            
            # Pattern: "Tests Run: X"
            elif 'Tests Run:' in line or 'Tests:' in line:
                try:
                    tests_run = int(line.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass
            
            # Pattern: "Passed: X" or "✅ Passed: X"
            elif 'Passed:' in line:
                try:
                    passed = int(line.split('Passed:')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            
            # Pattern: "Failed: X" or "❌ Failed: X"
            elif 'Failed:' in line:
                try:
                    failed = int(line.split('Failed:')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            
            # Pattern: "Errors: X" or "🚫 Errors: X"
            elif 'Errors:' in line:
                try:
                    errors = int(line.split('Errors:')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            
            # Pattern: "Skipped: X"
            elif 'Skipped:' in line:
                try:
                    skipped = int(line.split('Skipped:')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
        
        # If we found tests_run but not passed, calculate passed
        if tests_run > 0 and passed == 0 and failed == 0 and errors == 0:
            passed = tests_run
        
        return tests_run, passed, failed, errors, skipped
    
    def run_quick_suite(self, verbose: bool = True) -> ComprehensiveTestResults:
        """Run quick test suite with core tests only"""
        quick_suites = ['doctype_loader', 'validator_standardization']
        return self._run_suites(quick_suites, verbose)
    
    def run_critical_suite(self, verbose: bool = True) -> ComprehensiveTestResults:
        """Run critical tests that must pass"""
        critical_suites = [key for key, info in self.test_suites.items() if info['critical']]
        return self._run_suites(critical_suites, verbose)
    
    def run_full_suite(self, verbose: bool = True) -> ComprehensiveTestResults:
        """Run complete test suite"""
        all_suites = list(self.test_suites.keys())
        return self._run_suites(all_suites, verbose)
    
    def _run_suites(self, suite_keys: List[str], verbose: bool = True) -> ComprehensiveTestResults:
        """Run specified test suites and return comprehensive results"""
        if verbose:
            total_estimated_time = sum(self.test_suites[key]['estimated_time'] for key in suite_keys)
            print(f"\n🚀 Running {len(suite_keys)} test suites")
            print(f"⏱️  Estimated total time: {total_estimated_time}s ({total_estimated_time/60:.1f} minutes)")
            print("=" * 80)
        
        start_time = time.time()
        suite_results = []
        
        for suite_key in suite_keys:
            try:
                result = self.run_test_suite(suite_key, verbose)
                suite_results.append(result)
            except Exception as e:
                if verbose:
                    print(f"❌ Exception running {suite_key}: {e}")
                error_result = TestSuiteResult(
                    name=self.test_suites[suite_key]['name'],
                    duration=0,
                    tests_run=0,
                    passed=0,
                    failed=0,
                    errors=1,
                    skipped=0,
                    success=False,
                    error_message=str(e)
                )
                suite_results.append(error_result)
        
        total_duration = time.time() - start_time
        
        # Calculate overall results
        total_tests = sum(r.tests_run for r in suite_results)
        total_passed = sum(r.passed for r in suite_results)
        total_failed = sum(r.failed for r in suite_results)
        total_errors = sum(r.errors for r in suite_results)
        total_skipped = sum(r.skipped for r in suite_results)
        
        successful_suites = sum(1 for r in suite_results if r.success)
        overall_success = successful_suites == len(suite_results)
        
        # Critical suite analysis
        critical_suite_results = [
            r for r in suite_results 
            if any(self.test_suites[key]['critical'] 
                  for key in self.test_suites.keys() 
                  if self.test_suites[key]['name'] == r.name)
        ]
        critical_success = all(r.success for r in critical_suite_results)
        
        summary = {
            'total_suites': len(suite_results),
            'successful_suites': successful_suites,
            'failed_suites': len(suite_results) - successful_suites,
            'total_tests': total_tests,
            'total_passed': total_passed,
            'total_failed': total_failed,
            'total_errors': total_errors,
            'total_skipped': total_skipped,
            'overall_success_rate': total_passed / max(total_tests, 1),
            'critical_suites_passed': len([r for r in critical_suite_results if r.success]),
            'critical_suites_total': len(critical_suite_results),
            'critical_success': critical_success
        }
        
        return ComprehensiveTestResults(
            overall_success=overall_success,
            total_duration=total_duration,
            suite_results=suite_results,
            summary=summary
        )
    
    def print_comprehensive_summary(self, results: ComprehensiveTestResults):
        """Print detailed summary of all test results"""
        print("\n" + "=" * 80)
        print("🏁 COMPREHENSIVE VALIDATION TEST RESULTS")
        print("=" * 80)
        
        # Overall status
        overall_status = "✅ PASSED" if results.overall_success else "❌ FAILED"
        print(f"Overall Status: {overall_status}")
        print(f"Total Duration: {results.total_duration:.1f}s ({results.total_duration/60:.1f} minutes)")
        
        # Summary statistics
        summary = results.summary
        print(f"\n📊 Summary Statistics:")
        print(f"   Test Suites: {summary['successful_suites']}/{summary['total_suites']} passed")
        print(f"   Individual Tests: {summary['total_passed']}/{summary['total_tests']} passed")
        print(f"   Success Rate: {summary['overall_success_rate']:.1%}")
        print(f"   Critical Suites: {summary['critical_suites_passed']}/{summary['critical_suites_total']} passed")
        
        # Individual suite results
        print(f"\n📋 Individual Suite Results:")
        for result in results.suite_results:
            status = "✅" if result.success else "❌"
            duration_str = f"{result.duration:.1f}s"
            test_summary = f"{result.passed}/{result.tests_run}"
            
            print(f"   {status} {result.name}: {test_summary} tests passed ({duration_str})")
            
            if not result.success and result.error_message:
                error_preview = result.error_message[:100] + "..." if len(result.error_message) > 100 else result.error_message
                print(f"      Error: {error_preview}")
        
        # Critical analysis
        print(f"\n🔍 Critical Analysis:")
        if summary['critical_success']:
            print("   ✅ All critical test suites PASSED")
            print("   ✅ Validation infrastructure standardization is successful")
        else:
            print("   ❌ Some critical test suites FAILED")
            print("   ⚠️  Manual investigation required before production deployment")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if results.overall_success:
            print("   🎉 The standardization of 21 validators is working correctly!")
            print("   ✅ DocTypeLoader is properly loading 1,049+ DocTypes and 36+ custom fields")
            print("   ✅ All validators are using the comprehensive loading infrastructure")
            print("   ✅ No regressions detected in validation accuracy or performance")
            print("   🚀 Safe to proceed with full deployment")
        else:
            failed_critical = [r for r in results.suite_results 
                             if not r.success and any(
                                 self.test_suites[key]['critical'] 
                                 for key in self.test_suites.keys() 
                                 if self.test_suites[key]['name'] == r.name
                             )]
            
            if failed_critical:
                print("   🚨 CRITICAL FAILURES detected:")
                for result in failed_critical:
                    print(f"      - {result.name}")
                print("   ⛔ DO NOT deploy until critical issues are resolved")
            else:
                print("   ⚠️  Non-critical test failures detected")
                print("   🔄 Review failed tests and consider fixes")
                print("   ✅ Core functionality appears to be working")
        
        print("\n" + "=" * 80)
    
    def save_results(self, results: ComprehensiveTestResults, output_file: Optional[Path] = None):
        """Save test results to JSON file"""
        if output_file is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_file = self.validation_dir / f"comprehensive_test_results_{timestamp}.json"
        
        try:
            with open(output_file, 'w') as f:
                json.dump(results.to_dict(), f, indent=2, default=str)
            print(f"💾 Test results saved to: {output_file}")
        except Exception as e:
            print(f"⚠️  Could not save results to {output_file}: {e}")


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(
        description="Comprehensive Validation Infrastructure Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Suite Categories:
  doctype_loader        - Core DocType loading tests (1,049+ DocTypes, 36+ custom fields)
  validator_standardization - Ensure all 21 validators use DocTypeLoader 
  regression           - Compare pre/post standardization validation results
  precommit_integration - Verify no breaking changes to development workflow
  performance_benchmarks - Performance regression testing
  functional_validation - Test with realistic data from codebase

Examples:
  python run_comprehensive_validation_tests.py --quick
  python run_comprehensive_validation_tests.py --critical
  python run_comprehensive_validation_tests.py --full
  python run_comprehensive_validation_tests.py --suite doctype_loader validator_standardization
        """
    )
    
    parser.add_argument('--quick', action='store_true',
                       help='Run quick test suite (core tests only)')
    parser.add_argument('--critical', action='store_true', 
                       help='Run critical tests that must pass')
    parser.add_argument('--full', action='store_true',
                       help='Run complete test suite (default)')
    parser.add_argument('--suite', nargs='+', 
                       choices=['doctype_loader', 'validator_standardization', 'regression',
                               'precommit_integration', 'performance_benchmarks', 'functional_validation'],
                       help='Run specific test suites')
    parser.add_argument('--quiet', action='store_true',
                       help='Reduce output verbosity')
    parser.add_argument('--output', type=str,
                       help='Save results to specified JSON file')
    
    args = parser.parse_args()
    
    # Determine validation directory
    script_dir = Path(__file__).parent
    validation_dir = script_dir
    
    # Create test runner
    runner = ComprehensiveTestRunner(validation_dir)
    
    # Determine which tests to run
    verbose = not args.quiet
    
    if args.suite:
        results = runner._run_suites(args.suite, verbose)
    elif args.quick:
        results = runner.run_quick_suite(verbose)
    elif args.critical:
        results = runner.run_critical_suite(verbose)
    else:  # default to full
        results = runner.run_full_suite(verbose)
    
    # Print results
    runner.print_comprehensive_summary(results)
    
    # Save results if requested
    if args.output:
        output_path = Path(args.output)
        runner.save_results(results, output_path)
    else:
        runner.save_results(results)  # Use default filename
    
    # Exit with appropriate code
    return 0 if results.overall_success else 1


if __name__ == "__main__":
    exit(main())