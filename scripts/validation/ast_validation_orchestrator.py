#!/usr/bin/env python3
"""
AST-Based Validation Orchestrator
=================================

Clean architectural solution that uses the superior AST field analyzer as the 
primary validator instead of the basic field validator + post-processing filters.

This eliminates the "generate garbage, then clean it up" anti-pattern by using
high-accuracy validation upfront.

Architecture:
- AST Field Analyzer (primary, high-accuracy validator)
- Select Field Validator (for enum validation)
- Import Path Validator (for import validation)
- Unified result aggregation and reporting
"""

import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from collections import defaultdict
import json

# Import validation components
sys.path.insert(0, str(Path(__file__).parent))

# Import the superior AST analyzer
from ast_field_analyzer_improved_complete import ASTFieldAnalyzer

# Import other validators that don't have architectural issues
from select_field_value_validator import SelectFieldValueValidator, SelectFieldViolation
from import_path_validator import ImportPathValidator, ImportViolation

@dataclass
class ASTValidationResult:
    """Clean validation result structure"""
    file_path: str
    total_issues: int
    execution_time: float
    validator_results: Dict[str, Dict] = field(default_factory=dict)

@dataclass
class ValidationSummary:
    """Clean validation summary"""
    total_files_analyzed: int = 0
    total_issues: int = 0
    execution_time: float = 0.0
    validator_performance: Dict[str, float] = field(default_factory=dict)
    issues_by_type: Dict[str, int] = field(default_factory=dict)
    issues_by_file: List[Dict] = field(default_factory=list)

