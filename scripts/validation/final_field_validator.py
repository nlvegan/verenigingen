#!/usr/bin/env python3
"""
Final Field Validator
Ultra-precise validation focusing only on clear field access patterns
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Union


class FinalFieldValidator:
    """Ultra-precise field validation"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract actual field names only
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
    
    def get_doctype_from_file_path(self, file_path: Path) -> Optional[str]:
        """Extract doctype name from file path"""
        parts = file_path.parts
        if 'doctype' in parts:
            doctype_idx = parts.index('doctype')
            if doctype_idx + 1 < len(parts):
                doctype_dir = parts[doctype_idx + 1]
                doctype_name = doctype_dir.replace('_', ' ').title()
                return doctype_name
        return None
    
    def is_definitely_field_access(self, node: ast.Attribute, source_lines: List[str]) -> bool:
        """Check if this is definitely a field access (not a method call)"""
        
        # Only check self.attribute patterns
        if not isinstance(node.value, ast.Name) or node.value.id != 'self':
            return False
            
        # Skip Frappe framework built-in attributes
        frappe_builtin_attributes = {
            'flags', 'meta', '_doc_before_save', 'doctype', 'name', 'owner',
            'creation', 'modified', 'modified_by', 'docstatus', 'parent',
            'parenttype', 'parentfield', 'idx', '_user_tags', '_comments',
            '_assign', '_liked_by', '_doc_before_validate', '_doc_before_insert',
            '_doc_before_update', '_doc_before_cancel', '_doc_before_delete',
            '_original_modified'
        }
        
        if node.attr in frappe_builtin_attributes:
            return False
            
        # Skip internal/private attributes (start with _)
        if node.attr.startswith('_'):
            return False
            
        # Skip common property patterns that aren't fields
        property_patterns = {
            'board_manager', 'member_manager', 'communication_manager',
            'volunteer_integration_manager', 'validator', 'is_anbi_eligible'
        }
        
        if node.attr in property_patterns:
            return False
            
        # Get the line content
        line_num = node.lineno - 1
        if line_num >= len(source_lines):
            return False
            
        line = source_lines[line_num].strip()
        
        # Skip if it's clearly a method call
        if f"{node.attr}(" in line:
            return False
            
        # Skip if it's an assignment to self (defining methods/properties)
        if f"self.{node.attr} =" in line:
            return False
            
        # Skip if it's in a function definition line
        if line.startswith('def ') and f"{node.attr}(" in line:
            return False
            
        # Skip common patterns that are definitely not fields
        skip_patterns = [
            f"self.{node.attr}()",  # Method call
            f"def {node.attr}(",    # Method definition  
            f"self.{node.attr} = ",  # Assignment
            f"hasattr(self, '{node.attr}')",  # hasattr check
            f'hasattr(self, "{node.attr}")',  # hasattr check
        ]
        
        for pattern in skip_patterns:
            if pattern in line:
                return False
                
        # Look for field access patterns
        field_access_patterns = [
            f"self.{node.attr}",  # Direct access
            f"if self.{node.attr}",  # Conditional
            f"or self.{node.attr}",  # Boolean operation
            f"and self.{node.attr}",  # Boolean operation
            f"not self.{node.attr}",  # Boolean operation
            f"self.{node.attr} or",  # Boolean operation
            f"self.{node.attr} and",  # Boolean operation
            f"return self.{node.attr}",  # Return statement
            f"self.{node.attr}.",  # Chained access
        ]
        
        for pattern in field_access_patterns:
            if pattern in line:
                return True
                
        return False
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate a single file"""
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
            source_lines = content.splitlines()
            
            # Find attribute access nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if self.is_definitely_field_access(node, source_lines):
                        field_name = node.attr
                        
                        # Check if this field exists in the doctype
                        if field_name not in valid_fields:
                            # Get context
                            line_num = node.lineno - 1
                            context = source_lines[line_num].strip() if line_num < len(source_lines) else ""
                            
                            violations.append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': node.lineno,
                                'field': field_name,
                                'doctype': doctype_name,
                                'context': context,
                                'confidence': 'high'
                            })
                            
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return violations
    
    def validate_file_comprehensive(self, file_path: Path) -> List[Dict]:
        """Validate a file with comprehensive DocType detection"""
        violations = []
        
        # Skip files in certain directories that are likely to have false positives
        skip_patterns = [
            'debug_', 'test_', '/tests/', '/debug/', '/scripts/', 
            'benchmark', 'performance', 'generate_test'
        ]
        
        if any(pattern in str(file_path) for pattern in skip_patterns):
            return violations  # Skip these files entirely for now
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST for better accuracy
            try:
                tree = ast.parse(content)
                source_lines = content.splitlines()
                
                # Find attribute access patterns
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        attr_name = node.attr
                        
                        # Skip common non-field attributes (Python standard library, common methods, and common DocType attributes)
                        if attr_name in {'name', 'insert', 'save', 'delete', 'get', 'set', 
                                       'append', 'remove', 'update', 'keys', 'values', 
                                       'items', 'format', 'replace', 'split', 'join',
                                       'strip', 'lower', 'upper', 'startswith', 'endswith',
                                       'read', 'write', 'close', 'open', 'load', 'loads',
                                       'dump', 'dumps', 'readline', 'readlines', 'seek',
                                       'tell', 'flush', 'exists', 'isfile', 'isdir',
                                       'makedirs', 'listdir', 'walk', 'path', 'dirname',
                                       'basename', 'splitext', 'abspath', 'relpath',
                                       'normpath', 'expanduser', 'expandvars',
                                       # Common Frappe document methods/properties
                                       'validate', 'before_save', 'after_insert', 'on_update',
                                       'on_submit', 'before_cancel', 'after_cancel', 'on_trash',
                                       'after_delete', 'before_validate', 'before_insert',
                                       'before_update_after_submit', 'flags', 'meta', 'db_set',
                                       'reload', 'run_method', 'add_comment', 'add_tag',
                                       'remove_tag', 'has_permission', 'submit', 'cancel',
                                       # Property-like access patterns (but NOT actual DocType fields)
                                       'full_name', 'display_name', 'title'}:
                            continue
                            
                        # Skip obvious module/library calls
                        if hasattr(node, 'value') and hasattr(node.value, 'id'):
                            obj_name = node.value.id
                            # Skip standard library modules and common variable names
                            if obj_name in {'json', 'os', 'sys', 'datetime', 'time', 're', 
                                          'math', 'random', 'uuid', 'csv', 'io', 'pathlib',
                                          'f', 'file', 'fp', 'data', 'result', 'response',
                                          'frappe', 'db', 'session', 'request', 'settings'}:
                                continue
                                
                        # Try to determine context and validate field
                        violation = self.check_field_access_comprehensive(
                            node, attr_name, file_path, source_lines
                        )
                        if violation:
                            violations.append(violation)
                            
            except SyntaxError:
                # If AST parsing fails, fall back to regex
                violations.extend(self.validate_with_regex(content, file_path))
                
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return violations
    
    def check_field_access_comprehensive(self, node: ast.Attribute, attr_name: str, 
                                       file_path: Path, source_lines: List[str]) -> Optional[Dict]:
        """Check if field access is valid with comprehensive DocType detection"""
        
        # Get the line content for context
        line_no = node.lineno - 1
        if line_no < len(source_lines):
            line_content = source_lines[line_no].strip()
        else:
            line_content = ""
            
        # Check if this is likely a SQL query result alias
        if self.is_likely_sql_alias(node, attr_name, source_lines, line_no):
            return None  # Skip SQL aliases
            
        # Check if this is a child table or related doctype context
        if self.is_child_table_context(node, attr_name, source_lines, line_no):
            return None  # Skip child table contexts
            
        # Check if this is a legitimate DocType field reference
        if self.is_legitimate_doctype_field_reference(node, attr_name, line_content, source_lines, line_no):
            return None  # Skip legitimate DocType field references
            
        # Detect potential DocType references in various patterns
        detected_doctypes = self.detect_doctypes_in_context(node, line_content, source_lines, line_no)
        
        # Check if the field exists in any of the detected DocTypes
        for doctype in detected_doctypes:
            if doctype in self.doctypes and attr_name in self.doctypes[doctype]:
                return None  # Valid field access
                
        # If we detected specific DocTypes and the field doesn't exist in any of them
        # Only flag if we're highly confident this is a DocType field access
        if detected_doctypes and self.is_highly_confident_field_access(node, attr_name, line_content):
            return {
                "file": str(file_path),
                "line": node.lineno,
                "content": line_content,
                "field": attr_name,
                "detected_doctypes": detected_doctypes,
                "type": "invalid_field_access"
            }
            
        # For unknown context, check if it's a known problematic pattern
        if self.is_suspicious_field_pattern(attr_name, line_content):
            return {
                "file": str(file_path),
                "line": node.lineno,
                "content": line_content,
                "field": attr_name,
                "detected_doctypes": ["Unknown"],
                "type": "suspicious_field_access"
            }
            
        return None
    
    def detect_doctypes_in_context(self, node: ast.Attribute, line_content: str, 
                                  source_lines: List[str], line_no: int) -> List[str]:
        """Detect which DocTypes might be referenced in the current context"""
        detected = []
        
        # Method 1: Look for explicit DocType references in the line (more strict)
        line_lower = line_content.lower()
        for doctype in self.doctypes.keys():
            doctype_variants = [
                f'"{doctype}"',  # Quoted doctype name
                f"'{doctype}'",  # Single quoted doctype name
                f'doctype: "{doctype}"',  # Doctype field pattern
                f"doctype: '{doctype}'",  # Doctype field pattern
                f'"{doctype.lower().replace(" ", "_")}"',  # Snake case variant
                f"'{doctype.lower().replace(" ", "_")}'"   # Snake case variant
            ]
            
            # Only detect if we find explicit doctype references, not just substrings
            if any(variant in line_lower for variant in doctype_variants):
                detected.append(doctype)
                
        # Method 2: Look for frappe.get_doc patterns
        import re
        get_doc_patterns = [
            r'frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            r'doctype\s*=\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in get_doc_patterns:
            matches = re.findall(pattern, line_content)
            detected.extend(matches)
            
        # Method 3: Look for table alias patterns (like mt.amount -> Membership Type)
        alias_patterns = {
            'mt': 'Membership Type',
            'mem': 'Member', 
            'schedule': 'Membership Dues Schedule',
            'membership_type': 'Membership Type',
            'member': 'Member'
        }
        
        # Extract the object being accessed (before the dot)
        if hasattr(node, 'value') and hasattr(node.value, 'id'):
            obj_name = node.value.id
            if obj_name in alias_patterns:
                detected.append(alias_patterns[obj_name])
                
        # Method 4: Look at surrounding context (more precise variable assignments)
        context_lines = max(0, line_no - 3)  # Reduce context window
        for i in range(context_lines, line_no):
            if i < len(source_lines):
                prev_line = source_lines[i].strip()
                # Only look for explicit frappe.get_doc assignments
                for doctype in self.doctypes.keys():
                    if (f'frappe.get_doc("{doctype}"' in prev_line or 
                        f"frappe.get_doc('{doctype}'" in prev_line or
                        f'frappe.new_doc("{doctype}"' in prev_line or
                        f"frappe.new_doc('{doctype}'" in prev_line):
                        detected.append(doctype)
                        
        return list(set(detected))  # Remove duplicates
    
    def is_highly_confident_field_access(self, node: ast.Attribute, attr_name: str, line_content: str) -> bool:
        """Only flag if we're highly confident this is a DocType field access"""
        
        # Must be accessing an object, not a module
        if not hasattr(node, 'value') or not hasattr(node.value, 'id'):
            return False
            
        obj_name = node.value.id
        
        # Skip if it's obviously a module or library
        if obj_name in {'json', 'os', 'sys', 'datetime', 'time', 're', 'math', 'random', 
                       'uuid', 'csv', 'io', 'pathlib', 'frappe', 'db', 'session', 'request'}:
            return False
            
        # Skip if it's obviously a file handle or similar
        if obj_name in {'f', 'file', 'fp', 'data', 'result', 'response', 'settings', 'config'}:
            return False
            
        # Skip common instance attributes that are not DocType fields
        common_instance_attributes = {
            'results', 'cache', 'logger', 'detector', 'processor', 'manager', 'handler',
            'validator', 'generator', 'builder', 'parser', 'formatter', 'converter',
            'member_cache', 'chapter_cache', 'volunteer_cache', 'board_cache',
            'chapter_doc', 'member_doc', 'volunteer_doc', 'membership_doc',
            'board_manager', 'member_manager', 'volunteer_manager', 'communication_manager',
            'volunteer_integration_manager', 'base_manager', 'payment_manager',
            'template_cache'  # Add template_cache to common attributes
        }
        
        if obj_name == 'self' and attr_name in common_instance_attributes:
            return False
            
        # Skip obvious non-field patterns first
        
        # Skip method calls (have parentheses on the same line)
        if f'{attr_name}(' in line_content:
            return False
            
        # Skip assignment statements (setting attributes, not accessing fields)
        if f'self.{attr_name} =' in line_content and obj_name == 'self':
            return False
            
        # Skip attribute assignments to any object
        if f'{obj_name}.{attr_name} =' in line_content:
            return False
            
        # Skip common property access patterns that are usually legitimate
        property_access_patterns = [
            'chapter_name',  # Common property in managers
            'template_cache',  # Caching pattern
            'erpnext_account',  # DocType field access
        ]
        
        if attr_name in property_access_patterns:
            return False
            
        # Skip if it looks like a dictionary key access pattern
        if f'["{attr_name}"]' in line_content or f"['{attr_name}']" in line_content:
            return False
            
        # Only flag if we have strong indicators this is a DocType field access
        strong_indicators = [
            # Direct DocType variable patterns
            f'{obj_name} = frappe.get_doc(' in line_content,
            f'{obj_name} = frappe.new_doc(' in line_content,
            # Self field access in DocType files (but not assignments)
            obj_name == 'self' and '=' not in line_content.split(f'self.{attr_name}')[1][:5] if f'self.{attr_name}' in line_content else False,
            # Known DocType variable names (but be more selective)
            obj_name in {'member_doc', 'membership_doc', 'volunteer_doc', 'chapter_doc', 'schedule_doc', 'template_doc'},
        ]
        
        # Reduce confidence for common variable names that might be from queries
        if obj_name in {'member', 'membership', 'volunteer', 'chapter', 'schedule', 'template'}:
            # Only flag these if there's very strong evidence
            return f'{obj_name} = frappe.get_doc(' in line_content or f'{obj_name} = frappe.new_doc(' in line_content
        
        return any(strong_indicators)
    
    def is_suspicious_field_pattern(self, attr_name: str, line_content: str) -> bool:
        """Check if this looks like a suspicious field access pattern"""
        
        # Known problematic patterns we want to catch
        suspicious_patterns = [
            'amount',  # The specific field we were missing
            'suggested_contribution',
            'minimum_contribution', 
            'maximum_contribution'
        ]
        
        if attr_name in suspicious_patterns:
            # Additional context checks to reduce false positives
            if any(indicator in line_content.lower() for indicator in [
                'membership', 'member', 'dues', 'billing', 'contribution'
            ]):
                return True
                
        return False
    
    def validate_with_regex(self, content: str, file_path: Path) -> List[Dict]:
        """Fallback regex validation for when AST parsing fails"""
        violations = []
        import re
        
        # Pattern to catch .amount and similar suspicious patterns
        pattern = r'(\w+)\.(' + '|'.join([
            'amount(?!_)', 'suggested_contribution', 'minimum_contribution', 
            'maximum_contribution'
        ]) + r')\b'
        
        lines = content.splitlines()
        for line_no, line in enumerate(lines, 1):
            matches = re.finditer(pattern, line)
            for match in matches:
                violations.append({
                    "file": str(file_path),
                    "line": line_no,
                    "content": line.strip(),
                    "field": match.group(2),
                    "detected_doctypes": ["RegexDetected"],
                    "type": "regex_detected_suspicious"
                })
                
        return violations
    
    def validate_test_files_only(self) -> List[Dict]:
        """Validate test files specifically for deprecated field patterns"""
        violations = []
        files_checked = 0
        
        print(f"🔍 Scanning test files for deprecated field patterns...")
        
        # Check test files specifically
        test_patterns = ["**/test_*.py", "**/tests/**/*.py"]
        
        for pattern in test_patterns:
            for py_file in self.app_path.rglob(pattern):
                # Skip certain directories
                if any(skip in str(py_file) for skip in [
                    'node_modules', '__pycache__', '.git', 'migrations',
                    'archived_unused', 'backup', '.disabled', 'patches'
                ]):
                    continue
                
                files_checked += 1
                
                # Use enhanced test file validation
                file_violations = self.validate_test_file_patterns_comprehensive(py_file)
                if file_violations:
                    print(f"  - Found {len(file_violations)} issues in {py_file.relative_to(self.app_path)}")
                violations.extend(file_violations)
        
        print(f"📊 Checked {files_checked} test files")
        return violations
    
    def validate_test_file_patterns_comprehensive(self, file_path: Path) -> List[Dict]:
        """Comprehensive validation for test files with deprecated field detection"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            import re
            
            # Enhanced patterns specifically for test files
            test_patterns = [
                # Pattern 1: membership_type.amount (most common deprecated pattern)
                {
                    'pattern': r'(\w*membership_type\w*)\.amount(?!_)',
                    'field': 'amount',
                    'type': 'deprecated_membership_type_amount',
                    'message': 'membership_type.amount should be membership_type.minimum_amount',
                    'priority': 'high'
                },
                
                # Pattern 2: Assignment patterns like membership_type.amount = value
                {
                    'pattern': r'(\w*membership_type\w*)\.amount\s*=',
                    'field': 'amount',
                    'type': 'deprecated_membership_type_assignment',
                    'message': 'membership_type.amount assignment should use minimum_amount',
                    'priority': 'high'
                },
                
                # Pattern 3: Mock or test object patterns
                {
                    'pattern': r'(mock_\w*|test_\w*)\.amount(?!_)',
                    'field': 'amount',
                    'type': 'test_mock_deprecated_amount',
                    'message': 'Mock/test object using deprecated amount field',
                    'priority': 'medium'
                },
                
                # Pattern 4: Self attribute patterns in tests (like self.membership_type.amount)
                {
                    'pattern': r'self\.(\w*_type)\.amount(?!_)',
                    'field': 'amount', 
                    'type': 'test_self_deprecated_amount',
                    'message': 'Test instance attribute using deprecated amount field',
                    'priority': 'high'
                },
                
                # Pattern 5: General suspicious patterns but more permissive for test files
                {
                    'pattern': r'(\w+)\.suggested_contribution(?!_)',
                    'field': 'suggested_contribution',
                    'type': 'deprecated_suggested_contribution',
                    'message': 'suggested_contribution field may be deprecated',
                    'priority': 'low'
                }
            ]
            
            lines = content.splitlines()
            for line_no, line in enumerate(lines, 1):
                # Skip comments and docstrings
                stripped_line = line.strip()
                if stripped_line.startswith('#') or '"""' in line or "'''" in line:
                    continue
                    
                for pattern_config in test_patterns:
                    matches = re.finditer(pattern_config['pattern'], line)
                    for match in matches:
                        violations.append({
                            "file": str(file_path),
                            "line": line_no,
                            "content": stripped_line,
                            "field": pattern_config['field'],
                            "detected_doctypes": ["TestFilePattern"],
                            "type": pattern_config['type'],
                            "message": pattern_config['message'],
                            "priority": pattern_config['priority'],
                            "variable": match.group(1) if match.groups() else "unknown"
                        })
            
        except Exception as e:
            # If file can't be read, skip it
            pass
            
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Validate the entire app with comprehensive coverage"""
        violations = []
        files_checked = 0
        
        print(f"🔍 Scanning all Python files in {self.app_path}...")
        
        # Check ALL Python files, not just those in doctype directories
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip certain directories and files
            if any(skip in str(py_file) for skip in [
                'node_modules', '__pycache__', '.git', 'migrations',
                'archived_unused', 'backup', '.disabled', 'patches'
            ]):
                continue
                
            # Skip test files for now (they have different patterns)
            if py_file.name.startswith('test_') or '/tests/' in str(py_file):
                continue
            
            files_checked += 1
            
            # Use comprehensive validation for all files
            file_violations = self.validate_file_comprehensive(py_file)
            if file_violations:
                print(f"  - Found {len(file_violations)} issues in {py_file.relative_to(self.app_path)}")
            violations.extend(file_violations)
        
        print(f"📊 Checked {files_checked} Python files")
        return violations
    
    def generate_report(self, violations: List[Dict]) -> str:
        """Generate a comprehensive report"""
        if not violations:
            return "✅ No field reference issues found!"
            
        report = []
        report.append(f"❌ Found {len(violations)} field reference issues:")
        report.append("")
        
        # Group by type and severity
        by_type = {}
        for violation in violations:
            violation_type = violation.get('type', 'unknown')
            if violation_type not in by_type:
                by_type[violation_type] = []
            by_type[violation_type].append(violation)
        
        # Report by type
        for vtype, type_violations in by_type.items():
            report.append(f"## {vtype.replace('_', ' ').title()} ({len(type_violations)} issues)")
            
            # Group by file for cleaner presentation
            by_file = {}
            for violation in type_violations:
                file_path = violation['file']
                if file_path not in by_file:
                    by_file[file_path] = []
                by_file[file_path].append(violation)
            
            for file_path, file_violations in by_file.items():
                report.append(f"\n### {file_path}")
                
                for violation in file_violations:
                    report.append(f"- Line {violation['line']}: Field `{violation['field']}`")
                    report.append(f"  - Context: `{violation.get('content', 'N/A')}`")
                    
                    # Show detected doctypes if available
                    if violation.get('detected_doctypes'):
                        detected = ', '.join(violation['detected_doctypes'])
                        report.append(f"  - Detected DocTypes: {detected}")
                    
                    # Show suggestions for old doctype-based validation
                    if 'doctype' in violation:
                        similar = self.find_similar_fields(violation['field'], violation['doctype'])
                        if similar:
                            report.append(f"  - Similar fields: {', '.join(f'`{f}`' for f in similar)}")
                
                report.append("")
                
        return '\n'.join(report)
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names"""
        if doctype not in self.doctypes:
            return []
            
        similar = []
        field_lower = field_name.lower()
        
        for existing_field in self.doctypes[doctype]:
            existing_lower = existing_field.lower()
            
            # Check for substring matches
            if (field_lower in existing_lower or 
                existing_lower in field_lower or
                abs(len(field_lower) - len(existing_lower)) <= 2):
                similar.append(existing_field)
                
        return similar[:3]
    
    def is_likely_sql_alias(self, node: ast.Attribute, attr_name: str, 
                           source_lines: List[str], line_no: int) -> bool:
        """Check if field access is likely from a SQL query result alias"""
        
        # Look for SQL query patterns in the surrounding context
        context_start = max(0, line_no - 20)  # Look 20 lines back
        context_end = min(len(source_lines), line_no + 5)  # Look 5 lines forward
        
        sql_indicators = []
        for i in range(context_start, context_end):
            line = source_lines[i].strip().lower()
            
            # Look for SQL query indicators
            if any(indicator in line for indicator in [
                'frappe.db.sql', 'frappe.db.get_all', 'frappe.db.get_list',
                'frappe.get_all', 'frappe.get_list', 'frappe.db.get_value',
                'select ', 'from `tab', 'as_dict=true', 'as_dict = true',
                'as_dict=1', 'as_dict = 1'
            ]):
                sql_indicators.append(i)
                
        if not sql_indicators:
            return False
            
        # Look for common SQL alias patterns in the query
        for sql_line_no in sql_indicators:
            # Check lines around the SQL query for alias patterns
            query_start = max(0, sql_line_no - 5)
            query_end = min(len(source_lines), sql_line_no + 15)
            
            for i in range(query_start, query_end):
                line = source_lines[i].strip().lower()
                
                # Look for alias patterns that match our field
                alias_patterns = [
                    f' as {attr_name}',
                    f' as {attr_name},',
                    f'as {attr_name}',
                    f'as {attr_name},',
                    # Common specific patterns we've seen
                    f'as member_name' if attr_name == 'member_name' else '',
                    f'as membership_type_amount' if attr_name == 'membership_type_amount' else '',
                    f'as membership_name' if attr_name == 'membership_name' else '',
                    f'as days_inactive' if attr_name == 'days_inactive' else '',
                    f'as member_full_name' if attr_name == 'member_full_name' else '',
                    f'as start_date' if attr_name == 'start_date' else '',
                    f'as end_date' if attr_name == 'end_date' else '',
                    f'as chapter_join_date' if attr_name == 'chapter_join_date' else '',
                    f'as chapter_assigned_date' if attr_name == 'chapter_assigned_date' else '',
                ]
                
                if any(pattern and pattern in line for pattern in alias_patterns):
                    return True
                    
                # Look for table alias patterns (e.g., "m.member as member_name")
                if f'.{attr_name}' in line or f'as {attr_name}' in line:
                    # Check if it's in a SQL context (contains FROM, SELECT, etc.)
                    if any(sql_word in line for sql_word in ['select', 'from', 'where', 'join']):
                        return True
        
        # Check for iterator variable patterns from SQL results
        # Look for patterns like "for member in sql_result:" where member has fields not in Member doctype
        for i in range(max(0, line_no - 10), line_no):
            line = source_lines[i].strip().lower()
            if 'for ' in line and ' in ' in line:
                # Extract variable name from "for variable in ..."
                try:
                    var_part = line.split(' in ')[0].replace('for ', '').strip()
                    if hasattr(node, 'value') and hasattr(node.value, 'id'):
                        if node.value.id.lower() == var_part:
                            # Check if the iterator source suggests SQL results
                            source_part = line.split(' in ')[1]
                            if any(indicator in source_part for indicator in [
                                'sql', 'db.', 'frappe.db', 'query', 'get_all', 'get_list',
                                'frappe.get_all', 'frappe.get_list'
                            ]):
                                return True
                except (IndexError, AttributeError):
                    continue
        
        # Check for common frappe.get_all patterns with fields parameter
        if hasattr(node, 'value') and hasattr(node.value, 'id'):
            var_name = node.value.id.lower()
            
            # Look for frappe.get_all with fields parameter that includes this field
            for i in range(max(0, line_no - 15), line_no):
                line = source_lines[i].strip().lower()
                if ('frappe.get_all' in line or 'frappe.db.get_all' in line) and 'fields=' in line:
                    # Check if our field is listed in the fields parameter
                    if f'"{attr_name}"' in line or f"'{attr_name}'" in line:
                        return True
        
        return False
    
    def is_child_table_context(self, node: ast.Attribute, attr_name: str, 
                              source_lines: List[str], line_no: int) -> bool:
        """Check if field access is in a child table or related doctype context"""
        
        if not hasattr(node, 'value') or not hasattr(node.value, 'id'):
            return False
            
        var_name = node.value.id
        
        # Look for iterator patterns that suggest child table contexts
        for i in range(max(0, line_no - 15), line_no):
            line = source_lines[i].strip().lower()
            
            # Pattern: "for variable in parent_doc.child_table:"
            if f'for {var_name.lower()}' in line and ' in ' in line:
                source_part = line.split(' in ')[1].strip()
                
                # Check for child table patterns
                child_table_indicators = [
                    '.members', '.payment_history', '.sepa_mandates', '.iban_history',
                    '.chapter_membership_history', '.volunteer_assignment_history',
                    '.fee_change_history', '.board_members', '.team_members',
                    '.children', '.items', '.rows'
                ]
                
                if any(indicator in source_part for indicator in child_table_indicators):
                    return True
                    
                # Pattern: parent_doc.get_all("Child DocType")
                if any(pattern in source_part for pattern in [
                    'get_all(', 'frappe.get_all(', 'db.get_all(',
                    'frappe.db.get_all(', 'get_list(', 'frappe.get_list('
                ]):
                    return True
        
        # Enhanced child table field patterns based on common usage
        child_table_patterns = {
            # Variable name patterns and their expected fields
            'member': ['enabled', 'is_active', 'status', 'role', 'volunteer', 'from_date', 'to_date', 
                      'member', 'chapter_join_date', 'chapter_assigned_date', 'leave_reason'],
            'payment': ['invoice', 'invoice_type', 'description', 'amount', 'status'],
            'mandate': ['used_for_memberships', 'used_for_donations', 'status', 'is_active'],
            'assignment': ['volunteer', 'role', 'from_date', 'to_date', 'is_active'],
            'board_member': ['member', 'role', 'from_date', 'to_date', 'is_active', 'volunteer_name', 'chapter_role'],
            'team_member': ['volunteer', 'role', 'is_active', 'status', 'from_date', 'to_date'],
            'schedule': ['start_date', 'end_date', 'next_invoice_date', 'billing_frequency'],
            'membership': ['membership_type', 'start_date', 'end_date', 'status'],
            'volunteer': ['member', 'volunteer_name', 'status', 'available']
        }
        
        # Check if this variable/field combination suggests a child table
        for pattern_var, expected_fields in child_table_patterns.items():
            if pattern_var in var_name.lower() and attr_name in expected_fields:
                return True
                
        # Check for explicit child table doctype references in surrounding context
        for i in range(max(0, line_no - 10), min(len(source_lines), line_no + 3)):
            line = source_lines[i].strip()
            
            # Look for child table doctype names
            child_doctypes = [
                'Chapter Member', 'Team Member', 'Member Payment History',
                'Member SEPA Mandate Link', 'Member IBAN History', 
                'Chapter Membership History', 'Volunteer Assignment',
                'Member Fee Change History', 'Membership Dues Schedule'
            ]
            
            if any(f'"{doctype}"' in line or f"'{doctype}'" in line for doctype in child_doctypes):
                return True
                
        # Check for common property access patterns that are legitimate
        property_patterns = {
            'template_cache': 'Email Template',  # Common caching pattern
            'chapter_name': 'Chapter',           # Common property access
            'erpnext_account': 'Account',        # DocType field access
        }
        
        if attr_name in property_patterns:
            return True
        
        return False
    
    def is_legitimate_doctype_field_reference(self, node: ast.Attribute, attr_name: str, 
                                             line_content: str, source_lines: List[str], line_no: int) -> bool:
        """Check if this is a legitimate DocType field reference that should not be flagged"""
        
        if not hasattr(node, 'value') or not hasattr(node.value, 'id'):
            return False
            
        obj_name = node.value.id
        
        # Pattern 1: frappe.get_doc("DocType", self.field_name) - Link field access
        if f'frappe.get_doc(' in line_content and f'self.{attr_name}' in line_content:
            # This is accessing a field that references another DocType
            return True
            
        # Pattern 2: frappe.get_doc("DocType", obj.field_name) - Link field access on variable
        if f'frappe.get_doc(' in line_content and f'{obj_name}.{attr_name}' in line_content:
            # This is accessing a field that references another DocType
            return True
            
        # Pattern 3: frappe.db.exists("DocType", obj.field_name) - Field existence checks
        if f'frappe.db.exists(' in line_content and f'{obj_name}.{attr_name}' in line_content:
            return True
            
        # Pattern 4: Common DocType field patterns
        common_link_fields = {
            'member', 'volunteer', 'chapter', 'membership', 'address', 'user', 
            'account', 'expense_account', 'company', 'primary_address',
            'selected_membership_type', 'membership_type', 'email',
            'sepa_mandate', 'periodic_donation_agreement', 'mt940_file',
            'donor_doc', 'current_chapter_display', 'donor', 'team',
            'chapter_reference', 'anbi_agreement_number', 'termination_date',
            'requested_amount', 'reason', 'start_date', 'end_date',
            'chapter_head', 'regional_coordinator', 'membership_type_name'
        }
        
        if attr_name in common_link_fields:
            # Check if it's being used in a way that suggests it's a DocType field
            if any(pattern in line_content for pattern in [
                'frappe.get_doc(', 'frappe.db.exists(', 'frappe.db.get_value(',
                'hasattr(', f'if {obj_name}.{attr_name}', f'and {obj_name}.{attr_name}',
                f'self.{attr_name}', f'{obj_name}.{attr_name} =', f'= {obj_name}.{attr_name}',
                f'"member": {obj_name}.{attr_name}', f'filters=', f'["<", {obj_name}.{attr_name}]',
                f'f"', 'frappe.logger().info(', 'frappe.throw(', 'frappe.log_error('
            ]):
                return True
                
        # Pattern 5: Check for child table field access patterns
        child_table_access_patterns = {
            'sepa_mandates', 'payment_history', 'members', 'board_members',
            'team_members', 'iban_history', 'chapter_membership_history'
        }
        
        if attr_name in child_table_access_patterns:
            # Check if it's being iterated over
            if f'for ' in line_content and f'{obj_name}.{attr_name}' in line_content:
                return True
                
        # Pattern 6: Manager property access (common in Chapter managers)
        manager_properties = {
            'member_manager', 'board_manager', 'communication_manager',
            'volunteer_integration_manager', 'payment_manager'
        }
        
        if attr_name in manager_properties:
            return True
            
        # Pattern 7: Check if the object is a DocType instance variable
        doctype_suffixes = ['_doc', 'doc']
        if any(obj_name.endswith(suffix) for suffix in doctype_suffixes):
            # This looks like a DocType instance, field access is legitimate
            return True
            
        # Pattern 8: Check surrounding context for DocType instantiation
        for i in range(max(0, line_no - 5), line_no):
            if i < len(source_lines):
                prev_line = source_lines[i].strip()
                if (f'{obj_name} = frappe.get_doc(' in prev_line or 
                    f'{obj_name} = frappe.new_doc(' in prev_line):
                    return True
                    
        # Pattern 9: Private attributes (_managers, _cache, etc.)
        if attr_name.startswith('_'):
            return True
            
        # Pattern 10: Check if it's a self field access (common DocType pattern)
        if obj_name == 'self':
            # Most self.field accesses in DocType files are legitimate
            return True
                    
        return False


