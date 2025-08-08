#!/usr/bin/env python3
"""
Loop Context Field Validator

This validator catches invalid field references on objects obtained from frappe.get_all loops.
It tracks the DocType context of loop variables and validates attribute access.

The bug pattern it catches:
1. frappe.get_all('Chapter', fields=['name', 'region', ...])
2. for chapter in chapters:
3.     chapter.chapter_name  # <-- ERROR: field not in fields list!

Created: 2025-08-08
Purpose: Catch field reference errors in loop variable attribute access
"""

import ast
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class LoopContextFieldValidator(ast.NodeVisitor):
    """AST visitor that tracks loop variable DocType context and validates field access."""
    
    def __init__(self, doctypes: Dict[str, List[str]]):
        self.doctypes = doctypes
        self.errors = []
        self.loop_var_context = {}  # Maps variable names to (doctype, available_fields, is_dict)
        self.current_file = None
        self.assignments = {}  # Track variable assignments
        self.sql_results = set()  # Track variables that come from SQL queries
        self.in_assignment_target = False  # Track if we're in assignment target
        self.variable_fields = {}  # Track variable definitions for field lists
        
    def visit_Assign(self, node):
        """Track frappe.get_all assignments to variables."""
        # Track field list variable assignments
        if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.List):
            var_name = node.targets[0].id
            # Try to extract field names from list
            fields = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant):
                    fields.append(elt.value)
            if fields:
                self.variable_fields[var_name] = fields
        
        # Track list concatenation (base_fields + coverage_fields)
        if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.BinOp):
            if isinstance(node.value.op, ast.Add):
                var_name = node.targets[0].id
                combined_fields = []
                # Try to resolve both sides
                for operand in [node.value.left, node.value.right]:
                    if isinstance(operand, ast.Name) and operand.id in self.variable_fields:
                        combined_fields.extend(self.variable_fields[operand.id])
                    elif isinstance(operand, ast.List):
                        for elt in operand.elts:
                            if isinstance(elt, ast.Constant):
                                combined_fields.append(elt.value)
                if combined_fields:
                    self.variable_fields[var_name] = combined_fields
        
        if isinstance(node.value, ast.Call):
            # Check for SQL results
            if self._is_sql_query(node.value):
                if isinstance(node.targets[0], ast.Name):
                    var_name = node.targets[0].id
                    self.sql_results.add(var_name)
            # Check for frappe.get_all
            elif self._is_frappe_get_all(node.value):
                doctype, fields, as_dict = self._extract_get_all_info(node.value)
                if doctype and isinstance(node.targets[0], ast.Name):
                    var_name = node.targets[0].id
                    self.assignments[var_name] = (doctype, fields, as_dict)
        
        # Visit targets with assignment flag
        self.in_assignment_target = True
        for target in node.targets:
            self.visit(target)
        self.in_assignment_target = False
        
        # Visit value normally
        self.visit(node.value)
    
    def visit_For(self, node):
        """Track for loops over frappe.get_all results."""
        # Check if iterating over a variable we know about
        if isinstance(node.iter, ast.Name):
            iter_var = node.iter.id
            # Skip SQL results
            if iter_var in self.sql_results:
                self.generic_visit(node)
                return
            if iter_var in self.assignments:
                doctype, fields, as_dict = self.assignments[iter_var]
                if isinstance(node.target, ast.Name):
                    loop_var = node.target.id
                    # Store the DocType context for this loop variable
                    self.loop_var_context[loop_var] = (doctype, fields, as_dict)
        
        # Also check for direct iteration over frappe.get_all
        elif isinstance(node.iter, ast.Call) and self._is_frappe_get_all(node.iter):
            doctype, fields, as_dict = self._extract_get_all_info(node.iter)
            if doctype and isinstance(node.target, ast.Name):
                loop_var = node.target.id
                self.loop_var_context[loop_var] = (doctype, fields, as_dict)
        
        # Visit the loop body with context
        self.generic_visit(node)
        
        # Clean up context after loop (simple approach, may need refinement)
        if isinstance(node.target, ast.Name) and node.target.id in self.loop_var_context:
            del self.loop_var_context[node.target.id]
    
    def visit_Attribute(self, node):
        """Check attribute access on loop variables."""
        # Skip validation if we're in an assignment target (left side of =)
        if self.in_assignment_target:
            self.generic_visit(node)
            return
            
        if isinstance(node.value, ast.Name):
            var_name = node.value.id
            if var_name in self.loop_var_context:
                doctype, available_fields, as_dict = self.loop_var_context[var_name]
                field_name = node.attr
                
                # Skip validation for common methods (both dict methods and object methods)
                common_methods = ['get', 'keys', 'values', 'items', 'pop', 'update', 'setdefault', 
                                'copy', 'clear', 'as_dict', 'get_valid_dict', 'run_method', 'save', 
                                'insert', 'delete', 'reload', 'check_permission']
                if field_name in common_methods:
                    self.generic_visit(node)
                    return
                
                # Skip validation if fields=["*"] (all fields available)
                if available_fields is None:
                    self.generic_visit(node)
                    return
                
                # Check if the field was in the fields list
                if available_fields and field_name not in available_fields:
                    # Check if we have DocType definition loaded
                    valid_fields = self.doctypes.get(doctype, [])
                    if valid_fields:  # We have the DocType loaded
                        if field_name in valid_fields:
                            self.errors.append({
                                'file': self.current_file,
                                'line': node.lineno,
                                'error': f"Field '{field_name}' accessed on '{var_name}' but not included in frappe.get_all fields list",
                                'doctype': doctype,
                                'available_fields': available_fields,
                                'suggestion': f"Add '{field_name}' to the fields list in frappe.get_all"
                            })
                        else:
                            self.errors.append({
                                'file': self.current_file,
                                'line': node.lineno,
                                'error': f"Field '{field_name}' does not exist in DocType '{doctype}'",
                                'doctype': doctype,
                                'available_fields': available_fields,
                                'valid_fields': valid_fields[:10]  # Show first 10 valid fields
                            })
                    else:
                        # DocType not loaded (probably ERPNext or another app) - skip validation to avoid false positives
                        # Only warn if it seems suspicious (not a standard ERPNext DocType)
                        standard_doctypes = {'Account', 'Company', 'Customer', 'Supplier', 'Item', 'User', 'Employee'}
                        if doctype not in standard_doctypes:
                            self.errors.append({
                                'file': self.current_file,
                                'line': node.lineno,
                                'error': f"Field '{field_name}' accessed on '{var_name}' but not included in frappe.get_all fields list (DocType '{doctype}' not loaded for validation)",
                                'doctype': doctype,
                                'available_fields': available_fields,
                                'suggestion': f"Add '{field_name}' to the fields list in frappe.get_all"
                            })
        
        self.generic_visit(node)
    
    def _is_sql_query(self, node):
        """Check if a call is frappe.db.sql or similar SQL query."""
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'sql':
                if isinstance(node.func.value, ast.Attribute):
                    if (node.func.value.attr == 'db' and 
                        isinstance(node.func.value.value, ast.Name) and 
                        node.func.value.value.id == 'frappe'):
                        return True
        return False
    
    def _is_frappe_get_all(self, node):
        """Check if a call is frappe.get_all or frappe.db.get_all."""
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'get_all':
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'frappe':
                    return True
                if isinstance(node.func.value, ast.Attribute):
                    if (node.func.value.attr == 'db' and 
                        isinstance(node.func.value.value, ast.Name) and 
                        node.func.value.value.id == 'frappe'):
                        return True
        return False
    
    def _extract_get_all_info(self, node) -> Tuple[Optional[str], Optional[List[str]], bool]:
        """Extract DocType, fields, and as_dict flag from a frappe.get_all call."""
        doctype = None
        fields = None
        as_dict = False
        
        # Get DocType (first positional arg or 'doctype' keyword)
        if node.args and isinstance(node.args[0], ast.Constant):
            doctype = node.args[0].value
        else:
            for keyword in node.keywords:
                if keyword.arg == 'doctype' and isinstance(keyword.value, ast.Constant):
                    doctype = keyword.value.value
                    break
        
        # Get fields list and as_dict flag
        for keyword in node.keywords:
            if keyword.arg == 'fields':
                if isinstance(keyword.value, ast.List):
                    fields = []
                    for elt in keyword.value.elts:
                        if isinstance(elt, ast.Constant):
                            field_str = elt.value
                            # Handle wildcard - means all fields
                            if field_str == "*":
                                fields = None  # Will be handled as "all fields available"
                                break
                            # Handle field aliases like "posting_date as date"
                            if ' as ' in field_str:
                                # Use the alias name, not the original field
                                alias = field_str.split(' as ')[-1].strip()
                                fields.append(alias)
                            else:
                                fields.append(field_str)
                elif isinstance(keyword.value, ast.Name):
                    # Fields is a variable - try to resolve it
                    var_name = keyword.value.id
                    if var_name in self.variable_fields:
                        fields = self.variable_fields[var_name]
                    else:
                        # Can't resolve - assume all fields available to avoid false positives
                        fields = None
            elif keyword.arg == 'as_dict':
                # Check if as_dict=True
                if isinstance(keyword.value, ast.Constant):
                    as_dict = keyword.value.value == True
                elif isinstance(keyword.value, ast.NameConstant):
                    as_dict = keyword.value.value == True
        
        # If no fields specified, frappe.get_all returns ["name"] by default
        # BUT if fields was set to None due to wildcard ["*"], keep it None
        if doctype and fields is None:
            # Check if this was a wildcard case by looking for "*" in the original call
            is_wildcard = False
            for keyword in node.keywords:
                if keyword.arg == 'fields' and isinstance(keyword.value, ast.List):
                    for elt in keyword.value.elts:
                        if isinstance(elt, ast.Constant) and elt.value == "*":
                            is_wildcard = True
                            break
            
            if not is_wildcard:
                fields = ["name"]
        
        # frappe.get_all returns dictionaries by default (as_dict=True is the default)
        # Only returns objects when as_dict=False is explicitly set
        if 'as_dict' not in [kw.arg for kw in node.keywords]:
            as_dict = True  # Default behavior
        
        return doctype, fields, as_dict


