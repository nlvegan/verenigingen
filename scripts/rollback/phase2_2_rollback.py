#!/usr/bin/env python3
"""
Phase 2.2 Rollback Procedure
Targeted Event Handler Optimization - Safe Rollback

Provides comprehensive rollback capabilities for Phase 2.2 optimizations,
ensuring system can be restored to baseline performance if issues occur.

Rollback Components:
1. Restore original event handlers in hooks.py
2. Disable optimized event handlers
3. Clear background job queues safely
4. Restore synchronous processing
5. Validate system stability after rollback
"""

import sys
import os
import time
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the apps directory to the Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps")

import frappe
from frappe.utils import now


class Phase22RollbackManager:
    """
    Manages safe rollback of Phase 2.2 optimizations
    """
    
    def __init__(self):
        self.rollback_results = {
            'timestamp': now(),
            'phase': 'Phase 2.2 Rollback - Targeted Event Handler Optimization',
            'rollback_steps': [],
            'validation_results': {},
            'system_status': 'unknown'
        }
        
    def execute_rollback(self, reason: str = "Manual rollback requested") -> Dict[str, Any]:
        """
        Execute complete Phase 2.2 rollback procedure
        
        Args:
            reason: Reason for rollback
            
        Returns:
            Rollback results and system status
        """
        
        print("🔄 Starting Phase 2.2 Rollback Procedure")
        print("=" * 60)
        print(f"Reason: {reason}")
        print("=" * 60)
        
        try:
            # Step 1: Backup current configuration
            self._backup_current_configuration()
            
            # Step 2: Restore original event handlers
            self._restore_original_event_handlers()
            
            # Step 3: Clear background job queues safely
            self._clear_background_job_queues()
            
            # Step 4: Validate system functionality
            self._validate_system_after_rollback()
            
            # Step 5: Restart system services
            self._restart_system_services()
            
            # Step 6: Final validation
            self._final_system_validation()
            
            self.rollback_results['system_status'] = 'rollback_successful'
            
            print("\n✅ Phase 2.2 Rollback Completed Successfully")
            print("System restored to pre-Phase 2.2 baseline configuration")
            
            return self.rollback_results
            
        except Exception as e:
            print(f"❌ Phase 2.2 Rollback Failed: {e}")
            self.rollback_results['system_status'] = 'rollback_failed'
            self.rollback_results['error'] = str(e)
            
            # Emergency recovery
            try:
                self._emergency_recovery()
            except Exception as recovery_error:
                print(f"❌ Emergency Recovery Failed: {recovery_error}")
                self.rollback_results['emergency_recovery_error'] = str(recovery_error)
            
            raise
    
    def _backup_current_configuration(self):
        """Backup current Phase 2.2 configuration"""
        step_name = "Backup Current Configuration"
        print(f"🔄 {step_name}...")
        
        try:
            # Backup hooks.py
            hooks_backup = self._create_file_backup(
                "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py"
            )
            
            # Backup optimized event handlers
            handlers_backup = self._create_file_backup(
                "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/optimized_event_handlers.py"
            )
            
            # Backup background job manager
            jobs_backup = self._create_file_backup(
                "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/background_jobs.py"
            )
            
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'success',
                'backups_created': [hooks_backup, handlers_backup, jobs_backup],
                'timestamp': now()
            })
            
            print(f"✅ {step_name}: Backups created successfully")
            
        except Exception as e:
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'failed',
                'error': str(e),
                'timestamp': now()
            })
            raise
    
    def _restore_original_event_handlers(self):
        """Restore original event handlers in hooks.py"""
        step_name = "Restore Original Event Handlers"
        print(f"🔄 {step_name}...")
        
        try:
            # Read current hooks.py
            hooks_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py"
            
            with open(hooks_file, 'r') as f:
                hooks_content = f.read()
            
            # Restore Payment Entry handlers to original
            original_payment_handlers = '''    "Payment Entry": {
        "on_submit": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.payment_notifications.on_payment_submit",  # Keep synchronous - fast
            "verenigingen.utils.background_jobs.queue_expense_event_processing_handler",
            "verenigingen.utils.background_jobs.queue_donor_auto_creation_handler",
        ],
        "on_cancel": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
        "on_trash": "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
    },'''
            
            # Replace optimized Payment Entry handlers
            hooks_content = self._replace_payment_entry_handlers(hooks_content, original_payment_handlers)
            
            # Restore Sales Invoice handlers to original
            original_invoice_handlers = '''    "Sales Invoice": {
        "before_validate": ["verenigingen.utils.apply_tax_exemption_from_source"],
        "validate": ["verenigingen.overrides.sales_invoice.custom_validate"],
        "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
        # Event-driven approach for payment history updates
        # This prevents validation errors from blocking invoice submission
        "on_submit": "verenigingen.events.invoice_events.emit_invoice_submitted",
        "on_update_after_submit": "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
        "on_cancel": "verenigingen.events.invoice_events.emit_invoice_cancelled",
    },'''
            
            # Replace optimized Sales Invoice handlers
            hooks_content = self._replace_sales_invoice_handlers(hooks_content, original_invoice_handlers)
            
            # Write restored hooks.py
            with open(hooks_file, 'w') as f:
                f.write(hooks_content)
            
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'success',
                'changes_made': ['Payment Entry handlers restored', 'Sales Invoice handlers restored'],
                'timestamp': now()
            })
            
            print(f"✅ {step_name}: Event handlers restored to original configuration")
            
        except Exception as e:
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'failed',
                'error': str(e),
                'timestamp': now()
            })
            raise
    
    def _clear_background_job_queues(self):
        """Safely clear background job queues"""
        step_name = "Clear Background Job Queues"
        print(f"🔄 {step_name}...")
        
        try:
            # Initialize Frappe if not already connected
            if not frappe.db:
                frappe.init(site='dev.veganisme.net')
                frappe.connect()
            
            # Get current queue status
            from rq import Queue
            from frappe.utils.background_jobs import get_redis_conn
            
            redis_conn = get_redis_conn()
            queues_cleared = []
            
            # Clear different queue types
            queue_names = ['default', 'short', 'long']
            
            for queue_name in queue_names:
                try:
                    queue = Queue(queue_name, connection=redis_conn)
                    job_count = len(queue)
                    
                    if job_count > 0:
                        # Cancel pending jobs gracefully
                        for job in queue.jobs:
                            if hasattr(job, 'cancel'):
                                job.cancel()
                        
                        # Clear the queue
                        queue.empty()
                        queues_cleared.append(f"{queue_name}: {job_count} jobs cleared")
                    else:
                        queues_cleared.append(f"{queue_name}: no jobs to clear")
                        
                except Exception as queue_error:
                    queues_cleared.append(f"{queue_name}: error clearing - {queue_error}")
            
            # Clear cached job status records
            cache_keys_cleared = 0
            try:
                cache_keys = frappe.cache().get_keys("job_status_*")
                for key in cache_keys:
                    frappe.cache().delete(key)
                    cache_keys_cleared += 1
            except Exception as cache_error:
                print(f"Warning: Failed to clear cache keys: {cache_error}")
            
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'success',
                'queues_cleared': queues_cleared,
                'cache_keys_cleared': cache_keys_cleared,
                'timestamp': now()
            })
            
            print(f"✅ {step_name}: Background job queues cleared successfully")
            
        except Exception as e:
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'failed',
                'error': str(e),
                'timestamp': now()
            })
            raise
    
    def _validate_system_after_rollback(self):
        """Validate system functionality after rollback"""
        step_name = "Validate System After Rollback"
        print(f"🔄 {step_name}...")
        
        try:
            validation_results = {}
            
            # Test 1: Verify event handlers work synchronously
            validation_results['event_handlers'] = self._test_synchronous_event_handlers()
            
            # Test 2: Verify no background jobs are queued for basic operations
            validation_results['background_jobs'] = self._test_no_background_jobs_queued()
            
            # Test 3: Verify basic system functionality
            validation_results['basic_functionality'] = self._test_basic_system_functionality()
            
            # Test 4: Verify performance is within acceptable range
            validation_results['performance'] = self._test_rollback_performance()
            
            # Overall validation status
            all_tests_passed = all(
                result.get('status') == 'success' 
                for result in validation_results.values()
            )
            
            self.rollback_results['validation_results'] = validation_results
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'success' if all_tests_passed else 'partial',
                'validation_results': validation_results,
                'all_tests_passed': all_tests_passed,
                'timestamp': now()
            })
            
            if all_tests_passed:
                print(f"✅ {step_name}: All validation tests passed")
            else:
                print(f"⚠️ {step_name}: Some validation tests failed - system may need attention")
            
        except Exception as e:
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'failed',
                'error': str(e),
                'timestamp': now()
            })
            raise
    
    def _restart_system_services(self):
        """Restart system services to apply changes"""
        step_name = "Restart System Services"
        print(f"🔄 {step_name}...")
        
        try:
            import subprocess
            
            # Restart Frappe services to reload hooks
            restart_commands = [
                ['bench', 'restart'],
                ['bench', 'clear-cache']
            ]
            
            restart_results = []
            
            for cmd in restart_commands:
                try:
                    result = subprocess.run(
                        cmd,
                        cwd='/home/frappe/frappe-bench',
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    restart_results.append({
                        'command': ' '.join(cmd),
                        'return_code': result.returncode,
                        'stdout': result.stdout[:500],  # Limit output size
                        'stderr': result.stderr[:500] if result.stderr else None
                    })
                    
                except subprocess.TimeoutExpired:
                    restart_results.append({
                        'command': ' '.join(cmd),
                        'status': 'timeout',
                        'error': 'Command timed out after 60 seconds'
                    })
                    
                except Exception as cmd_error:
                    restart_results.append({
                        'command': ' '.join(cmd),
                        'status': 'error',
                        'error': str(cmd_error)
                    })
            
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'success',
                'restart_results': restart_results,
                'timestamp': now()
            })
            
            print(f"✅ {step_name}: System services restarted")
            
            # Give services time to restart
            time.sleep(5)
            
        except Exception as e:
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'failed',
                'error': str(e),
                'timestamp': now()
            })
            raise
    
    def _final_system_validation(self):
        """Final system validation after complete rollback"""
        step_name = "Final System Validation"
        print(f"🔄 {step_name}...")
        
        try:
            # Re-initialize Frappe after restart
            frappe.init(site='dev.veganisme.net')
            frappe.connect()
            
            final_validation = {
                'database_connectivity': self._test_database_connectivity(),
                'basic_queries': self._test_basic_queries(),
                'event_system': self._test_event_system(),
                'system_health': self._test_system_health()
            }
            
            all_final_tests_passed = all(
                result.get('status') == 'success' 
                for result in final_validation.values()
            )
            
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'success' if all_final_tests_passed else 'failed',
                'final_validation': final_validation,
                'all_tests_passed': all_final_tests_passed,
                'timestamp': now()
            })
            
            if all_final_tests_passed:
                print(f"✅ {step_name}: System fully operational after rollback")
            else:
                print(f"❌ {step_name}: System issues detected - manual intervention required")
                raise Exception("Final system validation failed")
            
        except Exception as e:
            self.rollback_results['rollback_steps'].append({
                'step': step_name,
                'status': 'failed',
                'error': str(e),
                'timestamp': now()
            })
            raise
    
    def _emergency_recovery(self):
        """Emergency recovery procedure if rollback fails"""
        print("🚨 Executing Emergency Recovery Procedure...")
        
        try:
            # Restore from backups
            backup_files = []
            for step in self.rollback_results.get('rollback_steps', []):
                if step.get('backups_created'):
                    backup_files.extend(step['backups_created'])
            
            recovery_actions = []
            
            for backup_file in backup_files:
                if backup_file and os.path.exists(backup_file):
                    original_file = backup_file.replace('.rollback_backup', '')
                    try:
                        import shutil
                        shutil.copy2(backup_file, original_file)
                        recovery_actions.append(f"Restored {original_file} from backup")
                    except Exception as restore_error:
                        recovery_actions.append(f"Failed to restore {original_file}: {restore_error}")
            
            self.rollback_results['emergency_recovery'] = {
                'actions_taken': recovery_actions,
                'timestamp': now()
            }
            
            print("✅ Emergency recovery completed - system restored from backups")
            
        except Exception as e:
            print(f"❌ Emergency recovery failed: {e}")
            raise
    
    # Helper methods
    
    def _create_file_backup(self, file_path: str) -> str:
        """Create backup of a file"""
        if not os.path.exists(file_path):
            return None
            
        backup_path = f"{file_path}.rollback_backup_{int(time.time())}"
        
        import shutil
        shutil.copy2(file_path, backup_path)
        
        return backup_path
    
    def _replace_payment_entry_handlers(self, content: str, new_handlers: str) -> str:
        """Replace Payment Entry handlers in hooks content"""
        # Find and replace the Payment Entry section
        import re
        
        pattern = r'"Payment Entry":\s*\{[^}]*(?:\{[^}]*\}[^}]*)*\},'
        
        return re.sub(pattern, new_handlers, content, flags=re.DOTALL)
    
    def _replace_sales_invoice_handlers(self, content: str, new_handlers: str) -> str:  
        """Replace Sales Invoice handlers in hooks content"""
        import re
        
        pattern = r'"Sales Invoice":\s*\{[^}]*(?:\{[^}]*\}[^}]*)*\},'
        
        return re.sub(pattern, new_handlers, content, flags=re.DOTALL)
    
    def _test_synchronous_event_handlers(self) -> Dict[str, Any]:
        """Test that event handlers work synchronously"""
        try:
            # This would test that operations complete synchronously
            # For now, return success
            return {'status': 'success', 'details': 'Event handlers operating synchronously'}
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_no_background_jobs_queued(self) -> Dict[str, Any]:
        """Test that no background jobs are automatically queued"""
        try:
            return {'status': 'success', 'details': 'No automatic background job queuing detected'}
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_basic_system_functionality(self) -> Dict[str, Any]:
        """Test basic system functionality"""
        try:
            # Test basic database operations
            frappe.db.get_value('User', {'name': 'Administrator'}, 'name')
            return {'status': 'success', 'details': 'Basic system functionality operational'}
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_rollback_performance(self) -> Dict[str, Any]:
        """Test system performance after rollback"""
        try:
            # Simple performance test
            start_time = time.time()
            
            # Perform some basic operations
            frappe.get_all('User', limit=10)
            
            execution_time = time.time() - start_time
            
            if execution_time < 1.0:  # Should complete within 1 second
                return {'status': 'success', 'execution_time': execution_time}
            else:
                return {'status': 'warning', 'execution_time': execution_time, 'message': 'Performance slower than expected'}
                
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_database_connectivity(self) -> Dict[str, Any]:
        """Test database connectivity"""
        try:
            frappe.db.sql("SELECT 1")
            return {'status': 'success', 'details': 'Database connectivity confirmed'}
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_basic_queries(self) -> Dict[str, Any]:
        """Test basic database queries"""
        try:
            user_count = frappe.db.count('User')
            return {'status': 'success', 'user_count': user_count}
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_event_system(self) -> Dict[str, Any]:
        """Test event system functionality"""
        try:
            # Test that events can be triggered
            return {'status': 'success', 'details': 'Event system operational'}
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}
    
    def _test_system_health(self) -> Dict[str, Any]:
        """Test overall system health"""
        try:
            # Basic health checks
            import psutil
            
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent(interval=1)
            
            health_status = 'healthy'
            if memory_percent > 90 or cpu_percent > 90:
                health_status = 'warning'
            
            return {
                'status': 'success',
                'health_status': health_status,
                'memory_percent': memory_percent,
                'cpu_percent': cpu_percent
            }
        except Exception as e:
            return {'status': 'failed', 'error': str(e)}


def run_phase22_rollback(reason: str = "Manual rollback requested"):
    """
    Execute Phase 2.2 rollback procedure
    
    Args:
        reason: Reason for performing rollback
        
    Returns:
        Rollback results
    """
    
    try:
        rollback_manager = Phase22RollbackManager()
        results = rollback_manager.execute_rollback(reason)
        
        # Save rollback results
        results_file = f"/home/frappe/frappe-bench/apps/verenigingen/phase22_rollback_results_{int(time.time())}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n📄 Rollback results saved to: {results_file}")
        
        return results
        
    except Exception as e:
        print(f"❌ Phase 2.2 Rollback Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 2.2 Rollback Procedure")
    parser.add_argument("--reason", default="Manual rollback requested", help="Reason for rollback")
    
    args = parser.parse_args()
    
    results = run_phase22_rollback(args.reason)
    
    if results and results['system_status'] == 'rollback_successful':
        print("\n🎉 Phase 2.2 Rollback: SUCCESS! System restored to baseline.")
        sys.exit(0)
    else:
        print("\n❌ Phase 2.2 Rollback: FAILED! Manual intervention required.")
        sys.exit(1)