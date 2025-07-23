#!/usr/bin/env python3
"""
Comprehensive Code Validator
Runs all validation checks in a unified suite with performance monitoring
"""

import sys
import time
import argparse
from pathlib import Path
from enhanced_field_validator import EnhancedFieldValidator
from template_variable_validator import TemplateVariableValidator


class ValidationSuite:
    """Comprehensive validation suite with performance monitoring"""
    
    def __init__(self, app_path: str, quiet: bool = False, skip_template: bool = False):
        self.app_path = Path(app_path)
        self.quiet = quiet
        self.skip_template = skip_template
        self.results = {}
        
    def log(self, message: str, force: bool = False):
        """Log message unless in quiet mode"""
        if not self.quiet or force:
            print(message)
    
    def run_field_validation(self) -> bool:
        """Run database field validation with timing"""
        start_time = time.time()
        
        self.log("\n1️⃣ Database Field Reference Validation")
        self.log("-" * 40)
        
        try:
            field_validator = EnhancedFieldValidator(str(self.app_path))
            field_passed = field_validator.run_validation()
            
            duration = time.time() - start_time
            self.results['field_validation'] = {
                'passed': field_passed,
                'duration': duration,
                'error': None
            }
            
            if not self.quiet:
                self.log(f"⏱️ Field validation completed in {duration:.2f}s")
                
            return field_passed
            
        except Exception as e:
            duration = time.time() - start_time
            self.results['field_validation'] = {
                'passed': False,
                'duration': duration,
                'error': str(e)
            }
            self.log(f"❌ Field validation failed: {e}", force=True)
            return False
    
    def run_template_validation(self) -> bool:
        """Run template variable validation with timing"""
        if self.skip_template:
            self.log("\n2️⃣ Template Variable Validation (SKIPPED)")
            self.results['template_validation'] = {
                'passed': True,
                'duration': 0,
                'error': None,
                'skipped': True
            }
            return True
        
        start_time = time.time()
        
        self.log("\n2️⃣ Template Variable Validation")
        self.log("-" * 40)
        
        try:
            template_validator = TemplateVariableValidator(str(self.app_path))
            template_passed = template_validator.run_validation()
            
            duration = time.time() - start_time
            self.results['template_validation'] = {
                'passed': template_passed,
                'duration': duration,
                'error': None
            }
            
            if not self.quiet:
                self.log(f"⏱️ Template validation completed in {duration:.2f}s")
                
            return template_passed
            
        except Exception as e:
            duration = time.time() - start_time
            self.results['template_validation'] = {
                'passed': False,
                'duration': duration,
                'error': str(e)
            }
            self.log(f"❌ Template validation failed: {e}", force=True)
            return False
    
    def run_comprehensive_validation(self) -> bool:
        """Run all validations with performance monitoring"""
        total_start = time.time()
        
        self.log("🚀 Running Comprehensive Code Validation Suite")
        self.log("=" * 60)
        
        # Run validations
        field_passed = self.run_field_validation()
        template_passed = self.run_template_validation()
        
        all_passed = field_passed and template_passed
        total_duration = time.time() - total_start
        
        # Summary
        self.log("\n" + "=" * 60, force=True)
        if all_passed:
            self.log("✅ ALL VALIDATIONS PASSED!", force=True)
            if not self.quiet:
                self.log("🎉 Your codebase looks great!")
        else:
            self.log("❌ Some validations failed", force=True)
            self.log("🔧 Please review and fix the issues above", force=True)
        
        # Performance summary
        field_time = self.results.get('field_validation', {}).get('duration', 0)
        template_time = self.results.get('template_validation', {}).get('duration', 0)
        
        self.log(f"\n⏱️ Total validation time: {total_duration:.2f}s", force=True)
        self.log(f"   • Field validation: {field_time:.2f}s", force=True)
        if not self.skip_template:
            self.log(f"   • Template validation: {template_time:.2f}s", force=True)
        
        self.log("=" * 60, force=True)
        
        return all_passed


def main():
    """Main entry point with CLI arguments"""
    parser = argparse.ArgumentParser(
        description="Comprehensive Code Validation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python comprehensive_validator.py                    # Run all validations
  python comprehensive_validator.py --quiet           # Run quietly (CI mode)
  python comprehensive_validator.py --skip-template   # Skip template validation
  python comprehensive_validator.py --field-only      # Run only field validation
        """
    )
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Run in quiet mode (minimal output, suitable for CI)'
    )
    
    parser.add_argument(
        '--skip-template',
        action='store_true',
        help='Skip template variable validation (faster for basic checks)'
    )
    
    parser.add_argument(
        '--field-only',
        action='store_true',
        help='Run only database field validation'
    )
    
    args = parser.parse_args()
    
    # Get app path
    script_path = Path(__file__).resolve()
    app_path = script_path.parent.parent.parent
    
    if not (app_path / 'verenigingen' / 'hooks.py').exists():
        print(f"Error: hooks.py not found at {app_path}")
        sys.exit(1)
    
    # Create validation suite
    skip_template = args.skip_template or args.field_only
    suite = ValidationSuite(str(app_path), quiet=args.quiet, skip_template=skip_template)
    
    # Run validations
    if args.field_only:
        success = suite.run_field_validation()
    else:
        success = suite.run_comprehensive_validation()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()