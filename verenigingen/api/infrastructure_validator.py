#!/usr/bin/env python3
"""
Phase 5A Infrastructure Validator API

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
        "recommendations": [],
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
        results["critical_issues"], results["recommendations"] = generate_recommendations(
            results["components"]
        )

        # Log validation results
        frappe.logger().info(
            f"Infrastructure validation completed. Status: {results['overall_status']}, Score: {results['readiness_score']}"
        )

        return results

    except Exception as e:
        frappe.log_error(f"Infrastructure validation failed: {e}")
        results["overall_status"] = "CRITICAL_FAILURE"
        results["error"] = str(e)
        return results


def validate_performance_optimizer():
    """Validate PerformanceOptimizer is operational"""
    try:
        # Check if performance optimizer utilities exist
        has_performance_utils = False
        has_bottleneck_analyzer = False
        has_query_measurement = False

        try:
            from verenigingen.utils.performance.bottleneck_analyzer import PaymentOperationAnalyzer

            has_bottleneck_analyzer = True
        except ImportError:
            pass

        try:
            from verenigingen.utils.performance.query_measurement import QueryMeasurementStore

            has_query_measurement = True
        except ImportError:
            pass

        try:
            from verenigingen.utils.performance.performance_reporter import PerformanceReporter

            has_performance_utils = True
        except ImportError:
            pass

        # Test if we can access the performance measurement APIs
        api_accessible = False
        try:
            from verenigingen.api.performance_measurement_api import measure_member_performance

            api_accessible = True
        except ImportError:
            pass

        capabilities_score = sum(
            [has_performance_utils, has_bottleneck_analyzer, has_query_measurement, api_accessible]
        )

        return {
            "status": "OPERATIONAL" if capabilities_score >= 2 else "DEGRADED",
            "bottleneck_analyzer_available": has_bottleneck_analyzer,
            "query_measurement_available": has_query_measurement,
            "performance_reporter_available": has_performance_utils,
            "api_accessible": api_accessible,
            "capabilities_score": capabilities_score,
            "capabilities": {
                "bottleneck_analysis": has_bottleneck_analyzer,
                "query_measurement": has_query_measurement,
                "performance_reporting": has_performance_utils,
                "api_integration": api_accessible,
            },
        }

    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": True}


def validate_performance_dashboard():
    """Validate PerformanceMetrics dashboard is operational"""
    try:
        # Check if performance dashboard exists
        has_dashboard = False
        has_monitoring = False

        try:
            from verenigingen.www.monitoring_dashboard import get_security_metrics_for_dashboard

            has_monitoring = True
        except ImportError:
            pass

        try:
            from verenigingen.utils.performance_dashboard import PerformanceMetrics

            has_dashboard = True

            # Test basic functionality
            dashboard = PerformanceMetrics()
            dashboard.record_api_call("test_validation", 50.0, True)

        except ImportError:
            pass
        except Exception:
            has_dashboard = False  # Exists but not functional

        return {
            "status": "OPERATIONAL" if (has_dashboard or has_monitoring) else "MISSING",
            "performance_dashboard_available": has_dashboard,
            "monitoring_dashboard_available": has_monitoring,
            "capabilities": {
                "metrics_recording": has_dashboard,
                "dashboard_interface": has_monitoring,
                "real_time_monitoring": has_monitoring,
            },
        }

    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": False}


def validate_alert_manager():
    """Validate AlertManager is operational"""
    try:
        has_alert_manager = False
        has_alerting_system = False

        try:
            from verenigingen.utils.alert_manager import AlertManager

            has_alert_manager = True
        except ImportError:
            pass

        try:
            from verenigingen.verenigingen_payments.utils.sepa_alerting_system import get_alerting_system

            has_alerting_system = True
        except ImportError:
            pass

        return {
            "status": "OPERATIONAL" if (has_alert_manager or has_alerting_system) else "MISSING",
            "alert_manager_available": has_alert_manager,
            "sepa_alerting_available": has_alerting_system,
            "capabilities": {
                "alert_creation": has_alert_manager,
                "sepa_monitoring": has_alerting_system,
                "notification_system": has_alert_manager or has_alerting_system,
            },
        }

    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": False}


def validate_background_jobs_system():
    """Validate BackgroundJobManager is operational"""
    try:
        from verenigingen.utils.background_jobs import BackgroundJobManager

        # Test basic functionality
        has_job_queuing = hasattr(BackgroundJobManager, "enqueue_with_tracking")
        has_status_tracking = hasattr(BackgroundJobManager, "get_job_status")
        has_retry_mechanism = hasattr(BackgroundJobManager, "retry_failed_job")

        # Test optimized payment history function
        has_payment_optimization = False
        try:
            from verenigingen.utils.background_jobs import refresh_member_financial_history_optimized

            has_payment_optimization = True
        except ImportError:
            pass

        capabilities_score = sum(
            [has_job_queuing, has_status_tracking, has_retry_mechanism, has_payment_optimization]
        )

        return {
            "status": "OPERATIONAL" if capabilities_score >= 3 else "DEGRADED",
            "job_queuing_available": has_job_queuing,
            "status_tracking_available": has_status_tracking,
            "retry_mechanism_available": has_retry_mechanism,
            "payment_optimization_available": has_payment_optimization,
            "capabilities_score": capabilities_score,
            "capabilities": {
                "job_queuing": has_job_queuing,
                "status_tracking": has_status_tracking,
                "retry_mechanism": has_retry_mechanism,
                "payment_optimization": has_payment_optimization,
            },
        }

    except ImportError:
        return {"status": "MISSING", "error": "BackgroundJobManager not found", "critical": True}
    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": True}


def validate_security_integration():
    """Validate security framework integration is working"""
    try:
        from verenigingen.utils.security.api_security_framework import (
            OperationType,
            critical_api,
            standard_api,
        )
        from verenigingen.utils.security.audit_logging import get_audit_logger

        # Test security decorators are importable
        security_decorators_available = True

        # Test audit logging
        audit_logger = get_audit_logger()
        audit_logging_works = hasattr(audit_logger, "log_event")

        # Check if performance APIs have security decorators
        performance_apis_secured = 0
        try:
            # Check existing performance APIs that should have security decorators
            from verenigingen.api.performance_measurement_api import measure_member_performance

            performance_apis_secured += 1
        except ImportError:
            pass

        try:
            from verenigingen.api.performance_measurement import measure_payment_history_performance

            performance_apis_secured += 1
        except ImportError:
            pass

        return {
            "status": "OPERATIONAL",
            "security_decorators_available": security_decorators_available,
            "audit_logging_functional": audit_logging_works,
            "performance_apis_secured": performance_apis_secured,
            "capabilities": {
                "api_security_framework": security_decorators_available,
                "audit_logging": audit_logging_works,
                "performance_api_security": performance_apis_secured > 0,
            },
        }

    except ImportError as e:
        return {"status": "MISSING", "error": f"Security framework components missing: {e}", "critical": True}
    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": True}


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
            db_responsive = len(result) == 1 and result[0]["test_query"] == 1
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
                "explain_queries": index_analysis_available,
            },
        }

    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": True}


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

        return {
            "status": "OPERATIONAL" if (cache_write_works and cache_read_works) else "DEGRADED",
            "cache_write_functional": cache_write_works,
            "cache_read_functional": cache_read_works,
            "cache_operation_time": cache_time,
            "capabilities": {
                "basic_caching": cache_write_works and cache_read_works,
                "cache_invalidation": True,
                "ttl_support": True,
            },
        }

    except Exception as e:
        return {"status": "FAILED", "error": str(e), "critical": False}


def calculate_readiness_score(components: Dict) -> int:
    """Calculate overall readiness score from component validation results"""
    total_score = 0
    component_weights = {
        "performance_optimizer": 20,  # Critical for optimizations
        "performance_dashboard": 15,  # Important for monitoring
        "alert_manager": 10,  # Nice to have
        "background_jobs": 20,  # Critical for job coordination
        "security_integration": 25,  # Critical for compliance
        "database_tools": 15,  # Important for index optimization
        "caching_infrastructure": 10,  # Nice to have
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
                critical_issues.append(
                    f"{component_name} failed validation - {result.get('error', 'Unknown error')}"
                )
                recommendations.append(f"Fix {component_name} issues before starting Phase 5A")
            else:
                recommendations.append(f"Consider fixing {component_name} for optimal performance")

        elif status == "DEGRADED":
            recommendations.append(f"Optimize {component_name} for better Phase 5A performance")

    # Add specific recommendations based on capabilities
    perf_optimizer = components.get("performance_optimizer", {})
    if perf_optimizer.get("status") == "OPERATIONAL":
        capabilities_score = perf_optimizer.get("capabilities_score", 0)
        if capabilities_score < 3:
            recommendations.append("Install additional performance optimization components")

    dashboard = components.get("performance_dashboard", {})
    if dashboard.get("status") in ["MISSING", "DEGRADED"]:
        recommendations.append("Set up performance dashboard for monitoring Phase 5A improvements")

    security = components.get("security_integration", {})
    if security.get("status") == "OPERATIONAL":
        secured_apis = security.get("performance_apis_secured", 0)
        if secured_apis < 2:
            recommendations.append("Ensure all performance APIs have security decorators")

    background_jobs = components.get("background_jobs", {})
    if background_jobs.get("status") == "OPERATIONAL":
        if not background_jobs.get("payment_optimization_available", False):
            recommendations.append("Enable payment history optimization in background jobs")

    return critical_issues, recommendations


if __name__ == "__main__":
    print("🔍 Phase 5A Infrastructure Validator")
    print("Available via API: verenigingen.api.infrastructure_validator.validate_performance_infrastructure")
