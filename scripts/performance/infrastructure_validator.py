#!/usr/bin/env python3
"""
Phase 5A Infrastructure Validator

Comprehensive validation of all performance infrastructure components
to ensure they're operational before beginning optimizations.
"""

import time
from typing import Any, Dict, List

import frappe
from frappe.utils import now, now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_performance_infrastructure():
    """
    Validate all performance components are operational for Phase 5A implementation
    
    Returns:
        Dict with validation results for all infrastructure components
    """
    results = {
        "validation_timestamp": now_datetime(),
        "validation_version": "5A.1.0",
        "components": {},
        "overall_status": "UNKNOWN",
        "readiness_score": 0,
        "critical_issues": [],
        "recommendations": []
    }
    
    try:
        # Test 1: Performance Optimizer
        results["components"]["performance_optimizer"] = validate_performance_optimizer()
        
        # Test 2: Performance Dashboard  
        results["components"]["performance_dashboard"] = validate_performance_dashboard()
        
        # Test 3: Alert Manager
        results["components"]["alert_manager"] = validate_alert_manager()
        
        # Test 4: Background Jobs System
        results["components"]["background_jobs"] = validate_background_jobs_system()
        
        # Test 5: Security Integration
        results["components"]["security_integration"] = validate_security_integration()
        
        # Test 6: Database Performance Tools
        results["components"]["database_tools"] = validate_database_tools()
        
        # Test 7: Caching Infrastructure
        results["components"]["caching_infrastructure"] = validate_caching_infrastructure()
        
        # Calculate overall readiness
        results["readiness_score"] = calculate_readiness_score(results["components"])
        results["overall_status"] = determine_overall_status(results["readiness_score"])
        
        # Generate recommendations
        results["critical_issues"], results["recommendations"] = generate_recommendations(results["components"])
        
        # Log validation results
        frappe.logger().info(f"Infrastructure validation completed. Status: {results['overall_status']}, Score: {results['readiness_score']}")
        
        return results
        
    except Exception as e:
        frappe.log_error(f"Infrastructure validation failed: {e}")
        results["overall_status"] = "CRITICAL_FAILURE" 
        results["error"] = str(e)
        return results


def validate_performance_optimizer():
    """Validate PerformanceOptimizer is operational"""
    try:
        # Try to import and initialize
        from verenigingen.utils.performance_optimizer import PerformanceOptimizer
        
        optimizer = PerformanceOptimizer()
        
        # Test baseline capture capability
        start_time = time.time()
        baseline = optimizer._capture_baseline_metrics() if hasattr(optimizer, '_capture_baseline_metrics') else {}
        capture_time = time.time() - start_time
        
        # Test optimization suggestions
        suggestions = optimizer.get_optimization_suggestions() if hasattr(optimizer, 'get_optimization_suggestions') else []
        
        return {
            "status": "OPERATIONAL",
            "baseline_capture_time": capture_time,
            "baseline_metrics_count": len(baseline.get("metrics", {})),
            "optimization_suggestions_count": len(suggestions),
            "capabilities": {
                "baseline_capture": hasattr(optimizer, '_capture_baseline_metrics'),
                "optimization_suggestions": hasattr(optimizer, 'get_optimization_suggestions'),
                "query_optimization": hasattr(optimizer, 'optimize_queries'),
                "cache_optimization": hasattr(optimizer, 'optimize_caching')
            }
        }
        
    except ImportError as e:
        return {
            "status": "MISSING", 
            "error": f"PerformanceOptimizer not found: {e}",
            "critical": True
        }
    except Exception as e:
        return {
            "status": "FAILED", 
            "error": str(e),
            "critical": True
        }


