#!/usr/bin/env python3
"""
Pre-commit Integration for Schema-Aware Validator

Provides seamless integration with existing pre-commit workflows while
maintaining backward compatibility and performance.
"""

import sys
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
import argparse
import time

# Add the validation directory to path
sys.path.insert(0, str(Path(__file__).parent))

from schema_aware_validator import SchemaAwareValidator, ValidationIssue
from validation_config import ConfigurationManager, ValidationLevel


class PreCommitValidator:
    """Pre-commit integration wrapper for the schema-aware validator"""
    
    def __init__(self, app_path: str, config_level: str = "balanced"):
        self.app_path = Path(app_path)
        self.config_manager = ConfigurationManager()
        
        # Load appropriate configuration for pre-commit
        try:
            level = ValidationLevel(config_level)
            self.config = self.config_manager.get_preset_config(level)
        except ValueError:
            print(f"⚠️  Unknown validation level '{config_level}', using balanced")
            self.config = self.config_manager.get_preset_config(ValidationLevel.BALANCED)
        
        # Adjust settings for pre-commit performance
        self.config.validation_rules.context_radius = 3  # Smaller for speed
        self.config.reporting_config.verbose_output = False
        self.config.reporting_config.max_issues_per_file = 10
        
        # Initialize validator
        self.validator = SchemaAwareValidator(
            app_path=str(self.app_path),
            min_confidence=self.config.confidence_thresholds.field_access,
            verbose=False
        )
    
    def validate_staged_files(self) -> List[ValidationIssue]:
        """Validate only staged Python files"""
        import subprocess
        
        try:
            # Get staged Python files
            result = subprocess.run(
                ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
                capture_output=True, text=True, cwd=self.app_path
            )
            
            if result.returncode != 0:
                print("⚠️  Could not get staged files, validating all files")
                return self.validator.validate_directory()
            
            staged_files = [
                line.strip() for line in result.stdout.strip().split('\n')
                if line.strip().endswith('.py')
            ]
            
            if not staged_files:
                return []
            
            print(f"🔍 Validating {len(staged_files)} staged Python files...")
            
            issues = []
            for file_path in staged_files:
                full_path = self.app_path / file_path
                if full_path.exists() and not self._should_skip_file(full_path):
                    file_issues = self.validator.validate_file(full_path)
                    issues.extend(file_issues)
            
            return issues
            
        except Exception as e:
            print(f"⚠️  Error getting staged files: {e}")
            print("   Falling back to directory validation")
            return self.validator.validate_directory()
    
    def validate_changed_files(self, base_ref: str = "HEAD~1") -> List[ValidationIssue]:
        """Validate files changed since a reference commit"""
        import subprocess
        
        try:
            # Get changed Python files
            result = subprocess.run(
                ['git', 'diff', '--name-only', f'{base_ref}...HEAD'],
                capture_output=True, text=True, cwd=self.app_path
            )
            
            if result.returncode != 0:
                print(f"⚠️  Could not get changed files since {base_ref}")
                return self.validator.validate_directory()
            
            changed_files = [
                line.strip() for line in result.stdout.strip().split('\n')
                if line.strip().endswith('.py')
            ]
            
            if not changed_files:
                return []
            
            print(f"🔍 Validating {len(changed_files)} changed Python files...")
            
            issues = []
            for file_path in changed_files:
                full_path = self.app_path / file_path
                if full_path.exists() and not self._should_skip_file(full_path):
                    file_issues = self.validator.validate_file(full_path)
                    issues.extend(file_issues)
            
            return issues
            
        except Exception as e:
            print(f"⚠️  Error getting changed files: {e}")
            return self.validator.validate_directory()
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped in pre-commit"""
        skip_patterns = self.config.exclusion_patterns.skip_file_patterns + [
            # Additional pre-commit specific patterns
            '/test_', '/tests/', '/fixtures/', '__init__.py'
        ]
        
        file_str = str(file_path)
        return any(pattern in file_str for pattern in skip_patterns)
    
    def generate_precommit_report(self, issues: List[ValidationIssue]) -> Dict[str, Any]:
        """Generate a pre-commit friendly report"""
        if not issues:
            return {
                'success': True,
                'message': "✅ Schema-aware validation passed",
                'issues_count': 0,
                'high_confidence_count': 0
            }
        
        # Categorize by confidence
        high_confidence = [i for i in issues if i.confidence >= 0.9]
        medium_confidence = [i for i in issues if 0.7 <= i.confidence < 0.9]
        
        # Group by file for better reporting
        by_file = {}
        for issue in issues:
            if issue.file_path not in by_file:
                by_file[issue.file_path] = []
            by_file[issue.file_path].append(issue)
        
        return {
            'success': len(high_confidence) == 0,  # Only fail on high confidence issues
            'issues_count': len(issues),
            'high_confidence_count': len(high_confidence),
            'medium_confidence_count': len(medium_confidence),
            'files_with_issues': len(by_file),
            'issues_by_file': by_file,
            'message': self._format_precommit_message(issues, high_confidence, by_file)
        }
    
    def _format_precommit_message(self, all_issues: List[ValidationIssue], 
                                 high_confidence: List[ValidationIssue],
                                 by_file: Dict[str, List[ValidationIssue]]) -> str:
        """Format a concise pre-commit message"""
        if not all_issues:
            return "✅ Schema-aware validation passed"
        
        lines = []
        
        if high_confidence:
            lines.append(f"❌ {len(high_confidence)} high-confidence field reference issues found:")
            
            # Show top 5 high confidence issues
            for issue in high_confidence[:5]:
                rel_path = str(Path(issue.file_path).relative_to(self.app_path))
                lines.append(f"   {rel_path}:{issue.line_number} - {issue.obj_name}.{issue.field_name}")
                lines.append(f"      {issue.message}")
            
            if len(high_confidence) > 5:
                lines.append(f"   ... and {len(high_confidence) - 5} more high-confidence issues")
            
            lines.append("")
            lines.append("🔧 To fix: Review field names in the highlighted DocTypes")
            
        else:
            lines.append(f"⚠️  {len(all_issues)} potential field issues found (low/medium confidence)")
            lines.append("   These may be false positives - review manually if needed")
            
            # Show files with most issues
            sorted_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)
            lines.append("   Files with most issues:")
            for file_path, file_issues in sorted_files[:3]:
                rel_path = str(Path(file_path).relative_to(self.app_path))
                lines.append(f"      {rel_path}: {len(file_issues)} issues")
        
        return '\n'.join(lines)


def create_precommit_hook():
    """Create a pre-commit hook script"""
    hook_content = '''#!/bin/bash
# Schema-Aware Field Validation Pre-commit Hook

# Change to the app directory
cd "$(dirname "$0")/../../.."

# Run the schema-aware validator on staged files
python scripts/validation/precommit_integration.py --staged --level balanced

# Exit with the validator's exit code
exit $?
'''
    
    hook_path = Path(".git/hooks/pre-commit")
    
    try:
        with open(hook_path, 'w') as f:
            f.write(hook_content)
        
        # Make executable
        import stat
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
        
        print(f"✅ Pre-commit hook created at {hook_path}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create pre-commit hook: {e}")
        return False


def update_precommit_config():
    """Update .pre-commit-config.yaml with schema-aware validator"""
    config_path = Path(".pre-commit-config.yaml")
    
    schema_validator_hook = """
  - repo: local
    hooks:
      - id: schema-aware-field-validator
        name: Schema-Aware Field Validator
        entry: python scripts/validation/precommit_integration.py --staged --level balanced
        language: system
        files: \\.py$
        pass_filenames: false
