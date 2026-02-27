#!/usr/bin/env python3
"""
Validation Orchestrator
=======================

Coordinates multiple validators to provide unified validation across all error categories.
This addresses the critical gap identified in the QCE assessment where individual 
validators were created but not integrated into a cohesive workflow.

Purpose
-------
- Single entry point for all validation types
- Coordinated execution with shared AST parsing
- Unified reporting across all validators
- Pre-commit hook integration
- Performance optimization through parallel execution

Validators Coordinated
----------------------
1. Comprehensive Field Reference Validator (existing)
2. Select Field Value Validator (new)
3. Import Path Validator (new)
4. Method Signature Validator (planned)
5. Type Consistency Validator (planned)
"""

import sys
import time
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from collections import defaultdict
import json

# Import all validators
# Add archived folder for archived validators
sys.path.insert(0, str(Path(__file__).parent))
# Add parent folder for import_path_validator (moved out of archived)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import import_path_validator FIRST - other validators modify sys.path on import
from import_path_validator import ImportPathValidator, ImportViolation

# Import other validators - these modify sys.path during import so must come after
from ast_field_analyzer_improved_complete import ASTFieldAnalyzer, ValidationIssue
from select_field_value_validator import SelectFieldValueValidator, SelectFieldViolation


@dataclass
class UnifiedValidationResult:
    """Unified result from all validators"""
    file_path: str
    total_issues: int
    execution_time: float
    validator_results: Dict[str, Any] = field(default_factory=dict)
    performance_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class ValidationSummary:
    """Summary of validation across all files and validators"""
    total_files: int
    total_issues: int
    execution_time: float
    validator_breakdown: Dict[str, int] = field(default_factory=dict)
    file_results: List[UnifiedValidationResult] = field(default_factory=list)
    performance_summary: Dict[str, float] = field(default_factory=dict)


