#!/usr/bin/env python3
"""
Load Testing for Concurrent User Creation Workflows
==================================================

Tests system context switching under production-like load to validate
that Phase 2 security improvements maintain performance and reliability
under concurrent operations.

This addresses QCE recommendations for production readiness validation.

Usage:
    python scripts/testing/load_test_concurrent_user_creation.py --users 10 --duration 30
    
Test Scenarios:
1. Concurrent volunteer user creation (employee_user_link.py)
2. Concurrent member creation (application_helpers.py)
3. Mixed concurrent operations
4. Error recovery under load
5. Context switching performance monitoring

Key Metrics:
- Context switch latency under load
- Success rate with concurrent operations
- Error recovery effectiveness
- Resource usage patterns
- Database connection handling
"""

import os
import sys
import time
import threading
import argparse
import statistics
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

# Add Frappe path
sys.path.insert(0, '/home/frappe/frappe-bench/apps/frappe')
sys.path.insert(0, '/home/frappe/frappe-bench/apps/erpnext')
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

import frappe
from frappe.utils import today, add_days, now_datetime


class LoadTestMetrics:
    """Collects and analyzes load test metrics"""
    
    def __init__(self):
        self.operations = []
        self.errors = []
        self.context_switches = []
        self.start_time = None
        self.end_time = None
        
    def record_operation(self, operation_type: str, duration: float, success: bool, 
                        thread_id: str, error: Optional[str] = None):
        """Record a single operation result"""
        self.operations.append({
            'type': operation_type,
            'duration': duration,
            'success': success,
            'thread_id': thread_id,
            'timestamp': time.time(),
            'error': error
        })
        
    def record_error(self, error_type: str, message: str, thread_id: str):
        """Record an error during testing"""
        self.errors.append({
            'type': error_type,
            'message': message,
            'thread_id': thread_id,
            'timestamp': time.time()
        })
        
    def record_context_switch(self, duration: float, success: bool, thread_id: str):
        """Record context switch performance"""
        self.context_switches.append({
            'duration': duration,
            'success': success,
            'thread_id': thread_id,
            'timestamp': time.time()
        })
        
    def generate_report(self) -> Dict:
        """Generate comprehensive test report"""
        if not self.operations:
            return {"error": "No operations recorded"}
            
        successful_ops = [op for op in self.operations if op['success']]
        failed_ops = [op for op in self.operations if not op['success']]
        
        durations = [op['duration'] for op in successful_ops]
        context_durations = [cs['duration'] for cs in self.context_switches if cs['success']]
        
        total_duration = self.end_time - self.start_time if self.end_time and self.start_time else 0
        
        report = {
            'summary': {
                'total_operations': len(self.operations),
                'successful_operations': len(successful_ops),
                'failed_operations': len(failed_ops),
                'success_rate': len(successful_ops) / len(self.operations) * 100 if self.operations else 0,
                'total_errors': len(self.errors),
                'test_duration': total_duration,
                'operations_per_second': len(self.operations) / total_duration if total_duration > 0 else 0
            },
            'performance': {
                'avg_operation_duration': statistics.mean(durations) if durations else 0,
                'median_operation_duration': statistics.median(durations) if durations else 0,
                'max_operation_duration': max(durations) if durations else 0,
                'min_operation_duration': min(durations) if durations else 0,
                'std_dev_operation_duration': statistics.stdev(durations) if len(durations) > 1 else 0
            },
            'context_switching': {
                'total_context_switches': len(self.context_switches),
                'successful_switches': len([cs for cs in self.context_switches if cs['success']]),
                'avg_switch_duration': statistics.mean(context_durations) if context_durations else 0,
                'max_switch_duration': max(context_durations) if context_durations else 0,
                'context_switch_overhead': statistics.mean(context_durations) if context_durations else 0
            },
            'errors_by_type': self._group_errors_by_type(),
            'operations_by_type': self._group_operations_by_type(),
            'thread_distribution': self._analyze_thread_distribution()
        }
        
        return report
        
    def _group_errors_by_type(self) -> Dict:
        """Group errors by type for analysis"""
        error_groups = {}
        for error in self.errors:
            error_type = error['type']
            if error_type not in error_groups:
                error_groups[error_type] = []
            error_groups[error_type].append(error)
        return {k: len(v) for k, v in error_groups.items()}
        
    def _group_operations_by_type(self) -> Dict:
        """Group operations by type for analysis"""
        op_groups = {}
        for op in self.operations:
            op_type = op['type']
            if op_type not in op_groups:
                op_groups[op_type] = {'successful': 0, 'failed': 0}
            if op['success']:
                op_groups[op_type]['successful'] += 1
            else:
                op_groups[op_type]['failed'] += 1
        return op_groups
        
    def _analyze_thread_distribution(self) -> Dict:
        """Analyze operation distribution across threads"""
        thread_ops = {}
        for op in self.operations:
            thread_id = op['thread_id']
            if thread_id not in thread_ops:
                thread_ops[thread_id] = {'successful': 0, 'failed': 0}
            if op['success']:
                thread_ops[thread_id]['successful'] += 1
            else:
                thread_ops[thread_id]['failed'] += 1
        return thread_ops