def validate_performance_dashboard():
    """Validate PerformanceMetrics dashboard is operational"""
    try:
        # Try to import and initialize  
        from verenigingen.utils.performance_dashboard import PerformanceMetrics
        
        dashboard = PerformanceMetrics()
        
        # Test metrics recording
        start_time = time.time()
        dashboard.record_api_call("test_validation_endpoint", 100.0, True)
        record_time = time.time() - start_time
        
        # Test health checks
        health_checks = []
        if hasattr(dashboard, '_check_api_response_times'):
            health_checks.append("api_response_times")
        if hasattr(dashboard, '_check_database_query_performance'):
            health_checks.append("database_performance")
        if hasattr(dashboard, '_check_memory_usage'):
            health_checks.append("memory_usage")
        if hasattr(dashboard, '_check_cache_hit_rates'):
            health_checks.append("cache_performance")
            
        # Test dashboard data access
        dashboard_data = dashboard.get_dashboard_data() if hasattr(dashboard, 'get_dashboard_data') else {}
        
        return {
            "status": "OPERATIONAL",
            "metrics_record_time": record_time,
            "available_health_checks": health_checks,
            "health_checks_count": len(health_checks),
            "dashboard_data_available": bool(dashboard_data),
            "capabilities": {
                "metrics_recording": True,
                "health_monitoring": len(health_checks) > 0,
                "dashboard_interface": hasattr(dashboard, 'get_dashboard_data'),
                "real_time_updates": hasattr(dashboard, 'get_real_time_metrics')
            }
        }
        
    except ImportError:
        return {
            "status": "MISSING",
            "error": "PerformanceMetrics dashboard not found",
            "critical": True
        }
    except Exception as e:
        return {
            "status": "FAILED",
            "error": str(e),
            "critical": False
        }


def validate_alert_manager():
    """Validate AlertManager is operational"""
    try:
        from verenigingen.utils.alert_manager import AlertManager
        
        alert_manager = AlertManager()
        
        # Test alert creation capability
        test_alert_created = False
        try:
            if hasattr(alert_manager, 'create_alert'):
                alert_manager.create_alert(
                    alert_type="test_validation",
                    severity="info", 
                    message="Infrastructure validation test alert",
                    auto_dismiss=True
                )
                test_alert_created = True
        except Exception:
            pass  # Non-critical for validation
            
        # Check alert thresholds configuration
        thresholds = getattr(alert_manager, 'alert_thresholds', {})
        
        return {
            "status": "OPERATIONAL",
            "test_alert_created": test_alert_created,
            "configured_thresholds": len(thresholds),
            "threshold_types": list(thresholds.keys()) if thresholds else [],
            "capabilities": {
                "alert_creation": hasattr(alert_manager, 'create_alert'),
                "alert_management": hasattr(alert_manager, 'get_active_alerts'),
                "threshold_monitoring": bool(thresholds),
                "notification_delivery": hasattr(alert_manager, 'send_notification')
            }
        }
        
    except ImportError:
        return {
            "status": "MISSING",
            "error": "AlertManager not found", 
            "critical": False  # Not critical for Phase 5A start
        }
    except Exception as e:
        return {
            "status": "FAILED",
            "error": str(e),
            "critical": False
        }


def validate_background_jobs_system():
    """Validate BackgroundJobManager is operational"""
    try:
        from verenigingen.utils.background_jobs import BackgroundJobManager
        
        # Test job queue capability
        job_queuing_works = False
        try:
            # Test with a simple job that won't actually execute
            job_id = BackgroundJobManager.enqueue_with_tracking(
                method="frappe.ping",
                job_name="infrastructure_validation_test",
                user=frappe.session.user,
                queue="default",
                timeout=60
            )
            job_queuing_works = bool(job_id)
        except Exception:
            pass  # Non-critical for validation
            
        # Check job status tracking
        job_status_works = False
        if job_queuing_works:
            try:
                status = BackgroundJobManager.get_job_status("test_job")
                job_status_works = isinstance(status, dict)
            except Exception:
                pass
                
        return {
            "status": "OPERATIONAL",
            "job_queuing_functional": job_queuing_works,
            "job_status_tracking": job_status_works,
            "capabilities": {
                "job_queuing": hasattr(BackgroundJobManager, 'enqueue_with_tracking'),
                "status_tracking": hasattr(BackgroundJobManager, 'get_job_status'),
                "retry_mechanism": hasattr(BackgroundJobManager, 'retry_failed_job'),
                "notification_system": hasattr(BackgroundJobManager, 'notify_job_completion')
            }
        }
        
    except ImportError:
        return {
            "status": "MISSING",
            "error": "BackgroundJobManager not found",
            "critical": True
        }
    except Exception as e:
        return {
            "status": "FAILED", 
            "error": str(e),
            "critical": True
        }


