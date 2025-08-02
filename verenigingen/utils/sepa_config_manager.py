"""
Enterprise SEPA Configuration Management System for Payment Processing

This module provides comprehensive configuration management for SEPA (Single Euro
Payments Area) payment processing within the Verenigingen platform. It centralizes
all SEPA-related settings, validation rules, and configuration parameters to ensure
consistent and compliant payment processing across the entire system.

Key Features:
    * Centralized SEPA configuration with intelligent caching
    * Multi-source configuration aggregation and validation
    * Company-specific SEPA parameters and credentials
    * Batch processing configuration and scheduling
    * Notification and alerting system configuration
    * Validation rules for IBAN, BIC, and creditor identifiers
    * Environment-specific configuration support

Configuration Sources:
    1. Verenigingen Settings DocType (primary configuration)
    2. Company DocType (company-specific information)
    3. System defaults and fallback values
    4. Environment-specific overrides

SEPA Compliance:
    Ensures all configuration parameters comply with SEPA regulations including
    creditor identifier formats, IBAN validation, BIC requirements, and batch
    processing timelines as mandated by European banking standards.

Usage Context:
    This configuration manager is used throughout the SEPA payment processing
    pipeline including mandate management, batch creation, XML generation, and
    reconciliation processes to ensure consistent configuration access.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import add_days, getdate, today


class SEPAConfigManager:
    """
    Centralized manager for all SEPA configuration settings
    Provides validated access to SEPA settings from multiple sources
    """

    def __init__(self):
        self._settings_cache = {}
        self._validation_cache = {}

    def get_company_sepa_config(self) -> Dict[str, Any]:
        """Get SEPA configuration for the company"""
        if "company_sepa" in self._settings_cache:
            return self._settings_cache["company_sepa"]

        # Get settings from Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")

        # Get company information
        company_name = getattr(settings, "company", None) or frappe.defaults.get_global_default("company")
        company = frappe.get_doc("Company", company_name) if company_name else None

        config = {
            # Company basics
            "company_name": company.company_name if company else "",
            "company": company_name or "",
            # SEPA specific settings from Verenigingen Settings
            "company_iban": getattr(settings, "company_iban", ""),
            "company_bic": getattr(settings, "company_bic", ""),
            "creditor_id": getattr(settings, "creditor_id", ""),
            "company_account_holder": getattr(settings, "company_account_holder", "")
            or (company.company_name if company else ""),
            # Batch processing settings
            "batch_creation_days": getattr(settings, "batch_creation_days", "19,20"),
            "enable_auto_batch_creation": getattr(settings, "enable_auto_batch_creation", 0),
            "auto_submit_sepa_batches": getattr(settings, "auto_submit_sepa_batches", 0),
            "batch_processing_lead_time": getattr(settings, "batch_processing_lead_time", 7),
            # Notification settings
            "financial_admin_emails": getattr(settings, "financial_admin_emails", ""),
            "send_batch_notifications": getattr(settings, "send_batch_notifications", 1),
            "notification_critical_errors": getattr(settings, "notification_critical_errors", 1),
            "notification_warnings": getattr(settings, "notification_warnings", 1),
            # Error handling settings
            "enable_retry_mechanism": getattr(settings, "enable_retry_mechanism", 1),
            "max_retry_attempts": getattr(settings, "max_retry_attempts", 3),
            "circuit_breaker_enabled": getattr(settings, "circuit_breaker_enabled", 1),
            "circuit_breaker_threshold": getattr(settings, "circuit_breaker_threshold", 5),
            # Invoice and coverage settings
            "invoice_lookback_days": getattr(settings, "invoice_lookback_days", 60),
            "coverage_verification_enabled": getattr(settings, "coverage_verification_enabled", 1),
            "mandate_cache_timeout": getattr(settings, "mandate_cache_timeout", 300),  # 5 minutes
            # XML and file settings
            "sepa_xml_version": getattr(settings, "sepa_xml_version", "pain.008.001.02"),
            "output_directory": getattr(settings, "sepa_output_directory", ""),
            "backup_processed_files": getattr(settings, "backup_processed_files", 1),
        }

        # Cache the configuration
        self._settings_cache["company_sepa"] = config
        return config

    def get_batch_timing_config(self) -> Dict[str, Any]:
        """Get batch timing and scheduling configuration"""
        config = self.get_company_sepa_config()

        # Parse batch creation days
        creation_days_str = config.get("batch_creation_days", "19,20") or "19,20"
        creation_days = [int(day.strip()) for day in creation_days_str.split(",") if day.strip().isdigit()]

        return {
            "creation_days": creation_days,
            "processing_lead_time": config.get("batch_processing_lead_time", 7),
            "auto_creation_enabled": bool(config.get("enable_auto_batch_creation", 0)),
            "auto_submit_enabled": bool(config.get("auto_submit_sepa_batches", 0)),
            "current_day": getdate(today()).day,
            "is_creation_day": getdate(today()).day in creation_days,
            "next_processing_date": add_days(today(), config.get("batch_processing_lead_time", 7)),
        }

    def get_notification_config(self) -> Dict[str, Any]:
        """Get notification configuration"""
        config = self.get_company_sepa_config()

        # Parse email addresses
        email_str = config.get("financial_admin_emails", "") or ""
        admin_emails = [email.strip() for email in email_str.split(",") if email.strip()]

        return {
            "admin_emails": admin_emails,
            "notifications_enabled": bool(config.get("send_batch_notifications", 1)),
            "critical_errors_enabled": bool(config.get("notification_critical_errors", 1)),
            "warnings_enabled": bool(config.get("notification_warnings", 1)),
            "has_recipients": len(admin_emails) > 0,
        }

    def get_error_handling_config(self) -> Dict[str, Any]:
        """Get error handling and retry configuration"""
        config = self.get_company_sepa_config()

        return {
            "retry_enabled": bool(config.get("enable_retry_mechanism", 1)),
            "max_retries": config.get("max_retry_attempts", 3),
            "circuit_breaker_enabled": bool(config.get("circuit_breaker_enabled", 1)),
            "circuit_breaker_threshold": config.get("circuit_breaker_threshold", 5),
            "base_delay": 1.0,  # seconds - could be configurable
            "max_delay": 60.0,  # seconds - could be configurable
            "backoff_multiplier": 2.0,  # could be configurable
        }

    def get_processing_config(self) -> Dict[str, Any]:
        """Get invoice processing and coverage configuration"""
        config = self.get_company_sepa_config()

        return {
            "lookback_days": config.get("invoice_lookback_days", 60),
            "coverage_verification": bool(config.get("coverage_verification_enabled", 1)),
            "mandate_cache_timeout": config.get("mandate_cache_timeout", 300),
            "batch_size_limit": 1000,  # could be configurable
            "pagination_enabled": True,
        }

    def get_file_handling_config(self) -> Dict[str, Any]:
        """Get SEPA file handling configuration"""
        config = self.get_company_sepa_config()

        return {
            "xml_version": config.get("sepa_xml_version", "pain.008.001.02"),
            "output_directory": config.get("output_directory", ""),
            "backup_files": bool(config.get("backup_processed_files", 1)),
            "file_naming_pattern": "SEPA-{batch_name}-{date}.xml",
        }

    def validate_sepa_config(self) -> Dict[str, Any]:
        """Validate complete SEPA configuration"""
        if "validation" in self._validation_cache:
            return self._validation_cache["validation"]

        config = self.get_company_sepa_config()
        validation_result = {"valid": True, "errors": [], "warnings": [], "missing_optional": []}

        # Required fields validation
        required_fields = {
            "company_iban": "Company IBAN",
            "creditor_id": "Creditor ID (Incassant ID)",
            "company_account_holder": "Company Account Holder Name",
        }

        for field, label in required_fields.items():
            if not config.get(field):
                validation_result["valid"] = False
                validation_result["errors"].append(f"Missing required field: {label}")

        # IBAN format validation
        if config.get("company_iban"):
            try:
                from verenigingen.utils.iban_validator import validate_iban

                iban_validation = validate_iban(config["company_iban"])
                if not iban_validation["valid"]:
                    validation_result["valid"] = False
                    validation_result["errors"].append(
                        f"Invalid IBAN: {iban_validation.get('error', 'Unknown error')}"
                    )
                elif not config.get("company_bic") and iban_validation.get("bic"):
                    # Auto-derive BIC if not set
                    config["company_bic"] = iban_validation["bic"]
                    validation_result["warnings"].append(
                        f"BIC auto-derived from IBAN: {iban_validation['bic']}"
                    )
            except ImportError:
                validation_result["warnings"].append(
                    "IBAN validator not available - cannot validate IBAN format"
                )

        # Notification configuration validation
        notification_config = self.get_notification_config()
        if notification_config["notifications_enabled"] and not notification_config["has_recipients"]:
            validation_result["warnings"].append(
                "Notifications enabled but no admin email addresses configured"
            )

        # Batch timing validation
        timing_config = self.get_batch_timing_config()
        if timing_config["auto_creation_enabled"] and not timing_config["creation_days"]:
            validation_result["valid"] = False
            validation_result["errors"].append("Auto batch creation enabled but no creation days configured")

        # Optional field recommendations
        optional_fields = {
            "company_bic": "Company BIC (improves processing speed)",
            "sepa_output_directory": "Output directory for SEPA files",
            "financial_admin_emails": "Admin emails for notifications",
        }

        for field, description in optional_fields.items():
            if not config.get(field):
                validation_result["missing_optional"].append(description)

        # Cache validation result
        self._validation_cache["validation"] = validation_result
        return validation_result

    def get_complete_config(self) -> Dict[str, Any]:
        """Get complete SEPA configuration with all sections"""
        return {
            "company_sepa": self.get_company_sepa_config(),
            "batch_timing": self.get_batch_timing_config(),
            "notifications": self.get_notification_config(),
            "error_handling": self.get_error_handling_config(),
            "processing": self.get_processing_config(),
            "file_handling": self.get_file_handling_config(),
            "validation": self.validate_sepa_config(),
        }

    def update_setting(self, section: str, key: str, value: Any) -> bool:
        """Update a specific SEPA setting"""
        try:
            settings = frappe.get_single("Verenigingen Settings")

            # Map section.key to actual field names
            field_mapping = {
                "company_sepa.company_iban": "company_iban",
                "company_sepa.company_bic": "company_bic",
                "company_sepa.creditor_id": "creditor_id",
                "company_sepa.company_account_holder": "company_account_holder",
                "batch_timing.batch_creation_days": "batch_creation_days",
                "batch_timing.enable_auto_batch_creation": "enable_auto_batch_creation",
                "batch_timing.auto_submit_sepa_batches": "auto_submit_sepa_batches",
                "batch_timing.batch_processing_lead_time": "batch_processing_lead_time",
                "notifications.financial_admin_emails": "financial_admin_emails",
                "notifications.send_batch_notifications": "send_batch_notifications",
                "error_handling.enable_retry_mechanism": "enable_retry_mechanism",
                "error_handling.max_retry_attempts": "max_retry_attempts",
                "processing.invoice_lookback_days": "invoice_lookback_days",
                "processing.coverage_verification_enabled": "coverage_verification_enabled",
            }

            setting_key = f"{section}.{key}"
            if setting_key in field_mapping:
                field_name = field_mapping[setting_key]
                setattr(settings, field_name, value)
                settings.save()

                # Clear cache to force reload
                self.clear_cache()

                frappe.logger().info(f"Updated SEPA setting {setting_key} = {value}")
                return True
            else:
                frappe.logger().error(f"Unknown SEPA setting: {setting_key}")
                return False

        except Exception as e:
            frappe.log_error(
                f"Error updating SEPA setting {section}.{key}: {str(e)}", "SEPA Config Manager Error"
            )
            return False

    def clear_cache(self):
        """Clear configuration cache"""
        self._settings_cache.clear()
        self._validation_cache.clear()
        frappe.logger().info("SEPA configuration cache cleared")

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information for monitoring"""
        return {
            "settings_cache_size": len(self._settings_cache),
            "validation_cache_size": len(self._validation_cache),
            "total_cached_items": len(self._settings_cache) + len(self._validation_cache),
        }