class ASTValidationOrchestrator:
    """Clean orchestrator using AST analyzer as primary validator"""
    
    def __init__(self, app_path: str, verbose: bool = True):
        self.app_path = Path(app_path)
        self.verbose = verbose
        self.validators = {}
        self._initialize_validators()
    
    def _initialize_validators(self):
        """Initialize validators with AST analyzer as primary"""
        try:
            # Primary: AST Field Analyzer (high accuracy)
            self.validators['field_reference'] = ASTFieldAnalyzer(
                app_path=str(self.app_path),
                verbose=False  # Reduce noise in batch mode
            )
            
            # Secondary: Select field validator
            self.validators['select_field'] = SelectFieldValueValidator(
                app_path=str(self.app_path),
                verbose=False
            )
            
            # Tertiary: Import path validator
            self.validators['import_path'] = ImportPathValidator(
                app_path=str(self.app_path),
                verbose=False
            )
            
            if self.verbose:
                print(f"✅ Initialized {len(self.validators)} validators")
                print(f"   🎯 Primary: AST Field Analyzer (high accuracy)")
                print(f"   📋 Secondary: Select Field Validator")
                print(f"   📦 Tertiary: Import Path Validator")
                
        except Exception as e:
            print(f"❌ Error initializing validators: {e}")
            raise
    
    def validate_file(self, file_path: Path) -> ASTValidationResult:
        """Validate single file with all validators"""
        start_time = time.time()
        
        if self.verbose:
            print(f"🔍 Validating {file_path}")
        
        result = ASTValidationResult(
            file_path=str(file_path),
            total_issues=0,
            execution_time=0.0
        )
        
        # Run each validator
        for validator_name, validator in self.validators.items():
            validator_start = time.time()
            
            try:
                if validator_name == 'field_reference':
                    # Use AST analyzer
                    issues = validator.validate_file(file_path)
                    result.validator_results[validator_name] = {
                        'issues': issues,
                        'count': len(issues),
                        'execution_time': time.time() - validator_start
                    }
                    result.total_issues += len(issues)
                    
                elif validator_name == 'select_field':
                    # Use select field validator
                    violations = validator.validate_file(file_path)
                    result.validator_results[validator_name] = {
                        'issues': violations,
                        'count': len(violations),
                        'execution_time': time.time() - validator_start
                    }
                    result.total_issues += len(violations)
                    
                elif validator_name == 'import_path':
                    # Use import path validator
                    violations = validator.validate_file(file_path)
                    result.validator_results[validator_name] = {
                        'issues': violations,
                        'count': len(violations),
                        'execution_time': time.time() - validator_start
                    }
                    result.total_issues += len(violations)
                
            except Exception as e:
                if self.verbose:
                    print(f"   ⚠️  {validator_name} error: {str(e)}")
                result.validator_results[validator_name] = {
                    'issues': [],
                    'count': 0,
                    'execution_time': time.time() - validator_start,
                    'error': str(e)
                }
        
        result.execution_time = time.time() - start_time
        return result
    
    def validate_files(self, file_paths: List[Path]) -> ValidationSummary:
        """Validate multiple files and generate summary"""
        start_time = time.time()
        
        if self.verbose:
            print(f"🎯 AST-Based Validation Suite")
            print(f"📂 Analyzing {len(file_paths)} files...")
        
        summary = ValidationSummary()
        all_results = []
        
        for file_path in file_paths:
            try:
                result = self.validate_file(file_path)
                all_results.append(result)
                summary.total_issues += result.total_issues
                
                # Track issues by type
                for validator_name, validator_result in result.validator_results.items():
                    issue_count = validator_result['count']
                    summary.issues_by_type[validator_name] = summary.issues_by_type.get(validator_name, 0) + issue_count
                    
                    # Track validator performance
                    exec_time = validator_result['execution_time']
                    summary.validator_performance[validator_name] = summary.validator_performance.get(validator_name, 0.0) + exec_time
                
                # Track files with issues
                if result.total_issues > 0:
                    file_summary = {
                        'file_path': str(file_path),
                        'total_issues': result.total_issues,
                        'issues_by_type': {}
                    }
                    for validator_name, validator_result in result.validator_results.items():
                        if validator_result['count'] > 0:
                            file_summary['issues_by_type'][validator_name] = validator_result['count']
                    
                    summary.issues_by_file.append(file_summary)
                    
            except Exception as e:
                if self.verbose:
                    print(f"   ❌ Error validating {file_path}: {str(e)}")
        
        summary.total_files_analyzed = len(file_paths)
        summary.execution_time = time.time() - start_time
        
        if self.verbose:
            self._print_summary(summary)
        
        return summary
    
    def _print_summary(self, summary: ValidationSummary):
        """Print clean validation summary"""
        print(f"\n🎯 AST-Based Validation Report")
        print(f"Files analyzed: {summary.total_files_analyzed}")
        print(f"Total issues: {summary.total_issues}")
        print(f"Execution time: {summary.execution_time:.1f}s")
        
        if summary.issues_by_type:
            print(f"\n📊 Issues by Validator:")
            for validator_name, count in summary.issues_by_type.items():
                print(f"   {validator_name}: {count} issues")
        
        if summary.validator_performance:
            print(f"\n⚡ Performance by Validator:")
            for validator_name, total_time in summary.validator_performance.items():
                files_count = summary.total_files_analyzed
                avg_time = (total_time / files_count * 1000) if files_count > 0 else 0
                print(f"   {validator_name}: {total_time:.1f}s total, {avg_time:.1f}ms/file avg")
        
        if summary.issues_by_file:
            print(f"\n📁 Files with Most Issues:")
            # Sort by issue count and show top 10
            sorted_files = sorted(summary.issues_by_file, key=lambda x: x['total_issues'], reverse=True)
            for file_info in sorted_files[:10]:
                print(f"   {file_info['file_path']}: {file_info['total_issues']} issues")
                for validator_name, count in file_info['issues_by_type'].items():
                    print(f"      {validator_name}: {count}")

def main():
    """Main entry point for AST-based validation"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AST-Based Validation Orchestrator')
    parser.add_argument('--app-path', default='/home/frappe/frappe-bench/apps/verenigingen', 
                        help='Path to the Frappe app')
    parser.add_argument('--file-patterns', nargs='+', 
                        default=['**/*.py'], 
                        help='File patterns to validate')
    parser.add_argument('--verbose', action='store_true', 
                        help='Verbose output')
    
    args = parser.parse_args()
    
    app_path = Path(args.app_path)
    if not app_path.exists():
        print(f"❌ App path does not exist: {app_path}")
        sys.exit(1)
    
    # Collect files to validate
    all_files = []
    for pattern in args.file_patterns:
        files = list(app_path.glob(pattern))
        # Filter out common non-application files
        filtered_files = [
            f for f in files 
            if f.is_file() and 
            'migrations' not in str(f) and 
            '__pycache__' not in str(f) and
            '.pyc' not in f.suffix
        ]
        all_files.extend(filtered_files)
    
    # Remove duplicates and sort
    all_files = sorted(list(set(all_files)))
    
    if not all_files:
        print("❌ No files found to validate")
        sys.exit(1)
    
    # Run validation
    orchestrator = ASTValidationOrchestrator(
        app_path=str(app_path),
        verbose=args.verbose
    )
    
    summary = orchestrator.validate_files(all_files)
    
    # Exit code based on results
    sys.exit(1 if summary.total_issues > 0 else 0)

if __name__ == '__main__':
    main()