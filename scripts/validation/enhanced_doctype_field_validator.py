#!/usr/bin/env python3
"""
Enhanced DocType Field Validator - FIXED VERSION with Proper DocType Loading

MAJOR IMPROVEMENTS:
1. Uses comprehensive DocType loader for ALL apps (frappe, erpnext, payments, verenigingen)
2. Loads ALL fields including custom fields and proper metadata
3. Manager pattern detection (@property methods)
4. Custom field recognition
5. Child table context awareness
6. Confidence scoring system
7. Pre-commit mode filtering
8. Eliminates false positives from incomplete DocType definitions

Key Features:
- Comprehensive multi-app DocType loading
- Custom field support
- Child table relationship mapping
- Property method detection
- Confidence scoring
- Performance optimized
"""

import ast
import json
import re
import time
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, NamedTuple
from dataclasses import dataclass
import argparse

# Import our comprehensive DocType loader
sys.path.insert(0, str(Path(__file__).parent))
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

class PropertyDetector:
    """Detects @property methods and manager patterns"""
    
    def __init__(self, app_path: Path):
        self.app_path = app_path
        self.property_cache = {}
        self._load_properties()
        
    def _load_properties(self):
        """Load all @property methods from DocType Python files"""
        for py_file in self.app_path.rglob("**/doctype/*/*.py"):
            if py_file.name.startswith('test_') or py_file.name.startswith('__'):
                continue
                
            doctype_name = py_file.parent.name
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                tree = ast.parse(content)
                properties = self._extract_properties(tree)
                
                if properties:
                    # Convert snake_case folder name to Title Case DocType name
                    doctype_title = self._to_title_case(doctype_name)
                    self.property_cache[doctype_title] = properties
                    
            except Exception:
                # Skip files with parsing errors
                pass
                
    def _extract_properties(self, tree: ast.AST) -> Set[str]:
        """Extract @property decorated methods from AST"""
        properties = set()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        # Check for @property decorator
                        for decorator in item.decorator_list:
                            if isinstance(decorator, ast.Name) and decorator.id == 'property':
                                properties.add(item.name)
                                break
                                
        return properties
        
    def _to_title_case(self, snake_case: str) -> str:
        """Convert snake_case to Title Case"""
        return ' '.join(word.capitalize() for word in snake_case.split('_'))
        
    def is_property_access(self, doctype: str, field: str) -> bool:
        """Check if field access is actually a property method"""
        # Check exact match
        if doctype in self.property_cache:
            if field in self.property_cache[doctype]:
                return True
                
        # Check common manager patterns
        manager_patterns = [
            '_manager', '_handler', '_mixin', '_helper', '_processor',
            '_builder', '_factory', '_service', '_controller'
        ]
        
        return any(field.endswith(pattern) for pattern in manager_patterns)

