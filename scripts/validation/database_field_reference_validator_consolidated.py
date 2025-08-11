#!/usr/bin/env python3
"""
Database Field Reference Validator - Using Consolidated Environment Handler
Validates field references in database queries with unified environment management.
"""

import ast
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Set, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum

# Import consolidated environment handler
from environment_handler import ValidationEnvironment, EnvironmentConfig, logger

# Import DocType loader
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata


class ValidationLevel(Enum):
    """Validation strictness levels."""
    STRICT = "strict"       # All potential issues
    BALANCED = "balanced"   # Practical balance
    PERMISSIVE = "permissive"  # Only high-confidence issues


@dataclass
class FieldReference:
    """Represents a field reference in code."""
    file_path: str
    line_number: int
    doctype: str
    field: str
    code_snippet: str
    confidence: str = "high"
    validation_type: str = "field_reference"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "file": self.file_path,
            "line": self.line_number,
            "doctype": self.doctype,
            "field": self.field,
            "snippet": self.code_snippet,
            "confidence": self.confidence,
            "type": self.validation_type
        }


class DatabaseFieldValidator:
    """Validates field references in database operations using consolidated environment."""
    
    def __init__(self, validation_level: ValidationLevel = ValidationLevel.BALANCED):
        """Initialize validator with consolidated environment handler."""
        self.validation_level = validation_level
        self.issues: List[FieldReference] = []
        self.val_env = ValidationEnvironment()
        self.loader = None
        self.initialized = False
        
    def initialize(self):
        """Initialize validation environment and DocType loader."""
        if self.initialized:
            return
            
        try:
            # Use validation context to initialize Frappe
            with self.val_env.validation_context() as env:
                # Initialize DocType loader with Frappe context
                self.loader = DocTypeLoader()
                self.loader.load_all_doctypes()
                
                # Store loaded DocTypes for use outside context
                self.doctypes = self.loader.doctypes.copy()
                self.initialized = True
                
                logger.info(f"Loaded {len(self.doctypes)} DocTypes for validation")
                
        except Exception as e:
            logger.error(f"Failed to initialize validator: {e}")
            raise
            
    def validate_file(self, file_path: str) -> List[FieldReference]:
        """Validate field references in a Python file."""
        if not self.initialized:
            self.initialize()
            
        issues = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST
            try:
                tree = ast.parse(content, filename=file_path)
            except SyntaxError as e:
                logger.warning(f"Syntax error in {file_path}: {e}")
                return issues
                
            # Visit nodes and validate
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    node_issues = self._validate_call_node(node, content, file_path)
                    issues.extend(node_issues)
                    
        except Exception as e:
            logger.error(f"Error validating {file_path}: {e}")
            
        return issues
        
    def _validate_call_node(self, node: ast.Call, content: str, file_path: str) -> List[FieldReference]:
        """Validate a function call node for field references."""
        issues = []
        
        # Check for frappe.db calls
        if self._is_frappe_db_call(node):
            # Extract DocType and fields
            doctype = self._extract_doctype(node)
            fields = self._extract_fields(node)
            
            if doctype and fields:
                for field in fields:
                    if not self._is_valid_field(doctype, field):
                        # Get line number and code snippet
                        line_no = node.lineno
                        snippet = self._get_code_snippet(content, line_no)
                        
                        # Determine confidence based on pattern
                        confidence = self._determine_confidence(field, snippet)
                        
                        if self._should_report(confidence):
                            issues.append(FieldReference(
                                file_path=file_path,
                                line_number=line_no,
                                doctype=doctype,
                                field=field,
                                code_snippet=snippet,
                                confidence=confidence
                            ))
                            
        return issues
        
    def _is_frappe_db_call(self, node: ast.Call) -> bool:
        """Check if node is a frappe.db call."""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Attribute):
                # frappe.db.method pattern
                if (isinstance(node.func.value.value, ast.Name) and 
                    node.func.value.value.id == 'frappe' and
                    node.func.value.attr == 'db'):
                    return True
        return False
        
    def _extract_doctype(self, node: ast.Call) -> Optional[str]:
        """Extract DocType from call arguments."""
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant):
                return first_arg.value
            elif isinstance(first_arg, ast.Str):  # Python 3.7 compatibility
                return first_arg.s
        return None
        
    def _extract_fields(self, node: ast.Call) -> List[str]:
        """Extract field names from call arguments."""
        fields = []
        
        # Check for field in second argument (get_value pattern)
        if len(node.args) > 1:
            second_arg = node.args[1]
            if isinstance(second_arg, (ast.Constant, ast.Str)):
                value = second_arg.value if isinstance(second_arg, ast.Constant) else second_arg.s
                if value != "*":  # Skip wildcard selections
                    fields.append(value)
                    
        # Check for fields in filters
        for keyword in node.keywords:
            if keyword.arg == 'filters' and isinstance(keyword.value, ast.Dict):
                for key in keyword.value.keys:
                    if isinstance(key, (ast.Constant, ast.Str)):
                        field = key.value if isinstance(key, ast.Constant) else key.s
                        fields.append(field)
                        
        return fields
        
    def _is_valid_field(self, doctype: str, field: str) -> bool:
        """Check if field exists in DocType."""
        if doctype not in self.doctypes:
            return True  # Assume valid if DocType not found
            
        meta = self.doctypes[doctype]
        return field in [f.fieldname for f in meta.fields]
        
    def _get_code_snippet(self, content: str, line_no: int) -> str:
        """Get code snippet around line number."""
        lines = content.split('\n')
        if 0 <= line_no - 1 < len(lines):
            return lines[line_no - 1].strip()
        return ""
        
    def _determine_confidence(self, field: str, snippet: str) -> str:
        """Determine confidence level of the issue."""
        # High confidence patterns
        if re.search(r'frappe\.db\.(get_value|set_value|get_list)', snippet):
            return "high"
            
        # Medium confidence patterns
        if 'filters' in snippet or 'fields' in snippet:
            return "medium"
            
        # Low confidence (might be dynamic)
        return "low"
        
    def _should_report(self, confidence: str) -> bool:
        """Determine if issue should be reported based on validation level."""
        if self.validation_level == ValidationLevel.STRICT:
            return True
        elif self.validation_level == ValidationLevel.BALANCED:
            return confidence in ["high", "medium"]
        else:  # PERMISSIVE
            return confidence == "high"
            
    def validate_directory(self, directory: str) -> List[FieldReference]:
        """Validate all Python files in directory."""
        if not self.initialized:
            self.initialize()
            
        all_issues = []
        py_files = Path(directory).rglob("*.py")
        
        for file_path in py_files:
            # Skip test files and migrations
            if any(skip in str(file_path) for skip in ['test_', 'tests/', 'migrations/']):
                continue
                
            issues = self.validate_file(str(file_path))
            all_issues.extend(issues)
            
        return all_issues
        
    def print_summary(self, issues: List[FieldReference]):
        """Print validation summary."""
        if not issues:
            print("✅ No field reference issues found!")
            return
            
        print(f"\n❌ Found {len(issues)} field reference issues:\n")
        
        # Group by file
        by_file = {}
        for issue in issues:
            if issue.file_path not in by_file:
                by_file[issue.file_path] = []
            by_file[issue.file_path].append(issue)
            
        for file_path, file_issues in by_file.items():
            print(f"\n📄 {file_path}")
            for issue in file_issues:
                print(f"  Line {issue.line_number}: {issue.doctype}.{issue.field}")
                print(f"    Confidence: {issue.confidence}")
                print(f"    Code: {issue.code_snippet[:80]}...")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate field references in database operations"
    )
    parser.add_argument(
        "--path",
        default=EnvironmentConfig.get_app_path(),
        help="Path to validate"
    )
    parser.add_argument(
        "--level",
        choices=["strict", "balanced", "permissive"],
        default="balanced",
        help="Validation level"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    
    args = parser.parse_args()
    
    # Create validator
    level = ValidationLevel(args.level)
    validator = DatabaseFieldValidator(validation_level=level)
    
    # Validate
    logger.info(f"Validating {args.path} with {args.level} level...")
    issues = validator.validate_directory(args.path)
    
    # Output results
    if args.json:
        output = {
            "validation_level": args.level,
            "total_issues": len(issues),
            "issues": [issue.to_dict() for issue in issues]
        }
        print(json.dumps(output, indent=2))
    else:
        validator.print_summary(issues)
        
    # Exit with error if issues found
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()