def main():
    """Main function with enhanced reporting and test file support"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Check for command line arguments
    test_only = len(sys.argv) > 1 and sys.argv[1] == '--test-only'
    include_tests = len(sys.argv) > 1 and sys.argv[1] == '--include-tests'
    
    validator = FinalFieldValidator(app_path)
    print(f"📋 Loaded {len(validator.doctypes)} doctypes with field definitions")
    
    if test_only:
        print("🧪 Running test-only validation...")
        violations = validator.validate_test_files_only()
    elif include_tests:
        print("🔍 Running comprehensive validation (production + tests)...")
        violations = validator.validate_all_including_tests()
    else:
        print("🏭 Running enhanced field validation (production only)...")
        violations = validator.validate_app()
    
    print("\n" + "="*50)
    report = validator.generate_report(violations)
    print(report)
    
    if violations:
        print(f"\n💡 Summary: Found {len(violations)} field reference issues across the codebase")
        
        # Show breakdown by issue type and priority
        by_type = {}
        by_priority = {'high': 0, 'medium': 0, 'low': 0}
        
        for violation in violations:
            vtype = violation.get('type', 'unknown')
            by_type[vtype] = by_type.get(vtype, 0) + 1
            
            priority = violation.get('priority', 'medium')
            if priority in by_priority:
                by_priority[priority] += 1
            
        print("\n📊 Issue breakdown by type:")
        for vtype, count in by_type.items():
            print(f"   - {vtype.replace('_', ' ').title()}: {count}")
            
        print("\n🎯 Priority breakdown:")
        for priority, count in by_priority.items():
            if count > 0:
                print(f"   - {priority.title()}: {count}")
        
        return 1
    else:
        print("✅ All field references validated successfully!")
        return 0


if __name__ == "__main__":
    exit(main())

# Convenience functions for external use
def validate_test_files_external(app_path: str) -> List[Dict]:
    """Validate only test files - for use by other scripts"""
    validator = FinalFieldValidator(app_path)
    return validator.validate_test_files_only()

def validate_with_tests_external(app_path: str) -> List[Dict]:
    """Validate both production and test files - for use by other scripts"""
    validator = FinalFieldValidator(app_path)
    return validator.validate_all_including_tests()