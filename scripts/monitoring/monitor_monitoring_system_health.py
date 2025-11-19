"""
Monitoring System Health Monitor
Phase 0 - Production Deployment

Meta-monitoring to ensure the monitoring system doesn't degrade performance.
Implements the revised success criteria from feedback synthesis.
"""

import json
import time
import psutil
from typing import Dict, Any
import frappe
from frappe.utils import now, get_datetime


@frappe.whitelist()
def monitor_monitoring_system_health() -> Dict[str, Any]:
    """
    Meta-monitoring to ensure monitoring doesn't degrade system performance
    
    Revised Success Criteria:
    - All APIs respond within 0.015s (was 0.050s)
    - Health score maintains ≥95 (was ≥90)
    - Query count stays ≤5 per operation (was ≤10)
    - Memory usage under 100MB sustained
    - Zero performance regression from baseline
    
    Returns:
        Dict containing monitoring system health status
    """
    
    print("🔍 Monitoring the Monitoring System...")
    
    health_report = {
        'timestamp': now(),
        'status': 'healthy',
        'issues': [],
        'metrics': {},
        'recommendations': []
    }
    
    try:
        # Test 1: API Response Time Check
        api_health = _check_api_response_times()
        health_report['metrics']['api_response_times'] = api_health
        
        if api_health['max_response_time'] > 0.015:
            health_report['issues'].append({
                'type': 'performance',
                'severity': 'high',
                'message': f"API response time {api_health['max_response_time']:.4f}s exceeds 0.015s limit"
            })
            health_report['status'] = 'degraded'
        
        # Test 2: Memory Usage Check
        memory_health = _check_memory_usage()
        health_report['metrics']['memory_usage'] = memory_health
        
        if memory_health['monitoring_memory_mb'] > 100:
            health_report['issues'].append({
                'type': 'resource',
                'severity': 'high',
                'message': f"Monitoring memory usage {memory_health['monitoring_memory_mb']:.1f}MB exceeds 100MB limit"
            })
            health_report['status'] = 'degraded'
        
        # Test 3: Query Count Validation
        query_health = _check_query_efficiency()
        health_report['metrics']['query_efficiency'] = query_health
        
        if query_health['avg_queries_per_operation'] > 5:
            health_report['issues'].append({
                'type': 'performance',
                'severity': 'medium',
                'message': f"Query count {query_health['avg_queries_per_operation']:.1f} exceeds 5 per operation"
            })
            if health_report['status'] == 'healthy':
                health_report['status'] = 'warning'
        
        # Test 4: Health Score Check
        health_score = _check_overall_health_score()
        health_report['metrics']['health_score'] = health_score
        
        if health_score['current_score'] < 95:
            health_report['issues'].append({
                'type': 'performance',
                'severity': 'high',
                'message': f"Health score {health_score['current_score']:.1f}/100 below 95 minimum"
            })
            health_report['status'] = 'degraded'
        
        # Test 5: Monitoring Overhead Check
        overhead_health = _check_monitoring_overhead()
        health_report['metrics']['monitoring_overhead'] = overhead_health
        
        if overhead_health['overhead_percentage'] > 5:
            health_report['issues'].append({
                'type': 'efficiency',
                'severity': 'medium',
                'message': f"Monitoring overhead {overhead_health['overhead_percentage']:.1f}% exceeds 5% limit"
            })
            if health_report['status'] == 'healthy':
                health_report['status'] = 'warning'
        
        # Test 6: Baseline Regression Check
        regression_health = _check_baseline_regression()
        health_report['metrics']['baseline_regression'] = regression_health
        
        if regression_health['has_regression']:
            health_report['issues'].append({
                'type': 'regression',
                'severity': 'critical',
                'message': f"Performance regression detected: {regression_health['regression_details']}"
            })
            health_report['status'] = 'critical'
        
        # Generate recommendations
        health_report['recommendations'] = _generate_health_recommendations(health_report)
        
        # Log health status
        _log_health_status(health_report)
        
        print(f"✅ Monitoring Health Check Complete: {health_report['status']}")
        
        return health_report
        
    except Exception as e:
        frappe.log_error(f"Monitoring health check failed: {str(e)}")
        return {
            'timestamp': now(),
            'status': 'error',
            'error': str(e),
            'issues': [{
                'type': 'system',
                'severity': 'critical',
                'message': f"Health check system failure: {str(e)}"
            }]
        }


