#!/usr/bin/env python3
"""
Enhanced DocType Field Validator

This validator combines the improvements from doctype_field_validator.py into a cleaner architecture
designed for future consolidation with other validators.

Key Features:
1. Manager property detection (@property methods)
2. Custom field recognition
3. Child table context awareness
4. Confidence scoring system
5. Pre-commit mode filtering
"""

import ast
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Union
from dataclasses import dataclass
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata

@dataclass
class ValidationIssue:
    """Represents a field validation issue with confidence scoring"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    context: str
    confidence: str  # high, medium, low
    issue_type: str
    suggested_fix: Optional[str] = None

class DocTypeSchema:
    """Manages DocType schema loading and caching using comprehensive loader"""
    
    def __init__(self, app_path: Path, bench_path: Path):
        self.app_path = app_path
        self.bench_path = bench_path
        
        # Initialize comprehensive DocType loader
        self.doctype_loader = DocTypeLoader(str(bench_path), verbose=False)
        self.schemas = self._convert_to_legacy_format()
        self.child_table_mapping = self._build_child_table_mapping()
        print(f"📊 Enhanced DocType validator loaded {len(self.schemas)} DocTypes")
        
    def _convert_to_legacy_format(self):
        """Convert doctype_loader format to legacy schema format"""
        legacy_schemas = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            field_names = self.doctype_loader.get_field_names(doctype_name)
            
            legacy_schemas[doctype_name] = {
                'fields': set(field_names),
                'app': 'comprehensive_loader',  # Could track actual app if needed
                'path': 'doctype_loader'
            }
        
        return legacy_schemas
    
    def _build_child_table_mapping(self):
        """Build child table mapping from comprehensive loader"""
        # Use the built-in child table mapping from the loader
        return self.doctype_loader.get_child_table_mapping()
                        
    def get_fields(self, doctype: str) -> Set[str]:
        """Get fields for a DocType"""
        return self.schemas.get(doctype, {}).get('fields', set())
        
    def get_child_doctype(self, parent_doctype: str, field_name: str) -> Optional[str]:
        """Get child DocType for a parent.field combination"""
        return self.child_table_mapping.get(f"{parent_doctype}.{field_name}")

class PropertyDetector:
    """Detects @property methods and manager patterns"""
    
    def __init__(self, app_path: Path):
        self.app_path = app_path
        self.property_cache = {}
        self._load_properties()
        
    def _load_properties(self):
        """Load all @property methods from DocType Python files"""
        # Common manager property patterns
        common_managers = {
            'Chapter': {'member_manager', 'board_manager', 'communication_manager'},
            'Member': {'payment_mixin', 'termination_handler'},
            'Direct Debit Batch': {'sepa_processor'},
        }
        
        # Start with common patterns
        self.property_cache.update(common_managers)
        
        # Scan DocType Python files for @property decorators
        for py_file in self.app_path.rglob("**/doctype/*/*.py"):
            if py_file.name.startswith('test_') or py_file.name.startswith('__'):
                continue
                
            doctype_name = self._to_title_case(py_file.parent.name)
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Find @property decorated methods
                property_pattern = r'@property\s+def\s+(\w+)\s*\('
                properties = re.findall(property_pattern, content)
                
                if properties:
                    if doctype_name not in self.property_cache:
                        self.property_cache[doctype_name] = set()
                    self.property_cache[doctype_name].update(properties)
                    
            except Exception:
                pass
                
    def _to_title_case(self, snake_case: str) -> str:
        """Convert snake_case to Title Case"""
        return ' '.join(word.capitalize() for word in snake_case.split('_'))
        
    def is_property_access(self, doctype: str, field: str) -> bool:
        """Check if field access is actually a property method"""
        # Check exact match
        if doctype in self.property_cache and field in self.property_cache[doctype]:
            return True
            
        # Check common manager patterns
        manager_patterns = [
            '_manager', '_handler', '_mixin', '_helper', '_processor',
            '_builder', '_factory', '_service', '_controller'
        ]
        
        return any(field.endswith(pattern) for pattern in manager_patterns)

class ContextAnalyzer:
    """Analyzes code context to detect DocType usage patterns"""
    
    def __init__(self, schemas: DocTypeSchema):
        self.schemas = schemas
        
    def detect_doctype(self, node: ast.AST, source_lines: List[str], obj_name: str) -> Optional[Tuple[str, bool]]:
        """
        Detect the DocType for a variable.

        Returns:
            Tuple of (doctype_name, is_explicit) where is_explicit indicates
            if the DocType was found via explicit assignment (high confidence)
            or heuristic (low confidence). Returns None if no DocType detected.
        """
        line_num = node.lineno

        # Check child table context FIRST (high confidence)
        child_doctype = self._detect_child_table_context(source_lines, line_num, obj_name)
        if child_doctype:
            return (child_doctype, True)

        # Look for explicit assignments (high confidence)
        context = '\n'.join(source_lines[max(0, line_num-30):line_num])

        patterns = [
            rf'{obj_name}\s*=\s*frappe\.get_doc\(["\']([^"\']+)["\']',
            rf'{obj_name}\s*=\s*frappe\.new_doc\(["\']([^"\']+)["\']',
            rf'{obj_name}\s*=\s*frappe\.get_cached_doc\(["\']([^"\']+)["\']',
        ]

        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                return (match.group(1), True)

        # REMOVED: Variable name heuristics - these caused too many false positives
        # Variables named 'member', 'invoice', etc. are often child table rows or
        # external API objects, not the DocType with that name.
        #
        # If we can't find an explicit assignment, return None instead of guessing.
        return None
        
    def _detect_child_table_context(self, source_lines: List[str], line_num: int, obj_name: str) -> Optional[str]:
        """Detect if variable comes from child table iteration"""
        context_start = max(0, line_num - 15)
        context_lines = source_lines[context_start:line_num]
        context = '\n'.join(context_lines)

        # Pattern 1: for obj_name in self.child_field: (DocType controller methods)
        # This is common in DocType Python files
        self_pattern = rf'for\s+{obj_name}\s+in\s+self\.(\w+)'
        self_match = re.search(self_pattern, context)
        if self_match:
            child_field = self_match.group(1)
            # Try to detect parent DocType from file path or class definition
            parent_doctype = self._detect_self_doctype(source_lines)
            if parent_doctype:
                child_doctype = self.schemas.get_child_doctype(parent_doctype, child_field)
                if child_doctype:
                    return child_doctype

        # Pattern 2: for obj_name in parent.child_field:
        patterns = [
            rf'for\s+{obj_name}\s+in\s+(\w+)\.(\w+):',
            rf'{obj_name}\s*=\s*(\w+)\.(\w+)\[',
            rf'{obj_name}\s+in\s+(\w+)\.(\w+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                parent_obj = match.group(1)
                child_field = match.group(2)

                # Skip if parent is 'self' (handled above)
                if parent_obj == 'self':
                    continue

                # Try to find the parent DocType in preceding context
                parent_context = '\n'.join(source_lines[max(0, line_num-50):line_num])
                parent_doctype = self._find_parent_doctype(parent_context, parent_obj)

                if parent_doctype:
                    child_doctype = self.schemas.get_child_doctype(parent_doctype, child_field)
                    if child_doctype:
                        return child_doctype

        return None

    def _detect_self_doctype(self, source_lines: List[str]) -> Optional[str]:
        """Detect the DocType when 'self' is used (inside a DocType controller class)"""
        # Look for class definition that inherits from Document
        content = '\n'.join(source_lines[:100])  # Check first 100 lines for class def

        # Pattern: class ClassName(Document): where ClassName is the DocType in snake_case
        class_pattern = r'class\s+(\w+)\s*\([^)]*Document[^)]*\):'
        match = re.search(class_pattern, content)
        if match:
            class_name = match.group(1)
            # Convert CamelCase to Title Case (e.g., DirectDebitBatch -> Direct Debit Batch)
            doctype_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', class_name)
            if doctype_name in self.schemas.schemas:
                return doctype_name

        return None
        
    def _find_parent_doctype(self, context: str, obj_name: str) -> Optional[str]:
        """Find the DocType of a parent object"""
        patterns = [
            rf'{obj_name}\s*=\s*frappe\.get_doc\(["\']([^"\']+)["\']',
            rf'{obj_name}\s*=\s*frappe\.new_doc\(["\']([^"\']+)["\']',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1)
                
        return None

class ConfidenceCalculator:
    """Calculates confidence scores for validation issues"""
    
    def calculate(self, node: ast.AST, obj_name: str, field_name: str, 
                 doctype: str, context: str, source_lines: List[str], file_path: str) -> str:
        """Calculate confidence level for the validation issue"""
        
        # Start with high confidence
        score = 100
        
        # Check if it's a custom field pattern
        if field_name.startswith('custom_'):
            score -= 40  # Custom fields are often added dynamically
            
        # Check if it's in a test file
        if any(pattern in str(file_path) for pattern in ['test_', '_test.py', '/tests/', 'debug_']):
            score -= 30
            
        # Check for SQL context patterns
        sql_patterns = [
            'frappe.db.sql',
            'as_dict=True',
            'SELECT.*FROM',
            '.format(',
            'GROUP BY',
            'ORDER BY'
        ]
        context_window = '\n'.join(source_lines[max(0, node.lineno-10):node.lineno+5])
        if any(pattern in context_window for pattern in sql_patterns):
            score -= 50  # SQL results often have different fields
            
        # Check for API/external data patterns
        api_patterns = [
            'requests.get',
            'requests.post',
            'json.loads',
            'api_response',
            'external_data',
            'third_party'
        ]
        if any(pattern in context_window for pattern in api_patterns):
            score -= 40
            
        # Convert score to category
        if score >= 80:
            return "high"
        elif score >= 50:
            return "medium"
        else:
            return "low"

class EnhancedFieldValidator:
    """Main validator with improved accuracy and architecture"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.verbose = verbose
        
        # Initialize components
        self.schemas = DocTypeSchema(self.app_path, self.bench_path)
        self.property_detector = PropertyDetector(self.app_path)
        self.context_analyzer = ContextAnalyzer(self.schemas)
        self.confidence_calculator = ConfidenceCalculator()
        
        print(f"📋 Loaded {len(self.schemas.schemas)} DocType schemas")
        
    def _is_valid_doctype_name(self, name: str) -> bool:
        """
        Check if a string looks like a valid DocType name.
        Filters out false positives from regex matches.
        """
        # Empty or whitespace-only
        if not name or not name.strip():
            return False

        # Too short (DocType names are typically at least 3 chars)
        if len(name) < 2:
            return False

        # Contains Python keywords or common false positive patterns
        invalid_patterns = [
            ' in ', ' and ', ' or ', ' not ', ' if ', ' else ',
            ' for ', ' while ', ' with ', ' as ', ' is ', ' from ',
            '{', '}', '(', ')', '[', ']', '=', '+', '-', '*', '/',
            'context', 'pattern', 'match', 'result', 'value',
        ]
        name_lower = name.lower()
        if any(pattern in name_lower for pattern in invalid_patterns):
            return False

        # Should start with an uppercase letter (DocType naming convention)
        if not name[0].isupper():
            return False

        # Should only contain letters, numbers, spaces, and hyphens
        if not re.match(r'^[A-Za-z0-9\s\-]+$', name):
            return False

        return True

    def validate_doctype_api_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """FIRST-LAYER CHECK: Validate DocType existence in API calls"""
        violations = []

        # Patterns for Frappe API calls that use DocType names
        # Use more specific patterns with proper string delimiters
        api_patterns = [
            r'frappe\.get_all\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.get_doc\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.delete_doc\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.db\.get_value\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.db\.exists\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.db\.count\(\s*["\']([A-Z][^"\']+)["\']',
            r'frappe\.get_cached_doc\(\s*["\']([A-Z][^"\']+)["\']',
        ]

        lines = content.splitlines()

        for line_num, line in enumerate(lines, 1):
            for pattern in api_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    doctype_name = match.group(1)

                    # Validate that this looks like a real DocType name
                    if not self._is_valid_doctype_name(doctype_name):
                        continue

                    # FIRST-LAYER CHECK: Does this DocType actually exist?
                    if doctype_name not in self.schemas.schemas:
                        # Suggest similar DocType names
                        suggestions = self._suggest_similar_doctype(doctype_name)

                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field="<doctype_reference>",
                            doctype=doctype_name,
                            reference=line.strip(),
                            message=f"DocType '{doctype_name}' does not exist. {suggestions}",
                            context=line.strip(),
                            confidence="high",
                            issue_type="missing_doctype",
                            suggested_fix=suggestions
                        ))

        return violations
    
    def _suggest_similar_doctype(self, invalid_name: str) -> str:
        """Suggest similar DocType names for typos"""
        available = list(self.schemas.schemas.keys())
        
        # Look for exact substring matches first
        exact_matches = [dt for dt in available if invalid_name.replace('Verenigingen ', '') in dt]
        if exact_matches:
            return f"Did you mean '{exact_matches[0]}'?"
        
        # Look for partial matches
        partial_matches = [dt for dt in available if any(word in dt for word in invalid_name.split())]
        if partial_matches:
            return f"Similar: {', '.join(partial_matches[:3])}"
        
        return f"Check {len(available)} available DocTypes"

    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single Python file"""
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # FIRST: Check DocType existence in API calls
            issues.extend(self.validate_doctype_api_calls(content, file_path))
                
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Walk through AST to find attribute access
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and hasattr(node.value, 'id'):
                    obj_name = node.value.id
                    field_name = node.attr
                    line_num = node.lineno
                    
                    # Skip excluded patterns
                    if self._should_skip(obj_name, field_name):
                        continue
                        
                    # Get line context
                    context = source_lines[line_num - 1].strip() if line_num <= len(source_lines) else ""
                    
                    # Skip method calls
                    if f'{field_name}(' in context:
                        continue
                        
                    # Detect DocType
                    doctype_result = self.context_analyzer.detect_doctype(node, source_lines, obj_name)

                    if doctype_result is None:
                        continue  # Could not determine DocType - skip this access

                    doctype, is_explicit = doctype_result

                    if doctype and doctype in self.schemas.schemas:
                        fields = self.schemas.get_fields(doctype)
                        
                        if field_name not in fields:
                            # Check if it's a property
                            if self.property_detector.is_property_access(doctype, field_name):
                                continue
                                
                            # Calculate confidence
                            confidence = self.confidence_calculator.calculate(
                                node, obj_name, field_name, doctype, context, 
                                source_lines, str(file_path)
                            )
                            
                            # Find similar fields
                            similar = self._find_similar_fields(field_name, fields)
                            similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                            
                            issues.append(ValidationIssue(
                                file=str(file_path.relative_to(self.app_path)),
                                line=line_num,
                                field=field_name,
                                doctype=doctype,
                                reference=f"{obj_name}.{field_name}",
                                message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                                context=context,
                                confidence=confidence,
                                issue_type="missing_field",
                                suggested_fix=similar[0] if similar else None
                            ))
                            
        except Exception as e:
            if self.verbose:
                print(f"Error processing {file_path}: {e}")
                
        return issues
        
    def _should_skip(self, obj_name: str, field_name: str) -> bool:
        """Check if this pattern should be skipped"""
        # Skip private attributes
        if field_name.startswith('_'):
            return True

        # Skip standard Frappe document properties (not DocType fields)
        # These are runtime properties added by the Frappe framework
        frappe_properties = {
            'flags',           # Document flags (ignore_validate, etc.)
            'meta',            # Document metadata
            'db',              # Database handle (frappe.db)
            'run_method',      # Method execution
            'get_doc',         # Document retrieval
            'as_dict',         # Dict conversion
            'as_json',         # JSON conversion
            'get_valid_dict',  # Valid dict conversion
            'get_title',       # Title retrieval
            'get_url',         # URL generation
            'has_permission',  # Permission check
            'is_new',          # New document check
            'is_dirty',        # Dirty check
            'check_permission', # Permission check
            'get_parentfield', # Parent field
            '_doc_before_save', # Before save state
            '_original_values', # Original values
        }

        if field_name in frappe_properties:
            return True

        # Skip common non-DocType variables
        skip_vars = {
            'self', 'cls', 'args', 'kwargs', 'request', 'response',
            'data', 'result', 'config', 'settings', 'options', 'json_file',
            'meta', 'template', 'file', 'fp', 'f', 'os', 'sys', 'json',
            're', 'datetime', 'date', 'time', 'frappe', 'cint', 'flt',
        }

        if obj_name in skip_vars:
            return True

        # Skip common methods/properties that look like field access
        skip_fields = {
            'get', 'set', 'update', 'save', 'insert', 'delete',
            'append', 'extend', 'remove', 'pop', 'clear', 'items',
            'keys', 'values', 'copy', 'format', 'strip', 'split',
            'join', 'replace', 'lower', 'upper', 'title', 'startswith',
            'endswith', 'encode', 'decode', 'read', 'write', 'close',
        }

        if field_name in skip_fields:
            return True

        return False
        
    def _find_similar_fields(self, field: str, available_fields: Set[str]) -> List[str]:
        """Find similar field names"""
        from difflib import get_close_matches
        return get_close_matches(field, list(available_fields), n=3, cutoff=0.6)
        
    def _is_api_client_file(self, file_path: Path) -> bool:
        """
        Detect if file is an external API client that shouldn't be validated
        for DocType field references.

        External API clients work with data structures from external services
        (Mollie, Stripe, etc.) that have different field names than Frappe DocTypes.
        """
        path_str = str(file_path).lower()

        # File name patterns that indicate external API client
        api_client_patterns = [
            '_client.py',
            '_connector.py',
            '_api.py',
            'mollie_',
            'stripe_',
            'adyen_',
            'ponto_',
            '/clients/',
            '/integration/',
            'webhook_handler',
            'api_client',
            'rest_client',
        ]

        if any(pattern in path_str for pattern in api_client_patterns):
            return True

        return False

    def validate_directory(self, directory: Optional[Path] = None, pre_commit: bool = False) -> List[ValidationIssue]:
        """Validate all Python files in directory"""
        search_path = directory or self.app_path
        all_issues = []
        file_count = 0
        skipped_api_clients = 0

        for py_file in search_path.rglob("*.py"):
            # Skip excluded directories
            if any(skip in str(py_file) for skip in [
                '__pycache__', '.git', 'node_modules',
                'archived/', 'one-off-test-debug-folder/', 'archived_unused/',
                'archived_deleted/', 'scripts/validation/archived/'
            ]):
                continue

            # Skip external API client files (they use different data structures)
            if self._is_api_client_file(py_file):
                skipped_api_clients += 1
                continue

            # In pre-commit mode, skip test files
            if pre_commit and any(pattern in str(py_file) for pattern in ['/tests/', 'test_', 'debug_']):
                continue

            file_count += 1
            issues = self.validate_file(py_file)
            all_issues.extend(issues)

        print(f"🔍 Validated {file_count} Python files (skipped {skipped_api_clients} API client files)")
        return all_issues

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Enhanced DocType Field Validator')
    parser.add_argument('--pre-commit', action='store_true',
                       help='Run in pre-commit mode (only high confidence issues)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--path', default='/home/frappe/frappe-bench/apps/verenigingen',
                       help='Path to validate')
    parser.add_argument('--confidence', default='high',
                       choices=['high', 'medium', 'low'],
                       help='Minimum confidence level to report')
    
    args = parser.parse_args()
    
    validator = EnhancedFieldValidator(app_path=args.path, verbose=args.verbose)
    
    print("🔍 Enhanced DocType Field Validator")
    print("=" * 50)
    
    issues = validator.validate_directory(pre_commit=args.pre_commit)
    
    if issues:
        # Group by confidence
        by_confidence = {'high': [], 'medium': [], 'low': []}
        for issue in issues:
            by_confidence[issue.confidence].append(issue)
            
        # Filter by minimum confidence
        min_conf_map = {'high': ['high'], 'medium': ['high', 'medium'], 'low': ['high', 'medium', 'low']}
        filtered_issues = []
        for conf in min_conf_map[args.confidence]:
            filtered_issues.extend(by_confidence[conf])
            
        if filtered_issues:
            print(f"\n❌ Found {len(filtered_issues)} issues:")
            
            # Show first 10 issues
            for issue in filtered_issues[:10]:
                print(f"\n{issue.file}:{issue.line}")
                print(f"  {issue.message}")
                print(f"  Context: {issue.context}")
                print(f"  Confidence: {issue.confidence}")
                if issue.suggested_fix:
                    print(f"  Suggested: {issue.suggested_fix}")
                    
            if len(filtered_issues) > 10:
                print(f"\n... and {len(filtered_issues) - 10} more issues")
                
        # Summary
        print(f"\n📊 Summary:")
        print(f"  Total issues: {len(issues)}")
        print(f"  High confidence: {len(by_confidence['high'])}")
        print(f"  Medium confidence: {len(by_confidence['medium'])}")
        print(f"  Low confidence: {len(by_confidence['low'])}")
        
        # Exit code for pre-commit
        if args.pre_commit:
            return len(by_confidence['high'])
        else:
            return 1 if filtered_issues else 0
    else:
        print("\n✅ No issues found!")
        return 0

if __name__ == "__main__":
    exit(main())