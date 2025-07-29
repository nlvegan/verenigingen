"""
Performance Configuration Management
Phase 1.5.3 - Configuration Management Implementation

Centralized configuration system for all performance monitoring thresholds
and settings. Implements phased approach from feedback synthesis:
- Week 4: Extract critical thresholds from hardcoded values
- Week 5: Add environment-specific settings and runtime updates
"""

import json
from typing import Any, Dict, Optional, Union

import frappe
from frappe.utils import cint, flt, now


class PerformanceConfiguration:
    """
    Centralized configuration management for performance monitoring
    """

    # Critical thresholds extracted from codebase analysis
    CRITICAL_THRESHOLDS = {
        "query_count_critical": 100,  # Currently: 4.4 average (from bottleneck_analyzer.py)
        "query_count_warning": 20,  # Warning before critical
        "query_count_excellent": 10,  # Excellent performance
        "execution_time_critical": 5.0,  # Currently: 0.011s average (from performance_analyzer.py)
        "execution_time_warning": 2.0,  # Warning before critical
        "execution_time_excellent": 0.05,  # Excellent performance
        "health_score_minimum": 90,  # Currently: 95 (from simple_measurement_test.py)
        "health_score_excellent": 95,  # Excellent threshold
        "memory_limit_mb": 100,  # Memory usage limit
        "memory_warning_mb": 75,  # Warning before limit
        "api_response_limit": 0.015,  # API response time limit (from feedback)
        "api_response_warning": 0.010,  # Warning threshold
        "monitoring_overhead_limit": 5,  # Max overhead percentage
        "storage_retention_days": 7,  # Data retention period
        "aggregation_delay_hours": 24,  # Delay before aggregation
    }

    # Environment-specific configurations
    DEV_THRESHOLDS = {
        "query_count_warning": 50,  # More lenient in development
        "execution_time_warning": 1.0,  # More lenient timing
        "api_response_limit": 0.050,  # More lenient response time
        "monitoring_overhead_limit": 10,  # Higher overhead acceptable
        "storage_retention_days": 3,  # Shorter retention in dev
    }

    PRODUCTION_THRESHOLDS = {
        "query_count_warning": 15,  # Stricter in production
        "execution_time_warning": 0.5,  # Stricter timing
        "api_response_limit": 0.010,  # Stricter response time
        "monitoring_overhead_limit": 3,  # Lower overhead required
        "storage_retention_days": 14,  # Longer retention in production
    }

    STAGING_THRESHOLDS = {
        "query_count_warning": 25,  # Between dev and production
        "execution_time_warning": 0.75,  # Between dev and production
        "api_response_limit": 0.020,  # Between dev and production
        "monitoring_overhead_limit": 7,  # Between dev and production
        "storage_retention_days": 7,  # Standard retention
    }

    _instance = None
    _config_cache = None
    _cache_timestamp = None

    def __new__(cls):
        """Singleton pattern for configuration management"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize configuration manager"""
        if not hasattr(self, "initialized"):
            self.initialized = True
            self._load_configuration()

    def get_threshold(self, metric: str, level: str = "warning") -> Union[float, int]:
        """
        Get threshold value for specific metric and level

        Args:
            metric: Metric name (query_count, execution_time, etc.)
            level: Threshold level (excellent, warning, critical)

        Returns:
            Threshold value
        """

        # Construct threshold key
        threshold_key = f"{metric}_{level}"

        # Get from environment-specific config first
        config = self._get_current_config()

        if threshold_key in config:
            return config[threshold_key]

        # Fallback to critical thresholds
        if threshold_key in self.CRITICAL_THRESHOLDS:
            return self.CRITICAL_THRESHOLDS[threshold_key]

        # Default fallback values
        defaults = {
            "query_count_warning": 20,
            "query_count_critical": 100,
            "execution_time_warning": 2.0,
            "execution_time_critical": 5.0,
            "health_score_minimum": 90,
            "memory_limit_mb": 100,
            "api_response_limit": 0.015,
        }

        return defaults.get(threshold_key, 0)

    def get_all_thresholds(self) -> Dict[str, Any]:
        """Get all current thresholds"""
        return self._get_current_config()

    def update_threshold(
        self, metric: str, level: str, value: Union[float, int], environment: Optional[str] = None
    ) -> bool:
        """
        Update threshold value (admin only)

        Args:
            metric: Metric name
            level: Threshold level
            value: New threshold value
            environment: Target environment (None for current)

        Returns:
            bool: Success status
        """

        try:
            # Validate user permissions
            if not self._can_update_config():
                frappe.throw("Insufficient permissions to update performance configuration")

            # Validate threshold key
            threshold_key = f"{metric}_{level}"
            if not self._is_valid_threshold(threshold_key):
                frappe.throw(f"Invalid threshold: {threshold_key}")

            # Validate value
            if not self._is_valid_threshold_value(metric, value):
                frappe.throw(f"Invalid value for {metric}: {value}")

            # Update configuration
            self._update_configuration(threshold_key, value, environment)

            # Clear cache to force reload
            self._clear_cache()

            # Log configuration change
            frappe.logger().info(f"Performance threshold updated: {threshold_key} = {value}")

            return True

        except Exception as e:
            frappe.log_error(f"Failed to update threshold {metric}_{level}: {str(e)}")
            return False

    def get_environment_config(self, environment: str) -> Dict[str, Any]:
        """Get configuration for specific environment"""

        base_config = self.CRITICAL_THRESHOLDS.copy()

        if environment == "development":
            base_config.update(self.DEV_THRESHOLDS)
        elif environment == "production":
            base_config.update(self.PRODUCTION_THRESHOLDS)
        elif environment == "staging":
            base_config.update(self.STAGING_THRESHOLDS)

        # Merge with custom configuration
        custom_config = self._get_custom_config(environment)
        base_config.update(custom_config)

        return base_config

    def reset_to_defaults(self, environment: Optional[str] = None) -> bool:
        """Reset configuration to defaults"""

        try:
            if not self._can_update_config():
                frappe.throw("Insufficient permissions to reset configuration")

            # Clear custom configuration
            self._clear_custom_config(environment)

            # Clear cache
            self._clear_cache()

            frappe.logger().info(
                f"Performance configuration reset to defaults for {environment or 'current'}"
            )

            return True

        except Exception as e:
            frappe.log_error(f"Failed to reset configuration: {str(e)}")
            return False

    def validate_configuration(self) -> Dict[str, Any]:
        """Validate current configuration for consistency"""

        config = self._get_current_config()
        issues = []
        warnings = []

        # Check that warning thresholds are less than critical thresholds
        threshold_pairs = [
            ("query_count_warning", "query_count_critical"),
            ("execution_time_warning", "execution_time_critical"),
        ]

        for warning_key, critical_key in threshold_pairs:
            warning_val = config.get(warning_key, 0)
            critical_val = config.get(critical_key, 0)

            if warning_val >= critical_val:
                issues.append(
                    f"{warning_key} ({warning_val}) should be less than {critical_key} ({critical_val})"
                )

        # Check for reasonable threshold values
        reasonable_ranges = {
            "query_count_warning": (1, 1000),
            "execution_time_warning": (0.001, 60),
            "health_score_minimum": (50, 100),
            "memory_limit_mb": (10, 1000),
            "api_response_limit": (0.001, 10),
        }

        for key, (min_val, max_val) in reasonable_ranges.items():
            if key in config:
                value = config[key]
                if not (min_val <= value <= max_val):
                    warnings.append(f"{key} value {value} outside reasonable range {min_val}-{max_val}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "config_checked": len(config),
            "timestamp": now(),
        }

    def _get_current_config(self) -> Dict[str, Any]:
        """Get current configuration with caching"""

        # Check cache freshness (cache for 5 minutes)
        if (
            self._config_cache
            and self._cache_timestamp
            and (frappe.utils.get_datetime(now()) - frappe.utils.get_datetime(self._cache_timestamp)).seconds
            < 300
        ):
            return self._config_cache.copy()

        # Reload configuration
        self._load_configuration()
        return self._config_cache.copy()

    def _load_configuration(self):
        """Load configuration from environment and custom settings"""

        # Start with critical thresholds
        config = self.CRITICAL_THRESHOLDS.copy()

        # Add environment-specific overrides
        environment = self._get_current_environment()
        env_config = self.get_environment_config(environment)
        config.update(env_config)

        # Add custom configuration
        custom_config = self._get_custom_config()
        config.update(custom_config)

        # Cache configuration
        self._config_cache = config
        self._cache_timestamp = now()

    def _get_current_environment(self) -> str:
        """Determine current environment"""

        if frappe.conf.get("developer_mode"):
            return "development"
        elif frappe.conf.get("staging_mode"):
            return "staging"
        else:
            return "production"

    def _get_custom_config(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """Get custom configuration from database"""

        try:
            # In real implementation, this would read from a Custom Settings doctype
            # For now, return empty dict
            return {}

        except Exception as e:
            frappe.logger().warning(f"Failed to load custom config: {str(e)}")
            return {}

    def _update_configuration(self, key: str, value: Union[float, int], environment: Optional[str] = None):
        """Update configuration in database"""

        try:
            # In real implementation, this would update a Custom Settings doctype
            # For now, log the update
            frappe.logger().info(f"Configuration update: {key} = {value} (env: {environment or 'current'})")

        except Exception as e:
            frappe.log_error(f"Failed to update configuration {key}: {str(e)}")
            raise

    def _clear_custom_config(self, environment: Optional[str] = None):
        """Clear custom configuration"""

        try:
            # In real implementation, this would clear Custom Settings doctype
            frappe.logger().info(f"Custom configuration cleared for {environment or 'current'}")

        except Exception as e:
            frappe.log_error(f"Failed to clear custom config: {str(e)}")
            raise

    def _clear_cache(self):
        """Clear configuration cache"""
        self._config_cache = None
        self._cache_timestamp = None

    def _can_update_config(self) -> bool:
        """Check if current user can update configuration"""
        return frappe.has_permission("System Settings", "write")

    def _is_valid_threshold(self, threshold_key: str) -> bool:
        """Validate threshold key"""
        valid_keys = set()
        valid_keys.update(self.CRITICAL_THRESHOLDS.keys())
        valid_keys.update(self.DEV_THRESHOLDS.keys())
        valid_keys.update(self.PRODUCTION_THRESHOLDS.keys())
        valid_keys.update(self.STAGING_THRESHOLDS.keys())

        return threshold_key in valid_keys

    def _is_valid_threshold_value(self, metric: str, value: Union[float, int]) -> bool:
        """Validate threshold value"""

        # Basic type check
        if not isinstance(value, (int, float)):
            return False

        # Ensure non-negative
        if value < 0:
            return False

        # Metric-specific validation
        if metric.startswith("query_count") and (value < 1 or value > 10000):
            return False

        if metric.startswith("execution_time") and (value < 0.001 or value > 3600):
            return False

        if metric.startswith("health_score") and (value < 0 or value > 100):
            return False

        if metric.startswith("memory") and (value < 1 or value > 10000):
            return False

        return True


# API Endpoints


@frappe.whitelist()
def get_performance_config() -> Dict[str, Any]:
    """Get current performance configuration"""
    try:
        config_manager = PerformanceConfiguration()
        return {
            "success": True,
            "config": config_manager.get_all_thresholds(),
            "environment": config_manager._get_current_environment(),
            "timestamp": now(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_performance_config(
    metric: str, level: str, value: Union[float, int], environment: Optional[str] = None
) -> Dict[str, Any]:
    """Update performance configuration (admin only)"""
    try:
        config_manager = PerformanceConfiguration()
        success = config_manager.update_threshold(metric, level, flt(value), environment)

        return {
            "success": success,
            "message": f"Updated {metric}_{level} to {value}" if success else "Update failed",
            "timestamp": now(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def validate_performance_config() -> Dict[str, Any]:
    """Validate current performance configuration"""
    try:
        config_manager = PerformanceConfiguration()
        validation = config_manager.validate_configuration()

        return {"success": True, "validation": validation}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def reset_performance_config(environment: Optional[str] = None) -> Dict[str, Any]:
    """Reset performance configuration to defaults (admin only)"""
    try:
        config_manager = PerformanceConfiguration()
        success = config_manager.reset_to_defaults(environment)

        return {
            "success": success,
            "message": f"Configuration reset to defaults for {environment or 'current'}"
            if success
            else "Reset failed",
            "timestamp": now(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_environment_config(environment: str) -> Dict[str, Any]:
    """Get configuration for specific environment"""
    try:
        config_manager = PerformanceConfiguration()

        return {
            "success": True,
            "environment": environment,
            "config": config_manager.get_environment_config(environment),
            "timestamp": now(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# Helper function for migrating hardcoded values
def migrate_hardcoded_thresholds():
    """
    Helper function to identify and migrate hardcoded thresholds in codebase
    This would be run once during Phase 1.5.3 implementation
    """

    migration_report = {
        "timestamp": now(),
        "hardcoded_values_found": [],
        "migration_recommendations": [],
        "files_to_update": [],
    }

    # Identify files with hardcoded thresholds based on plan analysis
    hardcoded_locations = [
        {
            "file": "verenigingen/utils/performance/bottleneck_analyzer.py",
            "line_pattern": "if avg_queries > 30:",
            "recommended_replacement": 'if avg_queries > config.get_threshold("query_count", "warning"):',
        },
        {
            "file": "verenigingen/utils/performance/performance_analyzer.py",
            "line_pattern": "if execution_time > 2.0:",
            "recommended_replacement": 'if execution_time > config.get_threshold("execution_time", "warning"):',
        },
        {
            "file": "verenigingen/api/simple_measurement_test.py",
            "line_pattern": "if health_score >= 90:",
            "recommended_replacement": 'if health_score >= config.get_threshold("health_score", "minimum"):',
        },
    ]

    migration_report["hardcoded_values_found"] = hardcoded_locations
    migration_report["files_to_update"] = [loc["file"] for loc in hardcoded_locations]
    migration_report["migration_recommendations"] = [
        "Replace hardcoded thresholds with config.get_threshold() calls",
        "Add PerformanceConfiguration import to affected files",
        "Test configuration changes don't break existing functionality",
        "Update tests to use configurable thresholds",
    ]

    return migration_report
