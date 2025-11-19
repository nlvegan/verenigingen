"""
Production Readiness Validation - Startup validation for service infrastructure.

This module provides comprehensive validation to ensure all services are properly
configured and ready for production use before the application starts.
"""

import logging
import time
from typing import Any, Dict, List

import frappe

from verenigingen.services.infrastructure.service_factory import get_service_factory
from verenigingen.services.infrastructure.service_metrics import get_health_monitor
from verenigingen.utils.service_error_handler import ServiceError


class ProductionReadinessValidator:
    """Validates that service infrastructure is ready for production use."""

    def __init__(self):
        self.logger = logging.getLogger("verenigingen.services.production_readiness")
        self.validation_results = {}

    def validate_all_services(self) -> Dict[str, Any]:
        """Comprehensive validation of all services and infrastructure.

        Returns:
            Validation results with overall status and detailed findings
        """
        self.logger.info("Starting production readiness validation...")
        start_time = time.time()

        validation_steps = [
            ("Service Factory", self._validate_service_factory),
            ("Core Services", self._validate_core_services),
            ("Database Access", self._validate_database_access),
            ("Configuration", self._validate_configuration),
            ("Health Monitoring", self._validate_health_monitoring),
            ("Error Handling", self._validate_error_handling),
            ("Performance", self._validate_performance),
        ]

        results = {}
        overall_success = True
        critical_errors = []

        for step_name, validation_func in validation_steps:
            try:
                self.logger.info(f"Validating {step_name}...")
                result = validation_func()
                results[step_name] = result

                if not result.get("success", False):
                    overall_success = False
                    if result.get("severity") == "critical":
                        critical_errors.extend(result.get("errors", []))

            except Exception as e:
                overall_success = False
                error_msg = f"Validation failed for {step_name}: {str(e)}"
                critical_errors.append(error_msg)
                results[step_name] = {
                    "success": False,
                    "severity": "critical",
                    "errors": [error_msg],
                    "timestamp": time.time(),
                }

        duration = time.time() - start_time

        summary = {
            "success": overall_success,
            "duration": duration,
            "timestamp": time.time(),
            "critical_errors": critical_errors,
            "total_steps": len(validation_steps),
            "passed_steps": sum(1 for r in results.values() if r.get("success", False)),
            "results": results,
        }

        if overall_success:
            self.logger.info(f"✅ Production readiness validation PASSED in {duration:.2f}s")
        else:
            self.logger.error(f"❌ Production readiness validation FAILED in {duration:.2f}s")
            self.logger.error(f"Critical errors: {critical_errors}")

        return summary

    def _validate_service_factory(self) -> Dict[str, Any]:
        """Validate service factory functionality."""
        try:
            factory = get_service_factory()

            # Test service registration
            test_services = factory.registry.list_services()
            if not test_services:
                return {
                    "success": False,
                    "severity": "warning",
                    "message": "No services registered in factory",
                    "errors": ["Service factory has no registered services"],
                }

            # Test singleton creation
            factory_metrics = factory.get_service_metrics()

            return {
                "success": True,
                "message": f"Service factory operational with {len(test_services)} services",
                "data": {"registered_services": test_services, "active_singletons": len(factory_metrics)},
            }

        except Exception as e:
            return {
                "success": False,
                "severity": "critical",
                "errors": [f"Service factory validation failed: {str(e)}"],
            }

    def _validate_core_services(self) -> Dict[str, Any]:
        """Validate core services can be created and are functional."""
        try:
            factory = get_service_factory()
            core_services = ["customer_handling"]  # Start with migrated service

            validation_results = {}
            all_healthy = True

            for service_name in core_services:
                try:
                    # Try to create service
                    service = factory.get_service(service_name)

                    # Validate configuration
                    config_valid = service.validate_configuration()

                    # Check health
                    is_healthy = service.is_healthy()

                    # Get metrics
                    metrics = service.get_metrics()

                    validation_results[service_name] = {
                        "created": True,
                        "config_valid": config_valid,
                        "healthy": is_healthy,
                        "metrics": metrics,
                    }

                    if not (config_valid and is_healthy):
                        all_healthy = False

                except Exception as e:
                    validation_results[service_name] = {"created": False, "error": str(e)}
                    all_healthy = False

            return {
                "success": all_healthy,
                "severity": "critical" if not all_healthy else "info",
                "message": f"Core services validation: {len([r for r in validation_results.values() if r.get('created', False)])}/{len(core_services)} services healthy",
                "data": validation_results,
                "errors": [
                    f"Service {name} failed: {result.get('error', 'unhealthy')}"
                    for name, result in validation_results.items()
                    if not result.get("created") or not result.get("healthy")
                ],
            }

        except Exception as e:
            return {
                "success": False,
                "severity": "critical",
                "errors": [f"Core services validation failed: {str(e)}"],
            }

    def _validate_database_access(self) -> Dict[str, Any]:
        """Validate database connectivity and required tables."""
        try:
            # Basic connectivity test
            frappe.db.sql("SELECT 1")

            # Test key DocTypes exist
            required_doctypes = ["Customer", "Member", "Selling Settings"]
            missing_doctypes = []

            for doctype in required_doctypes:
                try:
                    frappe.get_meta(doctype)
                except Exception:
                    missing_doctypes.append(doctype)

            if missing_doctypes:
                return {
                    "success": False,
                    "severity": "critical",
                    "errors": [f"Missing required DocTypes: {', '.join(missing_doctypes)}"],
                }

            # Test transaction capabilities
            frappe.db.begin()
            frappe.db.rollback()

            return {
                "success": True,
                "message": "Database access validated",
                "data": {"validated_doctypes": required_doctypes, "transaction_support": True},
            }

        except Exception as e:
            return {
                "success": False,
                "severity": "critical",
                "errors": [f"Database validation failed: {str(e)}"],
            }

    def _validate_configuration(self) -> Dict[str, Any]:
        """Validate configuration system."""
        try:
            from verenigingen.services.infrastructure.service_config import get_config_manager

            config_manager = get_config_manager()

            # Test configuration loading
            config_summary = config_manager.get_configuration_summary()

            # Test validation
            validation_errors = config_manager.validate_all_configurations()

            if validation_errors:
                return {
                    "success": False,
                    "severity": "warning",
                    "errors": [f"Configuration validation errors: {validation_errors}"],
                    "data": config_summary,
                }

            return {"success": True, "message": "Configuration system validated", "data": config_summary}

        except Exception as e:
            return {
                "success": False,
                "severity": "critical",
                "errors": [f"Configuration validation failed: {str(e)}"],
            }

    def _validate_health_monitoring(self) -> Dict[str, Any]:
        """Validate health monitoring system."""
        try:
            health_monitor = get_health_monitor()

            # Test system health check
            system_health = health_monitor.get_system_health_summary()

            # Test service health checks
            all_services_health = health_monitor.check_all_services_health()

            return {
                "success": system_health.get("success", False),
                "message": "Health monitoring operational",
                "data": {"system_health": system_health, "monitored_services": len(all_services_health)},
            }

        except Exception as e:
            return {
                "success": False,
                "severity": "warning",
                "errors": [f"Health monitoring validation failed: {str(e)}"],
            }

    def _validate_error_handling(self) -> Dict[str, Any]:
        """Validate error handling infrastructure."""
        try:
            from verenigingen.utils.service_error_handler import ServiceError, handle_service_error

            # Test ServiceError creation
            test_error = ServiceError("Test error for validation")

            # Test error handling function
            test_result = handle_service_error(
                error=test_error,
                service_name="validation_test",
                operation="test_operation",
                context={"test": True},
                raise_error=False,
            )

            if not isinstance(test_result, dict) or test_result.get("success") is not False:
                return {
                    "success": False,
                    "severity": "warning",
                    "errors": ["Error handling doesn't return expected format"],
                }

            return {
                "success": True,
                "message": "Error handling validated",
                "data": {"test_result_format": list(test_result.keys())},
            }

        except Exception as e:
            return {
                "success": False,
                "severity": "warning",
                "errors": [f"Error handling validation failed: {str(e)}"],
            }

    def _validate_performance(self) -> Dict[str, Any]:
        """Validate performance monitoring capabilities."""
        try:
            from verenigingen.services.infrastructure.service_metrics import get_metrics_collector

            metrics_collector = get_metrics_collector()

            # Test metrics recording
            metrics_collector.record_service_operation(
                "validation_test", "test_operation", 0.001, success=True
            )

            # Test metrics retrieval
            all_metrics = metrics_collector.get_all_metrics()
            aggregated = metrics_collector.get_aggregated_metrics()

            return {
                "success": True,
                "message": "Performance monitoring validated",
                "data": {
                    "metrics_services": len(all_metrics),
                    "aggregated_calls": aggregated.get("total_calls", 0),
                },
            }

        except Exception as e:
            return {
                "success": False,
                "severity": "warning",
                "errors": [f"Performance monitoring validation failed: {str(e)}"],
            }


def validate_production_readiness() -> Dict[str, Any]:
    """Convenience function to run full production readiness validation.

    Returns:
        Validation results
    """
    validator = ProductionReadinessValidator()
    return validator.validate_all_services()


def ensure_production_ready():
    """Ensure system is production ready or raise ServiceError.

    Raises:
        ServiceError: If critical validation failures are found
    """
    results = validate_production_readiness()

    if not results["success"]:
        critical_errors = results.get("critical_errors", [])
        if critical_errors:
            raise ServiceError(
                f"System not ready for production. Critical errors: {'; '.join(critical_errors)}"
            )
        else:
            # Only warnings, log but don't fail
            logging.getLogger("verenigingen.services").warning(
                "Production readiness validation completed with warnings"
            )
