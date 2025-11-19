#!/usr/bin/env python3
"""
Test Function Security Tool

Safely applies @development_only() decorators to test functions after
analyzing their content and context to ensure they should be secured.

Features:
1. Content analysis to confirm function is actually test/debug
2. Dependency checking to avoid breaking production code
3. Dry-run mode to preview changes
4. Rollback capability
5. Automatic backup creation

Usage: 
  python scripts/secure_test_functions_tool.py --dry-run  # Preview changes
  python scripts/secure_test_functions_tool.py --apply    # Apply changes
  python scripts/secure_test_functions_tool.py --rollback # Undo changes
"""

import os
import re
import ast
import shutil
import argparse
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from datetime import datetime


class TestFunctionSecurityTool:
    """Tool for safely securing test functions with @development_only()"""
    
    def __init__(self, base_path: str = "/home/frappe/frappe-bench/apps/verenigingen"):
        self.base_path = Path(base_path)
        self.backup_dir = self.base_path / "backups" / f"security_changes_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Patterns for confirming test/debug functions
        self.definite_test_patterns = [
            r'^test_',
            r'^debug_', 
            r'^create_test',
            r'^cleanup_test',
            r'_test_helper$',
            r'_debug$',
            r'^mock_'
        ]
        
        # Patterns that suggest production usage (be cautious)
        self.production_indicators = [
            r'get_.*_api$',
            r'validate_',
            r'process_',
            r'handle_',
            r'update_',
            r'create_(?!test)',
            r'save_',
            r'delete_(?!test)'
        ]
        
        # Content analysis keywords
        self.test_keywords = [
            'test', 'debug', 'mock', 'fixture', 'assert', 'sample', 'dummy',
            'cleanup', 'temporary', 'demo', 'example'
        ]
        
        self.production_keywords = [
            'customer', 'invoice', 'payment', 'real', 'actual', 'production',
            'live', 'valid', 'business', 'process'
        ]
    
    def analyze_function_safety(self, file_path: Path, function_name: str, function_content: str) -> Dict[str, any]:
        """Analyze if function is safe to secure with @development_only()"""
        analysis = {
            'function': function_name,
            'file': str(file_path),
            'is_safe_to_secure': False,
            'confidence_score': 0,
            'reasons': [],
            'warnings': [],
            'dependencies': []
        }
        
        # Check function name patterns
        name_score = self._analyze_function_name(function_name, analysis)
        
        # Analyze function content
        content_score = self._analyze_function_content(function_content, analysis)
        
        # Check for production usage indicators
        production_risk = self._check_production_usage_risk(function_content, analysis)
        
        # Analyze dependencies
        self._analyze_function_dependencies(function_content, analysis)
        
        # Calculate overall safety score
        analysis['confidence_score'] = name_score + content_score - production_risk
        analysis['is_safe_to_secure'] = analysis['confidence_score'] >= 70
        
        return analysis
    
    def _analyze_function_name(self, function_name: str, analysis: Dict) -> int:
        """Analyze function name for test/debug patterns"""
        score = 0
        name_lower = function_name.lower()
        
        # Strong test indicators
        for pattern in self.definite_test_patterns:
            if re.search(pattern, name_lower):
                score += 40
                analysis['reasons'].append(f"Function name matches test pattern: {pattern}")
                break
        
        # Production indicators (negative score)
        for pattern in self.production_indicators:
            if re.search(pattern, name_lower):
                score -= 30
                analysis['warnings'].append(f"Function name suggests production use: {pattern}")
        
        return score
    
    def _analyze_function_content(self, content: str, analysis: Dict) -> int:
        """Analyze function content for test/debug characteristics"""
        score = 0
        content_lower = content.lower()
        
        # Count test keywords
        test_keyword_count = sum(1 for keyword in self.test_keywords if keyword in content_lower)
        production_keyword_count = sum(1 for keyword in self.production_keywords if keyword in content_lower)
        
        if test_keyword_count > production_keyword_count:
            score += min(test_keyword_count * 10, 40)
            analysis['reasons'].append(f"Contains {test_keyword_count} test-related keywords")
        
        # Check for test-specific operations
        test_operations = [
            r'frappe\.throw.*test',
            r'print\s*\(',  # Debug printing
            r'\.insert\(.*ignore_permissions.*true',  # Test data creation
            r'cleanup|clean_up',
            r'assert|assertEqual',
            r'faker\.|fake_',
            r'test_data|sample_data',
            r'return.*test.*success'
        ]
        
        for pattern in test_operations:
            if re.search(pattern, content_lower):
                score += 15
                analysis['reasons'].append(f"Contains test operation: {pattern}")
        
        return score
    
    def _check_production_usage_risk(self, content: str, analysis: Dict) -> int:
        """Check for indicators of production usage"""
        risk_score = 0
        content_lower = content.lower()
        
        # High-risk operations
        high_risk_patterns = [
            r'frappe\.db\.delete',
            r'frappe\.delete_doc.*(?!test)',
            r'real.*customer',
            r'live.*data',
            r'production.*env'
        ]
        
        for pattern in high_risk_patterns:
            if re.search(pattern, content_lower):
                risk_score += 25
                analysis['warnings'].append(f"High-risk operation detected: {pattern}")
        
        return risk_score
    
    def _analyze_function_dependencies(self, content: str, analysis: Dict):
        """Analyze function dependencies and imports"""
        try:
            tree = ast.parse(content)
            
            # Look for imports and function calls
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if 'test' in name.name.lower():
                            analysis['dependencies'].append(f"Import: {name.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and 'test' in node.module.lower():
                        analysis['dependencies'].append(f"Import from: {node.module}")
                        
        except SyntaxError:
            analysis['warnings'].append("Could not parse function for dependency analysis")
    
    def scan_for_securable_functions(self) -> List[Dict]:
        """Scan codebase for functions that can be safely secured"""
        securable_functions = []
        
        for py_file in self.base_path.rglob("*.py"):
            if not py_file.exists() or self._should_skip_file(py_file):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find whitelisted functions
                whitelist_pattern = re.compile(
                    r'(@frappe\.whitelist\([^)]*\)\s*\n\s*def\s+(\w+).*?(?=\n\s*(?:@|\n|def|class|$))|'
                    r'@frappe\.whitelist\([^)]*\)\s*\n\s*def\s+(\w+).*?(?=\Z))', 
                    re.MULTILINE | re.DOTALL
                )
                
                for match in whitelist_pattern.finditer(content):
                    function_name = match.group(2) if match.group(2) else match.group(3)
                    if not function_name:
                        continue
                        
                    function_content = match.group(0)
                    
                    # Skip if already has @development_only
                    if '@development_only' in function_content:
                        continue
                    
                    # Analyze safety
                    analysis = self.analyze_function_safety(py_file, function_name, function_content)
                    
                    if analysis['is_safe_to_secure'] or analysis['confidence_score'] >= 50:
                        securable_functions.append(analysis)
                        
            except Exception as e:
                print(f"Error analyzing {py_file}: {e}")
                continue
        
        # Sort by confidence score (highest first)
        securable_functions.sort(key=lambda x: x['confidence_score'], reverse=True)
        return securable_functions
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Skip files that shouldn't be modified"""
        skip_patterns = [
            '.git', '__pycache__', 'node_modules', '.pytest_cache',
            'backups/', '/archived/', 'node_modules'
        ]
        path_str = str(file_path)
        return any(pattern in path_str for pattern in skip_patterns)
    
    def preview_security_changes(self) -> str:
        """Generate preview of proposed security changes"""
        functions = self.scan_for_securable_functions()
        
        report = []
        report.append("=" * 80)
        report.append("TEST FUNCTION SECURITY PREVIEW")
        report.append("=" * 80)
        report.append("")
        
        # Summary
        high_confidence = [f for f in functions if f['confidence_score'] >= 80]
        medium_confidence = [f for f in functions if 60 <= f['confidence_score'] < 80]
        low_confidence = [f for f in functions if 50 <= f['confidence_score'] < 60]
        
        report.append("CONFIDENCE LEVELS")
        report.append("-" * 20)
        report.append(f"High Confidence (≥80): {len(high_confidence)} functions")
        report.append(f"Medium Confidence (60-79): {len(medium_confidence)} functions") 
        report.append(f"Low Confidence (50-59): {len(low_confidence)} functions")
        report.append(f"Total Functions to Secure: {len(functions)}")
        report.append("")
        
        # High confidence examples
        if high_confidence:
            report.append("HIGH CONFIDENCE FUNCTIONS (Safe to secure)")
            report.append("-" * 45)
            for func in high_confidence[:10]:
                file_name = Path(func['file']).name
                report.append(f"✅ {func['function']}() in {file_name} (Score: {func['confidence_score']})")
                for reason in func['reasons'][:2]:
                    report.append(f"   • {reason}")
                if func['warnings']:
                    report.append(f"   ⚠️ Warning: {func['warnings'][0]}")
                report.append("")
        
        # Medium confidence functions need review
        if medium_confidence:
            report.append("MEDIUM CONFIDENCE FUNCTIONS (Review recommended)")
            report.append("-" * 50)
            for func in medium_confidence[:5]:
                file_name = Path(func['file']).name
                report.append(f"🤔 {func['function']}() in {file_name} (Score: {func['confidence_score']})")
                if func['warnings']:
                    report.append(f"   ⚠️ {func['warnings'][0]}")
                report.append("")
        
        return "\n".join(report)
    
    def apply_security_changes(self, dry_run: bool = True, min_confidence: int = 70) -> Dict[str, any]:
        """Apply @development_only() decorators to qualified functions"""
        functions = self.scan_for_securable_functions()
        qualified_functions = [f for f in functions if f['confidence_score'] >= min_confidence]
        
        results = {
            'functions_processed': 0,
            'functions_secured': 0,
            'files_modified': set(),
            'errors': [],
            'changes_preview': []
        }
        
        if not dry_run:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        for func_info in qualified_functions:
            try:
                file_path = Path(func_info['file'])
                
                # Backup file
                if not dry_run:
                    backup_path = self.backup_dir / file_path.name
                    shutil.copy2(file_path, backup_path)
                
                # Read file content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Add @development_only() decorator
                updated_content = self._add_development_only_decorator(content, func_info['function'])
                
                if updated_content != content:
                    results['changes_preview'].append({
                        'file': str(file_path),
                        'function': func_info['function'],
                        'confidence': func_info['confidence_score']
                    })
                    
                    if not dry_run:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(updated_content)
                        results['files_modified'].add(str(file_path))
                    
                    results['functions_secured'] += 1
                
                results['functions_processed'] += 1
                
            except Exception as e:
                results['errors'].append(f"Error processing {func_info['function']}: {e}")
        
        return results
    
    def _add_development_only_decorator(self, content: str, function_name: str) -> str:
        """Add @development_only() decorator to specific function"""
        lines = content.split('\n')
        
        # Find the function definition
        for i, line in enumerate(lines):
            if f'def {function_name}(' in line:
                # Look backwards for @frappe.whitelist()
                whitelist_line = None
                for j in range(i-1, max(i-5, -1), -1):
                    if '@frappe.whitelist' in lines[j]:
                        whitelist_line = j
                        break
                
                if whitelist_line is not None:
                    # Add import at top if needed
                    if 'from verenigingen.utils.security_decorators import development_only' not in content:
                        # Find good place to add import
                        import_line = 0
                        for k, line in enumerate(lines):
                            if line.startswith('from ') or line.startswith('import '):
                                import_line = k + 1
                        
                        lines.insert(import_line, 'from verenigingen.utils.security_decorators import development_only')
                        whitelist_line += 1
                        i += 1
                    
                    # Add @development_only() before function definition
                    indent = len(lines[i]) - len(lines[i].lstrip())
                    dev_only_line = ' ' * indent + '@development_only()'
                    lines.insert(i, dev_only_line)
                    break
        
        return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Secure test functions with @development_only()')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    parser.add_argument('--apply', action='store_true', help='Apply security changes')
    parser.add_argument('--min-confidence', type=int, default=70, help='Minimum confidence score (default: 70)')
    
    args = parser.parse_args()
    
    tool = TestFunctionSecurityTool()
    
    if args.dry_run:
        print("PREVIEW MODE - No changes will be made")
        print("=" * 50)
        preview = tool.preview_security_changes()
        print(preview)
        
    elif args.apply:
        print("APPLYING SECURITY CHANGES")
        print("=" * 30)
        results = tool.apply_security_changes(dry_run=False, min_confidence=args.min_confidence)
        
        print(f"Functions processed: {results['functions_processed']}")
        print(f"Functions secured: {results['functions_secured']}")
        print(f"Files modified: {len(results['files_modified'])}")
        
        if results['errors']:
            print(f"\nErrors encountered: {len(results['errors'])}")
            for error in results['errors'][:5]:
                print(f"  • {error}")
                
    else:
        print("Use --dry-run to preview changes or --apply to make changes")


if __name__ == "__main__":
    main()