#!/usr/bin/env python3
"""
Pragmatic Database Query Field Validator

A production-ready field validator that builds on the improved validator with 
selective exclusions for common false positive patterns while maintaining 
high-value validation for critical field references.

Key Features:
1. Builds on existing improved validator that already fixed genuine issues
2. Adds selective exclusions for common false positive patterns:
   - Child table field access patterns (item.field in loops)
   - Wildcard selections ("*" in frappe.db.get_value)
   - Field aliases with "as" keyword
   - Property method patterns (@property def field)
   - Dynamic field references in certain contexts
3. Maintains validation for:
   - Direct field references in frappe.db calls
   - Filter field references
   - Critical business logic field access
   - API endpoint field usage
4. Configurable validation levels (strict/balanced/permissive)
5. Performance suitable for pre-commit hooks
6. Clear documentation on what is and isn't validated

Validation Strategy:
- Pattern-based exclusion rules rather than complex parsing
- Configurable exclusion levels
- Clear error messages with context
- Practical for daily development use
"""

import ast
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Set, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum


class ValidationLevel(Enum):
    """Validation levels with different false positive tolerance"""
    STRICT = "strict"          # Minimal exclusions, catches everything
    BALANCED = "balanced"      # Practical exclusions for development
    PERMISSIVE = "permissive"  # Maximum exclusions, only critical issues


@dataclass
class ValidationConfig:
    """Configuration for validation behavior"""
    level: ValidationLevel = ValidationLevel.BALANCED
    exclude_child_table_patterns: bool = True
    exclude_wildcard_selections: bool = True
    exclude_field_aliases: bool = True
    exclude_property_methods: bool = True
    exclude_dynamic_references: bool = True
    exclude_template_contexts: bool = True
    
    @classmethod
    def for_level(cls, level: ValidationLevel) -> 'ValidationConfig':
        """Create config for validation level"""
        if level == ValidationLevel.STRICT:
            return cls(
                level=level,
                exclude_child_table_patterns=False,
                exclude_wildcard_selections=True,  # Always exclude, this is valid
                exclude_field_aliases=True,        # Always exclude, this is valid
                exclude_property_methods=False,
                exclude_dynamic_references=False,
                exclude_template_contexts=False,
            )
        elif level == ValidationLevel.BALANCED:
            return cls(
                level=level,
                exclude_child_table_patterns=True,
                exclude_wildcard_selections=True,
                exclude_field_aliases=True,
                exclude_property_methods=True,
                exclude_dynamic_references=True,
                exclude_template_contexts=True,
            )
        else:  # PERMISSIVE
            return cls(
                level=level,
                exclude_child_table_patterns=True,
                exclude_wildcard_selections=True,
                exclude_field_aliases=True,
                exclude_property_methods=True,
                exclude_dynamic_references=True,
                exclude_template_contexts=True,
            )


