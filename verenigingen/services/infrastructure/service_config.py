"""
Service Configuration - Centralized configuration management for services.

This module provides configuration management utilities for services with
environment-specific settings, validation, and dynamic reconfiguration.

Classes:
    - ServiceConfig: Configuration container with validation
    - ConfigurationManager: Centralized configuration management
    - EnvironmentConfig: Environment-specific configuration handling
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _

from verenigingen.utils.service_error_handler import ServiceError


class ServiceConfig:
    """Configuration container for services with validation and type checking."""

    def __init__(self, config_dict: Dict = None):
        """Initialize service configuration.

        Args:
            config_dict: Initial configuration dictionary
        """
        self._config = config_dict or {}
        self._validators = {}
        self._required_keys = set()
        self._environment_overrides = {}

    def set(self, key: str, value: Any, required: bool = False):
        """Set a configuration value.

        Args:
            key: Configuration key
            value: Configuration value
            required: Whether this key is required
        """
        self._config[key] = value
        if required:
            self._required_keys.add(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        # Check for environment override first
        env_key = f"VERENIGINGEN_{key.upper()}"
        if env_key in os.environ:
            return self._convert_env_value(os.environ[env_key])

        return self._config.get(key, default)

    def get_required(self, key: str) -> Any:
        """Get a required configuration value.

        Args:
            key: Configuration key

        Returns:
            Configuration value

        Raises:
            ServiceError: If required key is missing
        """
        if key not in self._config and f"VERENIGINGEN_{key.upper()}" not in os.environ:
            raise ServiceError(f"Required configuration key missing: {key}")

        return self.get(key)

    def add_validator(self, key: str, validator_func, error_message: str = None):
        """Add a validator function for a configuration key.

        Args:
            key: Configuration key
            validator_func: Function that validates the value
            error_message: Custom error message for validation failures
        """
        self._validators[key] = {
            "func": validator_func,
            "error_message": error_message or f"Validation failed for {key}",
        }

    def add_type_validator(self, key: str, expected_type: type, min_value: Any = None, max_value: Any = None):
        """Add type and range validation for a configuration key.

        Args:
            key: Configuration key
            expected_type: Expected Python type
            min_value: Minimum value (for numeric types)
            max_value: Maximum value (for numeric types)
        """

        def type_range_validator(value):
            if not isinstance(value, expected_type):
                return False
            if min_value is not None and value < min_value:
                return False
            if max_value is not None and value > max_value:
                return False
            return True

        error_parts = [f"must be {expected_type.__name__}"]
        if min_value is not None:
            error_parts.append(f"minimum {min_value}")
        if max_value is not None:
            error_parts.append(f"maximum {max_value}")

        self.add_validator(key, type_range_validator, f"Value for {key} {', '.join(error_parts)}")

    def add_choice_validator(self, key: str, valid_choices: List[Any]):
        """Add choice validation for a configuration key.

        Args:
            key: Configuration key
            valid_choices: List of valid values
        """

        def choice_validator(value):
            return value in valid_choices

        self.add_validator(
            key,
            choice_validator,
            f"Value for {key} must be one of: {', '.join(str(c) for c in valid_choices)}",
        )

    def validate(self) -> List[str]:
        """Validate all configuration values.

        Returns:
            List of validation errors
        """
        errors = []

        # Check required keys
        for key in self._required_keys:
            if key not in self._config and f"VERENIGINGEN_{key.upper()}" not in os.environ:
                errors.append(f"Required configuration key missing: {key}")

        # Run validators
        for key, validator_info in self._validators.items():
            try:
                value = self.get(key)
                if value is not None:
                    validator_func = (
                        validator_info.get("func") if isinstance(validator_info, dict) else validator_info
                    )
                    if not validator_func(value):
                        error_msg = (
                            validator_info.get("error_message")
                            if isinstance(validator_info, dict)
                            else f"Validation failed for {key}"
                        )
                        errors.append(error_msg)
            except Exception as e:
                errors.append(f"Configuration validator error for {key}: {str(e)}")

        return errors

    def merge(self, other_config: "ServiceConfig"):
        """Merge another configuration into this one.

        Args:
            other_config: ServiceConfig to merge
        """
        self._config.update(other_config._config)
        self._required_keys.update(other_config._required_keys)
        self._validators.update(other_config._validators)

    def validate_and_set(self, key: str, value: Any, required: bool = False) -> bool:
        """Set a value with immediate validation.

        Args:
            key: Configuration key
            value: Value to set
            required: Whether this key is required

        Returns:
            True if validation passed

        Raises:
            ValueError: If validation fails
        """
        # Temporarily set the value for validation
        old_value = self._config.get(key)
        self._config[key] = value

        try:
            # Run validation
            errors = self.validate()
            key_errors = [e for e in errors if key in e]

            if key_errors:
                # Restore old value and raise error
                if old_value is not None:
                    self._config[key] = old_value
                else:
                    self._config.pop(key, None)
                raise ValueError(f"Validation failed: {'; '.join(key_errors)}")

            # Validation passed, set required flag
            if required:
                self._required_keys.add(key)

            return True

        except Exception:
            # Restore old value on any error
            if old_value is not None:
                self._config[key] = old_value
            else:
                self._config.pop(key, None)
            raise

    def to_dict(self) -> Dict:
        """Convert configuration to dictionary.

        Returns:
            Configuration as dictionary
        """
        return self._config.copy()

    def _convert_env_value(self, value: str) -> Union[str, int, float, bool]:
        """Convert environment variable string to appropriate type.

        Args:
            value: String value from environment

        Returns:
            Converted value
        """
        # Try boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"

        # Try integer
        try:
            return int(value)
        except ValueError:
            pass

        # Try float
        try:
            return float(value)
        except ValueError:
            pass

        # Return as string
        return value


class ConfigurationManager:
    """Centralized configuration management for all services."""

    def __init__(self):
        self._service_configs = {}
        self._global_config = ServiceConfig()
        self.logger = logging.getLogger("verenigingen.services.config")

    def register_service_config(self, service_name: str, config: ServiceConfig):
        """Register configuration for a service.

        Args:
            service_name: Name of the service
            config: ServiceConfig instance
        """
        self._service_configs[service_name] = config
        self.logger.info(f"Registered configuration for service: {service_name}")

    def get_service_config(self, service_name: str) -> ServiceConfig:
        """Get configuration for a service.

        Args:
            service_name: Name of the service

        Returns:
            ServiceConfig instance

        Raises:
            ServiceError: If service configuration not found
        """
        if service_name not in self._service_configs:
            # Create default configuration
            self._service_configs[service_name] = ServiceConfig()
            self.logger.info(f"Created default configuration for service: {service_name}")

        return self._service_configs[service_name]

    def set_global_config(self, key: str, value: Any):
        """Set a global configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        self._global_config.set(key, value)

    def get_global_config(self, key: str, default: Any = None) -> Any:
        """Get a global configuration value.

        Args:
            key: Configuration key
            default: Default value

        Returns:
            Configuration value
        """
        return self._global_config.get(key, default)

    def load_from_settings(self):
        """Load configuration from Verenigingen Settings doctype."""
        try:
            settings = frappe.get_single("Verenigingen Settings")

            # Load common settings with defensive field access
            self._safe_load_field(settings, "default_member_id_prefix", "member_id_prefix")
            self._safe_load_field(settings, "enable_debug_logging", "debug_logging")

            # Load service-specific settings
            self._load_member_service_settings(settings)

            self.logger.info("Loaded configuration from Verenigingen Settings")

        except Exception as e:
            self.logger.warning(f"Could not load settings from DocType: {str(e)}")

    def _safe_load_field(self, settings, field_name: str, config_key: str, default=None):
        """Safely load a field from settings with defensive checking.

        Args:
            settings: Settings document
            field_name: Field name in the document
            config_key: Configuration key to set
            default: Default value if field doesn't exist
        """
        try:
            if hasattr(settings, field_name):
                value = getattr(settings, field_name, default)
                if value is not None:
                    self.set_global_config(config_key, value)
                    self.logger.debug(f"Loaded {field_name} -> {config_key}: {value}")
            else:
                self.logger.debug(f"Field {field_name} not found in settings")
        except Exception as e:
            self.logger.warning(f"Error loading field {field_name}: {str(e)}")
            if default is not None:
                self.set_global_config(config_key, default)

    def _load_member_service_settings(self, settings):
        """Load member service specific settings.

        Args:
            settings: Verenigingen Settings document
        """
        member_config = self.get_service_config("member_services")

        # Define field mappings with defaults and validation.
        #
        # Field names are the REAL Verenigingen Settings fieldnames (the loader
        # previously referenced stale/renamed names which never matched, so the
        # configured values silently fell through to the hardcoded defaults):
        #   member_id_start_number -> member_id_start
        #
        # `id_length` and `default_status` have NO corresponding field on the
        # current Verenigingen Settings doctype, so they keep their hardcoded
        # defaults (no field mapping) instead of referencing a phantom field.
        #
        # A `minimum_membership_age -> minimum_age` mapping used to live here,
        # with a hardcoded default of 16 and min_val=0 -- silently accepting the
        # exact missing/zero setting that AgeValidator._get_configurable_min_age
        # deliberately refuses on. No consumer of member_config.get("minimum_age")
        # ever existed (grepped: only this line and its own test read it), so the
        # contradiction was reachable by nothing. Removed rather than reconciled
        # with the policy it never enforced (#673); age minimums for actual
        # validation are sourced solely from AgeValidator._get_configurable_min_age.
        field_mappings = [
            ("member_id_start", "id_start_number", 1000, int, 1, 999999),
        ]

        # Config keys with no backing settings field: seed their defaults so
        # downstream consumers still get a value.
        member_config.set("id_length", 6)
        member_config.set("default_status", "Active")

        # Load each field safely with validation
        for field_name, config_key, default_value, expected_type, min_val, max_val in field_mappings:
            try:
                if hasattr(settings, field_name):
                    value = getattr(settings, field_name, default_value)
                    if value is not None:
                        # Add type and range validation
                        if expected_type in (int, float) and min_val is not None and max_val is not None:
                            member_config.add_type_validator(config_key, expected_type, min_val, max_val)
                        elif expected_type == str:
                            member_config.add_type_validator(config_key, expected_type)

                        try:
                            member_config.validate_and_set(config_key, value)
                            self.logger.debug(f"Loaded member service {field_name} -> {config_key}: {value}")
                        except ValueError as ve:
                            self.logger.warning(
                                f"Validation failed for {field_name}, using default: {str(ve)}"
                            )
                            member_config.set(config_key, default_value)
                    else:
                        member_config.set(config_key, default_value)
                else:
                    member_config.set(config_key, default_value)
                    self.logger.debug(f"Using default for {field_name}: {default_value}")
            except Exception as e:
                self.logger.warning(f"Error loading member service field {field_name}: {str(e)}")
                member_config.set(config_key, default_value)

    def save_to_file(self, file_path: str):
        """Save configuration to a JSON file.

        Args:
            file_path: Path to save configuration
        """
        config_data = {
            "global": self._global_config.to_dict(),
            "services": {name: config.to_dict() for name, config in self._service_configs.items()},
        }

        try:
            with open(file_path, "w") as f:
                json.dump(config_data, f, indent=2)
            self.logger.info(f"Saved configuration to: {file_path}")
        except Exception as e:
            raise ServiceError(f"Failed to save configuration: {str(e)}")

    def load_from_file(self, file_path: str):
        """Load configuration from a JSON file.

        Args:
            file_path: Path to load configuration from
        """
        try:
            with open(file_path, "r") as f:
                config_data = json.load(f)

            # Load global configuration
            if "global" in config_data:
                self._global_config = ServiceConfig(config_data["global"])

            # Load service configurations
            if "services" in config_data:
                for service_name, service_config_data in config_data["services"].items():
                    self._service_configs[service_name] = ServiceConfig(service_config_data)

            self.logger.info(f"Loaded configuration from: {file_path}")

        except Exception as e:
            raise ServiceError(f"Failed to load configuration: {str(e)}")

    def validate_all_configurations(self) -> Dict[str, List[str]]:
        """Validate all service configurations.

        Returns:
            Dictionary mapping service names to validation errors
        """
        all_errors = {}

        # Validate global configuration
        global_errors = self._global_config.validate()
        if global_errors:
            all_errors["global"] = global_errors

        # Validate service configurations
        for service_name, config in self._service_configs.items():
            errors = config.validate()
            if errors:
                all_errors[service_name] = errors

        return all_errors

    def get_configuration_summary(self) -> Dict:
        """Get a summary of all configurations.

        Returns:
            Configuration summary
        """
        return {
            "global_config_keys": list(self._global_config._config.keys()),
            "service_count": len(self._service_configs),
            "services": list(self._service_configs.keys()),
            "validation_status": len(self.validate_all_configurations()) == 0,
        }


