#!/usr/bin/env python3
"""
Pre-commit hook script for field validation
Uses smart validation logic to focus on real issues, ignoring framework noise
"""

import os
import sys
import re
import json
import argparse
import ast
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional

# Add the app path to Python path
app_path = Path(__file__).parent.parent
sys.path.insert(0, str(app_path))


class PreCommitSmartFieldValidator:
    """Smart field validator for pre-commit hooks"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.errors = []
        self.warnings = []
        self.doctype_schemas = {}
        self.load_doctype_schemas()
        
        # Known problematic patterns from our analysis
        self.critical_field_patterns = {
            'amount',  # Changed to dues_rate in Membership Dues Schedule
            'suggested_contribution', 
            'minimum_contribution',
            'maximum_contribution',
            'default_amount',  # Changed to minimum_amount in Membership Type
        }
        
        # Framework attributes that are NOT field access issues
        self.framework_attributes = {
            # Frappe framework
            'whitelist', 'get_doc', 'new_doc', 'get_value', 'get_all', 'db', 'session',
            'throw', 'msgprint', 'log_error', 'utils', 'local', 'response',
            
            # Python/system attributes
            'path', 'exists', 'load', 'loads', 'dumps', 'join', 'split', 'strip',
            'format', 'replace', 'startswith', 'endswith', 'lower', 'upper',
            'append', 'remove', 'insert', 'save', 'delete', 'update', 'get',
            'keys', 'values', 'items', 'reload', 'today', 'now', 'add_days',
            
            # Common object methods/properties
            'name', 'creation', 'modified', 'status', 'enabled', 'is_active',
            'member', 'volunteer', 'chapter', 'role', 'email', 'user',
            
            # Standard Frappe document methods/properties
            'doctype', 'docstatus', 'owner', 'modified_by', 'idx', 'parent',
            'parenttype', 'parentfield', 'validate', 'before_save', 'after_insert',
            'on_update', 'on_submit', 'cancel', 'submit', 'run_method',
        }
    
    def load_doctype_schemas(self):
        """Load all DocType schemas from JSON files"""
        doctype_path = app_path / "verenigingen" / "doctype"
        
        if not doctype_path.exists():
            print(f"Warning: DocType directory not found at {doctype_path}")
            return
            
        for doctype_dir in doctype_path.iterdir():
            if doctype_dir.is_dir():
                json_file = doctype_dir / f"{doctype_dir.name}.json"
                if json_file.exists():
                    try:
                        with open(json_file, 'r') as f:
                            schema = json.load(f)
                            doctype_name = schema.get('name', doctype_dir.name)
                            
                            # Extract field names
                            fields = set()
                            for field in schema.get('fields', []):
                                fieldname = field.get('fieldname')
                                if fieldname:
                                    fields.add(fieldname)
                            
                            # Add standard Frappe document fields
                            fields.update([
                                'name', 'creation', 'modified', 'modified_by', 'owner',
                                'docstatus', 'parent', 'parentfield', 'parenttype', 'idx'
                            ])
                            
                            self.doctype_schemas[doctype_name] = fields
                            
                            if self.verbose:
                                print(f"Loaded schema for {doctype_name} with {len(fields)} fields")
                    except Exception as e:
                        print(f"Warning: Failed to load schema from {json_file}: {e}")
    
    def is_critical_pattern(self, field_name: str, line_content: str) -> bool:
        """Check if this is a critical field pattern we care about"""
        
        # Focus on our known problematic patterns
        if field_name not in self.critical_field_patterns:
            return False
            
        # Additional context checks to reduce false positives
        critical_contexts = [
            'membership', 'dues', 'billing', 'contribution', 'template'
        ]
        
        line_lower = line_content.lower()
        return any(context in line_lower for context in critical_contexts)
    
    def is_sql_field_reference(self, line_content: str) -> List[str]:
        """Check for SQL field references that might be problematic"""
        problematic_sql = []
        
        # Look for SQL queries with our critical fields (exact word match)
        if 'select' in line_content.lower():
            for field in self.critical_field_patterns:
                # Use word boundary matching to avoid false positives like minimum_amount containing "amount"
                import re
                pattern = r'\b' + re.escape(field) + r'\b'
                if re.search(pattern, line_content.lower()):
                    # Check if it's in a table that we care about
                    if any(table in line_content.lower() for table in [
                        'tabmembership dues schedule',
                        'tabmembership type', 
                        'tabmember'
                    ]):
                        problematic_sql.append(field)
                        
        return problematic_sql
    
    def validate_file(self, filepath: str) -> bool:
        """Validate field references in a single file using smart logic"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.warnings.append(f"Could not read {filepath}: {e}")
            return True
        
        source_lines = content.splitlines()
        file_path = Path(filepath)
        has_critical_issues = False
        
        # Check for SQL field references first
        for line_no, line in enumerate(source_lines, 1):
            sql_issues = self.is_sql_field_reference(line)
            for field in sql_issues:
                self.errors.append(
                    f"{filepath}:{line_no} - SQL query references deprecated field '{field}'"
                )
                has_critical_issues = True
        
        # Parse AST for Python field access
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    field_name = node.attr
                    line_no = node.lineno
                    
                    if line_no <= len(source_lines):
                        line_content = source_lines[line_no - 1].strip()
                    else:
                        continue
                        
                    # Skip framework attributes
                    if field_name in self.framework_attributes:
                        continue
                    
                    # Skip legitimate amount references on specific doctypes
                    if field_name == 'amount':
                        # tier.amount is legitimate (Membership Tier has amount field)
                        if 'tier.' in line_content.lower() or 'membership tier' in line_content.lower():
                            continue
                        
                    # Only flag critical patterns
                    if self.is_critical_pattern(field_name, line_content):
                        # Provide specific fix suggestions
                        suggestion = ""
                        if field_name == 'amount':
                            if 'membership dues schedule' in line_content.lower():
                                suggestion = " (Fix: Replace with 'dues_rate')"
                            elif 'membership type' in line_content.lower():
                                suggestion = " (Fix: Replace with 'minimum_amount')"
                        
                        self.errors.append(
                            f"{filepath}:{line_no} - Field '{field_name}' may be deprecated{suggestion}"
                        )
                        has_critical_issues = True
                        
        except SyntaxError:
            # Skip files with syntax errors - they'll be caught by other tools
            pass
        
        return not has_critical_issues
    
    def validate_files(self, files: List[str]) -> bool:
        """Validate multiple files with smart filtering"""
        all_valid = True
        files_checked = 0
        
        # Prioritize production code
        production_files = []
        debug_files = []
        
        for filepath in files:
            if not filepath.endswith('.py'):
                continue
                
            # Skip certain patterns
            if any(skip in filepath for skip in [
                '__pycache__', '.git', 'node_modules', 'migrations',
                'patches', 'archived', 'backup', '.disabled'
            ]):
                continue
            
            # Separate production from debug/test files
            if any(pattern in filepath for pattern in [
                'debug', 'test_', '/tests/', 'fix_'
            ]):
                debug_files.append(filepath)
            else:
                production_files.append(filepath)
        
        # Check production files first (fail fast on critical issues)
        for filepath in production_files:
            files_checked += 1
            if not self.validate_file(filepath):
                all_valid = False
        
        # Check debug files but don't fail the commit on them
        debug_issues = 0
        for filepath in debug_files:
            files_checked += 1
            current_errors = len(self.errors)
            self.validate_file(filepath)
            if len(self.errors) > current_errors:
                debug_issues += len(self.errors) - current_errors
                # Remove debug file errors from main error list (convert to warnings)
                debug_errors = self.errors[current_errors:]
                self.errors = self.errors[:current_errors]
                for error in debug_errors:
                    self.warnings.append(f"DEBUG: {error}")
        
        if self.verbose and debug_issues > 0:
            print(f"Note: Found {debug_issues} issues in debug/test files (not blocking commit)")
        
        return all_valid
    
    def print_report(self):
        """Print validation report with smart formatting"""
        if self.errors:
            print("\n🚨 CRITICAL Field Reference Issues (blocking commit):")
            for error in self.errors:
                print(f"  {error}")
                
            print(f"\n💡 These {len(self.errors)} issues need to be fixed before commit.")
            print("   Use the smart field validator for more details:")
            print("   python scripts/validation/smart_field_validator.py")
        
        if self.warnings and self.verbose:
            print("\n⚠️  Field Reference Warnings (not blocking):")
            for warning in self.warnings:
                print(f"  {warning}")
        
        if not self.errors:
            print("✅ All critical field references validated successfully!")
        
        total_issues = len(self.errors) + len(self.warnings)
        if total_issues > 0:
            print(f"\n📊 Summary: {len(self.errors)} critical issues, {len(self.warnings)} warnings/debug issues")
        else:
            print("\n📊 Summary: No field reference issues found!")


def main():
    """Main function for pre-commit hook"""
    parser = argparse.ArgumentParser(description='Smart DocType field reference validation')
    parser.add_argument('files', nargs='*', help='Files to validate')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show warnings and debug info')
    parser.add_argument('--all', action='store_true', help='Validate all Python files')
    
    args = parser.parse_args()
    
    validator = PreCommitSmartFieldValidator(verbose=args.verbose)
    
    if args.all:
        # Find all Python files
        files = []
        for root, dirs, filenames in os.walk(app_path):
            # Skip certain directories
            if any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.egg']):
                continue
            
            for filename in filenames:
                if filename.endswith('.py'):
                    files.append(os.path.join(root, filename))
    else:
        files = args.files if args.files else []
    
    if not files:
        if args.verbose:
            print("No files to validate")
        return 0
    
    if args.verbose:
        print(f"🧠 Smart validation of {len(files)} files...")
        print(f"🎯 Focusing on {len(validator.critical_field_patterns)} critical field patterns")
    
    valid = validator.validate_files(files)
    validator.print_report()
    
    return 0 if valid else 1


if __name__ == '__main__':
    sys.exit(main())