def load_doctypes(doctype_dir: str) -> Dict[str, List[str]]:
    """Load all DocType definitions to get valid field names."""
    doctypes = {}
    
    for root, dirs, files in os.walk(doctype_dir):
        for file in files:
            if file.endswith('.json') and not file.startswith('__'):
                json_path = os.path.join(root, file)
                doctype_name = os.path.basename(os.path.dirname(json_path))
                
                try:
                    with open(json_path, 'r') as f:
                        data = json.load(f)
                        if data.get('doctype') == 'DocType':
                            fields = []
                            for field in data.get('fields', []):
                                if field.get('fieldname'):
                                    fields.append(field['fieldname'])
                            
                            # Use the 'name' field from JSON as the DocType name
                            actual_name = data.get('name', doctype_name.replace('_', ' ').title())
                            doctypes[actual_name] = fields
                except Exception:
                    pass
    
    return doctypes


def validate_file(filepath: str, doctypes: Dict[str, List[str]]) -> List[dict]:
    """Validate a single Python file for loop context field errors."""
    try:
        with open(filepath, 'r') as f:
            source = f.read()
        
        tree = ast.parse(source)
        validator = LoopContextFieldValidator(doctypes)
        validator.current_file = filepath
        validator.visit(tree)
        
        return validator.errors
    except Exception as e:
        return [{'file': filepath, 'error': f'Parse error: {str(e)}'}]


