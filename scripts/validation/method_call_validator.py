#!/usr/bin/env python3
"""
Method Call Validator

Validates that all Python method and function calls in the codebase reference existing methods.
Builds and maintains a cache of available methods for fast validation.

Features:
- AST-based call analysis
- Method signature caching
- Frappe-aware validation (hooks, controllers, etc.)
- Import tracking
- False positive filtering
"""

import ast
import json
import pickle
import hashlib
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import importlib.util
import sys


@dataclass
class MethodSignature:
    """Represents a method/function signature"""
    name: str
    module: str
    file_path: str
    line_number: int
    is_method: bool  # True for class methods, False for functions
    class_name: Optional[str] = None
    is_whitelisted: bool = False
    is_property: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    docstring: Optional[str] = None
    parameters: List[str] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = []


@dataclass
class MethodCall:
    """Represents a method/function call found in code"""
    name: str
    module: str
    file_path: str
    line_number: int
    column: int
    context: str
    call_type: str  # 'function', 'method', 'attribute'
    object_name: Optional[str] = None
    full_call: str = ""


@dataclass
class ValidationIssue:
    """Represents a validation issue"""
    file_path: str
    line_number: int
    column: int
    call_name: str
    issue_type: str
    message: str
    context: str
    confidence: str
    suggestions: List[str] = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class MethodCallValidator:
    """Validates method and function calls in Python code"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.cache_file = self.app_path / "scripts" / "validation" / ".method_cache.pkl"
        self.method_signatures: Dict[str, MethodSignature] = {}
        self.issues: List[ValidationIssue] = []
        
        # Built-in methods and common patterns to ignore
        self.builtin_methods = {
            # Python builtins
            'len', 'str', 'int', 'float', 'bool', 'list', 'dict', 'tuple', 'set',
            'print', 'range', 'enumerate', 'zip', 'map', 'filter', 'sorted',
            'max', 'min', 'sum', 'any', 'all', 'abs', 'round', 'type', 'isinstance',
            'hasattr', 'getattr', 'setattr', 'delattr', 'callable', 'iter',
            'next', 'open', 'input', 'format', 'join', 'split', 'replace',
            
            # Common string/list methods
            'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'index',
            'count', 'sort', 'reverse', 'copy', 'get', 'keys', 'values', 'items',
            'upper', 'lower', 'strip', 'lstrip', 'rstrip', 'startswith', 'endswith',
            'find', 'rfind', 'replace', 'split', 'rsplit', 'join', 'format',
            
            # Common object methods
            'save', 'insert', 'update', 'delete', 'validate', 'submit', 'cancel',
            'reload', 'as_dict', 'get_doc', 'get_value', 'set_value', 'db_set',
            'db_get', 'get_all', 'get_list', 'exists', 'get_single_value',
        }
        
        # Frappe-specific methods that are dynamically generated
        self.frappe_dynamic_methods = {
            'frappe.get_doc', 'frappe.new_doc', 'frappe.get_value', 'frappe.set_value',
            'frappe.get_all', 'frappe.get_list', 'frappe.db.get_value', 'frappe.db.set_value',
            'frappe.db.sql', 'frappe.db.commit', 'frappe.db.rollback', 'frappe.throw',
            'frappe.msgprint', 'frappe.log_error', 'frappe.whitelist', 'frappe.require',
            'frappe.session.user', 'frappe.local.site', 'frappe.utils.getdate',
            'frappe.utils.nowdate', 'frappe.utils.today', 'frappe.utils.now',
        }

    def build_method_cache(self, force_rebuild: bool = False) -> None:
        """Build or load method signature cache"""
        if not force_rebuild and self.cache_file.exists():
            try:
                cache_age = datetime.now().timestamp() - self.cache_file.stat().st_mtime
                if cache_age < 3600:  # Cache valid for 1 hour
                    with open(self.cache_file, 'rb') as f:
                        cache_data = pickle.load(f)
                        self.method_signatures = cache_data.get('signatures', {})
                        print(f"✅ Loaded {len(self.method_signatures)} method signatures from cache")
                        return
            except Exception as e:
                print(f"⚠️ Cache load failed: {e}, rebuilding...")
        
        print("🔍 Building method signature cache...")
        self._scan_all_methods()
        self._save_cache()
        print(f"✅ Built cache with {len(self.method_signatures)} method signatures")

    def _scan_all_methods(self) -> None:
        """Scan all Python files to build method signature database"""
        # Scan verenigingen app
        for py_file in self.app_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            self._extract_methods_from_file(py_file)
        
        # Also scan some core Frappe paths if accessible
        frappe_paths = [
            Path("/home/frappe/frappe-bench/apps/frappe"),
            Path("/home/frappe/frappe-bench/apps/erpnext"),
        ]
        
        for frappe_path in frappe_paths:
            if frappe_path.exists():
                print(f"📁 Scanning {frappe_path.name}...")
                for py_file in frappe_path.rglob("*.py"):
                    if self._should_skip_file(py_file):
                        continue
                    self._extract_methods_from_file(py_file)

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped during scanning"""
        skip_patterns = [
            '__pycache__', '.git', 'node_modules', '.pyc', 'test_',
            'debug_', 'migrations/', 'patches/', '.venv', 'env/',
        ]
        
        file_str = str(file_path)
        return any(pattern in file_str for pattern in skip_patterns)

    def _extract_methods_from_file(self, file_path: Path) -> None:
        """Extract method signatures from a Python file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse AST
            tree = ast.parse(content, filename=str(file_path))
            
            # Extract module name
            try:
                module_name = self._get_module_name(file_path)
            except Exception:
                module_name = file_path.stem
            
            # Walk AST to find function and method definitions
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self._process_function_def(node, file_path, module_name)
                elif isinstance(node, ast.ClassDef):
                    self._process_class_def(node, file_path, module_name)
                    
        except Exception as e:
            # Don't fail on syntax errors or other parsing issues
            pass

    def _get_module_name(self, file_path: Path) -> str:
        """Get module name from file path"""
        try:
            # Convert file path to module name
            relative_path = file_path.relative_to(self.app_path)
            module_parts = list(relative_path.parts[:-1])  # Exclude filename
            module_parts.append(relative_path.stem)  # Add filename without extension
            return '.'.join(module_parts)
        except Exception:
            return file_path.stem

    def _process_function_def(self, node: ast.FunctionDef, file_path: Path, module_name: str, class_name: str = None) -> None:
        """Process a function definition node"""
        # Extract parameters
        parameters = []
        for arg in node.args.args:
            parameters.append(arg.arg)
        
        # Check for decorators
        is_whitelisted = any(
            isinstance(decorator, ast.Name) and decorator.id == 'whitelist' or
            isinstance(decorator, ast.Attribute) and decorator.attr == 'whitelist'
            for decorator in node.decorator_list
        )
        
        is_property = any(
            isinstance(decorator, ast.Name) and decorator.id == 'property'
            for decorator in node.decorator_list
        )
        
        # Create signature
        signature = MethodSignature(
            name=node.name,
            module=module_name,
            file_path=str(file_path),
            line_number=node.lineno,
            is_method=class_name is not None,
            class_name=class_name,
            is_whitelisted=is_whitelisted,
            is_property=is_property,
            docstring=ast.get_docstring(node),
            parameters=parameters
        )
        
        # Store with multiple keys for lookup
        full_name = f"{module_name}.{node.name}"
        if class_name:
            full_name = f"{module_name}.{class_name}.{node.name}"
            class_method_name = f"{class_name}.{node.name}"
            self.method_signatures[class_method_name] = signature
        
        self.method_signatures[node.name] = signature
        self.method_signatures[full_name] = signature

    def _process_class_def(self, node: ast.ClassDef, file_path: Path, module_name: str) -> None:
        """Process a class definition node"""
        class_name = node.name
        
        # Process methods within the class
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                self._process_function_def(item, file_path, module_name, class_name)

    def _save_cache(self) -> None:
        """Save method signature cache to disk"""
        cache_data = {
            'signatures': self.method_signatures,
            'timestamp': datetime.now().timestamp(),
            'version': '1.0'
        }
        
        # Ensure cache directory exists
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.cache_file, 'wb') as f:
            pickle.dump(cache_data, f)

    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate method calls in a single file"""
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # Parse AST
            tree = ast.parse(content, filename=str(file_path))
            
            # Extract method calls
            calls = self._extract_method_calls(tree, file_path, lines)
            
            # Validate each call
            for call in calls:
                if not self._is_valid_call(call):
                    issue = self._create_validation_issue(call, lines)
                    if issue:
                        issues.append(issue)
                        
        except Exception as e:
            # Don't fail on syntax errors
            pass
            
        return issues

    def _extract_method_calls(self, tree: ast.AST, file_path: Path, lines: List[str]) -> List[MethodCall]:
        """Extract method calls from AST"""
        calls = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call = self._process_call_node(node, file_path, lines)
                if call:
                    calls.append(call)
        
        return calls

    def _process_call_node(self, node: ast.Call, file_path: Path, lines: List[str]) -> Optional[MethodCall]:
        """Process a function/method call node"""
        try:
            call_name = None
            object_name = None
            call_type = 'function'
            
            if isinstance(node.func, ast.Name):
                # Simple function call: func()
                call_name = node.func.id
                call_type = 'function'
            elif isinstance(node.func, ast.Attribute):
                # Method call: obj.method()
                call_name = node.func.attr
                call_type = 'method'
                
                # Try to get object name
                if isinstance(node.func.value, ast.Name):
                    object_name = node.func.value.id
                elif isinstance(node.func.value, ast.Attribute):
                    # Chained calls: obj.attr.method()
                    object_name = self._get_full_attribute_name(node.func.value)
            
            if not call_name:
                return None
            
            # Get context line
            line_num = node.lineno
            context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
            
            # Build full call representation
            full_call = f"{object_name}.{call_name}" if object_name else call_name
            
            return MethodCall(
                name=call_name,
                module=self._get_module_name(file_path),
                file_path=str(file_path),
                line_number=line_num,
                column=getattr(node, 'col_offset', 0),
                context=context,
                call_type=call_type,
                object_name=object_name,
                full_call=full_call
            )
            
        except Exception:
            return None

    def _get_full_attribute_name(self, node: ast.Attribute) -> str:
        """Get full attribute name from chained attribute access"""
        parts = []
        current = node
        
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        
        if isinstance(current, ast.Name):
            parts.append(current.id)
        
        return '.'.join(reversed(parts))

    def _is_valid_call(self, call: MethodCall) -> bool:
        """Check if a method call is valid"""
        # Skip built-in methods
        if call.name in self.builtin_methods:
            return True
            
        # Skip Frappe dynamic methods
        if call.full_call in self.frappe_dynamic_methods:
            return True
            
        # Check if method exists in our signatures
        lookup_keys = [
            call.name,  # Simple name
            call.full_call,  # Full call path
            f"{call.module}.{call.name}",  # Module.method
        ]
        
        for key in lookup_keys:
            if key in self.method_signatures:
                return True
        
        # Check for common patterns that are likely valid
        if self._is_likely_valid_pattern(call):
            return True
            
        return False

    def _is_likely_valid_pattern(self, call: MethodCall) -> bool:
        """Check if call matches patterns that are likely valid"""
        # Dynamic attribute access patterns
        dynamic_patterns = [
            # Common object methods
            call.name in ['get', 'set', 'update', 'delete', 'save', 'reload'],
            # Property access
            call.call_type == 'method' and call.object_name in ['self', 'cls'],
            # Frappe document methods
            call.name in ['insert', 'submit', 'cancel', 'validate', 'on_update'],
            # Database operations
            call.name in ['sql', 'commit', 'rollback', 'get_value', 'set_value'],
            # Common utilities
            call.name.startswith('get_') or call.name.startswith('set_'),
            # Magic methods
            call.name.startswith('__') and call.name.endswith('__'),
        ]
        
        return any(dynamic_patterns)

    def _create_validation_issue(self, call: MethodCall, lines: List[str]) -> Optional[ValidationIssue]:
        """Create a validation issue for an invalid call"""
        # Find potential suggestions
        suggestions = self._find_similar_methods(call.name)
        
        return ValidationIssue(
            file_path=call.file_path,
            line_number=call.line_number,
            column=call.column,
            call_name=call.full_call,
            issue_type="undefined_method",
            message=f"Method '{call.name}' not found in method signatures",
            context=call.context,
            confidence="medium" if suggestions else "high",
            suggestions=suggestions[:3]  # Top 3 suggestions
        )

    def _find_similar_methods(self, method_name: str) -> List[str]:
        """Find similar method names for suggestions"""
        similar = []
        
        for sig_name, signature in self.method_signatures.items():
            # Simple similarity checks
            if method_name.lower() in sig_name.lower():
                similar.append(sig_name)
            elif sig_name.lower() in method_name.lower():
                similar.append(sig_name)
            elif self._levenshtein_distance(method_name, sig_name) <= 2:
                similar.append(sig_name)
        
        return sorted(similar, key=lambda x: self._levenshtein_distance(method_name, x))[:5]

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein distance between two strings"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]

    def validate_directory(self, directory: str = None) -> List[ValidationIssue]:
        """Validate all Python files in a directory"""
        all_issues = []
        search_path = Path(directory) if directory else self.app_path
        
        print(f"🔍 Validating method calls in {search_path}...")
        
        for py_file in search_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
                
            issues = self.validate_file(py_file)
            all_issues.extend(issues)
            
        return all_issues

    def print_report(self, issues: List[ValidationIssue]) -> None:
        """Print validation report"""
        if not issues:
            print("✅ No method call issues found!")
            return
        
        # Group by confidence
        high_conf = [i for i in issues if i.confidence == "high"]
        medium_conf = [i for i in issues if i.confidence == "medium"]
        
        print(f"🚨 Found {len(issues)} method call issues:")
        print(f"   🔴 High confidence: {len(high_conf)}")
        print(f"   🟡 Medium confidence: {len(medium_conf)}")
        
        if high_conf:
            print(f"\n🔴 HIGH CONFIDENCE ISSUES:")
            for issue in high_conf[:10]:  # Limit output
                rel_path = Path(issue.file_path).relative_to(self.app_path)
                print(f"   {rel_path}:{issue.line_number} - {issue.call_name}")
                print(f"      {issue.message}")
                if issue.suggestions:
                    print(f"      💡 Suggestions: {', '.join(issue.suggestions)}")
        
        if medium_conf:
            print(f"\n🟡 MEDIUM CONFIDENCE ISSUES (showing first 5):")
            for issue in medium_conf[:5]:
                rel_path = Path(issue.file_path).relative_to(self.app_path)
                print(f"   {rel_path}:{issue.line_number} - {issue.call_name}")


def main():
    """Main function to run method call validation"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Build/load cache
    force_rebuild = '--rebuild-cache' in sys.argv
    validator.build_method_cache(force_rebuild=force_rebuild)
    
    # Validate files
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        # Validate specific file
        file_path = Path(sys.argv[1])
        issues = validator.validate_file(file_path)
    else:
        # Validate all files
        issues = validator.validate_directory()
    
    # Print report
    validator.print_report(issues)
    
    # Exit with error code if high confidence issues found
    high_conf_issues = [i for i in issues if i.confidence == "high"]
    if high_conf_issues:
        print(f"\n❌ Validation failed: {len(high_conf_issues)} critical issues found")
        sys.exit(1)
    else:
        print(f"\n✅ Method call validation passed")
        sys.exit(0)


if __name__ == "__main__":
    main()