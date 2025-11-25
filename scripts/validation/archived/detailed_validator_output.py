#!/usr/bin/env python3
"""
Detailed SQL Field Validator Output
Shows all medium confidence issues for investigation
"""

from enhanced_sql_field_validator import EnhancedSQLFieldValidator

def main():
    """Show detailed output for all medium confidence issues"""
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = EnhancedSQLFieldValidator(app_path)
    
    violations = validator.validate_directory()
    
    # Filter for medium confidence issues
    med_conf = [v for v in violations if v.confidence == 'medium']
    
    print(f"🟡 MEDIUM CONFIDENCE ISSUES ({len(med_conf)} total):")
    print()
    
    for i, violation in enumerate(med_conf, 1):
        print(f"{i}. ❌ {violation.file}:{violation.line}")
        print(f"   {violation.message}")
        print(f"   Reference: {violation.reference}")
        print(f"   SQL: {violation.sql_context}")
        print()
        
        # Show first 10 for detailed analysis
        if i >= 10:
            print(f"... and {len(med_conf) - 10} more medium confidence issues")
            break

if __name__ == "__main__":
    main()