"""
    
    try:
        if config_path.exists():
            with open(config_path, 'r') as f:
                content = f.read()
            
            # Check if already present
            if 'schema-aware-field-validator' in content:
                print("✅ Schema-aware validator already in .pre-commit-config.yaml")
                return True
            
            # Add to existing config
            if 'repos:' in content:
                # Insert before the last repo or at the end
                lines = content.split('\n')
                insert_pos = len(lines)
                
                # Find a good insertion point
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip().startswith('- repo:'):
                        insert_pos = i
                        break
                
                # Insert the new hook
                hook_lines = schema_validator_hook.strip().split('\n')
                for j, line in enumerate(hook_lines):
                    lines.insert(insert_pos + j, line)
                
                content = '\n'.join(lines)
            else:
                # Create new config
                content = f"repos:{schema_validator_hook}"
            
            with open(config_path, 'w') as f:
                f.write(content)
            
            print(f"✅ Updated {config_path} with schema-aware validator")
            return True
        else:
            # Create new config file
            content = f"repos:{schema_validator_hook}"
            with open(config_path, 'w') as f:
                f.write(content)
            
            print(f"✅ Created {config_path} with schema-aware validator")
            return True
            
    except Exception as e:
        print(f"❌ Failed to update pre-commit config: {e}")
        return False


def main():
    """Main pre-commit integration function"""
    parser = argparse.ArgumentParser(description='Schema-Aware Validator Pre-commit Integration')
    parser.add_argument('--app-path', default='/home/frappe/frappe-bench/apps/verenigingen',
                       help='Path to the Frappe app')
    parser.add_argument('--level', default='balanced', 
                       choices=['strict', 'balanced', 'permissive'],
                       help='Validation level')
    parser.add_argument('--staged', action='store_true',
                       help='Validate only staged files (for pre-commit hook)')
    parser.add_argument('--changed', type=str, metavar='BASE_REF',
                       help='Validate files changed since BASE_REF (e.g., HEAD~1)')
    parser.add_argument('--setup-hook', action='store_true',
                       help='Set up pre-commit hook')
    parser.add_argument('--update-config', action='store_true',
                       help='Update .pre-commit-config.yaml')
    parser.add_argument('--timeout', type=int, default=120,
                       help='Timeout in seconds (default: 120)')
    
    args = parser.parse_args()
    
    # Setup operations
    if args.setup_hook:
        return 0 if create_precommit_hook() else 1
    
    if args.update_config:
        return 0 if update_precommit_config() else 1
    
    # Validation operations
    print("🔍 Schema-Aware Field Validator (Pre-commit Integration)")
    
    start_time = time.time()
    validator = PreCommitValidator(args.app_path, args.level)
    
    try:
        # Validate based on mode
        if args.staged:
            issues = validator.validate_staged_files()
        elif args.changed:
            issues = validator.validate_changed_files(args.changed)
        else:
            # Default: validate all files (not recommended for pre-commit)
            print("⚠️  No specific mode selected, validating all files")
            issues = validator.validator.validate_directory()
        
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > args.timeout:
            print(f"⚠️  Validation took {elapsed:.1f}s (timeout: {args.timeout}s)")
            print("   Consider using --staged or --changed for faster validation")
        
        # Generate report
        report = validator.generate_precommit_report(issues)
        
        # Print results
        print("\n" + "="*60)
        print(report['message'])
        
        if not report['success']:
            print(f"\n📊 Summary:")
            print(f"   Files with issues: {report['files_with_issues']}")
            print(f"   High confidence issues: {report['high_confidence_count']}")
            print(f"   Total potential issues: {report['issues_count']}")
            print(f"\n⏱️  Validation completed in {elapsed:.1f}s")
        
        # Exit with appropriate code
        return 0 if report['success'] else 1
        
    except KeyboardInterrupt:
        print("\n⚠️  Validation interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Validation failed with error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())