def _check_api_response_times() -> Dict[str, Any]:
    """Check all monitoring API response times"""
    
    apis_to_test = [
        ('basic_measurement', 'verenigingen.api.simple_measurement_test.test_basic_query_measurement'),
        ('member_performance', 'verenigingen.api.performance_measurement_api.measure_member_performance')
    ]
    
    response_times = []
    api_results = {}
    
    # Get test member
    test_member = _get_test_member()
    
    for api_name, api_path in apis_to_test:
        try:
            module_path, function_name = api_path.rsplit('.', 1)
            module = frappe.get_module(module_path)
            api_function = getattr(module, function_name)
            
            # Measure response time
            start_time = time.time()
            
            if api_name == 'member_performance' and test_member:
                result = api_function(test_member)
            else:
                result = api_function()
            
            response_time = time.time() - start_time
            response_times.append(response_time)
            
            api_results[api_name] = {
                'response_time': response_time,
                'success': result.get('success', True) if isinstance(result, dict) else True,
                'error': result.get('error') if isinstance(result, dict) else None
            }
            
        except Exception as e:
            api_results[api_name] = {
                'response_time': 999,  # High penalty for failure
                'success': False,
                'error': str(e)
            }
            response_times.append(999)
    
    return {
        'max_response_time': max(response_times) if response_times else 0,
        'avg_response_time': sum(response_times) / len(response_times) if response_times else 0,
        'api_details': api_results,
        'total_apis_tested': len(apis_to_test)
    }


def _check_memory_usage() -> Dict[str, Any]:
    """Check memory usage of monitoring operations"""
    
    try:
        # Get current process memory
        process = psutil.Process()
        memory_before = process.memory_info().rss / 1024 / 1024  # MB
        
        # Run monitoring operations
        from verenigingen.api.simple_measurement_test import test_basic_query_measurement
        test_basic_query_measurement()
        
        memory_after = process.memory_info().rss / 1024 / 1024  # MB
        monitoring_memory = memory_after - memory_before
        
        return {
            'total_memory_mb': memory_after,
            'monitoring_memory_mb': max(monitoring_memory, 0),  # Don't report negative
            'memory_efficient': monitoring_memory < 10  # Less than 10MB overhead
        }
        
    except Exception as e:
        return {
            'total_memory_mb': 0,
            'monitoring_memory_mb': 0,
            'memory_efficient': False,
            'error': str(e)
        }


def _check_query_efficiency() -> Dict[str, Any]:
    """Check query efficiency of monitoring operations"""
    
    try:
        from verenigingen.api.simple_measurement_test import test_basic_query_measurement
        
        # Run measurement and extract query data
        result = test_basic_query_measurement()
        
        query_count = result.get('query_count', 0)
        execution_time = result.get('execution_time', 0)
        
        # Calculate efficiency metrics
        queries_per_second = query_count / execution_time if execution_time > 0 else 0
        
        return {
            'avg_queries_per_operation': query_count,
            'execution_time': execution_time,
            'queries_per_second': queries_per_second,
            'efficient': query_count <= 5
        }
        
    except Exception as e:
        return {
            'avg_queries_per_operation': 999,  # High penalty for failure
            'execution_time': 0,
            'queries_per_second': 0,
            'efficient': False,
            'error': str(e)
        }


def _check_overall_health_score() -> Dict[str, Any]:
    """Check overall system health score"""
    
    try:
        from verenigingen.api.simple_measurement_test import test_basic_query_measurement
        
        result = test_basic_query_measurement()
        health_score = result.get('health_score', 0)
        
        return {
            'current_score': health_score,
            'meets_minimum': health_score >= 95,
            'score_level': _classify_health_score(health_score)
        }
        
    except Exception as e:
        return {
            'current_score': 0,
            'meets_minimum': False,
            'score_level': 'critical',
            'error': str(e)
        }


def _check_monitoring_overhead() -> Dict[str, Any]:
    """Check overhead introduced by monitoring system"""
    
    try:
        # Measure baseline operation without monitoring
        test_member = _get_test_member()
        if not test_member:
            return {'overhead_percentage': 0, 'low_overhead': True}
        
        start_time = time.time()
        frappe.get_doc("Member", test_member)
        baseline_time = time.time() - start_time
        
        # Measure with monitoring
        from verenigingen.api.performance_measurement_api import measure_member_performance
        start_time = time.time()
        measure_member_performance(test_member)
        monitored_time = time.time() - start_time
        
        # Calculate overhead
        overhead = (monitored_time - baseline_time) / baseline_time if baseline_time > 0 else 0
        overhead_percentage = overhead * 100
        
        return {
            'baseline_time': baseline_time,
            'monitored_time': monitored_time,
            'overhead_percentage': overhead_percentage,
            'low_overhead': overhead_percentage <= 5
        }
        
    except Exception as e:
        return {
            'baseline_time': 0,
            'monitored_time': 0,
            'overhead_percentage': 100,  # High penalty for failure
            'low_overhead': False,
            'error': str(e)
        }