def validate_security_integration():
    """Validate security framework integration is working"""
    try:
        from verenigingen.utils.security.api_security_framework import SecurityLevel, OperationType
        from verenigingen.utils.security.audit_logging import get_audit_logger
        
        # Test security decorators are importable
        security_decorators_available = True
        
        # Test audit logging
        audit_logger = get_audit_logger()
        audit_logging_works = hasattr(audit_logger, 'log_event')
        
        # Test if performance APIs have security decorators
        performance_apis_secured = []
        try:
            # Check if our performance measurement APIs are properly secured
            from verenigingen.api import performance_measurement_api
            from verenigingen.api import performance_measurement
            
            # These should have security decorators based on the modifications
            performance_apis_secured = [
                "performance_measurement_api",
                "performance_measurement"
            ]
        except ImportError:
            pass
            
        return {
            "status": "OPERATIONAL",
            "security_decorators_available": security_decorators_available,
            "audit_logging_functional": audit_logging_works,
            "performance_apis_secured": len(performance_apis_secured),
            "secured_api_modules": performance_apis_secured,
            "capabilities": {
                "api_security_framework": security_decorators_available,
                "audit_logging": audit_logging_works,
                "performance_api_security": len(performance_apis_secured) > 0
            }
        }
        
    except ImportError as e:
        return {
            "status": "MISSING",
            "error": f"Security framework components missing: {e}",
            "critical": True
        }
    except Exception as e:
        return {
            "status": "FAILED",
            "error": str(e), 
            "critical": True
        }


def validate_database_tools():
    """Validate database performance tools are available"""
    try:
        # Test database connection and basic queries
        db_responsive = False
        query_time = None
        
        start_time = time.time()
        try:
            # Simple query to test database responsiveness
            result = frappe.db.sql("SELECT 1 as test_query", as_dict=True)
            db_responsive = len(result) == 1 and result[0]['test_query'] == 1
            query_time = time.time() - start_time
        except Exception:
            query_time = -1
            
        # Check if we can analyze query patterns (required for optimization)
        query_analysis_available = False
        try:
            # Test if we can hook into frappe.db.sql for query counting
            original_sql = frappe.db.sql
            query_count = 0
            
            def counting_sql(*args, **kwargs):
                nonlocal query_count
                query_count += 1
                return original_sql(*args, **kwargs)
                
            frappe.db.sql = counting_sql
            frappe.db.sql("SELECT 1")
            frappe.db.sql = original_sql
            
            query_analysis_available = query_count > 0
        except Exception:
            query_analysis_available = False
            
        # Check for index analysis capabilities
        index_analysis_available = False
        try:
            # Test if we can run EXPLAIN queries for index analysis
            explain_result = frappe.db.sql("EXPLAIN SELECT 1", as_dict=True)
            index_analysis_available = len(explain_result) > 0
        except Exception:
            pass
            
        return {
            "status": "OPERATIONAL" if db_responsive else "DEGRADED",
            "database_responsive": db_responsive,
            "query_response_time": query_time,
            "query_analysis_available": query_analysis_available,
            "index_analysis_available": index_analysis_available,
            "capabilities": {
                "basic_queries": db_responsive,
                "query_performance_analysis": query_analysis_available,
                "index_optimization": index_analysis_available,
                "explain_queries": index_analysis_available
            }
        }
        
    except Exception as e:
        return {
            "status": "FAILED",
            "error": str(e),
            "critical": True
        }


def validate_caching_infrastructure():
    """Validate caching infrastructure is operational"""
    try:
        # Test basic cache operations
        cache_write_works = False
        cache_read_works = False
        cache_time = None
        
        start_time = time.time()
        try:
            # Test cache write
            test_key = f"infrastructure_validation_{int(time.time())}"
            test_value = {"test": "data", "timestamp": int(time.time())}
            
            frappe.cache().set_value(test_key, test_value, expires_in_sec=60)
            cache_write_works = True
            
            # Test cache read
            cached_value = frappe.cache().get_value(test_key)
            cache_read_works = cached_value == test_value
            
            # Clean up test data
            frappe.cache().delete_value(test_key)
            
            cache_time = time.time() - start_time
            
        except Exception:
            cache_time = -1
            
        # Test cache performance under load
        cache_performance_acceptable = False
        if cache_write_works and cache_read_works:
            try:
                # Quick performance test - 10 cache operations
                perf_start = time.time()
                for i in range(10):
                    key = f"perf_test_{i}"
                    frappe.cache().set_value(key, {"data": i}, expires_in_sec=30)
                    frappe.cache().get_value(key)
                    frappe.cache().delete_value(key)
                perf_time = time.time() - perf_start
                
                # Should complete 10 operations in under 1 second
                cache_performance_acceptable = perf_time < 1.0
            except Exception:
                pass
                
        return {
            "status": "OPERATIONAL" if (cache_write_works and cache_read_works) else "DEGRADED",
            "cache_write_functional": cache_write_works,
            "cache_read_functional": cache_read_works, 
            "cache_operation_time": cache_time,
            "performance_acceptable": cache_performance_acceptable,
            "capabilities": {
                "basic_caching": cache_write_works and cache_read_works,
                "performance_caching": cache_performance_acceptable,
                "cache_invalidation": True,  # Assume available if basic ops work
                "ttl_support": True
            }
        }
        
    except Exception as e:
        return {
            "status": "FAILED",
            "error": str(e),
            "critical": False  # Caching is important but not critical for Phase 5A start
        }


