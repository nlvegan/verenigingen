"""
Configuration management for Verenigingen app

This module provides centralized configuration management to eliminate magic numbers
and hardcoded values throughout the codebase.
"""

from typing import Any, Dict, Optional

import frappe


class ConfigManager:
    """Centralized configuration management"""

    # Default configurations
    _default_config = {
        # Pagination and limits
        "default_page_size": 20,
        "max_page_size": 100,
        "api_rate_limit": 1000,  # requests per hour
        # Billing and payments
        "annual_billing_threshold": 12,  # months
        "payment_grace_period_days": 30,
        "sepa_mandate_validity_years": 5,
        "default_currency": "EUR",
        # Validation rules
        "dutch_postal_code_length": 4,
        "min_password_length": 8,
        "max_email_length": 254,
        "max_name_length": 100,
        # Performance settings
        "query_timeout_seconds": 30,
        "cache_ttl_seconds": 300,
        "slow_query_threshold_ms": 1000,
        "batch_processing_size": 100,
        # Security settings
        "session_timeout_hours": 24,
        "max_login_attempts": 5,
        "password_reset_token_validity_hours": 24,
        # Email settings
        "email_batch_size": 50,
        "email_retry_attempts": 3,
        "email_retry_delay_minutes": 5,
        # Membership settings
        "min_membership_age": 16,
        "max_membership_types": 20,
        "default_membership_type": "Individual",
        # Volunteer settings
        "max_team_assignments": 5,
        "volunteer_inactive_months": 12,
        "expense_approval_threshold": 100.00,
        # Chapter settings
        "max_chapters_per_member": 3,
        "postal_code_assignment_priority": True,
        "auto_chapter_assignment": True,
        # File upload settings
        "max_file_size_mb": 10,
        "allowed_file_extensions": ["pdf", "jpg", "jpeg", "png", "docx", "xlsx"],
        "receipt_required_amount": 25.00,
        # Notification settings
        "notification_batch_size": 100,
        "digest_frequency_days": 7,
        "reminder_advance_days": 7,
        # Report settings
        "report_cache_hours": 1,
        "export_max_records": 10000,
        "analytics_retention_months": 24,
        # System settings
        "maintenance_window_hours": [2, 4],  # 2 AM to 4 AM
        "backup_retention_days": 30,
        "log_retention_days": 90,
    }

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Get configuration value with fallback to default

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        # First try to get from Verenigingen Settings doctype
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, key):
                value = getattr(settings, key)
                if value is not None:
                    return value
        except:
            pass

        # Fall back to default configuration
        value = cls._default_config.get(key, default)
        return value

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """
        Set configuration value in Verenigingen Settings

        Args:
            key: Configuration key
            value: Value to set
        """
        try:
            settings = frappe.get_single("Verenigingen Settings")
            settings.set(key, value)
            settings.save()
        except Exception as e:
            frappe.log_error(f"Failed to set config {key}: {str(e)}", "Config Manager")

    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        """Get all configuration values"""
        config = cls._default_config.copy()

        # Overlay with values from Verenigingen Settings
        try:
            settings = frappe.get_single("Verenigingen Settings")
            for key in config.keys():
                if hasattr(settings, key):
                    value = getattr(settings, key)
                    if value is not None:
                        config[key] = value
        except:
            pass

        return config

    @classmethod
    def reset_to_defaults(cls) -> None:
        """Reset all configuration to default values"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            for key, value in cls._default_config.items():
                if hasattr(settings, key):
                    settings.set(key, value)
            settings.save()
        except Exception as e:
            frappe.log_error(f"Failed to reset config: {str(e)}", "Config Manager")


# Convenience functions for commonly used configurations


def get_page_size(requested_size: Optional[int] = None) -> int:
    """Get validated page size for pagination"""
    default_size = ConfigManager.get("default_page_size", 20)
    max_size = ConfigManager.get("max_page_size", 100)

    if requested_size is None:
        return default_size

    return min(max(1, requested_size), max_size)


def get_grace_period_days() -> int:
    """Get payment grace period in days"""
    return ConfigManager.get("payment_grace_period_days", 30)


def is_annual_billing(interval_months: int) -> bool:
    """Check if billing interval qualifies as annual"""
    threshold = ConfigManager.get("annual_billing_threshold", 12)
    return interval_months >= threshold


def get_dutch_postal_code_pattern() -> str:
    """Get regex pattern for Dutch postal codes"""
    return r"^\d{4}[A-Z]{2}$"


def validate_dutch_postal_code(postal_code: str) -> bool:
    """Validate Dutch postal code format"""
    import re

    pattern = get_dutch_postal_code_pattern()
    clean_code = postal_code.upper().replace(" ", "")
    return bool(re.match(pattern, clean_code))


def get_batch_size(operation_type: str = "default") -> int:
    """Get batch size for different operations"""
    size_map = {
        "default": ConfigManager.get("batch_processing_size", 100),
        "email": ConfigManager.get("email_batch_size", 50),
        "notification": ConfigManager.get("notification_batch_size", 100),
        "import": ConfigManager.get("batch_processing_size", 100),
        "export": ConfigManager.get("batch_processing_size", 100),
    }

    return size_map.get(operation_type, size_map["default"])


def get_file_upload_limits() -> Dict[str, Any]:
    """Get file upload configuration"""
    return {
        "max_size_mb": ConfigManager.get("max_file_size_mb", 10),
        "allowed_extensions": ConfigManager.get(
            "allowed_file_extensions", ["pdf", "jpg", "jpeg", "png", "docx", "xlsx"]
        ),
        "receipt_required_amount": ConfigManager.get("receipt_required_amount", 25.00),
    }


def get_security_config() -> Dict[str, Any]:
    """Get security-related configuration"""
    return {
        "session_timeout_hours": ConfigManager.get("session_timeout_hours", 24),
        "max_login_attempts": ConfigManager.get("max_login_attempts", 5),
        "min_password_length": ConfigManager.get("min_password_length", 8),
        "password_reset_token_validity_hours": ConfigManager.get("password_reset_token_validity_hours", 24),
    }


def get_performance_config() -> Dict[str, Any]:
    """Get performance-related configuration"""
    return {
        "cache_ttl_seconds": ConfigManager.get("cache_ttl_seconds", 300),
        "slow_query_threshold_ms": ConfigManager.get("slow_query_threshold_ms", 1000),
        "query_timeout_seconds": ConfigManager.get("query_timeout_seconds", 30),
        "batch_processing_size": ConfigManager.get("batch_processing_size", 100),
    }


def get_membership_config() -> Dict[str, Any]:
    """Get membership-related configuration"""
    return {
        "min_age": ConfigManager.get("min_membership_age", 16),
        "max_types": ConfigManager.get("max_membership_types", 20),
        "default_type": ConfigManager.get("default_membership_type", "Individual"),
        "grace_period_days": ConfigManager.get("payment_grace_period_days", 30),
    }


def get_volunteer_config() -> Dict[str, Any]:
    """Get volunteer-related configuration"""
    return {
        "max_team_assignments": ConfigManager.get("max_team_assignments", 5),
        "inactive_months": ConfigManager.get("volunteer_inactive_months", 12),
        "expense_approval_threshold": ConfigManager.get("expense_approval_threshold", 100.00),
    }


def get_chapter_config() -> Dict[str, Any]:
    """Get chapter-related configuration"""
    return {
        "max_chapters_per_member": ConfigManager.get("max_chapters_per_member", 3),
        "postal_code_assignment_priority": ConfigManager.get("postal_code_assignment_priority", True),
        "auto_assignment": ConfigManager.get("auto_chapter_assignment", True),
    }


# Configuration validation functions


def validate_config() -> Dict[str, Any]:
    """
    Validate current configuration for inconsistencies

    Returns:
        Dictionary with validation results
    """
    issues = []
    warnings = []

    config = ConfigManager.get_all()

    # Check for logical inconsistencies
    if config.get("min_membership_age", 0) < 0:
        issues.append("Minimum membership age cannot be negative")

    if config.get("max_page_size", 0) < config.get("default_page_size", 0):
        issues.append("Maximum page size cannot be less than default page size")

    if config.get("payment_grace_period_days", 0) < 0:
        issues.append("Payment grace period cannot be negative")

    if config.get("cache_ttl_seconds", 0) < 60:
        warnings.append("Cache TTL less than 60 seconds may impact performance")

    if config.get("slow_query_threshold_ms", 0) > 5000:
        warnings.append("Slow query threshold over 5 seconds may miss performance issues")

    return {"valid": len(issues) == 0, "issues": issues, "warnings": warnings, "config": config}


def export_config() -> Dict[str, Any]:
    """Export current configuration for backup"""
    return {
        "timestamp": frappe.utils.now(),
        "site": frappe.local.site,
        "config": ConfigManager.get_all(),
        "version": "1.0",
    }


def import_config(config_data: Dict[str, Any]) -> bool:
    """
    Import configuration from backup

    Args:
        config_data: Configuration data from export_config()

    Returns:
        True if successful
    """
    try:
        if config_data.get("version") != "1.0":
            frappe.throw("Unsupported configuration version")

        config = config_data.get("config", {})
        for key, value in config.items():
            ConfigManager.set(key, value)

        return True

    except Exception as e:
        frappe.log_error(f"Failed to import config: {str(e)}", "Config Manager")
        return False
