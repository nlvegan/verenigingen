#!/usr/bin/env python3
"""
Codanna-Powered Deprecated Function Checker

Uses Codanna's semantic search capabilities to identify deprecated function usage
across the codebase and provides actionable remediation suggestions.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

# Import Codanna MCP functions
try:
    from mcp import search_symbols, semantic_search_docs, find_symbol
    CODANNA_AVAILABLE = True
except ImportError:
    CODANNA_AVAILABLE = False


@dataclass
class DeprecatedUsage:
    """Represents usage of a deprecated function"""
    file_path: str
    line_number: int
    function_name: str
    usage_context: str
    deprecated_reason: str
    replacement_suggestion: Optional[str] = None
    confidence: float = 1.0


class CodannaDeprecatedChecker:
    """Uses Codanna to identify and analyze deprecated function usage"""

    def __init__(self):
        self.deprecated_functions = {}
        self.discovered_usages = []

    def load_deprecated_functions_from_codanna(self) -> Dict[str, Dict]:
        """Use Codanna to discover deprecated functions in the codebase"""
        if not CODANNA_AVAILABLE:
            print("⚠️  Codanna MCP not available, using fallback patterns")
            return self._get_fallback_deprecated_functions()

        deprecated_functions = {}

        try:
            # Search for functions marked as deprecated
            symbols = search_symbols("DEPRECATED", limit=20)

            for symbol in symbols.get('results', []):
                if symbol.get('kind') in ['Function', 'Method']:
                    deprecated_functions[symbol['name']] = {
                        'file_path': symbol['file'],
                        'signature': symbol.get('signature', ''),
                        'doc': symbol.get('doc', ''),
                        'reason': self._extract_deprecation_reason(symbol.get('doc', '')),
                        'replacement': self._extract_replacement(symbol.get('doc', ''))
                    }

            # Search for specific deprecated patterns
            deprecated_patterns = [
                "deprecated_pattern",
                "DEPRECATED:",
                "deprecated method",
                "use instead",
                "superseded by"
            ]

            for pattern in deprecated_patterns:
                docs = semantic_search_docs(pattern, limit=10)
                for doc in docs.get('results', []):
                    if 'deprecated' in doc.get('content', '').lower():
                        func_name = self._extract_function_name(doc)
                        if func_name and func_name not in deprecated_functions:
                            deprecated_functions[func_name] = {
                                'file_path': doc.get('file', ''),
                                'doc': doc.get('content', ''),
                                'reason': self._extract_deprecation_reason(doc.get('content', '')),
                                'replacement': self._extract_replacement(doc.get('content', ''))
                            }

        except Exception as e:
            print(f"⚠️  Error using Codanna: {e}")
            return self._get_fallback_deprecated_functions()

        return deprecated_functions

    def _get_fallback_deprecated_functions(self) -> Dict[str, Dict]:
        """Fallback deprecated functions based on known patterns"""
        return {
            # Context-specific deprecations using file path patterns
            'donation.create_sales_invoice': {
                'reason': 'DEPRECATED: Sales Invoice creation removed - using Payment History child table model',
                'replacement': 'Use Payment History child table model',
                'file_path': 'donation',
                'function_name': 'create_sales_invoice'
            },
            'get_creation_user': {
                'reason': 'Compatibility function - marked for migration review',
                'replacement': 'Verify if secure_operations.get_creation_user exists or should be implemented',
                'file_path': 'verenigingen/utils/application_helpers.py'
            },
            'save_with_system_context': {
                'reason': 'Working compatibility layer - no immediate action needed',
                'replacement': 'Consider migrating to secure_operations.secure_user_context for new code',
                'file_path': 'verenigingen/utils/application_helpers.py'
            }
        }

    def _extract_deprecation_reason(self, doc_text: str) -> str:
        """Extract deprecation reason from documentation"""
        patterns = [
            r'DEPRECATED[:\-\s]+(.*?)(?:\n|$)',
            r'deprecated[:\-\s]+(.*?)(?:\n|$)',
            r'use\s+(.+?)\s+instead',
            r'superseded\s+by\s+(.+?)(?:\n|$)'
        ]

        for pattern in patterns:
            match = re.search(pattern, doc_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "Function is marked as deprecated"

    def _extract_replacement(self, doc_text: str) -> Optional[str]:
        """Extract replacement suggestion from documentation"""
        patterns = [
            r'use\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+instead',
            r'replaced\s+by\s+([a-zA-Z_][a-zA-Z0-9_.]*)',
            r'superseded\s+by\s+([a-zA-Z_][a-zA-Z0-9_.]*)',
            r'new\s+code\s+use[:\s]+([a-zA-Z_][a-zA-Z0-9_.]*)'
        ]

        for pattern in patterns:
            match = re.search(pattern, doc_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_function_name(self, doc_info: Dict) -> Optional[str]:
        """Extract function name from documentation info"""
        # Try to extract from file path or content
        content = doc_info.get('content', '')

        # Look for function definitions
        func_match = re.search(r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
        if func_match:
            return func_match.group(1)

        # Look for function names in documentation
        name_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:is|was)?\s*deprecated', content, re.IGNORECASE)
        if name_match:
            return name_match.group(1)

        return None

    def scan_file_for_deprecated_usage(self, file_path: Path) -> List[DeprecatedUsage]:
        """Scan a single file for deprecated function usage"""
        if not file_path.exists() or not file_path.suffix == '.py':
            return []

        usages = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')

            # Parse with AST for function calls
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = self._get_function_name_from_call(node)
                        if func_name and self._should_flag_usage(func_name, file_path, node, lines):
                            line_num = getattr(node, 'lineno', 0)
                            usage_context = lines[line_num - 1] if line_num <= len(lines) else ""

                            # Skip defensive programming patterns
                            if self._is_defensive_coding(usage_context):
                                continue

                            deprecated_info = self._get_deprecated_info_for_context(func_name, file_path)
                            if deprecated_info:
                                usages.append(DeprecatedUsage(
                                    file_path=str(file_path),
                                    line_number=line_num,
                                    function_name=func_name,
                                    usage_context=usage_context.strip(),
                                    deprecated_reason=deprecated_info['reason'],
                                    replacement_suggestion=deprecated_info['replacement']
                                ))

            except SyntaxError:
                # Fall back to regex search for files with syntax issues
                self._regex_search_deprecated(file_path, content, lines, usages)

        except Exception as e:
            print(f"⚠️  Error scanning {file_path}: {e}")

        return usages

    def _get_function_name_from_call(self, call_node: ast.Call) -> Optional[str]:
        """Extract function name from AST Call node"""
        if isinstance(call_node.func, ast.Name):
            return call_node.func.id
        elif isinstance(call_node.func, ast.Attribute):
            return call_node.func.attr
        return None

    def _should_flag_usage(self, func_name: str, file_path: Path, node: ast.Call, lines: List[str]) -> bool:
        """Determine if this function usage should be flagged as deprecated"""
        # Check if we have any deprecated patterns for this function
        return self._get_deprecated_info_for_context(func_name, file_path) is not None

    def _get_deprecated_info_for_context(self, func_name: str, file_path: Path) -> Optional[Dict]:
        """Get deprecated function info based on context (file path and function name)"""
        file_path_str = str(file_path)

        # Check context-specific deprecations first
        context_key = f"donation.{func_name}"
        if context_key in self.deprecated_functions and 'donation' in file_path_str:
            return self.deprecated_functions[context_key]

        # Check general deprecations
        if func_name in self.deprecated_functions:
            return self.deprecated_functions[func_name]

        return None

    def _is_defensive_coding(self, usage_context: str) -> bool:
        """Detect defensive programming patterns that should not be flagged"""
        defensive_patterns = [
            r'if\s+hasattr\s*\(',          # if hasattr(obj, 'method')
            r'getattr\s*\(',               # getattr(obj, 'method', default)
            r'\.get_\w+\(\)\s+if\s+hasattr',  # obj.get_method() if hasattr(obj, 'get_method')
        ]

        for pattern in defensive_patterns:
            if re.search(pattern, usage_context, re.IGNORECASE):
                return True

        return False

    def _regex_search_deprecated(self, file_path: Path, content: str, lines: List[str], usages: List[DeprecatedUsage]):
        """Fallback regex search for deprecated function usage"""
        for func_name, func_info in self.deprecated_functions.items():
            # Search for function calls
            patterns = [
                rf'\b{re.escape(func_name)}\s*\(',  # Direct function call
                rf'\.{re.escape(func_name)}\s*\(',  # Method call
            ]

            for pattern in patterns:
                for match in re.finditer(pattern, content):
                    line_num = content[:match.start()].count('\n') + 1
                    usage_context = lines[line_num - 1] if line_num <= len(lines) else ""

                    usages.append(DeprecatedUsage(
                        file_path=str(file_path),
                        line_number=line_num,
                        function_name=func_name,
                        usage_context=usage_context.strip(),
                        deprecated_reason=func_info['reason'],
                        replacement_suggestion=func_info['replacement'],
                        confidence=0.8  # Lower confidence for regex matches
                    ))

    def scan_directory(self, directory: Path, exclude_patterns: Optional[List[str]] = None) -> List[DeprecatedUsage]:
        """Scan directory for deprecated function usage"""
        if exclude_patterns is None:
            exclude_patterns = ['__pycache__', '.git', 'node_modules', '.pytest_cache']

        all_usages = []

        for py_file in directory.rglob('*.py'):
            # Skip excluded patterns
            if any(pattern in str(py_file) for pattern in exclude_patterns):
                continue

            usages = self.scan_file_for_deprecated_usage(py_file)
            all_usages.extend(usages)

        return all_usages

    def generate_report(self, usages: List[DeprecatedUsage]) -> str:
        """Generate a comprehensive report of deprecated function usage"""
        if not usages:
            return "✅ No deprecated function usage found!"

        # Group by function
        by_function = defaultdict(list)
        for usage in usages:
            by_function[usage.function_name].append(usage)

        report = [
            "🔍 Deprecated Function Usage Report",
            "=" * 50,
            f"Total deprecated usages found: {len(usages)}",
            f"Functions affected: {len(by_function)}",
            ""
        ]

        for func_name, func_usages in by_function.items():
            report.extend([
                f"🚨 Function: {func_name}",
                f"   Usages: {len(func_usages)}",
                f"   Reason: {func_usages[0].deprecated_reason}",
                f"   Replacement: {func_usages[0].replacement_suggestion or 'See documentation'}",
                ""
            ])

            # Show top 5 usage locations
            for usage in func_usages[:5]:
                report.append(f"   📍 {usage.file_path}:{usage.line_number}")
                report.append(f"      {usage.usage_context}")

            if len(func_usages) > 5:
                report.append(f"   ... and {len(func_usages) - 5} more locations")

            report.append("")

        return "\n".join(report)

    def run_analysis(self, target_directory: str = None) -> None:
        """Run complete deprecated function analysis"""
        print("🔍 Starting Codanna-powered deprecated function analysis...")

        # Load deprecated functions
        print("📡 Loading deprecated functions from Codanna...")
        self.deprecated_functions = self.load_deprecated_functions_from_codanna()
        print(f"🎯 Found {len(self.deprecated_functions)} deprecated functions to check")

        # Scan directory
        if target_directory is None:
            target_directory = str(Path.cwd() / "verenigingen")

        target_path = Path(target_directory)
        if not target_path.exists():
            print(f"❌ Target directory not found: {target_directory}")
            return

        print(f"🔍 Scanning {target_path} for deprecated usage...")
        usages = self.scan_directory(target_path)

        # Generate and display report
        report = self.generate_report(usages)
        print(report)

        # Save report to file
        report_file = Path("deprecated_functions_report.md")
        with open(report_file, 'w') as f:
            f.write(f"# Deprecated Function Usage Report\n\n{report}")
        print(f"📄 Report saved to {report_file}")


def main():
    """Main function for CLI usage"""
    import argparse

    parser = argparse.ArgumentParser(description="Check for deprecated function usage using Codanna")
    parser.add_argument("--directory", "-d", help="Directory to scan (default: ./verenigingen)")
    parser.add_argument("--function", "-f", help="Check specific function only")

    args = parser.parse_args()

    checker = CodannaDeprecatedChecker()

    if args.function:
        # Check specific function
        checker.deprecated_functions = {args.function: {'reason': 'Specified function', 'replacement': None}}

    checker.run_analysis(args.directory)


if __name__ == "__main__":
    main()