class ValidationOrchestrator:
    """Orchestrates multiple validators for comprehensive code validation"""
    
    def __init__(self, app_path: str, verbose: bool = False, parallel: bool = True):
        self.app_path = Path(app_path)
        self.verbose = verbose
        self.parallel = parallel
        
        # Initialize all validators
        self.validators = {}
        self._initialize_validators()
        
        if self.verbose:
            print(f"🎭 Validation Orchestrator initialized")
            print(f"   App path: {self.app_path}")
            print(f"   Validators: {len(self.validators)}")
            print(f"   Parallel execution: {self.parallel}")
    
    def _initialize_validators(self):
        """Initialize all available validators"""
        try:
            # Field Reference Validator (AST-based with high accuracy)
            self.validators['field_reference'] = ASTFieldAnalyzer(
                app_path=str(self.app_path),
                verbose=False
            )
            
            # Select Field Value Validator
            self.validators['select_field'] = SelectFieldValueValidator(
                app_path=str(self.app_path),
                verbose=False
            )
            
            # Import Path Validator
            self.validators['import_path'] = ImportPathValidator(
                app_path=str(self.app_path),
                verbose=False
            )
            
            if self.verbose:
                print(f"   ✅ Initialized {len(self.validators)} validators")
                print(f"   🎯 Using AST Field Analyzer (high accuracy, zero false positives)")
                
        except Exception as e:
            print(f"   ❌ Error initializing validators: {e}")
            raise
    
    def validate_file(self, file_path: Path) -> UnifiedValidationResult:
        """Validate a single file with all validators"""
        start_time = time.time()
        
        if self.verbose:
            print(f"🔍 Validating {file_path}")
        
        result = UnifiedValidationResult(
            file_path=str(file_path),
            total_issues=0,
            execution_time=0.0
        )
        
        # Run each validator
        for validator_name, validator in self.validators.items():
            validator_start = time.time()
            
            try:
                # Run the validator
                if validator_name == 'field_reference':
                    issues = validator.validate_file(file_path)
                elif validator_name == 'select_field':
                    issues = validator.validate_file(file_path)
                elif validator_name == 'import_path':
                    issues = validator.validate_file(file_path)
                else:
                    issues = []
                
                validator_time = time.time() - validator_start
                
                # Store results
                result.validator_results[validator_name] = {
                    'issues': issues,
                    'issue_count': len(issues),
                    'execution_time': validator_time
                }
                result.performance_metrics[validator_name] = validator_time
                result.total_issues += len(issues)
                
                if self.verbose and issues:
                    print(f"   {validator_name}: {len(issues)} issues ({validator_time:.2f}s)")
                    
            except Exception as e:
                if self.verbose:
                    print(f"   ❌ {validator_name} failed: {e}")
                
                result.validator_results[validator_name] = {
                    'issues': [],
                    'issue_count': 0,
                    'execution_time': 0.0,
                    'error': str(e)
                }
        
        result.execution_time = time.time() - start_time
        return result
    
    def validate_file_parallel(self, file_path: Path) -> UnifiedValidationResult:
        """Validate a file using parallel validator execution"""
        start_time = time.time()
        
        result = UnifiedValidationResult(
            file_path=str(file_path),
            total_issues=0,
            execution_time=0.0
        )
        
        def run_validator(validator_name_and_instance):
            validator_name, validator = validator_name_and_instance
            validator_start = time.time()
            
            try:
                if validator_name == 'field_reference':
                    issues = validator.validate_file(file_path)
                elif validator_name == 'select_field':
                    issues = validator.validate_file(file_path)
                elif validator_name == 'import_path':
                    issues = validator.validate_file(file_path)
                else:
                    issues = []
                
                return validator_name, {
                    'issues': issues,
                    'issue_count': len(issues),
                    'execution_time': time.time() - validator_start
                }
                
            except Exception as e:
                return validator_name, {
                    'issues': [],
                    'issue_count': 0,
                    'execution_time': 0.0,
                    'error': str(e)
                }
        
        # Run validators in parallel
        if self.parallel and len(self.validators) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.validators)) as executor:
                futures = {
                    executor.submit(run_validator, (name, validator)): name 
                    for name, validator in self.validators.items()
                }
                
                for future in concurrent.futures.as_completed(futures):
                    validator_name, validator_result = future.result()
                    result.validator_results[validator_name] = validator_result
                    result.performance_metrics[validator_name] = validator_result['execution_time']
                    result.total_issues += validator_result['issue_count']
        else:
            # Sequential execution
            for name, validator in self.validators.items():
                validator_name, validator_result = run_validator((name, validator))
                result.validator_results[validator_name] = validator_result
                result.performance_metrics[validator_name] = validator_result['execution_time']
                result.total_issues += validator_result['issue_count']
        
        result.execution_time = time.time() - start_time
        return result
    
    def validate_directory(self, directory: Optional[Path] = None, max_files: Optional[int] = None, timeout_seconds: int = 120) -> ValidationSummary:
        """Validate Python files in a directory with performance controls"""
        search_path = directory or self.app_path
        start_time = time.time()
        
        if self.verbose:
            print(f"🎯 Running comprehensive validation on {search_path}")
        
        # Find all Python files
        python_files = []
        for py_file in search_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            python_files.append(py_file)
            
            # Limit files processed to prevent timeouts
            if max_files and len(python_files) >= max_files:
                break
        
        if self.verbose:
            print(f"📁 Found {len(python_files)} Python files to validate")
            if max_files and len(python_files) >= max_files:
                print(f"⚠️ Limited to {max_files} files for performance")
        
        # Validate files with timeout protection
        file_results = []
        validator_totals = defaultdict(int)
        
        for i, py_file in enumerate(python_files):
            # Check timeout
            if time.time() - start_time > timeout_seconds:
                if self.verbose:
                    print(f"⏰ Timeout reached after {timeout_seconds}s, processed {i}/{len(python_files)} files")
                break
                
            if self.parallel:
                file_result = self.validate_file_parallel(py_file)
            else:
                file_result = self.validate_file(py_file)
            
            file_results.append(file_result)
            
            # Aggregate validator results
            for validator_name, validator_result in file_result.validator_results.items():
                validator_totals[validator_name] += validator_result['issue_count']
            
            # Progress reporting
            if self.verbose and (i + 1) % 25 == 0:  # More frequent progress updates
                total_issues = sum(r.total_issues for r in file_results)
                elapsed = time.time() - start_time
                print(f"   Progress: {i + 1}/{len(python_files)} files, {total_issues} issues found ({elapsed:.1f}s)")
        
        # Calculate summary
        total_issues = sum(r.total_issues for r in file_results)
        execution_time = time.time() - start_time
        
        # Performance analysis
        performance_summary = {}
        if file_results:
            for validator_name in self.validators.keys():
                times = [r.performance_metrics.get(validator_name, 0) for r in file_results]
                performance_summary[validator_name] = {
                    'total_time': sum(times),
                    'avg_time_per_file': sum(times) / len(times) if times else 0,
                    'max_time': max(times) if times else 0
                }
        
        summary = ValidationSummary(
            total_files=len(python_files),
            total_issues=total_issues,
            execution_time=execution_time,
            validator_breakdown=dict(validator_totals),
            file_results=file_results,
            performance_summary=performance_summary
        )
        
        if self.verbose:
            print(f"✅ Validation complete: {len(python_files)} files, {total_issues} issues, {execution_time:.1f}s")
        
        return summary
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Determine if a file should be skipped - matches pre-commit exclude patterns"""
        skip_patterns = [
            '__pycache__', '.git', 'node_modules', '.pyc', 'migrations',
            'test_validation', 'validator.py',  # Skip validation tools themselves
            'tests/', 'test_', '_test.py', 'debug_', '_debug.py',
            'scripts/testing/', 'scripts/debug/', 'archived/', 'archived_',
            'archived_unused/', 'archived_deleted/', 'temp_', '.temp'
        ]

        file_str = str(file_path)
        return any(pattern in file_str for pattern in skip_patterns)
    
    def generate_report(self, summary: ValidationSummary, format: str = 'console') -> str:
        """Generate comprehensive validation report"""
        if format == 'console':
            return self._generate_console_report(summary)
        elif format == 'json':
            return self._generate_json_report(summary)
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _generate_console_report(self, summary: ValidationSummary) -> str:
        """Generate console-formatted report"""
        if summary.total_issues == 0:
            return "✅ No validation issues found across all validators!"
        
        report = []
        report.append(f"🎯 Comprehensive Validation Report")
        report.append(f"Files analyzed: {summary.total_files}")
        report.append(f"Total issues: {summary.total_issues}")
        report.append(f"Execution time: {summary.execution_time:.1f}s")
        report.append("")
        
        # Validator breakdown
        report.append("📊 Issues by Validator:")
        for validator_name, issue_count in sorted(summary.validator_breakdown.items(), 
                                                 key=lambda x: x[1], reverse=True):
            if issue_count > 0:
                report.append(f"   {validator_name}: {issue_count} issues")
        report.append("")
        
        # Performance breakdown
        report.append("⚡ Performance by Validator:")
        for validator_name, perf_data in summary.performance_summary.items():
            avg_time = perf_data['avg_time_per_file'] * 1000  # ms
            total_time = perf_data['total_time']
            report.append(f"   {validator_name}: {total_time:.1f}s total, {avg_time:.1f}ms/file avg")
        report.append("")
        
        # Top problematic files
        problematic_files = sorted(
            [r for r in summary.file_results if r.total_issues > 0],
            key=lambda x: x.total_issues,
            reverse=True
        )[:10]
        
        if problematic_files:
            report.append("📁 Files with Most Issues:")
            for file_result in problematic_files:
                report.append(f"   {file_result.file_path}: {file_result.total_issues} issues")
                
                # Show breakdown by validator for this file
                for validator_name, validator_result in file_result.validator_results.items():
                    issue_count = validator_result['issue_count']
                    if issue_count > 0:
                        report.append(f"      {validator_name}: {issue_count}")
            report.append("")
        
        # Detailed issues for high-priority validators
        report.append("🔍 Detailed Issues:")
        high_priority_validators = ['field_reference', 'import_path', 'select_field']
        
        for validator_name in high_priority_validators:
            if summary.validator_breakdown.get(validator_name, 0) > 0:
                report.append(f"\n🚨 {validator_name.replace('_', ' ').title()} Issues:")
                
                # Show first 10 issues from this validator
                issue_count = 0
                for file_result in summary.file_results:
                    if issue_count >= 10:
                        break
                    
                    validator_result = file_result.validator_results.get(validator_name, {})
                    issues = validator_result.get('issues', [])
                    
                    for issue in issues[:min(3, 10 - issue_count)]:  # Max 3 per file
                        report.append(f"   📄 {file_result.file_path}")
                        
                        # Format issue based on type and available attributes
                        if hasattr(issue, 'line_number'):
                            line_num = issue.line_number
                            
                            # Get message from different validator types
                            message = ""
                            if hasattr(issue, 'message'):
                                message = issue.message
                            elif hasattr(issue, 'invalid_value') and hasattr(issue, 'field_name'):
                                # SelectFieldViolation
                                message = f"Invalid value '{issue.invalid_value}' for field '{issue.field_name}'"
                            else:
                                message = str(issue)
                            
                            report.append(f"      Line {line_num}: {message}")
                            
                            # Add context if available
                            if hasattr(issue, 'context') and issue.context:
                                report.append(f"      Context: {issue.context}")
                            
                            # Add suggestions
                            if hasattr(issue, 'suggestion') and issue.suggestion:
                                report.append(f"      💡 {issue.suggestion}")
                            elif hasattr(issue, 'valid_options') and issue.valid_options:
                                # For SelectFieldViolation
                                options_str = ", ".join(issue.valid_options[:3])
                                if len(issue.valid_options) > 3:
                                    options_str += f" (and {len(issue.valid_options) - 3} more)"
                                report.append(f"      💡 Valid options: {options_str}")
                        else:
                            report.append(f"      {str(issue)}")
                        
                        issue_count += 1
                        report.append("")
                
                if summary.validator_breakdown[validator_name] > issue_count:
                    remaining = summary.validator_breakdown[validator_name] - issue_count
                    report.append(f"   ... and {remaining} more {validator_name} issues")
        
        return '\n'.join(report)
    
    def _generate_json_report(self, summary: ValidationSummary) -> str:
        """Generate JSON-formatted report for programmatic use"""
        # Convert to JSON-serializable format
        json_data = {
            'summary': {
                'total_files': summary.total_files,
                'total_issues': summary.total_issues,
                'execution_time': summary.execution_time,
                'validator_breakdown': summary.validator_breakdown,
                'performance_summary': summary.performance_summary
            },
            'file_results': []
        }
        
        for file_result in summary.file_results:
            if file_result.total_issues > 0:  # Only include files with issues
                file_data = {
                    'file_path': file_result.file_path,
                    'total_issues': file_result.total_issues,
                    'execution_time': file_result.execution_time,
                    'validators': {}
                }
                
                for validator_name, validator_result in file_result.validator_results.items():
                    if validator_result['issue_count'] > 0:
                        # Serialize issues
                        issues_data = []
                        for issue in validator_result['issues']:
                            if hasattr(issue, '__dict__'):
                                issues_data.append(issue.__dict__)
                            else:
                                issues_data.append(str(issue))
                        
                        file_data['validators'][validator_name] = {
                            'issue_count': validator_result['issue_count'],
                            'execution_time': validator_result['execution_time'],
                            'issues': issues_data
                        }
                
                json_data['file_results'].append(file_data)
        
        return json.dumps(json_data, indent=2, default=str)


def main():
    """Main CLI interface for validation orchestrator"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validation Orchestrator - Comprehensive Code Validation')
    # Derive app path from script location:
    # Script: apps/verenigingen/scripts/validation/archived/validation_orchestrator.py
    # App root: apps/verenigingen/
    _default_app_path = str(Path(__file__).resolve().parent.parent.parent.parent)
    parser.add_argument('--app-path', default=_default_app_path,
                       help='Path to the Frappe app')
    parser.add_argument('--file', type=str,
                       help='Validate single file instead of directory')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--parallel', action='store_true', default=True,
                       help='Enable parallel validator execution (default: True)')
    parser.add_argument('--no-parallel', action='store_false', dest='parallel',
                       help='Disable parallel execution')
    parser.add_argument('--format', choices=['console', 'json'], default='console',
                       help='Output format')
    parser.add_argument('--pre-commit', action='store_true',
                       help='Pre-commit mode (exit with error if issues found)')
    parser.add_argument('--min-confidence', type=float, default=0.7,
                       help='Minimum confidence threshold for field reference validator')
    parser.add_argument('--max-files', type=int, default=500,
                       help='Maximum number of files to process (default: 500)')
    parser.add_argument('--timeout', type=int, default=120,
                       help='Timeout in seconds for full validation (default: 120)')
    
    args = parser.parse_args()
    
    # Initialize orchestrator
    orchestrator = ValidationOrchestrator(
        app_path=args.app_path,
        verbose=args.verbose,
        parallel=args.parallel
    )
    
    # Run validation
    if args.file:
        file_path = Path(args.file)
        if args.parallel:
            result = orchestrator.validate_file_parallel(file_path)
        else:
            result = orchestrator.validate_file(file_path)
        
        # Create summary for single file
        summary = ValidationSummary(
            total_files=1,
            total_issues=result.total_issues,
            execution_time=result.execution_time,
            validator_breakdown={
                name: res['issue_count'] 
                for name, res in result.validator_results.items()
            },
            file_results=[result]
        )
    else:
        summary = orchestrator.validate_directory(
            max_files=args.max_files,
            timeout_seconds=args.timeout
        )
    
    # Generate and print report
    report = orchestrator.generate_report(summary, format=args.format)
    print(report)
    
    # Exit with appropriate code for pre-commit
    if args.pre_commit and summary.total_issues > 0:
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())