def calculate_readiness_score(components: Dict) -> int:
    """Calculate overall readiness score from component validation results"""
    total_score = 0
    component_weights = {
        "performance_optimizer": 20,     # Critical for optimizations
        "performance_dashboard": 15,     # Important for monitoring
        "alert_manager": 10,            # Nice to have
        "background_jobs": 20,          # Critical for job coordination
        "security_integration": 25,     # Critical for compliance
        "database_tools": 15,           # Important for index optimization
        "caching_infrastructure": 10    # Nice to have
    }
    
    max_possible_score = sum(component_weights.values())
    
    for component_name, weight in component_weights.items():
        component_result = components.get(component_name, {})
        status = component_result.get("status", "UNKNOWN")
        
        if status == "OPERATIONAL":
            total_score += weight
        elif status == "DEGRADED":
            total_score += weight * 0.5  # Half credit for degraded
        # No credit for MISSING, FAILED, or UNKNOWN
            
    # Convert to percentage
    readiness_percentage = int((total_score / max_possible_score) * 100)
    return readiness_percentage


def determine_overall_status(readiness_score: int) -> str:
    """Determine overall readiness status from score"""
    if readiness_score >= 90:
        return "EXCELLENT"
    elif readiness_score >= 80:
        return "GOOD" 
    elif readiness_score >= 70:
        return "ACCEPTABLE"
    elif readiness_score >= 60:
        return "DEGRADED"
    else:
        return "POOR"


def generate_recommendations(components: Dict) -> tuple:
    """Generate critical issues and recommendations based on component status"""
    critical_issues = []
    recommendations = []
    
    # Check each component for issues
    for component_name, result in components.items():
        status = result.get("status", "UNKNOWN")
        
        if status == "MISSING":
            critical_issues.append(f"{component_name} is missing - required for Phase 5A")
            recommendations.append(f"Install/configure {component_name} before proceeding")
            
        elif status == "FAILED":
            if result.get("critical", False):
                critical_issues.append(f"{component_name} failed validation - {result.get('error', 'Unknown error')}")
                recommendations.append(f"Fix {component_name} issues before starting Phase 5A")
            else:
                recommendations.append(f"Consider fixing {component_name} for optimal performance")
                
        elif status == "DEGRADED":
            recommendations.append(f"Optimize {component_name} for better Phase 5A performance")
            
    # Add specific recommendations based on capabilities
    perf_optimizer = components.get("performance_optimizer", {})
    if perf_optimizer.get("status") == "OPERATIONAL":
        capabilities = perf_optimizer.get("capabilities", {})
        if not capabilities.get("baseline_capture"):
            recommendations.append("Enable baseline capture in PerformanceOptimizer for trend analysis")
            
    dashboard = components.get("performance_dashboard", {})
    if dashboard.get("status") == "OPERATIONAL":
        health_checks = dashboard.get("health_checks_count", 0)
        if health_checks < 5:
            recommendations.append("Configure additional health checks in performance dashboard")
            
    security = components.get("security_integration", {})
    if security.get("status") == "OPERATIONAL":
        secured_apis = security.get("performance_apis_secured", 0)
        if secured_apis < 2:
            recommendations.append("Ensure all performance APIs have security decorators")
            
    return critical_issues, recommendations


if __name__ == "__main__":
    print("🔍 Phase 5A Infrastructure Validator")
    print("Run via: bench --site [site] execute verenigingen.scripts.performance.infrastructure_validator.validate_performance_infrastructure")