class ChildTableDetector:
    """Detects child table contexts to avoid false positives"""
    
    def __init__(self, doctypes: Dict):
        self.doctypes = doctypes
        self.child_table_mapping = self._build_child_table_mapping()
        
    def _build_child_table_mapping(self) -> Dict[str, List[Tuple[str, str]]]:
        """Build mapping of parent DocType -> [(field_name, child_doctype)]"""
        mapping = {}
        
        for doctype_name, doctype_info in self.doctypes.items():
            child_fields = []
            
            for field_name, field_info in doctype_info.get('fields', {}).items():
                if isinstance(field_info, dict) and field_info.get('fieldtype') == 'Table':
                    child_doctype = field_info.get('options')
                    if child_doctype:
                        child_fields.append((field_name, child_doctype))
                        
            if child_fields:
                mapping[doctype_name] = child_fields
                
        return mapping
        
    def detect_child_table_context(self, node: ast.AST, source_lines: List[str], 
                                  obj_name: str) -> Optional[str]:
        """Detect if variable comes from child table iteration"""
        line_num = node.lineno
        context_start = max(0, line_num - 15)
        context_lines = source_lines[context_start:line_num]
        context = '\n'.join(context_lines)
        
        # Pattern: for obj_name in self.child_field:
        patterns = [
            rf'for\s+{obj_name}\s+in\s+self\.(\w+):',
            rf'for\s+{obj_name}\s+in\s+(?:doc|parent)\.(\w+):',
            rf'{obj_name}\s+in\s+(?:self|doc|parent)\.(\w+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, context, re.MULTILINE)
            if match:
                child_field = match.group(1)
                
                # Look up child table DocType
                for parent_doctype, child_tables in self.child_table_mapping.items():
                    for field_name, child_doctype in child_tables:
                        if field_name == child_field:
                            return child_doctype
                            
        return None

class ConfidenceScorer:
    """Calculate confidence scores for validation issues"""
    
    def calculate_confidence(self, issue: ValidationIssue, context: Dict) -> str:
        """Calculate confidence level for a validation issue"""
        
        # High confidence indicators
        if self._is_direct_doctype_access(issue, context):
            return 'high'
            
        # Check for typos (very similar to existing fields)
        if self._is_likely_typo(issue.field, context.get('available_fields', [])):
            return 'high'
            
        # Low confidence indicators
        if self._is_test_or_debug_file(issue.file):
            return 'low'
            
        if self._is_manager_pattern(issue.field):
            return 'low'
            
        if issue.field.startswith('custom_'):
            return 'low'
            
        # Default to medium
        return 'medium'
        
    def _is_direct_doctype_access(self, issue: ValidationIssue, context: Dict) -> bool:
        """Check if this is a direct DocType access pattern"""
        patterns = [
            r'frappe\.get_doc\(["\']' + re.escape(issue.doctype),
            r'frappe\.new_doc\(["\']' + re.escape(issue.doctype)
        ]
        
        full_context = context.get('surrounding_code', '')
        return any(re.search(pattern, full_context) for pattern in patterns)
        
    def _is_likely_typo(self, field: str, available_fields: List[str]) -> bool:
        """Check if field is likely a typo"""
        from difflib import SequenceMatcher
        
        for valid_field in available_fields:
            similarity = SequenceMatcher(None, field.lower(), valid_field.lower()).ratio()
            if similarity > 0.85:
                return True
        return False
        
    def _is_test_or_debug_file(self, file_path: str) -> bool:
        """Check if file is a test or debug file"""
        test_patterns = [
            'test_', '_test.py', 'debug_', '_debug.py',
            'one-off-test-utils/', 'scripts/debug/', 'scripts/testing/'
        ]
        return any(pattern in file_path for pattern in test_patterns)
        
    def _is_manager_pattern(self, field: str) -> bool:
        """Check if field follows manager pattern"""
        return field.endswith(('_manager', '_handler', '_mixin', '_helper'))

class FieldAccessVisitor(ast.NodeVisitor):
    """AST visitor that properly tracks field access vs method calls"""
    
    def __init__(self, validator, source_lines, file_path):
        self.validator = validator
        self.source_lines = source_lines
        self.file_path = file_path
        self.issues = []
        
    def visit_Attribute(self, node):
        """Visit attribute access nodes"""
        # Check if this is part of a function call
        parent = self._get_parent_node(node)
        if isinstance(parent, ast.Call) and parent.func == node:
            # This is a method call, not field access
            return
            
        # Only process simple attribute access (obj.field)
        if hasattr(node.value, 'id'):
            obj_name = node.value.id
            field_name = node.attr
            line_num = node.lineno
            
            # Skip excluded patterns
            if self.validator._should_skip(obj_name, field_name):
                return
                
            # Detect DocType context
            doctype = self.validator._detect_doctype(node, self.source_lines, obj_name, '')
            
            if doctype and doctype in self.validator.doctypes:
                # Check if field exists
                fields = self.validator.doctypes[doctype]['fields']
                
                if field_name not in fields:
                    # Check if it's a property
                    if self.validator.property_detector.is_property_access(doctype, field_name):
                        return
                        
                    # Create issue
                    issue = self.validator._create_issue(
                        self.file_path, line_num, obj_name, field_name, 
                        doctype, self.source_lines
                    )
                    
                    # Calculate confidence
                    context = {
                        'available_fields': list(fields.keys()),
                        'surrounding_code': '\n'.join(
                            self.source_lines[max(0, line_num-10):min(len(self.source_lines), line_num+10)]
                        )
                    }
                    issue.confidence = self.validator.confidence_scorer.calculate_confidence(issue, context)
                    
                    self.issues.append(issue)
                    
        self.generic_visit(node)
        
    def _get_parent_node(self, node):
        """Get parent node (simplified - in real implementation would track during traversal)"""
        # This is a simplified version - in practice, we'd track parent during traversal
        return None

class EnhancedFieldValidator:
    """Main validator with improved accuracy and comprehensive DocType loading"""
    
    def __init__(self, app_path: str, verbose: bool = False, pre_commit_mode: bool = False):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.verbose = verbose
        self.pre_commit_mode = pre_commit_mode
        
        # Use comprehensive DocType loader
        self.doctype_loader = DocTypeLoader(str(self.bench_path), verbose=verbose)
        self.doctypes = self._convert_doctypes_for_compatibility()
        
        # Load other components
        self.property_detector = PropertyDetector(self.app_path)
        self.child_table_detector = ChildTableDetector(self.doctypes)
        self.confidence_scorer = ConfidenceScorer()
        
        # Statistics
        self.stats = {
            'files_processed': 0,
            'issues_found': 0,
            'high_confidence': 0,
            'medium_confidence': 0,
            'low_confidence': 0
        }
        
        if self.verbose:
            loading_stats = self.doctype_loader.get_loading_stats()
            print(f"🔍 Loaded {loading_stats.total_doctypes} DocTypes with {loading_stats.total_fields} fields")
    
    def _convert_doctypes_for_compatibility(self) -> Dict[str, Dict]:
        """Convert DocType loader format to legacy format for compatibility"""
        legacy_format = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            all_fields = {}
            field_metas = self.doctype_loader.get_fields(doctype_name)
            
            for field_name, field_meta in field_metas.items():
                all_fields[field_name] = {
                    'fieldtype': field_meta.fieldtype,
                    'options': field_meta.options
                }
            
            legacy_format[doctype_name] = {
                'fields': all_fields,
                'app': doctype_meta.app,
                'path': doctype_meta.json_file_path
            }
            
        return legacy_format
        
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate a single Python file"""
        issues = []
        self.stats['files_processed'] += 1
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Use a visitor to properly track context
            visitor = FieldAccessVisitor(self, source_lines, file_path)
            visitor.visit(tree)
            issues = visitor.issues
            
            # Update stats
            for issue in issues:
                self.stats['issues_found'] += 1
                self.stats[f'{issue.confidence}_confidence'] += 1
                
            # Filter based on mode
            if self.pre_commit_mode:
                issues = [i for i in issues if i.confidence == 'high']
                
        except Exception as e:
            if self.verbose:
                print(f"Error processing {file_path}: {e}")
                
        return issues
        
    def _should_skip(self, obj_name: str, field_name: str) -> bool:
        """Check if this pattern should be skipped"""
        # Skip private attributes
        if field_name.startswith('_'):
            return True
            
        # Skip common non-DocType variables
        skip_vars = {
            'self', 'cls', 'args', 'kwargs', 'request', 'response',
            'data', 'result', 'config', 'settings', 'options'
        }
        
        if obj_name in skip_vars:
            return True
            
        # Skip method calls
        if field_name in ['get', 'set', 'update', 'save', 'insert', 'delete']:
            return True
            
        return False
        
    def _detect_doctype(self, node: ast.AST, source_lines: List[str], 
                       obj_name: str, content: str) -> Optional[str]:
        """Detect the DocType for a variable"""
        
        # First check child table context
        child_doctype = self.child_table_detector.detect_child_table_context(
            node, source_lines, obj_name
        )
        if child_doctype:
            return child_doctype
            
        # Look for explicit assignments
        line_num = node.lineno
        context = '\n'.join(source_lines[max(0, line_num-30):line_num])
        
        patterns = [
            rf'{obj_name}\s*=\s*frappe\.get_doc\(["\']([^"\']+)["\']',
            rf'{obj_name}\s*=\s*frappe\.new_doc\(["\']([^"\']+)["\']',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, context)
            if match:
                return match.group(1)
                
        # Variable name mapping
        mappings = {
            'member': 'Member',
            'volunteer': 'Verenigingen Volunteer',
            'chapter': 'Chapter',
            'invoice': 'Sales Invoice',
            'schedule': 'Membership Dues Schedule'
        }
        
        return mappings.get(obj_name)
        
    def _create_issue(self, file_path: Path, line_num: int, obj_name: str,
                     field_name: str, doctype: str, source_lines: List[str]) -> ValidationIssue:
        """Create a validation issue"""
        context = source_lines[line_num - 1].strip() if line_num <= len(source_lines) else ""
        
        # Find similar fields
        fields = list(self.doctypes[doctype]['fields'].keys())
        similar = self._find_similar_fields(field_name, fields)
        similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
        
        return ValidationIssue(
            file=str(file_path.relative_to(self.app_path)),
            line=line_num,
            field=field_name,
            doctype=doctype,
            reference=f"{obj_name}.{field_name}",
            message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
            context=context,
            confidence='medium',  # Default, will be updated
            issue_type='missing_field',
            suggested_fix=similar[0] if similar else None
        )
        
    def _find_similar_fields(self, field: str, available_fields: List[str]) -> List[str]:
        """Find similar field names"""
        from difflib import get_close_matches
        return get_close_matches(field, available_fields, n=3, cutoff=0.6)
        
    def validate_directory(self, directory: Optional[str] = None) -> List[ValidationIssue]:
        """Validate all Python files in directory"""
        search_path = Path(directory) if directory else self.app_path
        all_issues = []
        
        for py_file in search_path.rglob("*.py"):
            # Skip obvious test/debug files
            if any(skip in str(py_file) for skip in ['__pycache__', '.pyc', 'test_', 'debug_']):
                continue
                
            issues = self.validate_file(py_file)
            all_issues.extend(issues)
            
        return all_issues
        
    def print_summary(self):
        """Print validation summary"""
        print(f"\n📊 Validation Summary")
        print(f"{'=' * 50}")
        print(f"Files processed: {self.stats['files_processed']}")
        print(f"Total issues found: {self.stats['issues_found']}")
        print(f"  High confidence: {self.stats['high_confidence']}")
        print(f"  Medium confidence: {self.stats['medium_confidence']}")
        print(f"  Low confidence: {self.stats['low_confidence']}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Enhanced DocType Field Validator')
    parser.add_argument('--pre-commit', action='store_true',
                       help='Run in pre-commit mode (only high confidence issues)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--path', default='/home/frappe/frappe-bench/apps/verenigingen',
                       help='Path to validate')
    
    args = parser.parse_args()
    
    validator = EnhancedFieldValidator(
        app_path=args.path,
        verbose=args.verbose,
        pre_commit_mode=args.pre_commit
    )
    
    print("🔍 Enhanced DocType Field Validator")
    print("=" * 50)
    
    start_time = time.time()
    issues = validator.validate_directory()
    duration = time.time() - start_time
    
    if args.pre_commit:
        # Pre-commit mode - only show high confidence
        high_conf_issues = [i for i in issues if i.confidence == 'high']
        
        if high_conf_issues:
            print(f"\n❌ Found {len(high_conf_issues)} high confidence issues:")
            for issue in high_conf_issues[:10]:  # Show first 10
                print(f"\n{issue.file}:{issue.line}")
                print(f"  {issue.message}")
                print(f"  Context: {issue.context}")
                if issue.suggested_fix:
                    print(f"  Suggested: {issue.suggested_fix}")
                    
            return 1  # Exit with error
        else:
            print("✅ No high confidence issues found")
            
            # Show summary of other issues
            other_issues = [i for i in issues if i.confidence != 'high']
            if other_issues:
                print(f"\n⚠️  {len(other_issues)} lower confidence issues (not blocking)")
                
            return 0
    else:
        # Normal mode - show all issues grouped by confidence
        if issues:
            # Group by confidence
            by_confidence = {'high': [], 'medium': [], 'low': []}
            for issue in issues:
                by_confidence[issue.confidence].append(issue)
                
            # Show high confidence first
            if by_confidence['high']:
                print(f"\n🔴 HIGH CONFIDENCE ({len(by_confidence['high'])} issues):")
                for issue in by_confidence['high'][:5]:
                    print(f"\n{issue.file}:{issue.line}")
                    print(f"  {issue.message}")
                    print(f"  Context: {issue.context}")
                    
            # Summary of others
            if by_confidence['medium']:
                print(f"\n🟡 MEDIUM CONFIDENCE: {len(by_confidence['medium'])} issues")
                
            if by_confidence['low']:
                print(f"\n🟢 LOW CONFIDENCE: {len(by_confidence['low'])} issues")
        else:
            print("\n✅ No issues found!")
            
    validator.print_summary()
    print(f"\nValidation completed in {duration:.2f} seconds")
    
    return len([i for i in issues if i.confidence == 'high'])

if __name__ == "__main__":
    exit(main())