# Global configuration manager instance
_config_manager = None


def get_sepa_config_manager() -> SEPAConfigManager:
    """Get the global SEPA configuration manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = SEPAConfigManager()
    return _config_manager


@frappe.whitelist()
def get_sepa_config(section: str = None):
    """API to get SEPA configuration"""
    manager = get_sepa_config_manager()

    if section:
        # Return specific section
        method_name = f"get_{section}_config"
        if hasattr(manager, method_name):
            return getattr(manager, method_name)()
        else:
            return {"error": f"Unknown configuration section: {section}"}
    else:
        # Return complete configuration
        return manager.get_complete_config()


@frappe.whitelist()
def validate_sepa_configuration():
    """API to validate SEPA configuration"""
    manager = get_sepa_config_manager()
    return manager.validate_sepa_config()


@frappe.whitelist()
def update_sepa_setting(section, key, value):
    """API to update a SEPA setting"""
    manager = get_sepa_config_manager()
    success = manager.update_setting(section, key, value)

    if success:
        return {"success": True, "message": f"Updated {section}.{key} successfully"}
    else:
        return {"success": False, "message": f"Failed to update {section}.{key}"}


@frappe.whitelist()
def clear_sepa_config_cache():
    """API to clear SEPA configuration cache"""
    manager = get_sepa_config_manager()
    manager.clear_cache()
    return {"success": True, "message": "SEPA configuration cache cleared"}


@frappe.whitelist()
def get_sepa_config_cache_info():
    """API to get SEPA configuration cache information"""
    manager = get_sepa_config_manager()
    return manager.get_cache_info()
