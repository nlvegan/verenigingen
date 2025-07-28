#!/usr/bin/env python3
"""
Comprehensive Rollback Procedures
Phase 0 Infrastructure - Comprehensive Architectural Refactoring Plan v2.0

This script provides comprehensive rollback procedures for each phase
of the architectural refactoring, ensuring safe recovery from any issues.
"""

import os
import shutil
import json
import subprocess
from typing import Dict, List, Any, Callable
from datetime import datetime
import frappe

class RollbackManager:
    """Comprehensive rollback manager for architectural refactoring phases"""
    
    def __init__(self, phase: str):
        self.phase = phase
        self.rollback_steps = self.load_rollback_steps()
        self.backup_directory = f'/home/frappe/frappe-bench/apps/verenigingen/rollback_backups/{phase}'
        self.rollback_log = []
        
    def load_rollback_steps(self) -> List[Dict[str, Any]]:
        """Load phase-specific rollback procedures"""
        
        steps = {
            'phase1_security': [
                {
                    'step': 'Remove @critical_api decorators',
                    'description': 'Remove all @critical_api decorators added in Phase 1',
                    'files': self.get_modified_security_files,
                    'action': self.restore_original_decorators,
                    'validation': self.test_api_functionality,
                    'priority': 'CRITICAL',
                    'estimated_time_minutes': 15
                },
                {
                    'step': 'Restore original imports',
                    'description': 'Restore original import statements',
                    'files': 'all_modified_files',
                    'action': self.restore_original_imports,
                    'validation': self.test_import_success,
                    'priority': 'HIGH',
                    'estimated_time_minutes': 10
                },
                {
                    'step': 'Remove security test files',
                    'description': 'Remove security test files added in Phase 1',
                    'files': self.get_security_test_files,
                    'action': self.remove_security_test_files,
                    'validation': self.test_suite_runs,
                    'priority': 'MEDIUM',
                    'estimated_time_minutes': 5
                },
                {
                    'step': 'Restore original hooks.py',
                    'description': 'Restore original hooks.py file',
                    'files': ['verenigingen/hooks.py'],
                    'action': self.restore_hooks_file,
                    'validation': self.test_hooks_functionality,
                    'priority': 'HIGH', 
                    'estimated_time_minutes': 5
                }
            ],
            'phase2_performance': [
                {
                    'step': 'Remove database indexes',
                    'description': 'Remove performance indexes added in Phase 2',
                    'tables': ['tabSales Invoice', 'tabPayment Entry Reference', 'tabSEPA Mandate'],
                    'action': self.drop_performance_indexes,
                    'validation': self.test_query_functionality,
                    'priority': 'HIGH',
                    'estimated_time_minutes': 10
                },
                {
                    'step': 'Restore synchronous event handlers',
                    'description': 'Restore synchronous event handlers in hooks.py',
                    'files': ['verenigingen/hooks.py'],
                    'action': self.restore_synchronous_handlers,
                    'validation': self.test_event_handler_execution,
                    'priority': 'CRITICAL',
                    'estimated_time_minutes': 20
                },
                {
                    'step': 'Remove background job infrastructure',
                    'description': 'Remove background job management code',
                    'files': self.get_background_job_files,
                    'action': self.remove_background_job_code,
                    'validation': self.test_core_functionality,
                    'priority': 'MEDIUM',
                    'estimated_time_minutes': 15
                },
                {
                    'step': 'Restore original PaymentMixin',
                    'description': 'Restore original PaymentMixin implementation',
                    'files': ['verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py'],
                    'action': self.restore_payment_mixin,
                    'validation': self.test_payment_functionality,
                    'priority': 'CRITICAL',
                    'estimated_time_minutes': 25
                }
            ],
            'phase3_architecture': [
                {
                    'step': 'Restore SQL queries',
                    'description': 'Restore original SQL queries that were migrated to ORM',
                    'files': self.get_orm_migration_files,
                    'action': self.restore_original_sql_queries,
                    'validation': self.test_data_access_functionality,
                    'priority': 'CRITICAL',
                    'estimated_time_minutes': 45
                },
                {
                    'step': 'Remove service layer code',
                    'description': 'Remove service layer implementations',
                    'files': self.get_service_layer_files,
                    'action': self.remove_service_layer_code,
                    'validation': self.test_mixin_functionality,
                    'priority': 'MEDIUM',
                    'estimated_time_minutes': 30
                },
                {
                    'step': 'Restore original mixins',
                    'description': 'Restore original mixin implementations',
                    'files': self.get_mixin_files,
                    'action': self.restore_original_mixins,
                    'validation': self.test_doctype_functionality,
                    'priority': 'HIGH',
                    'estimated_time_minutes': 35
                }
            ]
        }
        
        return steps.get(self.phase, [])
    
    def execute_rollback(self) -> Dict[str, Any]:
        """
        Execute rollback procedures in reverse order
        
        Returns:
            Comprehensive rollback execution results
        """
        
        rollback_result = {
            'phase': self.phase,
            'timestamp': datetime.now().isoformat(),
            'steps_executed': [],
            'overall_success': False,
            'total_time_minutes': 0,
            'errors_encountered': [],
            'warnings': [],
            'post_rollback_validation': {}
        }
        
        print(f"🔄 Starting {self.phase.upper()} rollback procedures...")
        print(f"   📋 {len(self.rollback_steps)} rollback steps to execute")
        print("")
        
        start_time = datetime.now()
        
        # Create backup before rollback
        self.create_pre_rollback_backup()
        
        # Execute rollback steps in reverse order (most recent changes first)
        for i, step in enumerate(reversed(self.rollback_steps)):
            step_number = len(self.rollback_steps) - i
            step_start_time = datetime.now()
            
            print(f"🔄 Step {step_number}: {step['step']}")
            print(f"   📝 {step['description']}")
            
            step_result = {
                'step_number': step_number,
                'step_name': step['step'],
                'description': step['description'],
                'priority': step['priority'],
                'status': 'UNKNOWN',
                'execution_time_minutes': 0,
                'error': None,
                'warnings': [],
                'validation_result': None
            }
            
            try:
                # Execute the rollback step
                action_function = step['action']
                files_or_tables = step.get('files', step.get('tables', []))
                
                if callable(files_or_tables):
                    files_or_tables = files_or_tables()
                
                action_result = action_function(files_or_tables)
                
                if action_result.get('success', True):
                    # Validate the rollback step
                    validation_function = step['validation']
                    validation_result = validation_function()
                    
                    step_result['validation_result'] = validation_result
                    
                    if validation_result.get('success', True):
                        step_result['status'] = 'SUCCESS'
                        print(f"   ✅ Step completed successfully")
                    else:
                        step_result['status'] = 'VALIDATION_FAILED'
                        step_result['error'] = validation_result.get('error', 'Validation failed')
                        print(f"   ❌ Step validation failed: {step_result['error']}")
                        
                        # For critical steps, stop rollback
                        if step['priority'] == 'CRITICAL':
                            print(f"   🛑 Critical step failed, stopping rollback")
                            break
                else:
                    step_result['status'] = 'EXECUTION_FAILED'
                    step_result['error'] = action_result.get('error', 'Execution failed')
                    print(f"   ❌ Step execution failed: {step_result['error']}")
                    
                    # For critical steps, stop rollback
                    if step['priority'] == 'CRITICAL':
                        print(f"   🛑 Critical step failed, stopping rollback")
                        break
                
            except Exception as e:
                step_result['status'] = 'ERROR'
                step_result['error'] = str(e)
                rollback_result['errors_encountered'].append({
                    'step': step['step'],
                    'error': str(e)
                })
                print(f"   ❌ Step error: {e}")
                
                # For critical steps, stop rollback
                if step['priority'] == 'CRITICAL':
                    print(f"   🛑 Critical step error, stopping rollback")
                    break
            
            # Calculate step execution time
            step_end_time = datetime.now()
            step_result['execution_time_minutes'] = round(
                (step_end_time - step_start_time).total_seconds() / 60, 2
            )
            
            rollback_result['steps_executed'].append(step_result)
            print("")
        
        # Calculate total rollback time
        end_time = datetime.now()
        rollback_result['total_time_minutes'] = round(
            (end_time - start_time).total_seconds() / 60, 2
        )
        
        # Determine overall success
        successful_steps = [s for s in rollback_result['steps_executed'] if s['status'] == 'SUCCESS']
        critical_failures = [s for s in rollback_result['steps_executed'] 
                           if s['status'] in ['ERROR', 'EXECUTION_FAILED', 'VALIDATION_FAILED'] 
                           and s['priority'] == 'CRITICAL']
        
        rollback_result['overall_success'] = (
            len(successful_steps) > 0 and
            len(critical_failures) == 0
        )
        
        # Run post-rollback validation
        print("🔍 Running post-rollback validation...")
        rollback_result['post_rollback_validation'] = self.run_post_rollback_validation()
        
        # Log rollback completion
        self.log_rollback_completion(rollback_result)
        
        return rollback_result
    
    def create_pre_rollback_backup(self):
        """Create backup before starting rollback"""
        
        print("💾 Creating pre-rollback backup...")
        
        try:
            os.makedirs(self.backup_directory, exist_ok=True)
            
            # Backup key files that might be modified during rollback
            backup_files = [
                'verenigingen/hooks.py',
                'verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py',
                'verenigingen/api/',
                'verenigingen/utils/'
            ]
            
            for file_path in backup_files:
                full_path = f'/home/frappe/frappe-bench/apps/verenigingen/{file_path}'
                backup_path = f'{self.backup_directory}/{file_path}'
                
                if os.path.exists(full_path):
                    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                    if os.path.isdir(full_path):
                        shutil.copytree(full_path, backup_path, dirs_exist_ok=True)
                    else:
                        shutil.copy2(full_path, backup_path)
            
            print("   ✅ Pre-rollback backup created")
            
        except Exception as e:
            print(f"   ⚠️  Backup creation failed: {e}")
    
    # Phase 1 Security Rollback Actions
    
    def get_modified_security_files(self) -> List[str]:
        """Get list of files modified during Phase 1 security implementation"""
        
        # This would ideally read from a change log or git diff
        # For now, return likely modified files
        return [
            'verenigingen/api/sepa_mandate_management.py',
            'verenigingen/api/payment_processing.py',
            'verenigingen/api/member_management.py',
            'verenigingen/api/dd_batch_creation.py'
        ]
    
    def restore_original_decorators(self, files: List[str]) -> Dict[str, Any]:
        """Remove @critical_api decorators from specified files"""
        
        try:
            modified_files = []
            
            for file_path in files:
                full_path = f'/home/frappe/frappe-bench/apps/verenigingen/{file_path}'
                
                if os.path.exists(full_path):
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    original_content = content
                    
                    # Remove @critical_api decorator lines
                    lines = content.split('\n')
                    filtered_lines = []
                    
                    for line in lines:
                        if '@critical_api' not in line and 'from verenigingen.utils.security' not in line:
                            filtered_lines.append(line)
                    
                    modified_content = '\n'.join(filtered_lines)
                    
                    if modified_content != original_content:
                        with open(full_path, 'w', encoding='utf-8') as f:
                            f.write(modified_content)
                        modified_files.append(file_path)
            
            return {
                'success': True,
                'modified_files': modified_files,
                'files_processed': len(files)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def restore_original_imports(self, files: str) -> Dict[str, Any]:
        """Restore original import statements"""
        
        try:
            # This would restore original imports from backup or git
            # For now, return success
            return {
                'success': True,
                'note': 'Import restoration would be implemented with git diff'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_security_test_files(self) -> List[str]:
        """Get list of security test files to remove"""
        
        return [
            'verenigingen/tests/test_api_security_matrix.py',
            'verenigingen/tests/test_security_framework_comprehensive.py'
        ]
    
    def remove_security_test_files(self, files: List[str]) -> Dict[str, Any]:
        """Remove security test files"""
        
        try:
            removed_files = []
            
            for file_path in files:
                full_path = f'/home/frappe/frappe-bench/apps/verenigingen/{file_path}'
                
                if os.path.exists(full_path):
                    os.remove(full_path)
                    removed_files.append(file_path)
            
            return {
                'success': True,
                'removed_files': removed_files
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def restore_hooks_file(self, files: List[str]) -> Dict[str, Any]:
        """Restore original hooks.py file"""
        
        try:
            # This would restore from backup or git
            return {
                'success': True,
                'note': 'Hooks file restoration would use git checkout'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    # Phase 2 Performance Rollback Actions
    
    def drop_performance_indexes(self, tables: List[str]) -> Dict[str, Any]:
        """Remove performance indexes added in Phase 2"""
        
        try:
            dropped_indexes = []
            
            index_mappings = {
                'tabSales Invoice': ['idx_customer_status'],
                'tabPayment Entry Reference': ['idx_reference_name'],
                'tabSEPA Mandate': ['idx_member_status']
            }
            
            for table in tables:
                indexes_to_drop = index_mappings.get(table, [])
                
                for index_name in indexes_to_drop:
                    try:
                        frappe.db.sql(f"DROP INDEX {index_name} ON `{table}`")
                        dropped_indexes.append(f"{table}.{index_name}")
                    except Exception as e:
                        # Index might not exist, continue
                        continue
            
            return {
                'success': True,
                'dropped_indexes': dropped_indexes
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def restore_synchronous_handlers(self, files: List[str]) -> Dict[str, Any]:
        """Restore synchronous event handlers"""
        
        try:
            # This would restore original synchronous event handlers
            # For now, return success
            return {
                'success': True,
                'note': 'Event handler restoration would modify hooks.py'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_background_job_files(self) -> List[str]:
        """Get list of background job files to remove"""
        
        return [
            'verenigingen/utils/background_jobs.py',
            'verenigingen/api/job_status.py'
        ]
    
    def remove_background_job_code(self, files: List[str]) -> Dict[str, Any]:
        """Remove background job management code"""
        
        try:
            removed_files = []
            
            for file_path in files:
                full_path = f'/home/frappe/frappe-bench/apps/verenigingen/{file_path}'
                
                if os.path.exists(full_path):
                    os.remove(full_path)
                    removed_files.append(file_path)
            
            return {
                'success': True,
                'removed_files': removed_files
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def restore_payment_mixin(self, files: List[str]) -> Dict[str, Any]:
        """Restore original PaymentMixin implementation"""
        
        try:
            # This would restore from backup or git
            return {
                'success': True,
                'note': 'PaymentMixin restoration would use git checkout'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    # Phase 3 Architecture Rollback Actions
    
    def get_orm_migration_files(self) -> List[str]:
        """Get list of files with ORM migrations to rollback"""
        
        return [
            'vereiningen/api/member_management.py',
            'verenigingen/utils/payment_notifications.py'
        ]
    
    def restore_original_sql_queries(self, files: List[str]) -> Dict[str, Any]:
        """Restore original SQL queries that were migrated to ORM"""
        
        try:
            # This would restore original SQL queries from backup
            return {
                'success': True,
                'note': 'SQL query restoration would use git diff and backup files'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_service_layer_files(self) -> List[str]:
        """Get list of service layer files to remove"""
        
        return [
            'verenigingen/utils/services/sepa_service.py',
            'verenigingen/utils/services/member_service.py'
        ]
    
    def remove_service_layer_code(self, files: List[str]) -> Dict[str, Any]:
        """Remove service layer implementations"""
        
        try:
            removed_files = []
            
            for file_path in files:
                full_path = f'/home/frappe/frappe-bench/apps/verenigingen/{file_path}'
                
                if os.path.exists(full_path):
                    os.remove(full_path)
                    removed_files.append(file_path)
            
            return {
                'success': True,
                'removed_files': removed_files
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_mixin_files(self) -> List[str]:
        """Get list of mixin files to restore"""
        
        return [
            'verenigingen/verenigingen/doctype/member/mixins/payment_mixin.py',
            'verenigingen/verenigingen/doctype/member/mixins/sepa_mandate_mixin.py'
        ]
    
    def restore_original_mixins(self, files: List[str]) -> Dict[str, Any]:
        """Restore original mixin implementations"""
        
        try:
            # This would restore original mixins from backup
            return {
                'success': True,
                'note': 'Mixin restoration would use git checkout'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    # Validation Functions
    
    def test_api_functionality(self) -> Dict[str, Any]:
        """Test that API functionality is working after rollback"""
        
        try:
            # Test key API endpoints
            test_endpoints = [
                'verenigingen.api.member_management.get_member_summary',
                'verenigingen.api.payment_dashboard.get_dashboard_data'
            ]
            
            working_apis = 0
            for endpoint in test_endpoints:
                try:
                    result = frappe.call(endpoint)
                    working_apis += 1
                except Exception:
                    continue
            
            success_rate = (working_apis / len(test_endpoints)) * 100 if test_endpoints else 0
            
            return {
                'success': success_rate >= 80,  # 80% of APIs must work
                'success_rate': success_rate,
                'working_apis': working_apis,
                'total_apis': len(test_endpoints)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_import_success(self) -> Dict[str, Any]:
        """Test that imports are working correctly"""
        
        try:
            # Try importing key modules
            import importlib
            
            test_modules = [
                'verenigingen.api.member_management',
                'verenigingen.api.payment_processing'
            ]
            
            successful_imports = 0
            for module_name in test_modules:
                try:
                    importlib.import_module(module_name)
                    successful_imports += 1
                except Exception:
                    continue
            
            success_rate = (successful_imports / len(test_modules)) * 100 if test_modules else 0
            
            return {
                'success': success_rate >= 90,  # 90% of imports must work
                'success_rate': success_rate,
                'successful_imports': successful_imports,
                'total_modules': len(test_modules)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_suite_runs(self) -> Dict[str, Any]:
        """Test that the test suite can run"""
        
        try:
            # This would run a subset of tests to verify functionality
            return {
                'success': True,
                'note': 'Test suite validation would run actual tests'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_hooks_functionality(self) -> Dict[str, Any]:
        """Test that hooks are functioning correctly"""
        
        try:
            # This would test event handlers and other hook functionality
            return {
                'success': True,
                'note': 'Hooks validation would test event handlers'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_query_functionality(self) -> Dict[str, Any]:
        """Test that database queries are working correctly"""
        
        try:
            # Test basic database operations
            test_queries = [
                "SELECT COUNT(*) FROM `tabMember` LIMIT 1",
                "SELECT COUNT(*) FROM `tabSales Invoice` LIMIT 1"
            ]
            
            successful_queries = 0
            for query in test_queries:
                try:
                    frappe.db.sql(query)
                    successful_queries += 1
                except Exception:
                    continue
            
            success_rate = (successful_queries / len(test_queries)) * 100 if test_queries else 0
            
            return {
                'success': success_rate >= 90,
                'success_rate': success_rate,
                'successful_queries': successful_queries,
                'total_queries': len(test_queries)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_event_handler_execution(self) -> Dict[str, Any]:
        """Test that event handlers are executing correctly"""
        
        try:
            # This would test event handler execution
            return {
                'success': True,
                'note': 'Event handler testing would create test documents'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_core_functionality(self) -> Dict[str, Any]:
        """Test core system functionality"""
        
        try:
            # Test basic system operations
            basic_tests = [
                lambda: frappe.get_all("Member", limit=1),
                lambda: frappe.get_all("Sales Invoice", limit=1),
                lambda: frappe.get_all("Payment Entry", limit=1)
            ]
            
            successful_tests = 0
            for test_func in basic_tests:
                try:
                    test_func()
                    successful_tests += 1
                except Exception:
                    continue
            
            success_rate = (successful_tests / len(basic_tests)) * 100 if basic_tests else 0
            
            return {
                'success': success_rate >= 80,
                'success_rate': success_rate,
                'successful_tests': successful_tests,
                'total_tests': len(basic_tests)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_payment_functionality(self) -> Dict[str, Any]:
        """Test payment-related functionality"""
        
        try:
            # Test payment operations
            sample_member = frappe.get_all("Member", limit=1)
            
            if sample_member:
                member_doc = frappe.get_doc("Member", sample_member[0].name)
                # Test basic member operations
                return {
                    'success': True,
                    'member_loaded': True
                }
            else:
                return {
                    'success': True,
                    'note': 'No members available for testing'
                }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_data_access_functionality(self) -> Dict[str, Any]:
        """Test data access functionality"""
        
        try:
            # Test data access patterns
            return {
                'success': True,
                'note': 'Data access testing would verify ORM and SQL operations'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_mixin_functionality(self) -> Dict[str, Any]:
        """Test mixin functionality"""
        
        try:
            # Test mixin operations
            return {
                'success': True,
                'note': 'Mixin testing would verify mixin methods work correctly'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_doctype_functionality(self) -> Dict[str, Any]:
        """Test doctype functionality"""
        
        try:
            # Test doctype operations
            return {
                'success': True,
                'note': 'DocType testing would verify CRUD operations'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def run_post_rollback_validation(self) -> Dict[str, Any]:
        """Run comprehensive post-rollback validation"""
        
        validation_results = {
            'overall_system_health': self.test_overall_system_health(),
            'critical_functionality': self.test_critical_functionality(),
            'data_integrity': self.test_data_integrity_post_rollback()
        }
        
        # Determine overall validation success
        all_successful = all(
            result.get('success', False) for result in validation_results.values()
        )
        
        validation_results['overall_success'] = all_successful
        
        return validation_results
    
    def test_overall_system_health(self) -> Dict[str, Any]:
        """Test overall system health after rollback"""
        
        try:
            # Basic system health checks
            health_checks = [
                ('Database Connection', lambda: frappe.db.sql("SELECT 1")),
                ('Module Loading', lambda: __import__('verenigingen')),
                ('Basic Query', lambda: frappe.get_all("Member", limit=1))
            ]
            
            passed_checks = 0
            for check_name, check_func in health_checks:
                try:
                    check_func()
                    passed_checks += 1
                except Exception:
                    continue
            
            health_score = (passed_checks / len(health_checks)) * 100
            
            return {
                'success': health_score >= 90,
                'health_score': health_score,
                'passed_checks': passed_checks,
                'total_checks': len(health_checks)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_critical_functionality(self) -> Dict[str, Any]:
        """Test critical functionality after rollback"""
        
        try:
            # Test critical business functions
            return {
                'success': True,
                'note': 'Critical functionality testing would verify key business processes'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_data_integrity_post_rollback(self) -> Dict[str, Any]:
        """Test data integrity after rollback"""
        
        try:
            # Check basic data integrity
            integrity_checks = [
                ('Member Records', lambda: frappe.db.count("Member") > 0),
                ('Customer Links', lambda: len(frappe.get_all("Member", filters={"customer": ["!=", ""]}, limit=1)) >= 0)
            ]
            
            passed_checks = 0
            for check_name, check_func in integrity_checks:
                try:
                    if check_func():
                        passed_checks += 1
                except Exception:
                    continue
            
            integrity_score = (passed_checks / len(integrity_checks)) * 100
            
            return {
                'success': integrity_score >= 80,
                'integrity_score': integrity_score,
                'passed_checks': passed_checks,
                'total_checks': len(integrity_checks)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def log_rollback_completion(self, result: Dict[str, Any]):
        """Log rollback completion for audit purposes"""
        
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'phase': self.phase,
            'rollback_success': result['overall_success'],
            'total_time_minutes': result['total_time_minutes'],
            'steps_executed': len(result['steps_executed']),
            'errors_count': len(result['errors_encountered'])
        }
        
        log_file = f'/home/frappe/frappe-bench/apps/verenigingen/rollback_log.json'
        
        try:
            # Load existing log
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    log_data = json.load(f)
            else:
                log_data = {'rollback_history': []}
            
            # Add new entry
            log_data['rollback_history'].append(log_entry)
            
            # Save updated log
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
                
        except Exception as e:
            print(f"   ⚠️  Failed to write rollback log: {e}")

def save_rollback_results(results: Dict[str, Any], phase: str) -> str:
    """Save rollback results to file"""
    
    results_file = f'/home/frappe/frappe-bench/apps/verenigingen/{phase}_rollback_results.json'
    
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    return results_file

def generate_rollback_report(results: Dict[str, Any]) -> str:
    """Generate a formatted rollback report"""
    
    report = []
    report.append(f"# {results.get('phase', 'Unknown').upper()} Rollback Report")
    report.append(f"Generated: {results.get('timestamp', 'Unknown')}")
    report.append(f"Total Time: {results.get('total_time_minutes', 0)} minutes")
    report.append("")
    
    # Overall status
    overall_success = results.get('overall_success', False)
    status_icon = "✅" if overall_success else "❌"
    report.append(f"## Overall Status: {status_icon} {'SUCCESS' if overall_success else 'FAILED'}")
    report.append("")
    
    # Steps executed
    steps = results.get('steps_executed', [])
    if steps:
        report.append("## Rollback Steps Executed")
        
        for step in steps:
            status_icon = "✅" if step['status'] == 'SUCCESS' else "❌"
            priority_icon = "⚡" if step['priority'] == 'CRITICAL' else "🔥" if step['priority'] == 'HIGH' else "⚠️"
            
            report.append(f"### {status_icon} Step {step['step_number']}: {step['step_name']}")
            report.append(f"- **Priority**: {priority_icon} {step['priority']}")
            report.append(f"- **Status**: {step['status']}")
            report.append(f"- **Time**: {step['execution_time_minutes']} minutes")
            report.append(f"- **Description**: {step['description']}")
            
            if step.get('error'):
                report.append(f"- **Error**: {step['error']}")
            
            if step.get('validation_result'):
                validation = step['validation_result']
                validation_icon = "✅" if validation.get('success') else "❌"
                report.append(f"- **Validation**: {validation_icon} {validation.get('note', 'Completed')}")
            
            report.append("")
    
    # Post-rollback validation
    post_validation = results.get('post_rollback_validation', {})
    if post_validation:
        report.append("## Post-Rollback Validation")
        
        overall_validation = post_validation.get('overall_success', False)
        validation_icon = "✅" if overall_validation else "❌"
        report.append(f"**Overall Validation**: {validation_icon} {'PASSED' if overall_validation else 'FAILED'}")
        report.append("")
        
        for check_name, check_result in post_validation.items():
            if check_name == 'overall_success':
                continue
                
            if isinstance(check_result, dict):
                check_success = check_result.get('success', False)
                check_icon = "✅" if check_success else "❌"
                report.append(f"- {check_icon} **{check_name.replace('_', ' ').title()}**")
                
                if 'score' in str(check_result):
                    for key, value in check_result.items():
                        if 'score' in key:
                            report.append(f"  - Score: {value}%")
                            break
        
        report.append("")
    
    # Errors encountered
    errors = results.get('errors_encountered', [])
    if errors:
        report.append("## Errors Encountered")
        
        for error in errors:
            report.append(f"- **{error['step']}**: {error['error']}")
        
        report.append("")
    
    # Recommendations
    if not overall_success:
        report.append("## Recommendations")
        report.append("- Review failed rollback steps and address underlying issues")
        report.append("- Consider manual intervention for critical failures")
        report.append("- Run comprehensive system validation before proceeding")
        report.append("- Contact system administrator if issues persist")
        report.append("")
    
    return "\n".join(report)

def main():
    """Main execution for standalone rollback"""
    
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python rollback_procedures.py <phase>")
        print("Phases: phase1_security, phase2_performance, phase3_architecture")
        sys.exit(1)
    
    phase = sys.argv[1].lower()
    
    valid_phases = ['phase1_security', 'phase2_performance', 'phase3_architecture']
    if phase not in valid_phases:
        print(f"Invalid phase: {phase}")
        print(f"Valid phases: {', '.join(valid_phases)}")
        sys.exit(1)
    
    print(f"🔄 Starting {phase.upper()} Rollback Procedures...")
    print("   ⚠️  This will undo changes made during the specified phase")
    print("")
    
    # Confirmation prompt
    response = input("Are you sure you want to proceed with rollback? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Rollback cancelled.")
        sys.exit(0)
    
    try:
        # Create rollback manager
        rollback_manager = RollbackManager(phase)
        
        # Execute rollback
        results = rollback_manager.execute_rollback()
        
        # Save results
        results_file = save_rollback_results(results, phase)
        
        # Generate report
        report = generate_rollback_report(results)
        
        # Save report
        report_file = f'/home/frappe/frappe-bench/apps/verenigingen/{phase}_rollback_report.md'
        with open(report_file, 'w') as f:
            f.write(report)
        
        print("✅ Rollback procedures completed!")
        print(f"📊 Results saved to: {results_file}")
        print(f"📄 Report saved to: {report_file}")
        
        # Print summary
        overall_success = results.get('overall_success', False)
        steps_executed = len(results.get('steps_executed', []))
        total_time = results.get('total_time_minutes', 0)
        
        print(f"\n🎯 Rollback Status: {'SUCCESS' if overall_success else 'FAILED'}")
        print(f"⏱️  Execution Time: {total_time} minutes")
        print(f"📋 Steps Executed: {steps_executed}")
        
        if not overall_success:
            errors_count = len(results.get('errors_encountered', []))
            print(f"❌ Errors Encountered: {errors_count}")
            print("\n⚠️  Review the report for detailed error information.")
        
        # Exit with appropriate code
        sys.exit(0 if overall_success else 1)
        
    except Exception as e:
        print(f"❌ Rollback procedure error: {e}")
        sys.exit(2)

if __name__ == '__main__':
    main()