#!/usr/bin/env python3
"""
Quick Field Reference Check
Simple wrapper for common field validation tasks
"""

import argparse
import sys
from pathlib import Path

# Add the validation directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from docfield_checker import DocfieldChecker
from smart_field_validator import SmartFieldValidator


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Check docfield references")
    parser.add_argument("--mode", choices=["quick", "smart", "full"], default="quick",
                       help="Validation mode")
    parser.add_argument("--include-tests", action="store_true",
                       help="Include test files")
    parser.add_argument("--doctype", type=str,
                       help="Check specific doctype only")
    parser.add_argument("--file", type=str,
                       help="Check specific file only")
    parser.add_argument("--fix-suggestions", action="store_true",
                       help="Show fix suggestions")
    
    args = parser.parse_args()
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    if args.mode == "quick":
        # Quick check focused on doctype files
        print("🔍 Running quick field reference check...")
        checker = DocfieldChecker(app_path)
        violations = checker.check_doctype_files()
        
        if violations:
            print(checker.generate_summary(violations))
            if args.fix_suggestions:
                suggestions = checker.find_likely_corrections(violations)
                if suggestions:
                    print("\n🔧 Suggested fixes:")
                    for suggestion in suggestions:
                        print(f"  {suggestion}")
        else:
            print("✅ No field reference issues found!")
            
    elif args.mode == "smart":
        # Smart validation with context awareness
        print("🔍 Running smart field reference validation...")
        validator = SmartFieldValidator(app_path)
        violations = validator.validate_app(include_tests=args.include_tests)
        
        report = validator.generate_report(violations, limit=30)
        print(report)
        
    elif args.mode == "full":
        # Full comprehensive check
        print("🔍 Running comprehensive field reference validation...")
        from docfield_reference_validator import DocfieldReferenceValidator
        
        validator = DocfieldReferenceValidator(app_path)
        violations = validator.validate_references()
        
        report = validator.generate_report(violations)
        print(report)
        
        if args.fix_suggestions:
            suggestions = validator.fix_suggestions(violations)
            if suggestions:
                print("\n💡 Fix suggestions:")
                for suggestion in suggestions:
                    print(f"  {suggestion}")
    
    return 1 if violations else 0


if __name__ == "__main__":
    exit(main())