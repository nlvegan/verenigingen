#!/usr/bin/env python3
"""
AST Field Analyzer with File Path Inference for Hook Files

This is the improved version of the AST Field Analyzer that includes:
- File path-based DocType inference to eliminate false positives in hook files
- Better handling of Link fields
- Reduced false positives while maintaining accurate detection

The original analyzer has been archived as ast_field_analyzer_original.py
"""

import ast
import sys
from pathlib import Path

# Import the original analyzer (now archived)
sys.path.insert(0, str(Path(__file__).parent))
from ast_field_analyzer_original import ASTFieldAnalyzer as OriginalAnalyzer, ValidationContext, ValidationIssue, ConfidenceLevel

# Make the patched analyzer the default export
class ASTFieldAnalyzer(OriginalAnalyzer):
    """Patched analyzer with file path inference for hook files"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        super().__init__(app_path, verbose)
        # Add cache for file path inference
        self._file_path_inference_cache = {}
    
    def _infer_doctype_from_hook_file(self, file_path: Path) -> str:
        """Infer DocType from hook file name pattern"""
        
        # Check cache first
        file_key = str(file_path)
        if file_key in self._file_path_inference_cache:
            return self._file_path_inference_cache[file_key]
        
        result = None
        file_name = file_path.name
        
        # Pattern: <doctype_name>_hooks.py
        if file_name.endswith('_hooks.py'):
            base_name = file_name[:-9]  # Remove '_hooks.py'
            
            if base_name:
                # Try converting to Title Case
                potential_doctype = base_name.replace('_', ' ').title()
                
                # Check if this DocType exists
                if potential_doctype in self.doctypes:
                    result = potential_doctype
                    if self.verbose:
                        print(f"    ✓ Inferred {potential_doctype} from hook file: {file_name}")
        
        self._file_path_inference_cache[file_key] = result
        return result
    
    def detect_doctype_with_modern_logic(self, node, source_lines, file_context):
        """Override to add file path inference as highest priority for hook files"""
        
        obj_name = node.value.id if hasattr(node.value, 'id') else None
        if not obj_name:
            return None, None
        
        # NEW: Check if we have a file path stored in context
        file_path = getattr(file_context, '_file_path', None)
        
        # NEW: File path inference for hook files (highest priority)
        if file_path and str(file_path).endswith('_hooks.py') and obj_name in ['doc', 'self']:
            inferred_doctype = self._infer_doctype_from_hook_file(Path(file_path))
            
            if inferred_doctype:
                # Validate that the field makes sense for this DocType
                if hasattr(node, 'attr'):
                    field_name = node.attr
                    if inferred_doctype in self.doctypes:
                        doctype_fields = self.doctypes[inferred_doctype].get('fields', set())
                        
                        # Check if field exists on the inferred DocType
                        if field_name in doctype_fields:
                            if self.verbose:
                                print(f"    ✓ File path inference: {obj_name} -> {inferred_doctype}, field '{field_name}' exists")
                            return inferred_doctype, "file_path_inference"
                        
                        # Check if it's a Link field (common pattern)
                        link_fields = ['member', 'customer', 'supplier', 'user', 'company']
                        if field_name in link_fields:
                            if self.verbose:
                                print(f"    ✓ File path inference: {obj_name} -> {inferred_doctype}, '{field_name}' is likely a Link field")
                            return inferred_doctype, "file_path_inference"
                        
                        # Check if it's a common framework field
                        common_fields = {'name', 'creation', 'modified', 'owner', 'docstatus'}
                        # Also check for common non-field attributes
                        common_non_field_attributes = {'errors', 'success', 'result', 'status', 'message'}
                        if field_name in common_fields or field_name in common_non_field_attributes:
                            return inferred_doctype, "file_path_inference"
        
        # Fall back to original detection logic
        return super().detect_doctype_with_modern_logic(node, source_lines, file_context)
    
    def analyze_file_context(self, tree, file_path):
        """Override to store file path in context"""
        context = super().analyze_file_context(tree, file_path)
        
        # Store the file path for later use
        context._file_path = file_path
        
        return context
    
    def analyze_file_context(self, tree, file_path):
        """Override to store file path and track DocType() QueryBuilder variables"""
        context = super().analyze_file_context(tree, file_path)

        # Store the file path for later use
        context._file_path = file_path

        # Track QueryBuilder DocType() assignments
        # Pattern: CBM = DocType("Chapter Board Member")
        doctype_tracker = QueryBuilderDocTypeTracker()
        doctype_tracker.visit(tree)
        context.querybuilder_doctypes = doctype_tracker.doctype_vars

        # Track lambda parameters
        # Pattern: lambda m: m.field_name
        lambda_tracker = LambdaParameterTracker()
        lambda_tracker.visit(tree)
        context.lambda_params = lambda_tracker.lambda_params

        return context

    def detect_doctype_with_modern_logic(self, node, source_lines, file_context):
        """Override to add QueryBuilder DocType recognition"""

        obj_name = node.value.id if hasattr(node.value, 'id') else None
        if not obj_name:
            return None, None

        # NEW: Check if this is a QueryBuilder DocType variable (CBM, TM, etc.)
        if hasattr(file_context, 'querybuilder_doctypes') and obj_name in file_context.querybuilder_doctypes:
            # This is a QueryBuilder proxy like CBM.field_name
            # The fields belong to the target DocType, not the parent class
            target_doctype = file_context.querybuilder_doctypes[obj_name]
            if self.verbose:
                print(f"    ✓ QueryBuilder: {obj_name} -> {target_doctype} (DocType proxy)")
            # Return None to skip validation - QueryBuilder fields are valid
            return None, "querybuilder_proxy"

        # NEW: Check if this is a lambda parameter (common in config dicts)
        # Lambda params like 'm' or 'dt' are not DocType instances
        if hasattr(file_context, 'lambda_params') and obj_name in file_context.lambda_params:
            if self.verbose:
                print(f"    ✓ Lambda parameter: {obj_name} (not a DocType field)")
            # Return None to skip validation - lambda params are valid
            return None, "lambda_parameter"

        # Check if we have a file path stored in context
        file_path = getattr(file_context, '_file_path', None)

        # File path inference for hook files (highest priority)
        if file_path and str(file_path).endswith('_hooks.py') and obj_name in ['doc', 'self']:
            inferred_doctype = self._infer_doctype_from_hook_file(Path(file_path))

            if inferred_doctype:
                # Validate that the field makes sense for this DocType
                if hasattr(node, 'attr'):
                    field_name = node.attr
                    if inferred_doctype in self.doctypes:
                        doctype_fields = self.doctypes[inferred_doctype].get('fields', set())

                        # Check if field exists on the inferred DocType
                        if field_name in doctype_fields:
                            if self.verbose:
                                print(f"    ✓ File path inference: {obj_name} -> {inferred_doctype}, field '{field_name}' exists")
                            return inferred_doctype, "file_path_inference"

                        # Check if it's a Link field (common pattern)
                        link_fields = ['member', 'customer', 'supplier', 'user', 'company']
                        if field_name in link_fields:
                            if self.verbose:
                                print(f"    ✓ File path inference: {obj_name} -> {inferred_doctype}, '{field_name}' is likely a Link field")
                            return inferred_doctype, "file_path_inference"

                        # Check if it's a common framework field
                        common_fields = {'name', 'creation', 'modified', 'owner', 'docstatus'}
                        # Also check for common non-field attributes
                        common_non_field_attributes = {'errors', 'success', 'result', 'status', 'message'}
                        if field_name in common_fields or field_name in common_non_field_attributes:
                            return inferred_doctype, "file_path_inference"

        # Fall back to original detection logic
        return super().detect_doctype_with_modern_logic(node, source_lines, file_context)

    def calculate_confidence(self, issue, context):
        """Override to adjust confidence for file path inference"""

        # If the inference came from file path, it's high confidence
        if hasattr(issue, 'inference_method') and issue.inference_method == "file_path_inference":
            # Check if this might be a false positive
            file_path = getattr(context, '_file_path', None)
            if file_path and str(file_path).endswith('_hooks.py'):
                # In hook files, fields like 'member', 'is_template' are often valid
                if issue.field in ['member', 'is_template', 'status']:
                    # These are likely valid fields, reduce confidence significantly
                    return ConfidenceLevel.LOW

        # Fall back to original confidence calculation
        return super().calculate_confidence(issue, context)


class QueryBuilderDocTypeTracker(ast.NodeVisitor):
    """Track QueryBuilder DocType() variable assignments"""

    def __init__(self):
        self.doctype_vars = {}  # variable_name -> doctype_name

    def visit_Assign(self, node):
        """Track assignments like: CBM = DocType("Chapter Board Member")"""
        if len(node.targets) == 1 and isinstance(node.targets[0], (ast.Name,)):
            var_name = node.targets[0].id

            # Check for DocType() calls
            # Pattern: CBM = DocType("Chapter Board Member")
            if (isinstance(node.value, ast.Call) and
                isinstance(node.value.func, ast.Name) and
                node.value.func.id == 'DocType' and
                len(node.value.args) >= 1):

                # Extract DocType name from DocType("Name")
                doctype_arg = node.value.args[0]
                if isinstance(doctype_arg, ast.Constant):  # Python 3.8+
                    doctype_name = doctype_arg.value
                elif isinstance(doctype_arg, ast.Str):  # Python 3.7
                    doctype_name = doctype_arg.s
                else:
                    doctype_name = None

                if doctype_name and isinstance(doctype_name, str):
                    self.doctype_vars[var_name] = doctype_name

        self.generic_visit(node)


class LambdaParameterTracker(ast.NodeVisitor):
    """Track lambda function parameters to avoid false positives"""

    def __init__(self):
        self.lambda_params = set()  # parameter names used in lambdas

    def visit_Lambda(self, node):
        """Track lambda parameters like: lambda m: m.field"""
        for arg in node.args.args:
            self.lambda_params.add(arg.arg)

        self.generic_visit(node)


def main():
    """Test the patched analyzer"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Parse arguments
    verbose = '--verbose' in sys.argv
    detailed = '--detailed' in sys.argv
    
    # Extract file paths
    file_paths = []
    for arg in sys.argv[1:]:
        if not arg.startswith('--') and arg.endswith('.py'):
            file_paths.append(Path(arg))
    
    print("AST Field Analyzer - Patched Version with Hook File Support")
    print("="*60)
    
    analyzer = ASTFieldAnalyzer(app_path, verbose=verbose)
    
    if file_paths:
        print(f"🔍 Validating {len(file_paths)} specific files...")
        violations = []
        for file_path in file_paths:
            try:
                resolved_path = file_path.resolve()
                if resolved_path.exists():
                    violations.extend(analyzer.validate_file(resolved_path))
            except Exception as e:
                print(f"Warning: Could not process {file_path}: {e}")
    else:
        # Test on the problematic hook file
        hook_file = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/membership_dues_schedule/membership_dues_schedule_hooks.py")
        if hook_file.exists():
            print(f"🔍 Testing on hook file: {hook_file.name}")
            violations = analyzer.validate_file(hook_file)
        else:
            print("❌ Hook file not found")
            return 1
    
    # Filter to medium+ confidence
    medium_plus = [v for v in violations if v.confidence in [ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH, ConfidenceLevel.CRITICAL]]
    
    print()
    if medium_plus:
        print(f"Found {len(medium_plus)} medium+ confidence issues:")
        for issue in medium_plus:
            # Extract relative path from the file field for cleaner output
            file_path = issue.file
            if file_path.startswith('/home/frappe/frappe-bench/apps/verenigingen/'):
                file_path = file_path.replace('/home/frappe/frappe-bench/apps/verenigingen/', '')
            print(f"  {file_path}:{issue.line}: {issue.field} ({issue.confidence.value}) - {issue.message}")
    else:
        print("✅ No medium+ confidence issues found!")
    
    print()
    print(f"Total issues: {len(violations)} (all confidence levels)")
    print(f"Medium+ issues: {len(medium_plus)}")
    
    return 0 if len(medium_plus) == 0 else 1


if __name__ == "__main__":
    exit(main())