def main():
    """Main validation function."""
    # Determine paths
    if len(sys.argv) > 1:
        # Validate specific file
        target = sys.argv[1]
        if os.path.isfile(target):
            files_to_check = [target]
        else:
            print(f"Error: {target} is not a valid file")
            sys.exit(1)
    else:
        # Validate all Python files in the project
        project_root = Path(__file__).parent.parent.parent
        files_to_check = []
        for pattern in ['**/*.py']:
            files_to_check.extend(project_root.glob(pattern))
    
    # Load DocType definitions from both directories
    doctype_dir1 = Path(__file__).parent.parent.parent / 'verenigingen' / 'doctype'
    doctype_dir2 = Path(__file__).parent.parent.parent / 'verenigingen' / 'e_boekhouden' / 'doctype'
    
    doctypes = load_doctypes(str(doctype_dir1))
    # Also load e_boekhouden DocTypes
    if doctype_dir2.exists():
        doctypes.update(load_doctypes(str(doctype_dir2)))
    
    print(f"🔍 Loop Context Field Validator")
    print(f"📚 Loaded {len(doctypes)} DocTypes")
    print(f"📁 Checking {len(files_to_check)} files")
    print("=" * 80)
    
    # Validate files
    all_errors = []
    for filepath in files_to_check:
        errors = validate_file(str(filepath), doctypes)
        all_errors.extend(errors)
    
    # Report results
    if all_errors:
        print(f"\n❌ Found {len(all_errors)} loop context field errors:\n")
        
        # Group by file
        by_file = {}
        for error in all_errors:
            file = error['file']
            if file not in by_file:
                by_file[file] = []
            by_file[file].append(error)
        
        for file, errors in sorted(by_file.items()):
            # Make path relative for cleaner output
            try:
                rel_path = Path(file).relative_to(Path.cwd())
            except:
                rel_path = file
            
            print(f"\n📄 {rel_path}:")
            for error in errors:
                if 'line' in error:
                    print(f"   Line {error['line']}: {error['error']}")
                    if 'suggestion' in error:
                        print(f"   💡 {error['suggestion']}")
                    if 'available_fields' in error and error['available_fields']:
                        print(f"   📋 Available fields: {', '.join(error['available_fields'][:5])}")
                else:
                    print(f"   {error['error']}")
        
        print(f"\n{'=' * 80}")
        print(f"❌ Total errors: {len(all_errors)}")
        sys.exit(1)
    else:
        print("\n✅ No loop context field errors found!")
        sys.exit(0)


if __name__ == "__main__":
    main()