class PragmaticDatabaseQueryValidator:
    """Enhanced validator with selective exclusions for false positives"""
    
    def __init__(self, app_path: str, config: ValidationConfig = None):
        self.app_path = Path(app_path)
        self.config = config or ValidationConfig.for_level(ValidationLevel.BALANCED)
        self.doctypes = self.load_doctypes()
        self.violations = []
        
        # Exclusion patterns based on configuration
        self.exclusion_patterns = self._build_exclusion_patterns()
        
    def _build_exclusion_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Build regex patterns for exclusions based on configuration"""
        patterns = {
            'child_table': [],
            'property_methods': [],
            'dynamic_references': [],
            'template_contexts': [],
        }
        
        if self.config.exclude_child_table_patterns:
            patterns['child_table'] = [
                # for item in items: ... item.field_name
                re.compile(r'for\s+\w+\s+in\s+.*:', re.IGNORECASE),
                # item.field patterns in general
                re.compile(r'\w+\.\w+(?:\s*[,\]\)]|$)', re.IGNORECASE),
                # Loop iteration patterns
                re.compile(r'(?:enumerate|zip|range)\s*\(', re.IGNORECASE),
            ]
            
        if self.config.exclude_property_methods:
            patterns['property_methods'] = [
                # @property decorator
                re.compile(r'@property', re.IGNORECASE),
                # def method with property-like naming
                re.compile(r'def\s+(?:get_|is_|has_)\w+', re.IGNORECASE),
            ]
            
        if self.config.exclude_dynamic_references:
            patterns['dynamic_references'] = [
                # getattr calls
                re.compile(r'getattr\s*\(', re.IGNORECASE),
                # hasattr calls
                re.compile(r'hasattr\s*\(', re.IGNORECASE),
                # setattr calls
                re.compile(r'setattr\s*\(', re.IGNORECASE),
                # Dynamic field access via dict
                re.compile(r'\[[\'\"].*?[\'\"]\]', re.IGNORECASE),
            ]
            
        if self.config.exclude_template_contexts:
            patterns['template_contexts'] = [
                # Template variable references
                re.compile(r'\{\{.*?\}\}', re.IGNORECASE),
                # JavaScript object field access
                re.compile(r'\.get\s*\(\s*[\'\"]\w+[\'\"]\s*\)', re.IGNORECASE),
            ]
            
        return patterns
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions (same as improved validator)"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name')
                    if not doctype_name:
                        continue
                        
                    fields = set()
                    for field in data.get('fields', []):
                        if 'fieldname' in field:
                            fields.add(field['fieldname'])
                    
                    # Add standard fields that exist on all doctypes
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx'
                    ])
                    
                    doctypes[doctype_name] = fields
                    
                except Exception as e:
                    print(f"Error loading {json_file}: {e}")
                    
        return doctypes
    
    def is_valid_frappe_pattern(self, field: str) -> bool:
        """Check if field reference uses valid Frappe patterns (enhanced from improved validator)"""
        
        # Pattern 1: Wildcard "*" - Always valid in Frappe
        if field == "*" and self.config.exclude_wildcard_selections:
            return True
            
        # Pattern 2: Field aliases with "as" - Valid SQL syntax supported by Frappe
        if " as " in field and self.config.exclude_field_aliases:
            return True
            
        # Pattern 3: Joined field references (table.field) - Valid in Frappe queries
        if "." in field and not field.startswith("eval:"):
            return True
            
        # Pattern 4: Conditional fields (eval:) - Skip validation
        if field.startswith("eval:"):
            return True
            
        # Pattern 5: SQL functions (COUNT, SUM, etc.)
        if any(func in field.upper() for func in ['COUNT(', 'SUM(', 'AVG(', 'MAX(', 'MIN(', 'DISTINCT']):
            return True
            
        return False
    
    def should_exclude_line(self, line: str, context_lines: List[str], line_number: int) -> Tuple[bool, str]:
        """
        Check if a line should be excluded from validation based on context patterns.
        Returns (should_exclude, reason)
        """
        line_stripped = line.strip()
        
        # Get surrounding context for better pattern matching
        context_start = max(0, line_number - 3)
        context_end = min(len(context_lines), line_number + 2)
        context_block = "\n".join(context_lines[context_start:context_end])
        
        # Check child table patterns
        if self.config.exclude_child_table_patterns:
            for pattern in self.exclusion_patterns['child_table']:
                if pattern.search(line_stripped) or pattern.search(context_block):
                    # Additional check: is this in a loop context?
                    for i in range(max(0, line_number - 5), min(len(context_lines), line_number + 1)):
                        if any(loop_keyword in context_lines[i] for loop_keyword in ['for ', 'while ', 'enumerate(', 'zip(']):
                            return True, f"child_table_iteration (line {i+1})"
        
        # Check property method patterns
        if self.config.exclude_property_methods:
            for pattern in self.exclusion_patterns['property_methods']:
                if pattern.search(context_block):
                    return True, "property_method_context"
        
        # Check dynamic reference patterns
        if self.config.exclude_dynamic_references:
            for pattern in self.exclusion_patterns['dynamic_references']:
                if pattern.search(line_stripped):
                    return True, "dynamic_field_reference"
        
        # Check template context patterns
        if self.config.exclude_template_contexts:
            for pattern in self.exclusion_patterns['template_contexts']:
                if pattern.search(line_stripped):
                    return True, "template_variable_context"
        
        return False, ""
    
    def extract_query_calls(self, content: str) -> List[Dict]:
        """Extract database query calls from Python content (enhanced from improved validator)"""
        queries = []
        source_lines = content.splitlines()
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    query_info = self.analyze_query_call(node, source_lines)
                    if query_info:
                        # Check if this line should be excluded
                        should_exclude, reason = self.should_exclude_line(
                            source_lines[node.lineno - 1], 
                            source_lines, 
                            node.lineno - 1
                        )
                        
                        if should_exclude:
                            query_info['excluded'] = True
                            query_info['exclusion_reason'] = reason
                        else:
                            query_info['excluded'] = False
                            
                        queries.append(query_info)
                        
        except Exception as e:
            print(f"Error parsing content: {e}")
            
        return queries
    
    def analyze_query_call(self, node: ast.Call, source_lines: List[str]) -> Optional[Dict]:
        """Analyze a function call to see if it's a database query (same as improved validator)"""
        
        # Check for frappe.get_all, frappe.db.get_value, etc.
        call_patterns = {
            'frappe.get_all': self.extract_get_all_fields,
            'frappe.db.get_all': self.extract_get_all_fields,
            'frappe.get_list': self.extract_get_all_fields,
            'frappe.db.get_list': self.extract_get_all_fields,
            'frappe.db.get_value': self.extract_get_value_fields,
            'frappe.db.get_values': self.extract_get_value_fields,
            'frappe.db.sql': self.extract_sql_fields,  # Basic SQL validation
        }
        
        # Get the full function call name
        func_name = self.get_function_name(node)
        if not func_name or func_name not in call_patterns:
            return None
            
        # Extract doctype and fields
        extractor = call_patterns[func_name]
        return extractor(node, source_lines, func_name)
    
    def get_function_name(self, node: ast.Call) -> Optional[str]:
        """Extract the full function name from a call node (same as improved validator)"""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Attribute):
                # frappe.db.get_all
                if (isinstance(node.func.value.value, ast.Name) and 
                    node.func.value.value.id == 'frappe'):
                    return f"frappe.{node.func.value.attr}.{node.func.attr}"
            elif isinstance(node.func.value, ast.Name) and node.func.value.id == 'frappe':
                # frappe.get_all
                return f"frappe.{node.func.attr}"
        return None
    
    def extract_get_all_fields(self, node: ast.Call, source_lines: List[str], func_name: str) -> Optional[Dict]:
        """Extract fields from frappe.get_all() calls (same as improved validator)"""
        if not node.args:
            return None
            
        # First argument should be doctype
        doctype = self.extract_string_value(node.args[0])
        if not doctype:
            return None
            
        result = {
            'line': node.lineno,
            'function': func_name,
            'doctype': doctype,
            'context': source_lines[node.lineno - 1].strip() if node.lineno <= len(source_lines) else "",
            'filter_fields': [],
            'select_fields': []
        }
        
        # Look for filters and fields in keyword arguments
        for keyword in node.keywords:
            if keyword.arg == 'filters':
                result['filter_fields'] = self.extract_filter_fields(keyword.value)
            elif keyword.arg == 'fields':
                result['select_fields'] = self.extract_field_list(keyword.value)
        
        return result
    
    def extract_get_value_fields(self, node: ast.Call, source_lines: List[str], func_name: str) -> Optional[Dict]:
        """Extract fields from frappe.db.get_value() calls (same as improved validator)"""
        if len(node.args) < 2:
            return None
            
        doctype = self.extract_string_value(node.args[0])
        if not doctype:
            return None
            
        result = {
            'line': node.lineno,
            'function': func_name,
            'doctype': doctype,
            'context': source_lines[node.lineno - 1].strip() if node.lineno <= len(source_lines) else "",
            'filter_fields': [],
            'select_fields': []
        }
        
        # Second argument can be filters (dict) or name (string)
        if len(node.args) > 1:
            filters = self.extract_filter_fields(node.args[1])
            if filters:
                result['filter_fields'] = filters
        
        # Third argument is usually the fields to select
        if len(node.args) > 2:
            result['select_fields'] = self.extract_field_list(node.args[2])
            
        return result
    
    def extract_sql_fields(self, node: ast.Call, source_lines: List[str], func_name: str) -> Optional[Dict]:
        """Basic SQL field extraction (limited) - same as improved validator"""
        # Skip SQL validation for now as it's complex
        return None
    
    def extract_string_value(self, node: ast.AST) -> Optional[str]:
        """Extract string value from an AST node (same as improved validator)"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        # Fallback for older Python versions
        elif hasattr(node, 's') and isinstance(getattr(node, 's', None), str):
            return node.s
        return None
    
    def extract_filter_fields(self, node: ast.AST) -> List[str]:
        """Extract field names from filter dictionaries (same as improved validator)"""
        fields = []
        
        if isinstance(node, ast.Dict):
            for key in node.keys:
                field_name = self.extract_string_value(key)
                if field_name:
                    fields.append(field_name)
                    
        return fields
    
    def extract_field_list(self, node: ast.AST) -> List[str]:
        """Extract field names from field lists (same as improved validator)"""
        fields = []
        
        if isinstance(node, ast.List):
            for item in node.elts:
                field_name = self.extract_string_value(item)
                if field_name:
                    fields.append(field_name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Single field as string
            field_name = self.extract_string_value(node)
            if field_name:
                fields.append(field_name)
        # Fallback for older Python versions
        elif hasattr(node, 's') and isinstance(getattr(node, 's', None), str):
            field_name = self.extract_string_value(node)
            if field_name:
                fields.append(field_name)
                
        return fields
    
    def validate_field_reference(self, doctype: str, field: str) -> Optional[Dict]:
        """Validate a single field reference (same as improved validator)"""
        
        # Skip validation for valid Frappe patterns
        if self.is_valid_frappe_pattern(field):
            return None
            
        # Check if doctype exists
        if doctype not in self.doctypes:
            return None  # Skip unknown doctypes
            
        valid_fields = self.doctypes[doctype]
        
        # Check if field exists
        if field not in valid_fields:
            return {
                'doctype': doctype,
                'field': field,
                'error': f"Field '{field}' does not exist in {doctype}",
                'available_fields': sorted(list(valid_fields))
            }
            
        return None
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate database queries in a single file (enhanced with exclusions)"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            queries = self.extract_query_calls(content)
            
            for query in queries:
                # Skip excluded queries
                if query.get('excluded', False):
                    continue
                    
                doctype = query['doctype']
                
                # Check filter fields
                for field in query['filter_fields']:
                    violation = self.validate_field_reference(doctype, field)
                    if violation:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': query['line'],
                            'field': field,
                            'doctype': doctype,
                            'context': query['context'],
                            'issue_type': 'filter_field',
                            'function': query['function'],
                            'error': violation['error'],
                            'suggestions': violation['available_fields'][:5],  # Top 5 suggestions
                            'validation_level': self.config.level.value
                        })
                
                # Check select fields  
                for field in query['select_fields']:
                    violation = self.validate_field_reference(doctype, field)
                    if violation:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': query['line'],
                            'field': field,
                            'doctype': doctype,
                            'context': query['context'],
                            'issue_type': 'select_field',
                            'function': query['function'],
                            'error': violation['error'],
                            'suggestions': violation['available_fields'][:5],  # Top 5 suggestions
                            'validation_level': self.config.level.value
                        })
                        
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
            
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Validate database queries in the entire app (same as improved validator)"""
        violations = []
        
        # Check Python files throughout the app
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip test files and __pycache__
            if '__pycache__' in str(py_file) or '.git' in str(py_file):
                continue
                
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            
        return violations
    
    def get_validation_stats(self) -> Dict:
        """Get statistics about validation configuration"""
        return {
            'validation_level': self.config.level.value,
            'exclusions_enabled': {
                'child_table_patterns': self.config.exclude_child_table_patterns,
                'wildcard_selections': self.config.exclude_wildcard_selections,
                'field_aliases': self.config.exclude_field_aliases,
                'property_methods': self.config.exclude_property_methods,
                'dynamic_references': self.config.exclude_dynamic_references,
                'template_contexts': self.config.exclude_template_contexts,
            },
            'doctypes_loaded': len(self.doctypes),
        }


