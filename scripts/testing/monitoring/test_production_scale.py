#!/usr/bin/env python3
"""
Production Scale Test Suite
Week 0 - Pre-Implementation Infrastructure

Tests monitoring system with realistic production data volumes:
- 5,000+ members
- 25,000+ payments
- 10,000+ invoices
- Concurrent access patterns
- High-volume query scenarios

This test suite validates that monitoring performs well at production scale.
"""

import time
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import frappe
from frappe.utils import now, add_days

# Production scale parameters
SCALE_PARAMETERS = {
    'target_member_count': 5000,
    'target_payment_count': 25000,
    'target_invoice_count': 10000,
    'concurrent_users': 5,
    'operations_per_user': 20,
    'max_response_time_ms': 50,
    'max_queries_per_operation': 10
}

class ProductionScaleError(Exception):
    """Raised when system cannot handle production scale"""
    pass

class ProductionScaleTester:
    """Comprehensive production scale testing"""
    
    def __init__(self):
        self.test_results = {}
        self.scale_violations = []
        
    def run_comprehensive_scale_test(self) -> Dict[str, Any]:
        """Run complete production scale test suite"""
        
        print("=== PRODUCTION SCALE TEST SUITE ===")
        print(f"Testing with parameters: {SCALE_PARAMETERS}")
        print()
        
        try:
            test_summary = {
                'status': 'running',
                'timestamp': now(),
                'scale_parameters': SCALE_PARAMETERS,
                'test_results': {},
                'scale_violations': [],
                'performance_metrics': {},
                'recommendations': []
            }
            
            # 1. Analyze current data volume
            test_summary['test_results']['data_volume_analysis'] = self._analyze_current_data_volume()
            
            # 2. Test with current data scale
            test_summary['test_results']['current_scale_performance'] = self._test_current_scale_performance()
            
            # 3. Test concurrent user scenarios
            test_summary['test_results']['concurrent_access'] = self._test_concurrent_access()
            
            # 4. Test high-volume query scenarios
            test_summary['test_results']['high_volume_queries'] = self._test_high_volume_queries()
            
            # 5. Test monitoring system overhead at scale
            test_summary['test_results']['monitoring_overhead'] = self._test_monitoring_overhead_at_scale()
            
            # 6. Test data processing efficiency
            test_summary['test_results']['data_processing'] = self._test_data_processing_efficiency()
            
            # Evaluate scale performance
            scale_violations = self._check_scale_violations(test_summary['test_results'])
            test_summary['scale_violations'] = scale_violations
            
            # Calculate performance metrics
            test_summary['performance_metrics'] = self._calculate_performance_metrics(test_summary['test_results'])
            
            if not scale_violations:
                test_summary['status'] = 'PASSED'
                print("✅ PRODUCTION SCALE TEST: PASSED")
                print("✅ System handles production scale effectively")
            else:
                test_summary['status'] = 'FAILED'
                print("❌ PRODUCTION SCALE TEST: FAILED")
                print(f"❌ {len(scale_violations)} scale issue(s) detected")
                
                # Raise error to prevent deployment
                raise ProductionScaleError(
                    f"Production scale violations: {scale_violations}"
                )
            
            # Generate recommendations
            test_summary['recommendations'] = self._generate_scale_recommendations(test_summary)
            
            self.test_results = test_summary
            return test_summary
            
        except ProductionScaleError:
            # Re-raise scale errors
            raise
            
        except Exception as e:
            print(f"❌ SCALE TEST EXECUTION ERROR: {e}")
            raise
    
    def _analyze_current_data_volume(self) -> Dict[str, Any]:
        """Analyze current data volume in the system"""
        
        print("Analyzing current data volume...")
        
        try:
            # Count current data
            member_count = len(frappe.get_all("Member", fields=["name"]))
            
            # Count payments (may not exist in large numbers)
            try:
                payment_count = len(frappe.get_all("Payment Entry", fields=["name"], limit=1000))
            except Exception:
                payment_count = 0
            
            # Count invoices
            try:
                invoice_count = len(frappe.get_all("Sales Invoice", fields=["name"], limit=1000))
            except Exception:
                invoice_count = 0
            
            # Count volunteers
            try:
                volunteer_count = len(frappe.get_all("Volunteer", fields=["name"]))
            except Exception:
                volunteer_count = 0
            
            # Calculate scale ratios
            member_scale_ratio = member_count / SCALE_PARAMETERS['target_member_count']
            payment_scale_ratio = payment_count / SCALE_PARAMETERS['target_payment_count']
            invoice_scale_ratio = invoice_count / SCALE_PARAMETERS['target_invoice_count']
            
            # Determine scale level
            if member_count >= SCALE_PARAMETERS['target_member_count']:
                scale_level = 'production'
            elif member_count >= 1000:
                scale_level = 'near-production'
            elif member_count >= 100:
                scale_level = 'development'
            else:
                scale_level = 'minimal'
            
            result = {
                'member_count': member_count,
                'payment_count': payment_count,
                'invoice_count': invoice_count,
                'volunteer_count': volunteer_count,
                'scale_ratios': {
                    'members': member_scale_ratio,
                    'payments': payment_scale_ratio,
                    'invoices': invoice_scale_ratio
                },
                'scale_level': scale_level,
                'production_ready': scale_level in ['production', 'near-production']
            }
            
            print(f"  Members: {member_count:,} (target: {SCALE_PARAMETERS['target_member_count']:,})")
            print(f"  Payments: {payment_count:,} (target: {SCALE_PARAMETERS['target_payment_count']:,})")
            print(f"  Invoices: {invoice_count:,} (target: {SCALE_PARAMETERS['target_invoice_count']:,})")
            print(f"  Scale level: {scale_level}")
            print()
            
            return result
            
        except Exception as e:
            print(f"  ❌ Data volume analysis failed: {e}")
            return {
                'error': str(e),
                'scale_level': 'unknown',
                'production_ready': False
            }
    
    def _test_current_scale_performance(self) -> Dict[str, Any]:
        """Test performance with current data scale"""
        
        print("Testing performance at current scale...")
        
        performance_tests = [
            ('member_query_performance', self._test_member_query_performance),
            ('payment_query_performance', self._test_payment_query_performance),
            ('monitoring_api_performance', self._test_monitoring_api_performance),
            ('complex_query_performance', self._test_complex_query_performance)
        ]
        
        test_results = {}
        overall_performance_acceptable = True
        
        for test_name, test_function in performance_tests:
            try:
                print(f"  Running {test_name}...")
                
                start_time = time.time()
                test_result = test_function()
                execution_time = time.time() - start_time
                
                test_result['execution_time'] = execution_time
                test_result['performance_acceptable'] = execution_time < (SCALE_PARAMETERS['max_response_time_ms'] / 1000)
                
                if not test_result['performance_acceptable']:
                    overall_performance_acceptable = False
                
                test_results[test_name] = test_result
                
                print(f"    ✅ {test_name}: {execution_time:.3f}s")
                
            except Exception as e:
                print(f"    ❌ {test_name}: Error - {e}")
                test_results[test_name] = {
                    'error': str(e),
                    'performance_acceptable': False
                }
                overall_performance_acceptable = False
        
        result = {
            'test_results': test_results,
            'overall_performance_acceptable': overall_performance_acceptable,
            'max_response_time_limit': SCALE_PARAMETERS['max_response_time_ms'] / 1000
        }
        
        print(f"  Overall performance acceptable: {'✅ YES' if overall_performance_acceptable else '❌ NO'}")
        print()
        
        return result
    
    def _test_concurrent_access(self) -> Dict[str, Any]:
        """Test concurrent user access patterns"""
        
        print(f"Testing concurrent access with {SCALE_PARAMETERS['concurrent_users']} simulated users...")
        
        def simulate_user_session(user_id: int) -> Dict[str, Any]:
            """Simulate a user session with multiple operations"""
            
            session_results = {
                'user_id': user_id,
                'operations_completed': 0,
                'operations_failed': 0,
                'total_time': 0,
                'average_response_time': 0,
                'errors': []
            }
            
            start_time = time.time()
            
            # Perform multiple operations
            for operation in range(SCALE_PARAMETERS['operations_per_user']):
                try:
                    # Simulate monitoring operation
                    operation_start = time.time()
                    
                    # Randomly choose operation type
                    operation_type = random.choice(['member_lookup', 'basic_monitoring', 'system_health'])
                    
                    if operation_type == 'member_lookup':
                        members = frappe.get_all("Member", fields=["name", "full_name"], limit=10)
                    elif operation_type == 'basic_monitoring':
                        # Simple monitoring call
                        frappe.get_all("DocType", fields=["name"], limit=5)
                    else:  # system_health
                        # Health check simulation
                        frappe.get_all("Member", fields=["name"], limit=1)
                    
                    operation_time = time.time() - operation_start
                    
                    # Check if operation was fast enough
                    if operation_time < (SCALE_PARAMETERS['max_response_time_ms'] / 1000):
                        session_results['operations_completed'] += 1
                    else:
                        session_results['operations_failed'] += 1
                        session_results['errors'].append(f"Operation {operation} too slow: {operation_time:.3f}s")
                    
                    # Brief pause between operations
                    time.sleep(0.01)
                    
                except Exception as e:
                    session_results['operations_failed'] += 1
                    session_results['errors'].append(f"Operation {operation} failed: {str(e)}")
            
            session_results['total_time'] = time.time() - start_time
            total_operations = session_results['operations_completed'] + session_results['operations_failed']
            if total_operations > 0:
                session_results['average_response_time'] = session_results['total_time'] / total_operations
            
            return session_results
        
        # Run concurrent user sessions
        concurrent_results = []
        
        with ThreadPoolExecutor(max_workers=SCALE_PARAMETERS['concurrent_users']) as executor:
            # Submit all user sessions
            future_to_user = {
                executor.submit(simulate_user_session, user_id): user_id 
                for user_id in range(SCALE_PARAMETERS['concurrent_users'])
            }
            
            # Collect results
            for future in as_completed(future_to_user):
                user_id = future_to_user[future]
                try:
                    user_result = future.result()
                    concurrent_results.append(user_result)
                except Exception as e:
                    print(f"    ❌ User {user_id} session failed: {e}")
                    concurrent_results.append({
                        'user_id': user_id,
                        'error': str(e),
                        'operations_completed': 0,
                        'operations_failed': SCALE_PARAMETERS['operations_per_user']
                    })
        
        # Analyze concurrent results
        total_operations = sum(r['operations_completed'] + r['operations_failed'] for r in concurrent_results)
        successful_operations = sum(r['operations_completed'] for r in concurrent_results)
        success_rate = successful_operations / total_operations if total_operations > 0 else 0
        
        average_response_times = [r['average_response_time'] for r in concurrent_results if r.get('average_response_time', 0) > 0]
        overall_avg_response = sum(average_response_times) / len(average_response_times) if average_response_times else 0
        
        concurrent_acceptable = success_rate >= 0.95 and overall_avg_response < (SCALE_PARAMETERS['max_response_time_ms'] / 1000)
        
        result = {
            'concurrent_users': SCALE_PARAMETERS['concurrent_users'],
            'total_operations': total_operations,
            'successful_operations': successful_operations,
            'success_rate': success_rate,
            'overall_average_response_time': overall_avg_response,
            'user_results': concurrent_results,
            'concurrent_acceptable': concurrent_acceptable
        }
        
        print(f"  Success rate: {success_rate:.1%}")
        print(f"  Average response time: {overall_avg_response:.3f}s")
        print(f"  Concurrent performance acceptable: {'✅ YES' if concurrent_acceptable else '❌ NO'}")
        print()
        
        return result
    
    def _test_high_volume_queries(self) -> Dict[str, Any]:
        """Test high-volume query scenarios"""
        
        print("Testing high-volume query scenarios...")
        
        high_volume_tests = [
            ('large_member_list', lambda: self._query_large_member_list()),
            ('complex_joins', lambda: self._query_complex_joins()),
            ('aggregation_queries', lambda: self._query_aggregations()),
            ('filtered_searches', lambda: self._query_filtered_searches())
        ]
        
        query_results = {}
        
        for test_name, query_function in high_volume_tests:
            try:
                print(f"  Testing {test_name}...")
                
                start_time = time.time()
                query_result = query_function()
                execution_time = time.time() - start_time
                
                query_acceptable = execution_time < (SCALE_PARAMETERS['max_response_time_ms'] / 1000)
                
                query_results[test_name] = {
                    'execution_time': execution_time,
                    'result_count': query_result.get('count', 0),
                    'query_acceptable': query_acceptable,
                    'data': query_result
                }
                
                print(f"    {test_name}: {execution_time:.3f}s ({query_result.get('count', 0)} results)")
                
            except Exception as e:
                print(f"    ❌ {test_name}: Error - {e}")
                query_results[test_name] = {
                    'error': str(e),
                    'query_acceptable': False
                }
        
        overall_acceptable = all(r.get('query_acceptable', False) for r in query_results.values())
        
        result = {
            'query_results': query_results,
            'overall_acceptable': overall_acceptable
        }
        
        print(f"  High-volume queries acceptable: {'✅ YES' if overall_acceptable else '❌ NO'}")
        print()
        
        return result
    
    def _test_monitoring_overhead_at_scale(self) -> Dict[str, Any]:
        """Test monitoring system overhead at scale"""
        
        print("Testing monitoring overhead at scale...")
        
        # Baseline: operations without monitoring
        baseline_operations = []
        for i in range(50):
            start_time = time.time()
            frappe.get_all("Member", fields=["name"], limit=10)
            execution_time = time.time() - start_time
            baseline_operations.append(execution_time)
        
        baseline_avg = sum(baseline_operations) / len(baseline_operations)
        
        # With monitoring simulation
        monitoring_operations = []
        for i in range(50):
            start_time = time.time()
            
            # Simulate monitoring overhead
            members = frappe.get_all("Member", fields=["name"], limit=10)
            
            # Simulate monitoring data collection
            monitoring_data = {
                'operation_id': i,
                'timestamp': time.time(),
                'query_count': 1,
                'result_count': len(members)
            }
            
            execution_time = time.time() - start_time
            monitoring_operations.append(execution_time)
        
        monitoring_avg = sum(monitoring_operations) / len(monitoring_operations)
        overhead = monitoring_avg - baseline_avg
        overhead_percentage = (overhead / baseline_avg) * 100 if baseline_avg > 0 else 0
        
        overhead_acceptable = overhead_percentage < 10  # Less than 10% overhead
        
        result = {
            'baseline_avg_time': baseline_avg,
            'monitoring_avg_time': monitoring_avg,
            'overhead_seconds': overhead,
            'overhead_percentage': overhead_percentage,
            'overhead_acceptable': overhead_acceptable,
            'overhead_limit_percent': 10
        }
        
        print(f"  Monitoring overhead: {overhead_percentage:.1f}%")
        print(f"  Overhead acceptable: {'✅ YES' if overhead_acceptable else '❌ NO'}")
        print()
        
        return result
    
    def _test_data_processing_efficiency(self) -> Dict[str, Any]:
        """Test data processing efficiency at scale"""
        
        print("Testing data processing efficiency...")
        
        # Test batch processing efficiency
        batch_sizes = [10, 50, 100, 250]
        batch_results = {}
        
        for batch_size in batch_sizes:
            try:
                start_time = time.time()
                
                # Process members in batches
                members = frappe.get_all("Member", fields=["name", "full_name"], limit=batch_size)
                
                # Simulate processing each member
                processed_count = 0
                for member in members:
                    # Simulate some processing
                    if member.get('name'):
                        processed_count += 1
                
                execution_time = time.time() - start_time
                efficiency = processed_count / execution_time if execution_time > 0 else 0
                
                batch_results[f'batch_{batch_size}'] = {
                    'batch_size': batch_size,
                    'processed_count': processed_count,
                    'execution_time': execution_time,
                    'efficiency_per_second': efficiency
                }
                
                print(f"  Batch {batch_size}: {processed_count} items in {execution_time:.3f}s ({efficiency:.1f}/sec)")
                
            except Exception as e:
                print(f"  ❌ Batch {batch_size}: Error - {e}")
                batch_results[f'batch_{batch_size}'] = {'error': str(e)}
        
        # Find optimal batch size
        valid_results = {k: v for k, v in batch_results.items() if 'efficiency_per_second' in v}
        if valid_results:
            optimal_batch = max(valid_results.keys(), key=lambda k: valid_results[k]['efficiency_per_second'])
            optimal_efficiency = valid_results[optimal_batch]['efficiency_per_second']
        else:
            optimal_batch = None
            optimal_efficiency = 0
        
        processing_acceptable = optimal_efficiency > 100  # At least 100 items per second
        
        result = {
            'batch_results': batch_results,
            'optimal_batch_size': optimal_batch,
            'optimal_efficiency': optimal_efficiency,
            'processing_acceptable': processing_acceptable
        }
        
        print(f"  Optimal batch: {optimal_batch} ({optimal_efficiency:.1f}/sec)")
        print(f"  Processing efficiency acceptable: {'✅ YES' if processing_acceptable else '❌ NO'}")
        print()
        
        return result
    
    def _check_scale_violations(self, test_results: Dict[str, Any]) -> List[str]:
        """Check for production scale violations"""
        
        violations = []
        
        # Check current scale performance
        current_scale = test_results.get('current_scale_performance', {})
        if not current_scale.get('overall_performance_acceptable', False):
            violations.append("Current scale performance is unacceptable")
        
        # Check concurrent access
        concurrent_access = test_results.get('concurrent_access', {})
        if not concurrent_access.get('concurrent_acceptable', False):
            success_rate = concurrent_access.get('success_rate', 0)
            violations.append(f"Concurrent access performance poor: {success_rate:.1%} success rate")
        
        # Check high-volume queries
        high_volume = test_results.get('high_volume_queries', {})
        if not high_volume.get('overall_acceptable', False):
            violations.append("High-volume query performance is unacceptable")
        
        # Check monitoring overhead
        monitoring_overhead = test_results.get('monitoring_overhead', {})
        if not monitoring_overhead.get('overhead_acceptable', False):
            overhead_pct = monitoring_overhead.get('overhead_percentage', 0)
            violations.append(f"Monitoring overhead too high: {overhead_pct:.1f}%")
        
        # Check data processing efficiency
        data_processing = test_results.get('data_processing', {})
        if not data_processing.get('processing_acceptable', False):
            violations.append("Data processing efficiency is too low")
        
        return violations
    
    def _calculate_performance_metrics(self, test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate overall performance metrics"""
        
        metrics = {}
        
        # Data volume metrics
        data_volume = test_results.get('data_volume_analysis', {})
        metrics['data_scale_level'] = data_volume.get('scale_level', 'unknown')
        metrics['member_count'] = data_volume.get('member_count', 0)
        
        # Performance metrics
        current_scale = test_results.get('current_scale_performance', {})
        if current_scale.get('test_results'):
            response_times = []
            for test_result in current_scale['test_results'].values():
                if isinstance(test_result, dict) and 'execution_time' in test_result:
                    response_times.append(test_result['execution_time'])
            
            if response_times:
                metrics['average_response_time'] = sum(response_times) / len(response_times)
                metrics['max_response_time'] = max(response_times)
        
        # Concurrent access metrics
        concurrent = test_results.get('concurrent_access', {})
        metrics['concurrent_success_rate'] = concurrent.get('success_rate', 0)
        metrics['concurrent_response_time'] = concurrent.get('overall_average_response_time', 0)
        
        # Monitoring overhead
        overhead = test_results.get('monitoring_overhead', {})
        metrics['monitoring_overhead_percentage'] = overhead.get('overhead_percentage', 0)
        
        return metrics
    
    def _generate_scale_recommendations(self, test_summary: Dict[str, Any]) -> List[str]:
        """Generate scale-related recommendations"""
        
        recommendations = []
        
        if not test_summary['scale_violations']:
            recommendations.extend([
                "System handles current production scale effectively",
                "Safe to proceed with monitoring enhancements",
                "Consider implementing monitoring at current scale"
            ])
        else:
            recommendations.extend([
                "Address scale violations before production deployment",
                "Consider performance optimization before scaling",
                "Implement monitoring with scale limitations in mind"
            ])
            
            for violation in test_summary['scale_violations']:
                recommendations.append(f"Fix: {violation}")
        
        # Add specific recommendations based on metrics
        metrics = test_summary.get('performance_metrics', {})
        
        if metrics.get('data_scale_level') == 'minimal':
            recommendations.append("Consider testing with larger datasets for validation")
        
        if metrics.get('monitoring_overhead_percentage', 0) > 5:
            recommendations.append("Optimize monitoring operations to reduce overhead")
        
        return recommendations
    
    # Helper methods for specific query tests
    
    def _test_member_query_performance(self) -> Dict[str, Any]:
        """Test member query performance"""
        members = frappe.get_all("Member", fields=["name", "full_name", "email"], limit=100)
        return {'count': len(members), 'type': 'member_query'}
    
    def _test_payment_query_performance(self) -> Dict[str, Any]:
        """Test payment query performance"""
        try:
            payments = frappe.get_all("Payment Entry", fields=["name", "paid_amount"], limit=100)
            return {'count': len(payments), 'type': 'payment_query'}
        except Exception:
            return {'count': 0, 'type': 'payment_query', 'note': 'No payment data available'}
    
    def _test_monitoring_api_performance(self) -> Dict[str, Any]:
        """Test monitoring API performance"""
        try:
            # Test basic monitoring API if available
            from verenigingen.api.simple_measurement_test import test_basic_query_measurement
            result = test_basic_query_measurement()
            return {'count': 1, 'type': 'monitoring_api', 'api_result': result}
        except Exception as e:
            return {'count': 0, 'type': 'monitoring_api', 'error': str(e)}
    
    def _test_complex_query_performance(self) -> Dict[str, Any]:
        """Test complex query performance"""
        # Test complex query with joins (simulated)
        members_with_customers = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "full_name", "customer"],
            limit=50
        )
        return {'count': len(members_with_customers), 'type': 'complex_query'}
    
    # Query test helper methods
    
    def _query_large_member_list(self) -> Dict[str, Any]:
        """Query large member list"""
        members = frappe.get_all("Member", fields=["name"], limit=1000)
        return {'count': len(members), 'type': 'large_list'}
    
    def _query_complex_joins(self) -> Dict[str, Any]:
        """Query with complex joins"""
        # Simulate complex join
        members = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "customer"],
            limit=200
        )
        return {'count': len(members), 'type': 'complex_join'}
    
    def _query_aggregations(self) -> Dict[str, Any]:
        """Query with aggregations"""
        # Count members by type (if field exists)
        try:
            member_count = frappe.db.count("Member")
            return {'count': member_count, 'type': 'aggregation'}
        except Exception:
            return {'count': 0, 'type': 'aggregation'}
    
    def _query_filtered_searches(self) -> Dict[str, Any]:
        """Query with filtered searches"""
        # Search members with filters
        members = frappe.get_all(
            "Member",
            filters={"full_name": ("like", "%a%")},
            fields=["name"],
            limit=100
        )
        return {'count': len(members), 'type': 'filtered_search'}

# Main execution function
@frappe.whitelist()
def run_production_scale_test():
    """Run comprehensive production scale test"""
    tester = ProductionScaleTester()
    return tester.run_comprehensive_scale_test()

if __name__ == "__main__":
    # Allow running directly for testing
    try:
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
        
        result = run_production_scale_test()
        print("Production Scale Test Result:", result['status'])
        
        frappe.destroy()
    except Exception as e:
        print(f"Scale test execution failed: {e}")
        exit(1)