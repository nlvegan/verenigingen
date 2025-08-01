#!/usr/bin/env python3
"""
Precise Field Validator
Only catches actual docfield reference issues, not framework methods
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional


class PreciseFieldValidator:
    """Very precise validation that only catches real field issues"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        self.frappe_methods = self.load_frappe_methods()
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract only actual field names
                    fields = set()
                    for field in data.get('fields', []):
                        fieldname = field.get('fieldname')
                        if fieldname:
                            fields.add(fieldname)
                            
                    # Add standard Frappe document fields
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
                        'doctype', '_user_tags', '_comments', '_assign', '_liked_by'
                    ])
                    
                    doctypes[doctype_name] = fields
                    
                except Exception:
                    continue
                    
        return doctypes
    
    def load_frappe_methods(self) -> Set[str]:
        """Load known Frappe framework methods and attributes that are NOT fields"""
        return {
            # Core Frappe methods
            'get_doc', 'new_doc', 'get_all', 'get_list', 'get_value', 'set_value',
            'db', 'throw', 'msgprint', 'log_error', 'logger', 'whitelist',
            'call', 'enqueue', 'publish_progress', 'publish_realtime',
            
            # Document methods (lifecycle and validation)
            'save', 'insert', 'delete', 'reload', 'submit', 'cancel', 'validate',
            'before_save', 'after_insert', 'before_delete', 'on_update', 'on_submit',
            'on_cancel', 'before_submit', 'before_cancel', 'after_delete',
            'on_trash', 'on_update_after_submit', 'before_update_after_submit',
            
            # Standard document methods that look like fields but are methods
            'validate_dates', 'validate_amount', 'validate_goals', 'validate_required_fields',
            'validate_member_link', 'validate_chapter_membership_tracking', 'validate_chair_role',
            'validate_subscription_period', 'validate_subscription_plan', 'validate_migration_scope',
            'validate_api_connection', 'validate_required_settings', 'validate_termination_request',
            'validate_expense_details', 'validate_approver_permissions', 'validate_payment_amount',
            'validate_user_roles', 'validate_bank_account', 'validate_sepa_mandate',
            'update_progress', 'update_status', 'update_chapter_membership_history',
            'update_migration_stats', 'update_connection_status', 'update_data_availability',
            'create_employee_if_needed', 'create_minimal_employee', 'create_journal_entry',
            'get_or_create_membership_item', 'get_board_assignments', 'get_team_assignments',
            'get_activity_assignments', 'get_aggregated_assignments', 'get_aggregated_assignments_optimized',
            'get_aggregated_assignments_fallback', 'get_volunteer_history_optimized', 'get_volunteer_history_fallback',
            'get_expense_approver_from_assignments', 'get_board_financial_approver',
            'assign_employee_role', 'ensure_user_has_expense_approver_role',
            'generate_dashboard_html', 'generate_recent_migrations_html',
            
            # Document attributes and state
            'flags', 'meta', 'as_dict', 'as_json', 'get_formatted', 'get_value',
            'set_value', 'db_set', 'db_get', 'run_method', 'has_permission',
            'get_doc_before_save', 'get_title', 'get_feed', 'get_timeline_data',
            'get_url', 'get_signature', 'get_tags', 'add_tag', 'remove_tag',
            'is_new', 'has_value_changed', 'get_doc_before_save', 'is_dirty',
            
            # Collection methods
            'append', 'extend', 'remove', 'pop', 'clear', 'copy', 'update',
            'get', 'set', 'add', 'discard', 'keys', 'values', 'items',
            
            # Python built-ins
            'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple',
            'type', 'isinstance', 'hasattr', 'getattr', 'setattr', 'delattr',
            'vars', 'dir', 'id', 'repr', 'hash', 'iter', 'next', 'enumerate',
            
            # Common variables (not fields)
            'app', 'module', 'method', 'function', 'class', 'object', 'item',
            'key', 'value', 'data', 'result', 'response', 'request', 'config',
            'settings', 'params', 'args', 'kwargs', 'context', 'session',
            'user', 'role', 'permission', 'filter', 'sort', 'limit', 'offset',
            'page', 'size', 'count', 'total', 'sum', 'avg', 'min', 'max',
            'cache', 'logger', 'debug', 'info', 'warn', 'error', 'critical',
            
            # Your app-specific non-field variables
            'volunteer', 'member', 'chapter', 'migration', 'batch', 'mandate',
            'payment', 'invoice', 'expense', 'application', 'termination',
        }
    
    def get_doctype_from_file_path(self, file_path: Path) -> Optional[str]:
        """Extract doctype name from file path"""
        parts = file_path.parts
        if 'doctype' in parts:
            doctype_idx = parts.index('doctype')
            if doctype_idx + 1 < len(parts):
                doctype_dir = parts[doctype_idx + 1]
                # Convert underscore to title case
                doctype_name = doctype_dir.replace('_', ' ').title()
                return doctype_name
        return None
    
    def is_field_access_pattern(self, node: ast.Attribute, source_code: str) -> bool:
        """Check if this is actually a field access pattern"""
        
        # Only consider attribute access on specific variables
        if not isinstance(node.value, ast.Name):
            return False
            
        var_name = node.value.id
        
        # Only check variables that are likely to be document instances
        if var_name not in ['self', 'doc', 'document']:
            return False
            
        # Skip if the attribute is a known method/framework attribute
        if node.attr in self.frappe_methods:
            return False
            
        # Skip private attributes
        if node.attr.startswith('_'):
            return False
            
        # Check if it's followed by parentheses (method call)
        line_start = source_code.rfind('\n', 0, node.col_offset) + 1
        line_end = source_code.find('\n', node.col_offset)
        if line_end == -1:
            line_end = len(source_code)
        line = source_code[line_start:line_end]
        
        # Find the attribute position in the line
        attr_pos = line.find(node.attr)
        if attr_pos != -1:
            # Check what comes after the attribute
            after_attr = line[attr_pos + len(node.attr):].strip()
            if after_attr.startswith('('):
                return False  # It's a method call
                
        return True
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate a single file for field reference issues"""
        violations = []
        
        # Only check files in doctype directories
        doctype_name = self.get_doctype_from_file_path(file_path)
        if not doctype_name or doctype_name not in self.doctypes:
            return violations
            
        valid_fields = self.doctypes[doctype_name]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST
            tree = ast.parse(content)
            
            # Check each attribute access
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if self.is_field_access_pattern(node, content):
                        field_name = node.attr
                        
                        # Check if this field exists in the doctype
                        if field_name not in valid_fields:
                            violations.append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': node.lineno,
                                'column': node.col_offset,
                                'field': field_name,
                                'doctype': doctype_name,
                                'variable': node.value.id,
                                'severity': 'error'
                            })
                            
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Validate the entire app"""
        violations = []
        
        # Only check Python files in doctype directories
        for doctype_dir in self.app_path.rglob("**/doctype/*/"):
            for py_file in doctype_dir.glob("*.py"):
                if py_file.name.startswith('test_'):
                    continue
                    
                file_violations = self.validate_file(py_file)
                violations.extend(file_violations)
                
        return violations
    
    def generate_report(self, violations: List[Dict]) -> str:
        """Generate a focused report"""
        if not violations:
            return "✅ No field reference issues found!"
            
        report = []
        report.append(f"❌ Found {len(violations)} field reference issues:")
        report.append("")
        
        # Group by doctype
        by_doctype = {}
        for violation in violations:
            doctype = violation['doctype']
            if doctype not in by_doctype:
                by_doctype[doctype] = []
            by_doctype[doctype].append(violation)
            
        for doctype, doctype_violations in by_doctype.items():
            report.append(f"## {doctype} ({len(doctype_violations)} issues)")
            
            # Show each violation
            for violation in doctype_violations:
                report.append(f"- Field `{violation['field']}` does not exist")
                report.append(f"  - Location: {violation['file']}:{violation['line']}")
                report.append(f"  - Variable: `{violation['variable']}.{violation['field']}`")
                
                # Suggest similar fields
                similar = self.find_similar_fields(violation['field'], violation['doctype'])
                if similar:
                    report.append(f"  - Similar fields: {', '.join(f'`{f}`' for f in similar)}")
                    
                report.append("")
                
        return '\n'.join(report)
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names in the doctype"""
        if doctype not in self.doctypes:
            return []
            
        similar = []
        field_lower = field_name.lower()
        
        for existing_field in self.doctypes[doctype]:
            existing_lower = existing_field.lower()
            
            # Check for substring matches or similar length
            if (field_lower in existing_lower or 
                existing_lower in field_lower or
                abs(len(field_lower) - len(existing_lower)) <= 2):
                similar.append(existing_field)
                
        return similar[:3]  # Return top 3 matches


def main():
    """Main function"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Running precise field validation...")
    validator = PreciseFieldValidator(app_path)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    
    violations = validator.validate_app()
    
    report = validator.generate_report(violations)
    print(report)
    
    if violations:
        print(f"\n💡 Found {len(violations)} actual field reference issues")
        return 1
    else:
        print("✅ No field reference issues found!")
        return 0


if __name__ == "__main__":
    exit(main())