class EnvironmentConfig:
    """Environment-specific configuration handling."""

    ENVIRONMENTS = ["development", "testing", "staging", "production"]

    @staticmethod
    def get_current_environment() -> str:
        """Get the current environment.

        Returns:
            Current environment name
        """
        return os.environ.get("VERENIGINGEN_ENVIRONMENT", "development")

    @staticmethod
    def is_development() -> bool:
        """Check if running in development environment."""
        return EnvironmentConfig.get_current_environment() == "development"

    @staticmethod
    def is_production() -> bool:
        """Check if running in production environment."""
        return EnvironmentConfig.get_current_environment() == "production"

    @staticmethod
    def load_environment_config(config_manager: ConfigurationManager):
        """Load environment-specific configuration.

        Args:
            config_manager: ConfigurationManager to configure
        """
        env = EnvironmentConfig.get_current_environment()

        if env == "development":
            config_manager.set_global_config("debug_logging", True)
            config_manager.set_global_config("cache_timeout", 60)
            config_manager.set_global_config("strict_validation", False)

        elif env == "testing":
            config_manager.set_global_config("debug_logging", True)
            config_manager.set_global_config("cache_timeout", 0)  # No caching in tests
            config_manager.set_global_config("strict_validation", True)

        elif env == "production":
            config_manager.set_global_config("debug_logging", False)
            config_manager.set_global_config("cache_timeout", 3600)
            config_manager.set_global_config("strict_validation", True)


# Global configuration manager instance
_global_config_manager = None


def get_config_manager() -> ConfigurationManager:
    """Get the global configuration manager instance.

    Returns:
        Global ConfigurationManager instance
    """
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = ConfigurationManager()
        _global_config_manager.load_from_settings()
        EnvironmentConfig.load_environment_config(_global_config_manager)
    return _global_config_manager


def get_service_config(service_name: str) -> ServiceConfig:
    """Get configuration for a service.

    Args:
        service_name: Name of the service

    Returns:
        ServiceConfig instance
    """
    return get_config_manager().get_service_config(service_name)


def get_global_config(key: str, default: Any = None) -> Any:
    """Get a global configuration value.

    Args:
        key: Configuration key
        default: Default value

    Returns:
        Configuration value
    """
    return get_config_manager().get_global_config(key, default)


def validate_service_configuration(service_name: str) -> List[str]:
    """Validate configuration for a specific service.

    Args:
        service_name: Name of the service

    Returns:
        List of validation errors
    """
    config = get_service_config(service_name)
    return config.validate()
