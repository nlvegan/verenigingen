#!/usr/bin/env python3
"""
Validation Test Runner
Integrates code validation with the test suite
"""

import sys
import time
import argparse
import subprocess
from pathlib import Path


class ValidationTestRunner:
    """Test runner that includes code validation checks"""
    
    def __init__(self, site: str = "dev.veganisme.net"):
        self.site = site
        # Go up from scripts/testing/runners/ to app root (4 levels up)
        self.app_path = Path(__file__).resolve().parent.parent.parent.parent
        self.results = {}
        
    def run_validation_suite(self, quiet: bool = True, field_only: bool = False) -> bool:
        """Run the comprehensive validation suite"""
        print("🔍 Running Code Validation...")
        
        validator_path = self.app_path / "scripts" / "validation" / "comprehensive_validator.py"
        
        cmd = [sys.executable, str(validator_path)]
        if quiet:
            cmd.append("--quiet")
        if field_only:
            cmd.append("--field-only")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )
            
            if result.returncode == 0:
                print("✅ Code validation passed")
                return True
            else:
                print("❌ Code validation failed")
                print(result.stdout)
                if result.stderr:
                    print("STDERR:", result.stderr)
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Code validation timed out after 2 minutes")
            return False
        except Exception as e:
            print(f"❌ Code validation error: {e}")
            return False
    
    def run_frappe_tests(self, module: str = None, verbose: bool = False) -> bool:
        """Run Frappe unit tests"""
        print("🧪 Running Frappe Tests...")
        
        cmd = ["bench", "--site", self.site, "run-tests", "--app", "verenigingen"]
        
        if module:
            cmd.extend(["--module", module])
        
        if verbose:
            cmd.append("--verbose")
        
        try:
            result = subprocess.run(cmd, cwd="/home/frappe/frappe-bench", timeout=300)
            
            if result.returncode == 0:
                print("✅ Frappe tests passed")
                return True
            else:
                print("❌ Frappe tests failed")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Frappe tests timed out after 5 minutes")
            return False
        except Exception as e:
            print(f"❌ Frappe test error: {e}")
            return False
    
    def run_custom_test_scripts(self) -> bool:
        """Run custom test scripts"""
        print("🔧 Running Custom Tests...")
        
        test_scripts = [
            "scripts/testing/integration/simple_test.py",
            "scripts/testing/integration/test_smoke.py",
        ]
        
        all_passed = True
        
        for script in test_scripts:
            script_path = self.app_path / script
            if not script_path.exists():
                print(f"⏩ Skipping {script} (not found)")
                continue
            
            try:
                result = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode == 0:
                    print(f"✅ {script}")
                else:
                    print(f"❌ {script}")
                    all_passed = False
                    
            except Exception as e:
                print(f"❌ {script}: {e}")
                all_passed = False
        
        return all_passed
    
    def run_comprehensive_test_suite(
        self, 
        include_validation: bool = True,
        include_frappe_tests: bool = True,
        include_custom_tests: bool = True,
        field_validation_only: bool = False,
        quiet_validation: bool = True
    ) -> bool:
        """Run comprehensive test suite with validation"""
        
        start_time = time.time()
        print("🚀 Running Comprehensive Test Suite")
        print("=" * 60)
        
        all_passed = True
        
        # 1. Code Validation (fast, run first)
        if include_validation:
            validation_passed = self.run_validation_suite(
                quiet=quiet_validation, 
                field_only=field_validation_only
            )
            all_passed = all_passed and validation_passed
            
            # If validation fails and we're in strict mode, stop here
            if not validation_passed and field_validation_only:
                print("\n❌ Field validation failed - stopping test suite")
                return False
        
        # 2. Custom Tests (medium speed)
        if include_custom_tests:
            custom_passed = self.run_custom_test_scripts()
            all_passed = all_passed and custom_passed
        
        # 3. Frappe Tests (slowest, run last)
        if include_frappe_tests:
            frappe_passed = self.run_frappe_tests()
            all_passed = all_passed and frappe_passed
        
        # Summary
        duration = time.time() - start_time
        print("\n" + "=" * 60)
        
        if all_passed:
            print("✅ ALL TESTS PASSED!")
            print(f"🎉 Test suite completed in {duration:.1f}s")
        else:
            print("❌ Some tests failed")
            print(f"⏱️ Test suite completed in {duration:.1f}s")
        
        print("=" * 60)
        return all_passed


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Comprehensive Test Runner with Code Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Suite Modes:
  --validation-only         Run only code validation
  --field-validation-only   Run only database field validation 
  --no-validation          Skip code validation
  --no-frappe-tests        Skip Frappe unit tests
  --no-custom-tests        Skip custom test scripts
  --fast                   Run only fast tests (validation + custom)

Examples:
  python validation_test_runner.py                    # Full test suite
  python validation_test_runner.py --fast             # Fast tests only
  python validation_test_runner.py --validation-only  # Code validation only
  python validation_test_runner.py --field-validation-only  # Field validation only
        """
    )
    
    parser.add_argument(
        '--site', '-s',
        default='dev.veganisme.net',
        help='Frappe site name (default: dev.veganisme.net)'
    )
    
    parser.add_argument(
        '--validation-only',
        action='store_true',
        help='Run only code validation'
    )
    
    parser.add_argument(
        '--field-validation-only',
        action='store_true',
        help='Run only database field validation'
    )
    
    parser.add_argument(
        '--no-validation',
        action='store_true',
        help='Skip code validation'
    )
    
    parser.add_argument(
        '--no-frappe-tests',
        action='store_true',
        help='Skip Frappe unit tests'
    )
    
    parser.add_argument(
        '--no-custom-tests',
        action='store_true',
        help='Skip custom test scripts'
    )
    
    parser.add_argument(
        '--fast',
        action='store_true',
        help='Run only fast tests (validation + custom, skip Frappe tests)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    
    args = parser.parse_args()
    
    # Create test runner
    runner = ValidationTestRunner(site=args.site)
    
    # Determine what to run
    if args.validation_only:
        success = runner.run_validation_suite(quiet=not args.verbose)
    elif args.field_validation_only:
        success = runner.run_validation_suite(quiet=not args.verbose, field_only=True)
    else:
        # Comprehensive test suite
        include_validation = not args.no_validation
        include_frappe = not args.no_frappe_tests and not args.fast
        include_custom = not args.no_custom_tests
        field_only = args.field_validation_only
        
        success = runner.run_comprehensive_test_suite(
            include_validation=include_validation,
            include_frappe_tests=include_frappe,
            include_custom_tests=include_custom,
            field_validation_only=field_only,
            quiet_validation=not args.verbose
        )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()