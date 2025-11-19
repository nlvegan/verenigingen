#!/usr/bin/env python3
"""
Comprehensive Code Validator
Runs all validation checks in a unified suite with performance monitoring
"""

import sys
import time
import argparse
import ast
from pathlib import Path
from enhanced_field_reference_validator import ContextAwareFieldValidator
from template_variable_validator import ModernTemplateValidator
from loop_context_field_validator import LoopContextFieldValidator, load_doctypes
from child_table_creation_validator import ChildTableCreationValidator


class ValidationSuite:
    """Comprehensive validation suite with performance monitoring"""
    
    def __init__(self, app_path: str, quiet: bool = False, skip_template: bool = False, skip_loop_context: bool = False):
        self.app_path = Path(app_path)
        self.quiet = quiet
        self.skip_template = skip_template
        self.skip_loop_context = skip_loop_context
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
            field_validator = ContextAwareFieldValidator(str(self.app_path))
            issues = field_validator.validate_directory(pre_commit=True)
            field_passed = len(issues) == 0
            
            if not field_passed and not self.quiet:
                self.log(f"⚠️ Found {len(issues)} field reference issues")
            
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
            template_validator = ModernTemplateValidator(str(self.app_path))
            issues, template_passed = template_validator.run_validation()
            
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
    
    def run_loop_context_validation(self) -> bool:
        """Run loop context field validation with timing"""
        if self.skip_loop_context:
            self.results['loop_context_validation'] = {
                'passed': True,
                'duration': 0,
                'error': None,
                'skipped': True
            }
            return True
        
        start_time = time.time()
        
        self.log("\n3️⃣ Loop Context Field Validation")
        self.log("-" * 40)
        
        try:
            # Load DocType definitions
            doctype_dir = self.app_path / 'verenigingen' / 'doctype'
            doctypes = load_doctypes(str(doctype_dir))
            
            # Find all Python files to validate
            python_files = list(self.app_path.glob('**/*.py'))
            
            # Filter out test files and archived files
            python_files = [
                f for f in python_files 
                if not any(excluded in str(f) for excluded in [
                    'archived_unused', 'archived_', 'phase4_removed', 'backup', 
                    '__pycache__', '.git', 'test_', 'one-off-test-utils'
                ])
            ]
            
            # Validate files
            all_errors = []
            for filepath in python_files:
                try:
                    with open(filepath, 'r') as f:
                        source = f.read()
                    
                    tree = ast.parse(source)
                    validator = LoopContextFieldValidator(doctypes)
                    validator.current_file = str(filepath)
                    validator.visit(tree)
                    
                    all_errors.extend(validator.errors)
                except Exception:
                    # Skip files that can't be parsed
                    pass
            
            duration = time.time() - start_time
            
            if all_errors:
                if not self.quiet:
                    self.log(f"\n❌ Found {len(all_errors)} loop context field errors")
                    # Show first 5 errors in non-quiet mode
                    for error in all_errors[:5]:
                        rel_path = Path(error['file']).relative_to(self.app_path)
                        self.log(f"   {rel_path}:{error['line']}: {error['error']}")
                    if len(all_errors) > 5:
                        self.log(f"   ... and {len(all_errors) - 5} more")
                
                self.results['loop_context_validation'] = {
                    'passed': False,
                    'duration': duration,
                    'error': f"{len(all_errors)} loop context errors found",
                    'error_count': len(all_errors)
                }
                return False
            else:
                if not self.quiet:
                    self.log("✅ No loop context field errors found")
                
                self.results['loop_context_validation'] = {
                    'passed': True,
                    'duration': duration,
                    'error': None,
                    'error_count': 0
                }
                return True
            
        except Exception as e:
            duration = time.time() - start_time
            self.results['loop_context_validation'] = {
                'passed': False,
                'duration': duration,
                'error': str(e)
            }
            self.log(f"❌ Loop context validation failed: {e}", force=True)
            return False
    
    def run_child_table_validation(self) -> bool:
        """Run child table creation pattern validation with timing"""
        start_time = time.time()
        
        self.log("\n4️⃣ Child Table Creation Pattern Validation")
        self.log("-" * 40)
        
        try:
            # Find bench path - go up from app path to find bench root
            bench_path = self.app_path.parent.parent
            if not (bench_path / 'apps' / 'sites').exists():
                # Try alternative bench path detection
                bench_path = self.app_path
                while bench_path.parent != bench_path:
                    if (bench_path / 'apps').exists() and (bench_path / 'sites').exists():
                        break
                    bench_path = bench_path.parent
                else:
                    bench_path = self.app_path.parent.parent  # Fallback
            
            validator = ChildTableCreationValidator(bench_path)
            issues = validator.validate_directory(self.app_path)
            
            # Filter to high confidence for suite validation
            high_confidence_issues = [i for i in issues if i.confidence == 'high']
            child_table_passed = len(high_confidence_issues) == 0
            
            duration = time.time() - start_time
            self.results['child_table_validation'] = {
                'passed': child_table_passed,
                'duration': duration,
                'error': None,
                'issues_found': len(issues),
                'high_confidence_issues': len(high_confidence_issues)
            }
            
            if not child_table_passed and not self.quiet:
                self.log(f"⚠️ Found {len(high_confidence_issues)} high-confidence child table creation issues")
                for issue in high_confidence_issues[:3]:  # Show first 3
                    rel_path = Path(issue.file).relative_to(self.app_path)
                    self.log(f"   {rel_path}:{issue.line}: {issue.message}")
                if len(high_confidence_issues) > 3:
                    self.log(f"   ... and {len(high_confidence_issues) - 3} more")
            
            if not self.quiet:
                self.log(f"⏱️ Child table validation completed in {duration:.2f}s")
                if len(issues) > len(high_confidence_issues):
                    self.log(f"   (Found {len(issues) - len(high_confidence_issues)} additional lower-confidence issues)")
                
            return child_table_passed
            
        except Exception as e:
            duration = time.time() - start_time
            self.results['child_table_validation'] = {
                'passed': False,
                'duration': duration,
                'error': str(e)
            }
            self.log(f"❌ Child table validation failed: {e}", force=True)
            return False
    
    def run_comprehensive_validation(self) -> bool:
        """Run all validations with performance monitoring"""
        total_start = time.time()
        
        self.log("🚀 Running Comprehensive Code Validation Suite")
        self.log("=" * 60)
        
        # Run validations
        field_passed = self.run_field_validation()
        template_passed = self.run_template_validation()
        loop_context_passed = self.run_loop_context_validation()
        child_table_passed = self.run_child_table_validation()
        
        all_passed = field_passed and template_passed and loop_context_passed and child_table_passed
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
        loop_context_time = self.results.get('loop_context_validation', {}).get('duration', 0)
        child_table_time = self.results.get('child_table_validation', {}).get('duration', 0)
        
        self.log(f"\n⏱️ Total validation time: {total_duration:.2f}s", force=True)
        self.log(f"   • Field validation: {field_time:.2f}s", force=True)
        if not self.skip_template:
            self.log(f"   • Template validation: {template_time:.2f}s", force=True)
        if not self.skip_loop_context:
            self.log(f"   • Loop context validation: {loop_context_time:.2f}s", force=True)
        self.log(f"   • Child table validation: {child_table_time:.2f}s", force=True)
        
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
    
    parser.add_argument(
        '--skip-loop-context',
        action='store_true',
        help='Skip loop context field validation'
    )
    
    parser.add_argument(
        '--loop-context-only',
        action='store_true',
        help='Run only loop context field validation'
    )
    
    args = parser.parse_args()
    
    # Get app path
    script_path = Path(__file__).resolve()
    app_path = script_path.parent.parent.parent
    
    if not (app_path / 'verenigingen' / 'hooks.py').exists():
        print(f"Error: hooks.py not found at {app_path}")
        sys.exit(1)
    
    # Create validation suite
    skip_template = args.skip_template or args.field_only or args.loop_context_only
    skip_loop_context = args.skip_loop_context or args.field_only
    suite = ValidationSuite(
        str(app_path), 
        quiet=args.quiet, 
        skip_template=skip_template,
        skip_loop_context=skip_loop_context
    )
    
    # Run validations
    if args.field_only:
        success = suite.run_field_validation()
    elif args.loop_context_only:
        success = suite.run_loop_context_validation()
    else:
        success = suite.run_comprehensive_validation()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()