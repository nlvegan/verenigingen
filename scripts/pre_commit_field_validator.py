#!/usr/bin/env python3
"""
Pre-commit hook script for field validation
Validates that all DocType field references in Python code exist in the schema
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from typing import List, Dict, Set, Tuple

# Add the app path to Python path
app_path = Path(__file__).parent.parent
sys.path.insert(0, str(app_path))


class PreCommitFieldValidator:
    """Validates field references in code files"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.errors = []
        self.warnings = []
        self.doctype_schemas = {}
        self.load_doctype_schemas()
    
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
                            
                            self.doctype_schemas[doctype_name] = fields
                            
                            if self.verbose:
                                print(f"Loaded schema for {doctype_name} with {len(fields)} fields")
                    except Exception as e:
                        print(f"Warning: Failed to load schema from {json_file}: {e}")
    
    def extract_field_references(self, content: str, filename: str) -> List[Tuple[str, str, int]]:
        """Extract potential field references from Python code"""
        references = []
        
        # Patterns to match field references
        patterns = [
            # Direct field access: doc.fieldname or self.fieldname
            (r'(?:doc|self|member|volunteer|chapter|item)\.([a-zA-Z_][a-zA-Z0-9_]*)', 'attribute'),
            
            # Dictionary access: doc["fieldname"] or doc['fieldname']
            (r'(?:doc|data|kwargs|fields)\[["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', 'dict'),
            
            # get() method: doc.get("fieldname")
            (r'\.get\(["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', 'get'),
            
            # db_set() method: doc.db_set("fieldname", value)
            (r'\.db_set\(["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', 'db_set'),
            
            # frappe.db.get_value() calls
            (r'frappe\.db\.get_value\(["\'][A-Za-z\s]+["\']\s*,\s*[^,]+,\s*\[[^\]]*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', 'get_value'),
            
            # Field in filters
            (r'filters\s*=\s*{[^}]*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', 'filter'),
        ]
        
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            # Skip comments and strings
            if line.strip().startswith('#') or line.strip().startswith('"""') or line.strip().startswith("'''"):
                continue
                
            for pattern, ref_type in patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    field_name = match.group(1)
                    
                    # Skip common non-field attributes
                    skip_attrs = {
                        'name', 'save', 'insert', 'delete', 'submit', 'cancel',
                        'reload', 'load_from_db', 'run_method', 'get', 'set',
                        'append', 'remove', 'extend', 'clear', 'validate',
                        'before_save', 'after_insert', 'on_update', 'on_submit',
                        'doctype', 'docstatus', 'owner', 'creation', 'modified',
                        'modified_by', 'idx', 'parent', 'parenttype', 'parentfield'
                    }
                    
                    if field_name not in skip_attrs:
                        references.append((field_name, ref_type, line_num))
        
        return references
    
    def extract_doctype_context(self, content: str, line_num: int) -> str:
        """Try to determine which DocType is being referenced"""
        lines = content.split('\n')
        
        # Look backwards for DocType clues
        for i in range(max(0, line_num - 20), line_num):
            line = lines[i]
            
            # Check for explicit DocType references
            doctype_match = re.search(r'["\']doctype["\']\s*[:=]\s*["\']([A-Za-z\s]+)["\']', line)
            if doctype_match:
                return doctype_match.group(1)
            
            # Check for frappe.get_doc calls
            get_doc_match = re.search(r'frappe\.get_doc\(["\']([A-Za-z\s]+)["\']', line)
            if get_doc_match:
                return get_doc_match.group(1)
            
            # Check for variable names that hint at DocType
            if 'member' in line.lower() and 'Member' in self.doctype_schemas:
                return 'Member'
            elif 'volunteer' in line.lower() and 'Volunteer' in self.doctype_schemas:
                return 'Volunteer'
            elif 'chapter' in line.lower() and 'Chapter' in self.doctype_schemas:
                return 'Chapter'
        
        return None
    
    def validate_file(self, filepath: str) -> bool:
        """Validate field references in a single file"""
        try:
            with open(filepath, 'r') as f:
                content = f.read()
        except Exception as e:
            self.warnings.append(f"Could not read {filepath}: {e}")
            return True
        
        # Extract references
        references = self.extract_field_references(content, filepath)
        
        for field_name, ref_type, line_num in references:
            # Try to determine DocType context
            doctype = self.extract_doctype_context(content, line_num)
            
            if doctype and doctype in self.doctype_schemas:
                if field_name not in self.doctype_schemas[doctype]:
                    # Check if it might be a valid field in another DocType
                    found_in = []
                    for dt, fields in self.doctype_schemas.items():
                        if field_name in fields:
                            found_in.append(dt)
                    
                    if found_in:
                        self.warnings.append(
                            f"{filepath}:{line_num} - Field '{field_name}' not in {doctype}, "
                            f"but exists in: {', '.join(found_in)}"
                        )
                    else:
                        self.errors.append(
                            f"{filepath}:{line_num} - Field '{field_name}' does not exist in DocType '{doctype}'"
                        )
        
        return len(self.errors) == 0
    
    def validate_files(self, files: List[str]) -> bool:
        """Validate multiple files"""
        all_valid = True
        
        for filepath in files:
            if filepath.endswith('.py'):
                if not self.validate_file(filepath):
                    all_valid = False
        
        return all_valid
    
    def print_report(self):
        """Print validation report"""
        if self.errors:
            print("\n❌ Field Validation Errors:")
            for error in self.errors:
                print(f"  {error}")
        
        if self.warnings and self.verbose:
            print("\n⚠️  Field Validation Warnings:")
            for warning in self.warnings:
                print(f"  {warning}")
        
        if not self.errors:
            print("✅ All field references validated successfully!")
        
        print(f"\nSummary: {len(self.errors)} errors, {len(self.warnings)} warnings")


def main():
    """Main function for pre-commit hook"""
    parser = argparse.ArgumentParser(description='Validate DocType field references')
    parser.add_argument('files', nargs='*', help='Files to validate')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show warnings')
    parser.add_argument('--all', action='store_true', help='Validate all Python files')
    
    args = parser.parse_args()
    
    validator = PreCommitFieldValidator(verbose=args.verbose)
    
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
        print("No files to validate")
        return 0
    
    print(f"Validating {len(files)} files...")
    
    valid = validator.validate_files(files)
    validator.print_report()
    
    return 0 if valid else 1


if __name__ == '__main__':
    sys.exit(main())