def _check_baseline_regression() -> Dict[str, Any]:
    """Check for regression from established baseline"""
    
    try:
        from scripts.monitoring.establish_baseline import get_current_baseline
        
        baseline = get_current_baseline()
        
        # Run current measurement
        from verenigingen.api.simple_measurement_test import test_basic_query_measurement
        current = test_basic_query_measurement()
        
        # Check for regression
        regressions = []
        
        # Health score regression (≥5% drop)
        baseline_health = baseline.get('health_score_avg', 95)
        current_health = current.get('health_score', 95)
        if current_health < baseline_health * 0.95:
            regressions.append(f"Health score: {current_health:.1f} < {baseline_health * 0.95:.1f}")
        
        # Query count regression (≥10% increase)
        baseline_queries = baseline.get('query_count_avg', 4.4)
        current_queries = current.get('query_count', 4.4)
        if current_queries > baseline_queries * 1.10:
            regressions.append(f"Query count: {current_queries:.1f} > {baseline_queries * 1.10:.1f}")
        
        # Response time regression (≥20% increase)
        baseline_time = baseline.get('response_time_avg', 0.011)
        current_time = current.get('execution_time', 0.011)
        if current_time > baseline_time * 1.20:
            regressions.append(f"Response time: {current_time:.4f}s > {baseline_time * 1.20:.4f}s")
        
        return {
            'has_regression': len(regressions) > 0,
            'regression_count': len(regressions),
            'regression_details': '; '.join(regressions),
            'baseline_timestamp': baseline.get('timestamp', 'unknown')
        }
        
    except FileNotFoundError:
        return {
            'has_regression': False,
            'regression_count': 0,
            'regression_details': 'No baseline available for comparison',
            'baseline_timestamp': 'none'
        }
    except Exception as e:
        return {
            'has_regression': True,  # Assume regression on error
            'regression_count': 1,
            'regression_details': f'Baseline check failed: {str(e)}',
            'baseline_timestamp': 'error'
        }


def _get_test_member() -> str:
    """Get a test member for monitoring checks"""
    test_members = frappe.get_all("Member", 
        filters={"customer": ("!=", "")}, 
        fields=["name"], 
        limit=1
    )
    return test_members[0].name if test_members else None


def _classify_health_score(score: float) -> str:
    """Classify health score into categories"""
    if score >= 95:
        return 'excellent'
    elif score >= 90:
        return 'good'
    elif score >= 80:
        return 'fair'
    elif score >= 70:
        return 'poor'
    else:
        return 'critical'


def _generate_health_recommendations(health_report: Dict[str, Any]) -> List[str]:
    """Generate recommendations based on health report"""
    recommendations = []
    
    # Response time recommendations
    api_health = health_report['metrics'].get('api_response_times', {})
    if api_health.get('max_response_time', 0) > 0.015:
        recommendations.append("Consider optimizing API query patterns to reduce response time")
    
    # Memory recommendations
    memory_health = health_report['metrics'].get('memory_usage', {})
    if memory_health.get('monitoring_memory_mb', 0) > 50:
        recommendations.append("Monitor memory usage - consider implementing data cleanup")
    
    # Query efficiency recommendations
    query_health = health_report['metrics'].get('query_efficiency', {})
    if query_health.get('avg_queries_per_operation', 0) > 5:
        recommendations.append("Review query patterns for potential N+1 issues")
    
    # Health score recommendations
    health_score = health_report['metrics'].get('health_score', {})
    if health_score.get('current_score', 0) < 95:
        recommendations.append("Investigate performance bottlenecks to improve health score")
    
    # Add general recommendations
    if health_report['status'] in ['degraded', 'critical']:
        recommendations.append("Consider pausing monitoring enhancements until issues are resolved")
    
    if not recommendations:
        recommendations.append("Monitoring system is performing optimally")
    
    return recommendations


def _log_health_status(health_report: Dict[str, Any]):
    """Log health status for monitoring"""
    
    log_entry = {
        'timestamp': health_report['timestamp'],
        'status': health_report['status'],
        'issue_count': len(health_report['issues']),
        'metrics_summary': {
            'max_response_time': health_report['metrics'].get('api_response_times', {}).get('max_response_time'),
            'memory_usage_mb': health_report['metrics'].get('memory_usage', {}).get('monitoring_memory_mb'),
            'query_count': health_report['metrics'].get('query_efficiency', {}).get('avg_queries_per_operation'),
            'health_score': health_report['metrics'].get('health_score', {}).get('current_score')
        }
    }
    
    frappe.logger().info(f"Monitoring System Health: {json.dumps(log_entry, default=str)}")
    
    # Alert on critical issues
    if health_report['status'] == 'critical':
        frappe.logger().error(f"CRITICAL: Monitoring system health issues detected: {health_report['issues']}")


if __name__ == "__main__":
    # CLI execution
    frappe.init()
    frappe.connect()
    result = monitor_monitoring_system_health()
    print(json.dumps(result, indent=2, default=str))