def main():
    """Run the pragmatic database query field validator"""
    parser = argparse.ArgumentParser(description='Pragmatic Field Validator with Selective Exclusions')
    parser.add_argument('--level', 
                        choices=['strict', 'balanced', 'permissive'], 
                        default='balanced',
                        help='Validation level (default: balanced)')
    parser.add_argument('--app-path',
                        default="/home/frappe/frappe-bench/apps/verenigingen/verenigingen",
                        help='Path to app directory')
    parser.add_argument('--stats', action='store_true',
                        help='Show validation statistics')
    
    args = parser.parse_args()
    
    # Create validation config
    validation_level = ValidationLevel(args.level)
    config = ValidationConfig.for_level(validation_level)
    
    print(f"🔍 Running pragmatic database query field validation...")
    print(f"📊 Validation Level: {validation_level.value.upper()}")
    
    validator = PragmaticDatabaseQueryValidator(args.app_path, config)
    
    if args.stats:
        stats = validator.get_validation_stats()
        print(f"\n📈 Validation Statistics:")
        print(f"   🏷️  Doctypes loaded: {stats['doctypes_loaded']}")
        print(f"   ⚙️  Level: {stats['validation_level']}")
        print(f"   🚫 Exclusions enabled:")
        for exclusion, enabled in stats['exclusions_enabled'].items():
            status = "✅" if enabled else "❌"
            print(f"      {status} {exclusion.replace('_', ' ').title()}")
        print()
    
    violations = validator.validate_app()
    
    if violations:
        print(f"\n❌ Found {len(violations)} field reference issues:")
        print("-" * 80)
        
        for v in violations:
            print(f"📁 {v['file']}:{v['line']}")
            print(f"   🏷️  {v['doctype']}.{v['field']} - {v['error']}")
            print(f"   📋 {v['issue_type']} in {v['function']}()")
            print(f"   💾 {v['context']}")
            if v.get('suggestions'):
                print(f"   💡 Suggestions: {', '.join(v['suggestions'])}")
            print(f"   ⚙️  Level: {v['validation_level']}")
            print()
            
        return 1
    else:
        print("✅ No field reference issues found!")
        print(f"🎯 Validation level '{validation_level.value}' applied with appropriate exclusions")
        print("🔍 All critical field references validated successfully")
        return 0


if __name__ == "__main__":
    exit(main())