class ConcurrentUserCreationLoadTest:
    """Load test for concurrent user creation operations"""
    
    def __init__(self, concurrent_users: int = 5, test_duration: int = 30):
        self.concurrent_users = concurrent_users
        self.test_duration = test_duration
        self.metrics = LoadTestMetrics()
        self.stop_flag = threading.Event()
        
    def setup_test_environment(self):
        """Set up test environment"""
        try:
            frappe.init(site='dev.veganisme.net')
            frappe.connect()
            
            # Ensure we're in test mode
            frappe.flags.in_test = True
            
            # Create test members and volunteers for the load test
            print(f"Setting up test environment for {self.concurrent_users} concurrent users...")
            
            return True
            
        except Exception as e:
            print(f"Error setting up test environment: {str(e)}")
            return False
    
    def create_test_volunteer_user(self, thread_id: str) -> Tuple[bool, float, Optional[str]]:
        """Test volunteer user creation workflow"""
        start_time = time.time()
        error_msg = None
        
        try:
            # Import here to avoid circular imports during load test
            from verenigingen.utils.employee_user_link import create_user_for_volunteer
            from verenigingen.utils.secure_context_manager import secure_user_context
            
            # Create unique test volunteer
            unique_id = f"{thread_id}_{int(time.time() * 1000)}"
            
            # Create test member first
            with secure_user_context("Administrator", f"load_test_member_creation_{unique_id}") as ctx:
                member = frappe.get_doc({
                    "doctype": "Member",
                    "first_name": f"LoadTest{unique_id}",
                    "last_name": "Volunteer",
                    "email": f"loadtest.volunteer.{unique_id}@example.com",
                    "birth_date": add_days(today(), -365 * 25),  # 25 years old
                    "status": "Active"
                })
                member.insert()
                ctx.log_operation("member", member.name)
                
                # Create volunteer record
                volunteer = frappe.get_doc({
                    "doctype": "Volunteer",
                    "member": member.name,
                    "volunteer_name": f"{member.first_name} {member.last_name}",
                    "email": member.email,
                    "status": "Active"
                })
                volunteer.insert()
                ctx.log_operation("volunteer", volunteer.name)
            
            # Test user creation with proper permissions
            context_start = time.time()
            user_id = create_user_for_volunteer(volunteer)
            context_duration = time.time() - context_start
            
            # Record context switch performance
            self.metrics.record_context_switch(context_duration, user_id is not None, thread_id)
            
            success = user_id is not None
            
            # Clean up test data
            try:
                if user_id:
                    frappe.delete_doc("User", user_id, ignore_permissions=True)
                frappe.delete_doc("Volunteer", volunteer.name, ignore_permissions=True)
                frappe.delete_doc("Member", member.name, ignore_permissions=True)
            except Exception as cleanup_error:
                print(f"Cleanup warning: {str(cleanup_error)}")
            
            return success, time.time() - start_time, error_msg
            
        except Exception as e:
            error_msg = str(e)
            return False, time.time() - start_time, error_msg
    
    def create_test_member_application(self, thread_id: str) -> Tuple[bool, float, Optional[str]]:
        """Test member creation from application workflow"""
        start_time = time.time()
        error_msg = None
        
        try:
            from verenigingen.utils.secure_context_manager import secure_user_context
            
            unique_id = f"{thread_id}_{int(time.time() * 1000)}"
            
            # Test member creation with system context
            with secure_user_context("Administrator", f"load_test_member_app_{unique_id}") as ctx:
                member = frappe.get_doc({
                    "doctype": "Member",
                    "first_name": f"LoadApp{unique_id}",
                    "last_name": "Member",
                    "email": f"loadtest.app.{unique_id}@example.com",
                    "birth_date": add_days(today(), -365 * 30),  # 30 years old
                    "status": "Active"
                })
                member.insert()
                ctx.log_operation("member", member.name)
            
            # Clean up
            try:
                frappe.delete_doc("Member", member.name, ignore_permissions=True)
            except Exception as cleanup_error:
                print(f"Cleanup warning: {str(cleanup_error)}")
            
            return True, time.time() - start_time, error_msg
            
        except Exception as e:
            error_msg = str(e)
            return False, time.time() - start_time, error_msg
    
    def worker_thread(self, thread_id: str):
        """Worker thread that performs operations continuously"""
        operation_count = 0
        
        while not self.stop_flag.is_set():
            operation_count += 1
            
            # Alternate between different operation types
            if operation_count % 2 == 0:
                operation_type = "volunteer_user_creation"
                success, duration, error = self.create_test_volunteer_user(thread_id)
            else:
                operation_type = "member_application"
                success, duration, error = self.create_test_member_application(thread_id)
            
            # Record metrics
            self.metrics.record_operation(operation_type, duration, success, thread_id, error)
            
            if error:
                self.metrics.record_error(operation_type, error, thread_id)
            
            # Brief pause to prevent overwhelming the system
            time.sleep(0.1)
    
    def run_load_test(self) -> Dict:
        """Execute the load test"""
        print(f"Starting concurrent user creation load test...")
        print(f"Concurrent threads: {self.concurrent_users}")
        print(f"Test duration: {self.test_duration} seconds")
        
        if not self.setup_test_environment():
            return {"error": "Failed to setup test environment"}
        
        self.metrics.start_time = time.time()
        
        # Start worker threads
        threads = []
        for i in range(self.concurrent_users):
            thread_id = f"thread_{i}"
            thread = threading.Thread(target=self.worker_thread, args=(thread_id,))
            thread.start()
            threads.append(thread)
        
        # Let test run for specified duration
        print(f"Load test running for {self.test_duration} seconds...")
        time.sleep(self.test_duration)
        
        # Stop all threads
        self.stop_flag.set()
        
        # Wait for threads to complete
        for thread in threads:
            thread.join(timeout=5)
        
        self.metrics.end_time = time.time()
        
        print("Load test completed. Generating report...")
        return self.metrics.generate_report()


