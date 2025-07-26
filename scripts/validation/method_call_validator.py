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
import re


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
        
        # Track class hierarchy and imports for better context awareness
        self.class_hierarchy: Dict[str, Set[str]] = {}  # class_name -> set of methods
        self.file_imports: Dict[str, Dict[str, str]] = {}  # file_path -> {alias: full_module}
        self.static_method_calls: Dict[str, Set[str]] = {}  # class_name -> static methods
        
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
        """Build or load method signature cache with enhanced data structures"""
        if not force_rebuild and self.cache_file.exists():
            try:
                cache_age = datetime.now().timestamp() - self.cache_file.stat().st_mtime
                if cache_age < 3600:  # Cache valid for 1 hour
                    with open(self.cache_file, 'rb') as f:
                        cache_data = pickle.load(f)
                        self.method_signatures = cache_data.get('signatures', {})
                        self.class_hierarchy = cache_data.get('class_hierarchy', {})
                        self.static_method_calls = cache_data.get('static_method_calls', {})
                        self.file_imports = cache_data.get('file_imports', {})
                        print(f"✅ Loaded {len(self.method_signatures)} method signatures from cache")
                        print(f"   Classes: {len(self.class_hierarchy)}, Static methods: {sum(len(m) for m in self.static_method_calls.values())}")
                        return
            except Exception as e:
                print(f"⚠️ Cache load failed: {e}, rebuilding...")
        
        print("🔍 Building enhanced method signature cache...")
        self._scan_all_methods()
        self._save_cache()
        print(f"✅ Built cache with {len(self.method_signatures)} method signatures")
        print(f"   Classes tracked: {len(self.class_hierarchy)}")
        print(f"   Static methods: {sum(len(methods) for methods in self.static_method_calls.values())}")

    def _scan_all_methods(self) -> None:
        """Scan all Python files to build method signature database"""
        # Scan verenigingen app only (faster)
        print("📁 Scanning verenigingen app...")
        count = 0
        for py_file in self.app_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            self._extract_methods_from_file(py_file)
            count += 1
            if count % 50 == 0:
                print(f"   Processed {count} files...")
        
        # Add common Frappe methods manually for better performance
        self._add_common_frappe_methods()
        
        # Optionally scan Frappe core for comprehensive analysis
        import sys
        if '--include-frappe' in sys.argv:
            self._scan_frappe_core()
        
        print(f"   Final method count: {len(self.method_signatures)}")

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
            
            # First pass: Extract imports for context awareness
            self._extract_imports_from_file(tree, str(file_path))
            
            # Second pass: Extract classes and methods with better hierarchy tracking
            self._extract_classes_and_methods(tree, file_path, module_name)
                    
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

    def _extract_imports_from_file(self, tree: ast.AST, file_path: str) -> None:
        """Extract import statements for better context awareness"""
        imports = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        name = alias.asname if alias.asname else alias.name
                        full_name = f"{node.module}.{alias.name}"
                        imports[name] = full_name
        
        self.file_imports[file_path] = imports
    
    def _extract_classes_and_methods(self, tree: ast.AST, file_path: Path, module_name: str) -> None:
        """Extract classes and methods with better hierarchy tracking"""
        # Use a visitor pattern to properly track nested structures
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._process_class_def_enhanced(node, file_path, module_name)
            elif isinstance(node, ast.FunctionDef):
                # Only process top-level functions here
                # Class methods are handled within _process_class_def_enhanced
                if not self._is_inside_class(node, tree):
                    self._process_function_def(node, file_path, module_name)
    
    def _is_inside_class(self, func_node: ast.FunctionDef, tree: ast.AST) -> bool:
        """Check if a function node is inside a class"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if item is func_node:
                        return True
        return False
    
    def _find_parent_class(self, func_node: ast.FunctionDef, tree: ast.AST) -> Optional[str]:
        """Find the parent class of a function node"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if item is func_node:
                        return node.name
        return None
    
    def _process_class_def_enhanced(self, node: ast.ClassDef, file_path: Path, module_name: str) -> None:
        """Process a class definition node with enhanced tracking"""
        class_name = node.name
        class_methods = set()
        
        # Track inheritance first
        self._track_inheritance_hierarchy(node, module_name)
        
        # Extract all methods and track static/class methods
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                class_methods.add(item.name)
                
                # Check for static/class method decorators
                is_static = any(
                    isinstance(d, ast.Name) and d.id == 'staticmethod' or
                    isinstance(d, ast.Attribute) and d.attr == 'staticmethod'
                    for d in item.decorator_list
                )
                
                is_classmethod = any(
                    isinstance(d, ast.Name) and d.id == 'classmethod' or
                    isinstance(d, ast.Attribute) and d.attr == 'classmethod'
                    for d in item.decorator_list
                )
                
                if is_static or is_classmethod:
                    # Track both simple and full class names
                    for cls_key in [class_name, f"{module_name}.{class_name}"]:
                        if cls_key not in self.static_method_calls:
                            self.static_method_calls[cls_key] = set()
                        self.static_method_calls[cls_key].add(item.name)
                
                self._process_function_def(item, file_path, module_name, class_name)
        
        # Store class hierarchy (update rather than replace to preserve inheritance)
        if class_name not in self.class_hierarchy:
            self.class_hierarchy[class_name] = set()
        self.class_hierarchy[class_name].update(class_methods)
        
        # Also store with full module name
        full_class_name = f"{module_name}.{class_name}"
        if full_class_name not in self.class_hierarchy:
            self.class_hierarchy[full_class_name] = set()
        self.class_hierarchy[full_class_name].update(class_methods)

    def _save_cache(self) -> None:
        """Save enhanced method signature cache to disk"""
        cache_data = {
            'signatures': self.method_signatures,
            'class_hierarchy': self.class_hierarchy,
            'static_method_calls': self.static_method_calls,
            'file_imports': self.file_imports,
            'timestamp': datetime.now().timestamp(),
            'version': '2.0'  # Updated version for enhanced cache
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
                
                # Handle different attribute access patterns
                if isinstance(node.func.value, ast.Name):
                    # obj.method()
                    object_name = node.func.value.id
                elif isinstance(node.func.value, ast.Attribute):
                    # obj.attr.method() or module.submodule.method()
                    object_name = self._get_full_attribute_name(node.func.value)
                elif isinstance(node.func.value, ast.Call):
                    # func().method() - dynamic call result
                    object_name = "<dynamic_call>"
                elif isinstance(node.func.value, ast.Subscript):
                    # obj[key].method() - subscript access
                    object_name = "<subscript_access>"
                elif isinstance(node.func.value, ast.Constant):
                    # "string".method() or 123.method()
                    object_name = f"<{type(node.func.value.value).__name__}>"
                elif isinstance(node.func.value, ast.List):
                    # [].method()
                    object_name = "<list>"
                elif isinstance(node.func.value, ast.Dict):
                    # {}.method()
                    object_name = "<dict>"
                else:
                    # Other complex expressions
                    object_name = "<expression>"
                    
            elif isinstance(node.func, ast.Subscript):
                # Callable subscript: obj[key]()
                call_name = "<subscript_call>"
                call_type = 'subscript'
                
            elif isinstance(node.func, ast.Call):
                # Higher-order function: func()()
                call_name = "<higher_order_call>"
                call_type = 'higher_order'
                
            elif isinstance(node.func, ast.Lambda):
                # Lambda call: (lambda x: x)()
                call_name = "<lambda_call>"
                call_type = 'lambda'
                
            else:
                # Other complex call patterns
                call_name = "<complex_call>"
                call_type = 'complex'
            
            if not call_name:
                return None
            
            # Get context line
            line_num = node.lineno
            context = lines[line_num - 1].strip() if line_num <= len(lines) else ""
            
            # Build full call representation
            if object_name and not object_name.startswith('<'):
                full_call = f"{object_name}.{call_name}"
            else:
                full_call = call_name
            
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
    
    def _add_common_frappe_methods(self) -> None:
        """Add common Frappe methods that are dynamically generated"""
        common_methods = [
            # Frappe core methods
            ('frappe.get_doc', 'frappe.core', False),
            ('frappe.new_doc', 'frappe.core', False),
            ('frappe.get_value', 'frappe.core', False),
            ('frappe.set_value', 'frappe.core', False),
            ('frappe.get_all', 'frappe.core', False),
            ('frappe.get_list', 'frappe.core', False),
            ('frappe.throw', 'frappe.core', False),
            ('frappe.msgprint', 'frappe.core', False),
            ('frappe.log_error', 'frappe.core', False),
            ('frappe.whitelist', 'frappe.core', False),
            ('frappe.require', 'frappe.core', False),
            
            # Database methods
            ('sql', 'frappe.database', False),
            ('commit', 'frappe.database', False),
            ('rollback', 'frappe.database', False),
            ('get_value', 'frappe.database', False),
            ('set_value', 'frappe.database', False),
            ('get_all', 'frappe.database', False),
            ('get_list', 'frappe.database', False),
            ('exists', 'frappe.database', False),
            
            # Document methods (appear on all documents)
            ('save', 'frappe.document', True),
            ('insert', 'frappe.document', True),
            ('submit', 'frappe.document', True),
            ('cancel', 'frappe.document', True),
            ('delete', 'frappe.document', True),
            ('reload', 'frappe.document', True),
            ('validate', 'frappe.document', True),
            ('on_update', 'frappe.document', True),
            ('on_submit', 'frappe.document', True),
            ('on_cancel', 'frappe.document', True),
            ('before_save', 'frappe.document', True),
            ('after_insert', 'frappe.document', True),
            ('as_dict', 'frappe.document', True),
            ('get', 'frappe.document', True),
            ('set', 'frappe.document', True),
            ('update', 'frappe.document', True),
            ('append', 'frappe.document', True),
            ('remove', 'frappe.document', True),
            ('db_set', 'frappe.document', True),
            ('db_get', 'frappe.document', True),
            
            # Utils
            ('getdate', 'frappe.utils', False),
            ('nowdate', 'frappe.utils', False),
            ('today', 'frappe.utils', False),
            ('now', 'frappe.utils', False),
            ('formatdate', 'frappe.utils', False),
            ('add_to_date', 'frappe.utils', False),
        ]
        
        for method_name, module, is_method in common_methods:
            signature = MethodSignature(
                name=method_name.split('.')[-1],
                module=module,
                file_path="<frappe_core>",
                line_number=0,
                is_method=is_method,
                parameters=[]
            )
            self.method_signatures[method_name] = signature
            self.method_signatures[signature.name] = signature
    
    def _scan_frappe_core(self) -> None:
        """Scan Frappe core apps for comprehensive method database"""
        frappe_paths = [
            Path("/home/frappe/frappe-bench/apps/frappe"),
            Path("/home/frappe/frappe-bench/apps/erpnext"),
        ]
        
        total_count = 0
        for frappe_path in frappe_paths:
            if not frappe_path.exists():
                continue
                
            print(f"📁 Scanning {frappe_path.name} for comprehensive analysis...")
            count = 0
            
            for py_file in frappe_path.rglob("*.py"):
                if self._should_skip_file(py_file):
                    continue
                    
                self._extract_methods_from_file(py_file)
                count += 1
                total_count += 1
                
                if count % 200 == 0:
                    print(f"   Processed {count} files from {frappe_path.name}...")
        
        print(f"   Scanned {total_count} additional files from Frappe core")

    def _is_valid_call(self, call: MethodCall) -> bool:
        """Check if a method call is valid with enhanced context awareness"""
        # Skip built-in methods
        if call.name in self.builtin_methods:
            return True
            
        # Skip Frappe dynamic methods
        if call.full_call in self.frappe_dynamic_methods:
            return True
        
        # Enhanced validation logic
        if self._validate_with_context_awareness(call):
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
    
    def _validate_with_context_awareness(self, call: MethodCall) -> bool:
        """Enhanced validation with better context awareness"""
        # Case 1: self.method() calls - be more conservative but accurate
        if call.object_name == 'self' and call.call_type == 'method':
            # Try to find the class this method belongs to
            current_class = self._find_current_class_context(call)
            if current_class:
                if self._method_exists_in_class(call.name, current_class):
                    return True
                # Also check for common Frappe document methods on self
                if call.name in {
                    'save', 'insert', 'submit', 'cancel', 'delete', 'reload', 'validate',
                    'on_update', 'before_save', 'after_insert', 'on_submit', 'on_cancel',
                    'as_dict', 'get', 'set', 'update', 'append', 'remove', 'db_set', 'db_get',
                    'is_new', 'has_value', 'get_doc_before_save', 'flags'
                }:
                    return True
        
        # Case 2: Class.static_method() calls - check imported classes
        if call.call_type == 'method' and call.object_name and not call.object_name.startswith('<'):
            # Check if this is a static method call on an imported class
            if self._is_static_method_call(call):
                return True
            
            # Check if this is a call on an imported module/class
            if self._is_imported_class_method(call):
                return True
        
        # Case 3: Chained method calls like obj.attr.method()
        if call.object_name and '.' in call.object_name and not call.object_name.startswith('<'):
            # More sophisticated module resolution
            if self._validate_chained_call(call):
                return True
        
        return False
    
    def _find_current_class_context(self, call: MethodCall) -> Optional[str]:
        """Find the current class context for a method call"""
        try:
            with open(call.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse AST to find the class context
            tree = ast.parse(content)
            
            # Find the class that contains the line
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if the call is within this class's line range
                    class_start = node.lineno
                    class_end = self._get_node_end_line(node, content)
                    
                    if class_start <= call.line_number <= class_end:
                        return node.name
            
            return None
        except Exception:
            return None
    
    def _get_node_end_line(self, node: ast.AST, content: str) -> int:
        """Get the end line number of an AST node"""
        try:
            lines = content.split('\n')
            # Simple heuristic: find the next class/function at same indentation level
            if hasattr(node, 'lineno'):
                start_line = node.lineno - 1  # Convert to 0-based
                if start_line < len(lines):
                    start_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
                    
                    for i in range(start_line + 1, len(lines)):
                        line = lines[i]
                        if line.strip():
                            current_indent = len(line) - len(line.lstrip())
                            if current_indent <= start_indent and (line.strip().startswith('class ') or line.strip().startswith('def ')):
                                return i
                    
                    return len(lines)
            return node.lineno + 10  # Fallback
        except Exception:
            return getattr(node, 'lineno', 1) + 10
    
    def _method_exists_in_class(self, method_name: str, class_name: str) -> bool:
        """Check if a method exists in the given class"""
        # Check direct class name
        if class_name in self.class_hierarchy:
            if method_name in self.class_hierarchy[class_name]:
                return True
        
        # Check with module prefixes - be more comprehensive
        for full_class_name, methods in self.class_hierarchy.items():
            if (full_class_name.endswith(f'.{class_name}') or 
                full_class_name == class_name or
                full_class_name.split('.')[-1] == class_name):
                if method_name in methods:
                    return True
        
        # Check if this might be a Frappe Document class
        if method_name in {
            'save', 'insert', 'submit', 'cancel', 'delete', 'reload', 'validate',
            'on_update', 'before_save', 'after_insert', 'on_submit', 'on_cancel',
            'as_dict', 'get', 'set', 'update', 'append', 'remove', 'db_set', 'db_get'
        }:
            return True
        
        return False
    
    def _is_static_method_call(self, call: MethodCall) -> bool:
        """Check if this is a valid static method call"""
        if not call.object_name:
            return False
        
        class_name = call.object_name
        
        # Check if this class has the static method (direct name)
        if class_name in self.static_method_calls:
            if call.name in self.static_method_calls[class_name]:
                return True
        
        # Check with module prefix
        module_class_name = f"{call.module}.{class_name}"
        if module_class_name in self.static_method_calls:
            if call.name in self.static_method_calls[module_class_name]:
                return True
        
        # Check with file imports
        file_imports = self.file_imports.get(call.file_path, {})
        if class_name in file_imports:
            full_class_name = file_imports[class_name]
            # Extract class name from full import path
            imported_class = full_class_name.split('.')[-1]
            
            # Check both imported class name and full class name
            for check_name in [imported_class, full_class_name, class_name]:
                if check_name in self.static_method_calls:
                    if call.name in self.static_method_calls[check_name]:
                        return True
        
        # Special case: check if this is a class defined in the same file
        if class_name in self.class_hierarchy:
            # If the method exists in the class, assume it's valid for static/class method calls
            if call.name in self.class_hierarchy[class_name]:
                return True
        
        return False
    
    def _is_imported_class_method(self, call: MethodCall) -> bool:
        """Check if this is a method call on an imported class/module"""
        if not call.object_name:
            return False
        
        file_imports = self.file_imports.get(call.file_path, {})
        
        # Check if object_name is an imported module/class
        if call.object_name in file_imports:
            full_name = file_imports[call.object_name]
            # Look for the method in our signatures with the full path
            lookup_keys = [
                f"{full_name}.{call.name}",
                f"{call.object_name}.{call.name}",
            ]
            
            for key in lookup_keys:
                if key in self.method_signatures:
                    return True
            
            # Also check if this is a known class with methods
            imported_class = full_name.split('.')[-1]
            if imported_class in self.class_hierarchy:
                if call.name in self.class_hierarchy[imported_class]:
                    return True
        
        return False
    
    def _validate_chained_call(self, call: MethodCall) -> bool:
        """Validate chained method calls like module.submodule.method()"""
        if not call.object_name or '.' not in call.object_name:
            return False
        
        # Check if this matches a known module pattern
        parts = call.object_name.split('.')
        
        # Try different combinations
        for i in range(len(parts)):
            partial_module = '.'.join(parts[:i+1])
            method_path = f"{partial_module}.{call.name}"
            
            if method_path in self.method_signatures:
                return True
        
        return False

    def _is_likely_valid_pattern(self, call: MethodCall) -> bool:
        """Check if call matches patterns that are likely valid (more conservative)"""
        # Skip complex call types that we can't easily validate
        if call.call_type in ['subscript', 'higher_order', 'lambda', 'complex']:
            return True
            
        # Skip calls on dynamic objects
        if call.object_name and call.object_name.startswith('<'):
            return True
        
        # More conservative dynamic patterns to reduce false positives
        conservative_patterns = [
            # Magic methods (very safe)
            call.name.startswith('__') and call.name.endswith('__'),
            
            # Built-in type methods on typed objects
            call.object_name in ['<str>', '<list>', '<dict>', '<set>', '<tuple>'] and call.name in [
                'append', 'extend', 'insert', 'remove', 'pop', 'index', 'count', 'sort', 'reverse',
                'upper', 'lower', 'strip', 'split', 'join', 'replace', 'find', 'startswith', 'endswith',
                'keys', 'values', 'items', 'get', 'update', 'clear', 'copy', 'add', 'discard'
            ],
            
            # Frappe specific patterns (very common and safe)
            call.full_call.startswith('frappe.') or call.object_name == 'frappe',
            call.full_call.startswith('frappe.db.') or (call.object_name == 'frappe.db' if call.object_name else False),
            
            # Test framework methods (safe)
            call.name.startswith('assert') and call.object_name in ['self', None],
            call.name.startswith('test_') and call.object_name in ['self', None],
            
            # Lambda and complex expressions (can't validate easily)
            call.object_name and any(pattern in call.object_name for pattern in [
                '<lambda>', '<comprehension>', '<generator>'
            ]),
            
            # Document lifecycle methods (Frappe framework)
            call.name in ['validate', 'on_update', 'before_save', 'after_insert', 'on_submit', 'on_cancel'] and 
            call.object_name == 'self',
            
            # Very common utility patterns that are likely always valid
            call.name in ['len', 'str', 'int', 'float', 'bool', 'type', 'isinstance', 'hasattr', 'getattr', 'setattr'],
        ]
        
        return any(conservative_patterns)
    
    def _track_inheritance_hierarchy(self, node: ast.ClassDef, module_name: str) -> None:
        """Track class inheritance for better method resolution"""
        class_name = node.name
        base_classes = []
        
        # Extract base classes
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_classes.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_classes.append(self._get_full_attribute_name(base))
        
        # Store inheritance information
        full_class_name = f"{module_name}.{class_name}"
        if full_class_name not in self.class_hierarchy:
            self.class_hierarchy[full_class_name] = set()
        
        # Add inherited methods (simplified - real implementation would need full resolution)
        for base_class in base_classes:
            if base_class in self.class_hierarchy:
                self.class_hierarchy[full_class_name].update(self.class_hierarchy[base_class])
            
            # Check for common Frappe base classes
            if base_class in ['Document', 'DocType']:
                # Add common Frappe document methods
                frappe_methods = {
                    'save', 'insert', 'submit', 'cancel', 'delete', 'reload', 'validate',
                    'on_update', 'before_save', 'after_insert', 'on_submit', 'on_cancel',
                    'as_dict', 'get', 'set', 'update', 'append', 'remove', 'db_set', 'db_get'
                }
                self.class_hierarchy[full_class_name].update(frappe_methods)

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
                try:
                    rel_path = Path(issue.file_path).relative_to(self.app_path)
                except ValueError:
                    rel_path = Path(issue.file_path)
                print(f"   {rel_path}:{issue.line_number} - {issue.call_name}")
                print(f"      {issue.message}")
                if issue.suggestions:
                    print(f"      💡 Suggestions: {', '.join(issue.suggestions)}")
        
        if medium_conf:
            print(f"\n🟡 MEDIUM CONFIDENCE ISSUES (showing first 5):")
            for issue in medium_conf[:5]:
                try:
                    rel_path = Path(issue.file_path).relative_to(self.app_path)
                except ValueError:
                    rel_path = Path(issue.file_path)
                print(f"   {rel_path}:{issue.line_number} - {issue.call_name}")


def main():
    """Main function to run method call validation
    
    Usage:
        python method_call_validator.py                    # Quick validation (verenigingen only)
        python method_call_validator.py --rebuild-cache    # Rebuild cache first
        python method_call_validator.py --include-frappe   # Comprehensive (includes Frappe core)
        python method_call_validator.py --comprehensive    # Full analysis with Frappe
        python method_call_validator.py file.py            # Validate single file
    """
    import sys
    
    if '--help' in sys.argv or '-h' in sys.argv:
        print(main.__doc__)
        sys.exit(0)
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = MethodCallValidator(app_path)
    
    # Build/load cache
    force_rebuild = '--rebuild-cache' in sys.argv or '--comprehensive' in sys.argv
    
    print("🔍 Comprehensive Method Call Validator")
    print("=" * 50)
    
    if '--include-frappe' in sys.argv or '--comprehensive' in sys.argv:
        print("🚀 Running COMPREHENSIVE analysis (includes Frappe core)")
        print("   This will take 2-5 minutes but provides thorough validation")
    else:
        print("⚡ Running QUICK analysis (verenigingen app only)")
        print("   Use --include-frappe for comprehensive Frappe core analysis")
    
    print()
    validator.build_method_cache(force_rebuild=force_rebuild)
    
    # Validate files
    if len(sys.argv) > 1 and not any(arg.startswith('--') for arg in sys.argv[1:]):
        # Validate specific file (first non-flag argument)
        file_path = Path(next(arg for arg in sys.argv[1:] if not arg.startswith('--')))
        print(f"\n🔍 Validating single file: {file_path}")
        issues = validator.validate_file(file_path)
    else:
        # Validate all files
        issues = validator.validate_directory()
    
    # Print report
    validator.print_report(issues)
    
    # Print summary stats
    total_methods = len(validator.method_signatures)
    print(f"\n📊 VALIDATION SUMMARY:")
    print(f"   Method signatures in database: {total_methods:,}")
    print(f"   Issues found: {len(issues)}")
    
    # Exit with error code if high confidence issues found
    high_conf_issues = [i for i in issues if i.confidence == "high"]
    if high_conf_issues:
        print(f"\n❌ Validation failed: {len(high_conf_issues)} critical issues found")
        print("   Consider fixing these before committing")
        sys.exit(1)
    else:
        print(f"\n✅ Method call validation passed")
        sys.exit(0)


if __name__ == "__main__":
    main()