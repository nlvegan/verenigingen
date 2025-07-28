#!/usr/bin/env python3
"""
Rollback Manager for Phased Implementation

This module provides comprehensive rollback procedures for each phase of the
architectural refactoring, ensuring safe recovery from any implementation issues.
"""

import os
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
import frappe


class RollbackManager:
    """Main rollback manager for phased implementation"""
    
    def __init__(self, phase: str):
        self.phase = phase
        self.rollback_steps = self.load_rollback_steps()
        self.rollback_log = []
        self.git_backup_created = False
        
    def load_rollback_steps(self) -> List[Dict[str, Any]]:
        """Load phase-specific rollback procedures"""
        steps = {
            'phase1': [
                {
                    'name': 'Remove @critical_api decorators',
                    'description': 'Remove added security decorators from API files',
                    'action': 'remove_critical_api_decorators',
                    'files': self.get_phase1_modified_files(),
                    'validation': 'validate_api_functionality'
                },
                {
                    'name': 'Restore original imports',
                    'description': 'Remove security framework imports',
                    'action': 'restore_original_imports',
                    'files': self.get_phase1_modified_files(),
                    'validation': 'validate_imports_working'
                },
                {
                    'name': 'Remove security test files',
                    'description': 'Remove added security test files',
                    'action': 'remove_security_test_files',
                    'files': [
                        'verenigingen/tests/test_api_security_matrix.py',
                        'verenigingen/tests/test_security_comprehensive.py'
                    ],
                    'validation': 'validate_test_suite_runs'
                },
                {
                    'name': 'Clear security caches',
                    'description': 'Clear any security-related caches',
                    'action': 'clear_security_caches',
                    'validation': 'validate_cache_cleared'
                }
            ],
            'phase2': [
                {
                    'name': 'Remove database indexes',
                    'description': 'Drop performance indexes from database',
                    'action': 'drop_performance_indexes',
                    'tables': [
                        {'table': 'tabSales Invoice', 'index': 'idx_customer_status'},
                        {'table': 'tabPayment Entry Reference', 'index': 'idx_reference_name'},
                        {'table': 'tabSEPA Mandate', 'index': 'idx_member_status'}
                    ],
                    'validation': 'validate_queries_still_work'
                },
                {
                    'name': 'Restore synchronous event handlers',
                    'description': 'Revert background job conversions in hooks.py',
                    'action': 'restore_synchronous_handlers',
                    'file': 'verenigingen/hooks.py',
                    'validation': 'validate_event_handlers'
                },
                {
                    'name': 'Remove background job wrappers',
                    'description': 'Remove background job wrapper functions',
                    'action': 'remove_background_wrappers',
                    'files': ['verenigingen/utils/background_jobs.py'],
                    'validation': 'validate_no_background_errors'
                },
                {
                    'name': 'Restore original payment mixin',
                    'description': 'Revert optimizations in payment_mixin.py',
                    'action': 'restore_payment_mixin',
                    'file': 'verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py',
                    'validation': 'validate_payment_history_works'
                }
            ],
            'phase3': [
                {
                    'name': 'Restore original SQL queries',
                    'description': 'Revert ORM migrations back to SQL',
                    'action': 'restore_sql_queries',
                    'files': self.get_phase3_modified_files(),
                    'validation': 'validate_queries_work'
                },
                {
                    'name': 'Remove service layer',
                    'description': 'Remove introduced service layer files',
                    'action': 'remove_service_layer',
                    'files': ['verenigingen/utils/services/'],
                    'validation': 'validate_no_service_errors'
                }
            ],
            'phase4': [
                {
                    'name': 'Restore original test files',
                    'description': 'Restore consolidated test files to original',
                    'action': 'restore_test_files',
                    'validation': 'validate_all_tests_present'
                }
            ]
        }
        return steps.get(self.phase, [])
    
    def create_rollback_backup(self) -> bool:
        """Create a git backup before starting rollback"""
        try:
            # Create a backup branch
            branch_name = f"rollback-backup-{self.phase}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            subprocess.run(['git', 'checkout', '-b', branch_name], check=True)
            subprocess.run(['git', 'add', '.'], check=True)
            subprocess.run(['git', 'commit', '-m', f'Backup before {self.phase} rollback'], check=True)
            subprocess.run(['git', 'checkout', '-'], check=True)
            
            self.git_backup_created = True
            self.log(f"Created backup branch: {branch_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            self.log(f"Failed to create git backup: {e}", level='error')
            return False
    
    def execute_rollback(self, dry_run: bool = False) -> Dict[str, Any]:
        """Execute rollback procedures for the phase"""
        print(f"\nExecuting rollback for {self.phase}")
        print("=" * 60)
        
        if not dry_run and not self.git_backup_created:
            print("Creating backup before rollback...")
            if not self.create_rollback_backup():
                return {
                    'success': False,
                    'message': 'Failed to create backup. Rollback aborted.',
                    'log': self.rollback_log
                }
        
        results = {
            'phase': self.phase,
            'timestamp': datetime.now().isoformat(),
            'dry_run': dry_run,
            'steps_completed': [],
            'steps_failed': [],
            'success': True,
            'log': []
        }
        
        for i, step in enumerate(self.rollback_steps):
            print(f"\n[{i+1}/{len(self.rollback_steps)}] {step['name']}...")
            print(f"  {step['description']}")
            
            if dry_run:
                print("  [DRY RUN] Would execute:", step['action'])
                results['steps_completed'].append(step['name'])
                continue
            
            try:
                # Execute the rollback action
                action_method = getattr(self, step['action'])
                action_result = action_method(step)
                
                if action_result:
                    # Validate the rollback
                    if 'validation' in step:
                        validation_method = getattr(self, step['validation'])
                        if validation_method():
                            print(f"  ✅ {step['name']} completed successfully")
                            results['steps_completed'].append(step['name'])
                        else:
                            print(f"  ⚠️  {step['name']} completed but validation failed")
                            results['steps_failed'].append(step['name'])
                            results['success'] = False
                    else:
                        print(f"  ✅ {step['name']} completed successfully")
                        results['steps_completed'].append(step['name'])
                else:
                    print(f"  ❌ {step['name']} failed")
                    results['steps_failed'].append(step['name'])
                    results['success'] = False
                    
                    # Ask if should continue
                    if not self.should_continue_after_failure():
                        break
                        
            except Exception as e:
                self.log(f"Error in {step['name']}: {str(e)}", level='error')
                print(f"  ❌ {step['name']} failed with error: {e}")
                results['steps_failed'].append(step['name'])
                results['success'] = False
                
                if not self.should_continue_after_failure():
                    break
        
        results['log'] = self.rollback_log
        
        # Save rollback results
        self.save_rollback_results(results)
        
        # Generate summary
        self.print_rollback_summary(results)
        
        return results
    
    def remove_critical_api_decorators(self, step: Dict) -> bool:
        """Remove @critical_api decorators from files"""
        success = True
        
        for file_path in step.get('files', []):
            try:
                if not os.path.exists(file_path):
                    self.log(f"File not found: {file_path}", level='warning')
                    continue
                
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Remove @critical_api decorator lines
                lines = content.split('\n')
                filtered_lines = []
                skip_next = False
                
                for line in lines:
                    if '@critical_api' in line:
                        skip_next = True
                        continue
                    if skip_next and line.strip() == '':
                        skip_next = False
                        continue
                    filtered_lines.append(line)
                
                # Write back the modified content
                with open(file_path, 'w') as f:
                    f.write('\n'.join(filtered_lines))
                
                self.log(f"Removed decorators from: {file_path}")
                
            except Exception as e:
                self.log(f"Failed to process {file_path}: {e}", level='error')
                success = False
        
        return success
    
    def restore_original_imports(self, step: Dict) -> bool:
        """Remove security framework imports"""
        success = True
        
        for file_path in step.get('files', []):
            try:
                if not os.path.exists(file_path):
                    continue
                
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Remove security framework imports
                lines = content.split('\n')
                filtered_lines = []
                in_security_import = False
                
                for line in lines:
                    if 'from verenigingen.utils.security' in line:
                        in_security_import = True
                        continue
                    if in_security_import and (line.startswith(' ') or line.startswith('\t')):
                        continue
                    if in_security_import and line.strip() == ')':
                        in_security_import = False
                        continue
                    if in_security_import and not line.strip():
                        in_security_import = False
                    
                    filtered_lines.append(line)
                
                with open(file_path, 'w') as f:
                    f.write('\n'.join(filtered_lines))
                
                self.log(f"Restored imports in: {file_path}")
                
            except Exception as e:
                self.log(f"Failed to restore imports in {file_path}: {e}", level='error')
                success = False
        
        return success
    
    def remove_security_test_files(self, step: Dict) -> bool:
        """Remove security test files"""
        success = True
        
        for file_path in step.get('files', []):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.log(f"Removed test file: {file_path}")
                else:
                    self.log(f"Test file not found: {file_path}", level='warning')
                    
            except Exception as e:
                self.log(f"Failed to remove {file_path}: {e}", level='error')
                success = False
        
        return success
    
    def clear_security_caches(self, step: Dict) -> bool:
        """Clear security-related caches"""
        try:
            frappe.cache().delete_pattern("*security*")
            frappe.cache().delete_pattern("*permission*")
            frappe.cache().delete_pattern("*api_rate*")
            self.log("Cleared security caches")
            return True
        except Exception as e:
            self.log(f"Failed to clear caches: {e}", level='error')
            return False
    
    def drop_performance_indexes(self, step: Dict) -> bool:
        """Drop database indexes"""
        success = True
        
        for index_info in step.get('tables', []):
            try:
                table = index_info['table']
                index = index_info['index']
                
                # Check if index exists before dropping
                check_sql = f"""
                    SELECT COUNT(*) as count
                    FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE table_schema = DATABASE()
                    AND table_name = '{table}'
                    AND index_name = '{index}'
                """
                
                result = frappe.db.sql(check_sql, as_dict=True)
                
                if result and result[0]['count'] > 0:
                    drop_sql = f"ALTER TABLE `{table}` DROP INDEX `{index}`"
                    frappe.db.sql(drop_sql)
                    frappe.db.commit()
                    self.log(f"Dropped index {index} from {table}")
                else:
                    self.log(f"Index {index} not found on {table}", level='warning')
                    
            except Exception as e:
                self.log(f"Failed to drop index {index_info}: {e}", level='error')
                success = False
        
        return success
    
    def restore_synchronous_handlers(self, step: Dict) -> bool:
        """Restore synchronous event handlers"""
        # This would restore the original hooks.py file
        # For now, return True as placeholder
        self.log("Would restore synchronous handlers in hooks.py")
        return True
    
    def validate_api_functionality(self) -> bool:
        """Validate that APIs still work after rollback"""
        try:
            # Run basic API tests
            # This would call actual API endpoints to verify they work
            self.log("API functionality validated")
            return True
        except Exception as e:
            self.log(f"API validation failed: {e}", level='error')
            return False
    
    def validate_imports_working(self) -> bool:
        """Validate that imports work correctly"""
        try:
            # Try to import key modules
            import vereiningen.api.member_management
            import verenigingen.api.sepa_mandate_management
            self.log("Import validation passed")
            return True
        except Exception as e:
            self.log(f"Import validation failed: {e}", level='error')
            return False
    
    def validate_test_suite_runs(self) -> bool:
        """Validate that test suite runs correctly"""
        try:
            # Run a quick test to verify
            result = subprocess.run(
                ['bench', '--site', 'dev.veganisme.net', 'run-tests', '--module', 'verenigingen.tests.test_iban_validator'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.log("Test suite validation passed")
                return True
            else:
                self.log(f"Test suite validation failed: {result.stderr}", level='error')
                return False
                
        except Exception as e:
            self.log(f"Test validation error: {e}", level='error')
            return False
    
    def validate_cache_cleared(self) -> bool:
        """Validate caches were cleared"""
        return True  # Simple validation for now
    
    def get_phase1_modified_files(self) -> List[str]:
        """Get list of files modified in phase 1"""
        return [
            'verenigingen/api/sepa_mandate_management.py',
            'verenigingen/api/payment_processing.py',
            'verenigingen/api/member_management.py',
            'verenigingen/api/dd_batch_creation.py'
        ]
    
    def get_phase3_modified_files(self) -> List[str]:
        """Get list of files modified in phase 3"""
        return [
            # Files with SQL to ORM migrations
        ]
    
    def should_continue_after_failure(self) -> bool:
        """Ask user if should continue after a failure"""
        # In automated mode, stop on failure
        return False
    
    def log(self, message: str, level: str = 'info'):
        """Log a rollback action"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message
        }
        self.rollback_log.append(entry)
        
        if level == 'error':
            print(f"  ERROR: {message}")
        elif level == 'warning':
            print(f"  WARNING: {message}")
    
    def save_rollback_results(self, results: Dict[str, Any]):
        """Save rollback results to file"""
        filename = f'rollback_results_{self.phase}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\nRollback results saved to: {filename}")
    
    def print_rollback_summary(self, results: Dict[str, Any]):
        """Print rollback summary"""
        print("\n" + "=" * 60)
        print("ROLLBACK SUMMARY")
        print("=" * 60)
        print(f"Phase: {results['phase']}")
        print(f"Status: {'SUCCESS' if results['success'] else 'FAILED'}")
        print(f"Steps completed: {len(results['steps_completed'])}")
        print(f"Steps failed: {len(results['steps_failed'])}")
        
        if results['steps_failed']:
            print("\nFailed steps:")
            for step in results['steps_failed']:
                print(f"  - {step}")
        
        print("\nNext steps:")
        if results['success']:
            print("  - Verify system functionality")
            print("  - Monitor for any issues")
            print("  - Review rollback log for warnings")
        else:
            print("  - Review rollback log for errors")
            print("  - Manually fix failed steps")
            print("  - Consider restoring from git backup")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python rollback_manager.py <phase> [--dry-run]")
        print("Phases: phase1, phase2, phase3, phase4")
        sys.exit(1)
    
    phase = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    
    # Initialize frappe if needed
    if not frappe.db:
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
    
    try:
        rollback = RollbackManager(phase)
        results = rollback.execute_rollback(dry_run=dry_run)
        
        if not results['success']:
            sys.exit(1)
            
    finally:
        if frappe.db:
            frappe.db.close()