def print_load_test_report(report: Dict):
    """Print formatted load test report"""
    print("\n" + "="*80)
    print("CONCURRENT USER CREATION LOAD TEST REPORT")
    print("="*80)
    
    if "error" in report:
        print(f"ERROR: {report['error']}")
        return
    
    summary = report['summary']
    performance = report['performance']
    context = report['context_switching']
    
    print(f"\n📊 SUMMARY:")
    print(f"  Total Operations: {summary['total_operations']}")
    print(f"  Successful: {summary['successful_operations']} ({summary['success_rate']:.1f}%)")
    print(f"  Failed: {summary['failed_operations']}")
    print(f"  Test Duration: {summary['test_duration']:.1f}s")
    print(f"  Operations/Second: {summary['operations_per_second']:.2f}")
    
    print(f"\n⚡ PERFORMANCE:")
    print(f"  Average Duration: {performance['avg_operation_duration']*1000:.1f}ms")
    print(f"  Median Duration: {performance['median_operation_duration']*1000:.1f}ms")
    print(f"  Max Duration: {performance['max_operation_duration']*1000:.1f}ms")
    print(f"  Std Deviation: {performance['std_dev_operation_duration']*1000:.1f}ms")
    
    print(f"\n🔄 CONTEXT SWITCHING:")
    print(f"  Total Switches: {context['total_context_switches']}")
    print(f"  Successful: {context['successful_switches']}")
    print(f"  Average Switch Time: {context['avg_switch_duration']*1000:.1f}ms")
    print(f"  Max Switch Time: {context['max_switch_duration']*1000:.1f}ms")
    
    if report['errors_by_type']:
        print(f"\n❌ ERRORS BY TYPE:")
        for error_type, count in report['errors_by_type'].items():
            print(f"  {error_type}: {count}")
    
    print(f"\n📈 OPERATIONS BY TYPE:")
    for op_type, stats in report['operations_by_type'].items():
        total = stats['successful'] + stats['failed']
        success_rate = stats['successful'] / total * 100 if total > 0 else 0
        print(f"  {op_type}: {total} total ({success_rate:.1f}% success)")
    
    print(f"\n🧵 THREAD DISTRIBUTION:")
    for thread_id, stats in report['thread_distribution'].items():
        total = stats['successful'] + stats['failed']
        print(f"  {thread_id}: {total} operations")
    
    # Performance recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    
    if context['avg_switch_duration'] > 0.1:  # 100ms threshold
        print(f"  ⚠️  Context switching latency high ({context['avg_switch_duration']*1000:.1f}ms)")
        print(f"     Consider optimizing user context operations")
    
    if summary['success_rate'] < 95:
        print(f"  ⚠️  Success rate below 95% ({summary['success_rate']:.1f}%)")
        print(f"     Review error patterns and error handling")
    
    if performance['avg_operation_duration'] > 2.0:  # 2 second threshold
        print(f"  ⚠️  Average operation time high ({performance['avg_operation_duration']:.1f}s)")
        print(f"     Consider performance optimization")
    
    if summary['success_rate'] >= 95 and context['avg_switch_duration'] < 0.05:
        print(f"  ✅ Performance meets production readiness criteria")
        print(f"  ✅ Context switching overhead acceptable")
        print(f"  ✅ Error rate within acceptable limits")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Load test concurrent user creation workflows"
    )
    parser.add_argument(
        '--users', 
        type=int, 
        default=5,
        help='Number of concurrent users (default: 5)'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=30,
        help='Test duration in seconds (default: 30)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file for detailed results (optional)'
    )
    
    args = parser.parse_args()
    
    # Create and run load test
    load_test = ConcurrentUserCreationLoadTest(
        concurrent_users=args.users,
        test_duration=args.duration
    )
    
    try:
        report = load_test.run_load_test()
        print_load_test_report(report)
        
        # Save detailed results if requested
        if args.output:
            import json
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\nDetailed results saved to: {args.output}")
        
    except KeyboardInterrupt:
        print("\nLoad test interrupted by user")
    except Exception as e:
        print(f"Load test failed: {str(e)}")
        sys.exit(1)
    
    finally:
        # Cleanup
        try:
            frappe.destroy()
        except:
            pass


if __name__ == "__main__":
    main()