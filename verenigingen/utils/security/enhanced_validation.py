"""
Enhanced Input Validation and Error Handling Framework

This module extends the existing validation framework with comprehensive
schema-based validation, business rule validation, and secure error handling
specifically designed for association management APIs.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union

import frappe
from frappe import _
from frappe.utils import cstr, get_datetime, getdate

from verenigingen.utils.error_handling import ValidationError as VValidationError
from verenigingen.utils.security.audit_logging import AuditSeverity, get_audit_logger
from verenigingen.utils.validation.api_validators import APIValidator


class ValidationType(Enum):
    """Types of validation rules"""

    REQUIRED = "required"
    TYPE = "type"
    FORMAT = "format"
    RANGE = "range"
    LENGTH = "length"
    PATTERN = "pattern"
    ENUM = "enum"
    CUSTOM = "custom"
    BUSINESS_RULE = "business_rule"


class ValidationSeverity(Enum):
    """Validation error severity levels"""

    ERROR = "error"  # Validation failure - reject request
    WARNING = "warning"  # Validation concern - log but allow
    INFO = "info"  # Informational - log only


class ValidationRule:
    """Individual validation rule definition"""

    def __init__(
        self,
        rule_type: ValidationType,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
        message: str = None,
        validator: Callable = None,
        **params,
    ):
        self.rule_type = rule_type
        self.severity = severity
        self.message = message
        self.validator = validator
        self.params = params

    def validate(self, value: Any, field_name: str = None) -> Dict[str, Any]:
        """
        Validate value against this rule

        Returns:
            Dictionary with validation result
        """
        try:
            if self.rule_type == ValidationType.REQUIRED:
                return self._validate_required(value, field_name)
            elif self.rule_type == ValidationType.TYPE:
                return self._validate_type(value, field_name)
            elif self.rule_type == ValidationType.FORMAT:
                return self._validate_format(value, field_name)
            elif self.rule_type == ValidationType.RANGE:
                return self._validate_range(value, field_name)
            elif self.rule_type == ValidationType.LENGTH:
                return self._validate_length(value, field_name)
            elif self.rule_type == ValidationType.PATTERN:
                return self._validate_pattern(value, field_name)
            elif self.rule_type == ValidationType.ENUM:
                return self._validate_enum(value, field_name)
            elif self.rule_type == ValidationType.CUSTOM:
                return self._validate_custom(value, field_name)
            else:
                return {"valid": True}

        except Exception as e:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message or str(e),
                "rule_type": self.rule_type.value,
            }

    def _validate_required(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate required field"""
        if value is None or value == "" or (isinstance(value, str) and not value.strip()):
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message or _("{0} is required").format(field_name or "Field"),
                "rule_type": self.rule_type.value,
            }
        return {"valid": True}

    def _validate_type(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate data type"""
        expected_type = self.params.get("expected_type")
        if not expected_type:
            return {"valid": True}

        # Handle None values
        if value is None:
            return {"valid": True}

        # Special handling for string types
        if expected_type == "string" and not isinstance(value, str):
            value = cstr(value)
        elif expected_type == "integer":
            try:
                int(value)
            except (ValueError, TypeError):
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message or _("{0} must be an integer").format(field_name or "Field"),
                    "rule_type": self.rule_type.value,
                }
        elif expected_type == "float":
            try:
                float(value)
            except (ValueError, TypeError):
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message or _("{0} must be a number").format(field_name or "Field"),
                    "rule_type": self.rule_type.value,
                }
        elif expected_type == "boolean" and not isinstance(value, bool):
            if value not in [0, 1, "0", "1", "true", "false", "True", "False"]:
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message or _("{0} must be a boolean value").format(field_name or "Field"),
                    "rule_type": self.rule_type.value,
                }
        elif expected_type == "date":
            try:
                getdate(value)
            except:
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message or _("{0} must be a valid date").format(field_name or "Field"),
                    "rule_type": self.rule_type.value,
                }
        elif expected_type == "datetime":
            try:
                get_datetime(value)
            except:
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message
                    or _("{0} must be a valid datetime").format(field_name or "Field"),
                    "rule_type": self.rule_type.value,
                }

        return {"valid": True}

    def _validate_format(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate specific formats (email, phone, IBAN, etc.)"""
        if value is None or value == "":
            return {"valid": True}

        format_type = self.params.get("format_type")

        try:
            if format_type == "email":
                APIValidator.validate_email(value)
            elif format_type == "phone":
                APIValidator.validate_phone(value)
            elif format_type == "iban":
                APIValidator.validate_iban(value)
            elif format_type == "postal_code":
                country = self.params.get("country", "NL")
                APIValidator.validate_postal_code(value, country)
            else:
                return {"valid": True}  # Unknown format type

        except VValidationError as e:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message or str(e),
                "rule_type": self.rule_type.value,
            }

        return {"valid": True}

    def _validate_range(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate numeric ranges"""
        if value is None:
            return {"valid": True}

        try:
            numeric_value = float(value)

            min_val = self.params.get("min")
            max_val = self.params.get("max")

            if min_val is not None and numeric_value < min_val:
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message
                    or _("{0} must be at least {1}").format(field_name or "Field", min_val),
                    "rule_type": self.rule_type.value,
                }

            if max_val is not None and numeric_value > max_val:
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message
                    or _("{0} cannot exceed {1}").format(field_name or "Field", max_val),
                    "rule_type": self.rule_type.value,
                }

        except (ValueError, TypeError):
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message or _("{0} must be a numeric value").format(field_name or "Field"),
                "rule_type": self.rule_type.value,
            }

        return {"valid": True}

    def _validate_length(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate string/array length"""
        if value is None:
            return {"valid": True}

        length = len(value) if hasattr(value, "__len__") else 0

        min_length = self.params.get("min")
        max_length = self.params.get("max")

        if min_length is not None and length < min_length:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message
                or _("{0} must be at least {1} characters").format(field_name or "Field", min_length),
                "rule_type": self.rule_type.value,
            }

        if max_length is not None and length > max_length:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message
                or _("{0} cannot exceed {1} characters").format(field_name or "Field", max_length),
                "rule_type": self.rule_type.value,
            }

        return {"valid": True}

    def _validate_pattern(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate against regex pattern"""
        if value is None or value == "":
            return {"valid": True}

        pattern = self.params.get("pattern")
        if not pattern:
            return {"valid": True}

        try:
            if not re.match(pattern, str(value)):
                return {
                    "valid": False,
                    "severity": self.severity.value,
                    "message": self.message or _("{0} format is invalid").format(field_name or "Field"),
                    "rule_type": self.rule_type.value,
                }
        except re.error:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message or _("Invalid pattern configuration"),
                "rule_type": self.rule_type.value,
            }

        return {"valid": True}

    def _validate_enum(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Validate against allowed values"""
        if value is None:
            return {"valid": True}

        allowed_values = self.params.get("allowed_values", [])
        if value not in allowed_values:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message
                or _("{0} must be one of: {1}").format(
                    field_name or "Field", ", ".join(map(str, allowed_values))
                ),
                "rule_type": self.rule_type.value,
            }

        return {"valid": True}

    def _validate_custom(self, value: Any, field_name: str) -> Dict[str, Any]:
        """Run custom validation function"""
        if not self.validator:
            return {"valid": True}

        try:
            result = self.validator(value, field_name, **self.params)
            if isinstance(result, bool):
                return {
                    "valid": result,
                    "severity": self.severity.value if not result else ValidationSeverity.INFO.value,
                    "message": self.message if not result else None,
                    "rule_type": self.rule_type.value,
                }
            elif isinstance(result, dict):
                return result
            else:
                return {"valid": True}

        except Exception as e:
            return {
                "valid": False,
                "severity": self.severity.value,
                "message": self.message or str(e),
                "rule_type": self.rule_type.value,
            }


class ValidationSchema:
    """Schema-based validation configuration"""

    def __init__(self, schema_name: str, description: str = None):
        self.schema_name = schema_name
        self.description = description
        self.fields: Dict[str, List[ValidationRule]] = {}
        self.global_rules: List[ValidationRule] = []

    def add_field_rule(self, field_name: str, rule: ValidationRule):
        """Add validation rule for specific field"""
        if field_name not in self.fields:
            self.fields[field_name] = []
        self.fields[field_name].append(rule)

    def add_global_rule(self, rule: ValidationRule):
        """Add validation rule that applies to entire dataset"""
        self.global_rules.append(rule)

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate data against schema

        Returns:
            Validation result with errors, warnings, and sanitized data
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "info": [],
            "sanitized_data": {},
            "schema_name": self.schema_name,
        }

        # Validate each field
        for field_name, value in data.items():
            if field_name in self.fields:
                field_result = self._validate_field(field_name, value)

                # Collect validation issues
                for issue in field_result.get("issues", []):
                    if issue["severity"] == ValidationSeverity.ERROR.value:
                        result["errors"].append(issue)
                        result["valid"] = False
                    elif issue["severity"] == ValidationSeverity.WARNING.value:
                        result["warnings"].append(issue)
                    else:
                        result["info"].append(issue)

                # Use sanitized value
                result["sanitized_data"][field_name] = field_result.get("sanitized_value", value)
            else:
                # Field not in schema - sanitize basic string values
                if isinstance(value, str):
                    result["sanitized_data"][field_name] = APIValidator.sanitize_text(value, max_length=1000)
                else:
                    result["sanitized_data"][field_name] = value

        # Run global rules
        for rule in self.global_rules:
            global_result = rule.validate(data, "dataset")
            if not global_result.get("valid", True):
                issue = {
                    "field": "global",
                    "severity": global_result.get("severity", ValidationSeverity.ERROR.value),
                    "message": global_result.get("message", "Global validation failed"),
                    "rule_type": global_result.get("rule_type", "unknown"),
                }

                if issue["severity"] == ValidationSeverity.ERROR.value:
                    result["errors"].append(issue)
                    result["valid"] = False
                elif issue["severity"] == ValidationSeverity.WARNING.value:
                    result["warnings"].append(issue)
                else:
                    result["info"].append(issue)

        return result

    def _validate_field(self, field_name: str, value: Any) -> Dict[str, Any]:
        """Validate individual field against its rules"""
        result = {"issues": [], "sanitized_value": value}

        rules = self.fields.get(field_name, [])
        for rule in rules:
            rule_result = rule.validate(value, field_name)

            if not rule_result.get("valid", True):
                result["issues"].append(
                    {
                        "field": field_name,
                        "severity": rule_result.get("severity", ValidationSeverity.ERROR.value),
                        "message": rule_result.get("message", "Validation failed"),
                        "rule_type": rule_result.get("rule_type", "unknown"),
                    }
                )

            # Apply sanitization for string fields
            if isinstance(value, str) and rule.rule_type == ValidationType.FORMAT:
                try:
                    result["sanitized_value"] = APIValidator.sanitize_text(value)
                except:
                    pass  # Keep original value if sanitization fails

        return result


class SchemaRegistry:
    """Registry for validation schemas"""

    def __init__(self):
        self.schemas: Dict[str, ValidationSchema] = {}
        self._setup_default_schemas()

    def register_schema(self, schema: ValidationSchema):
        """Register a validation schema"""
        self.schemas[schema.schema_name] = schema

    def get_schema(self, schema_name: str) -> Optional[ValidationSchema]:
        """Get registered schema by name"""
        return self.schemas.get(schema_name)

    def _setup_default_schemas(self):
        """Setup default validation schemas for common Verenigingen operations"""

        # Member data validation schema
        member_schema = ValidationSchema("member_data", "Member information validation")
        member_schema.add_field_rule("first_name", ValidationRule(ValidationType.REQUIRED))
        member_schema.add_field_rule("first_name", ValidationRule(ValidationType.LENGTH, max=100))
        member_schema.add_field_rule("last_name", ValidationRule(ValidationType.REQUIRED))
        member_schema.add_field_rule("last_name", ValidationRule(ValidationType.LENGTH, max=100))
        member_schema.add_field_rule("email_id", ValidationRule(ValidationType.REQUIRED))
        member_schema.add_field_rule("email_id", ValidationRule(ValidationType.FORMAT, format_type="email"))
        member_schema.add_field_rule(
            "phone",
            ValidationRule(ValidationType.FORMAT, severity=ValidationSeverity.WARNING, format_type="phone"),
        )
        member_schema.add_field_rule(
            "postal_code", ValidationRule(ValidationType.FORMAT, format_type="postal_code", country="NL")
        )
        member_schema.add_field_rule("birth_date", ValidationRule(ValidationType.TYPE, expected_type="date"))
        self.register_schema(member_schema)

        # Payment data validation schema
        payment_schema = ValidationSchema("payment_data", "Payment processing validation")
        payment_schema.add_field_rule("amount", ValidationRule(ValidationType.REQUIRED))
        payment_schema.add_field_rule("amount", ValidationRule(ValidationType.TYPE, expected_type="float"))
        payment_schema.add_field_rule("amount", ValidationRule(ValidationType.RANGE, min=0.01, max=10000.00))
        payment_schema.add_field_rule("iban", ValidationRule(ValidationType.FORMAT, format_type="iban"))
        payment_schema.add_field_rule("description", ValidationRule(ValidationType.LENGTH, max=500))
        payment_schema.add_field_rule(
            "currency", ValidationRule(ValidationType.ENUM, allowed_values=["EUR", "USD"])
        )
        self.register_schema(payment_schema)

        # SEPA batch validation schema
        sepa_schema = ValidationSchema("sepa_batch", "SEPA batch operation validation")
        sepa_schema.add_field_rule("batch_name", ValidationRule(ValidationType.REQUIRED))
        sepa_schema.add_field_rule("batch_name", ValidationRule(ValidationType.LENGTH, min=3, max=100))
        sepa_schema.add_field_rule("execution_date", ValidationRule(ValidationType.REQUIRED))
        sepa_schema.add_field_rule(
            "execution_date", ValidationRule(ValidationType.TYPE, expected_type="date")
        )
        sepa_schema.add_field_rule("invoice_ids", ValidationRule(ValidationType.REQUIRED))
        sepa_schema.add_field_rule(
            "creditor_account", ValidationRule(ValidationType.FORMAT, format_type="iban")
        )
        self.register_schema(sepa_schema)

        # Volunteer data validation schema
        volunteer_schema = ValidationSchema("volunteer_data", "Volunteer information validation")
        volunteer_schema.add_field_rule("member", ValidationRule(ValidationType.REQUIRED))
        volunteer_schema.add_field_rule("skills", ValidationRule(ValidationType.LENGTH, max=2000))
        volunteer_schema.add_field_rule("availability", ValidationRule(ValidationType.LENGTH, max=1000))
        volunteer_schema.add_field_rule(
            "emergency_contact",
            ValidationRule(ValidationType.FORMAT, severity=ValidationSeverity.WARNING, format_type="phone"),
        )
        self.register_schema(volunteer_schema)


# Global schema registry
_schema_registry = None


def get_schema_registry() -> SchemaRegistry:
    """Get global schema registry instance"""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = SchemaRegistry()
    return _schema_registry


class EnhancedValidator:
    """Enhanced validation engine with comprehensive error handling"""

    def __init__(self):
        self.audit_logger = get_audit_logger()
        self.schema_registry = get_schema_registry()

    def validate_with_schema(self, data: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
        """
        Validate data using registered schema

        Args:
            data: Data to validate
            schema_name: Name of validation schema

        Returns:
            Validation result with errors and sanitized data
        """
        schema = self.schema_registry.get_schema(schema_name)
        if not schema:
            raise VValidationError(_("Unknown validation schema: {0}").format(schema_name))

        result = schema.validate(data)

        # Log validation events
        if result["errors"]:
            self.audit_logger.log_event(
                "validation_failed",
                AuditSeverity.WARNING,
                details={
                    "schema": schema_name,
                    "error_count": len(result["errors"]),
                    "warning_count": len(result["warnings"]),
                    "errors": result["errors"],
                },
            )
        elif result["warnings"]:
            self.audit_logger.log_event(
                "validation_warnings",
                AuditSeverity.INFO,
                details={
                    "schema": schema_name,
                    "warning_count": len(result["warnings"]),
                    "warnings": result["warnings"],
                },
            )

        return result

    def validate_business_rules(self, data: Dict[str, Any], rules: List[Callable]) -> Dict[str, Any]:
        """
        Validate against business rules

        Args:
            data: Data to validate
            rules: List of business rule validation functions

        Returns:
            Validation result
        """
        result = {"valid": True, "errors": [], "warnings": [], "sanitized_data": data.copy()}

        for rule_func in rules:
            try:
                rule_result = rule_func(data)

                if isinstance(rule_result, dict):
                    if not rule_result.get("valid", True):
                        severity = rule_result.get("severity", "error")
                        issue = {
                            "rule": rule_func.__name__,
                            "severity": severity,
                            "message": rule_result.get("message", "Business rule validation failed"),
                        }

                        if severity == "error":
                            result["errors"].append(issue)
                            result["valid"] = False
                        elif severity == "warning":
                            result["warnings"].append(issue)

            except Exception as e:
                result["errors"].append(
                    {
                        "rule": rule_func.__name__,
                        "severity": "error",
                        "message": f"Business rule execution failed: {str(e)}",
                    }
                )
                result["valid"] = False

        return result

    def create_secure_error_response(
        self, validation_result: Dict[str, Any], expose_details: bool = False
    ) -> Dict[str, Any]:
        """
        Create secure error response that doesn't expose sensitive information

        Args:
            validation_result: Validation result from schema or business rule validation
            expose_details: Whether to expose detailed error information (admin only)

        Returns:
            Secure error response
        """
        if validation_result.get("valid", True):
            return {
                "success": True,
                "data": validation_result.get("sanitized_data", {}),
                "warnings": validation_result.get("warnings", []) if expose_details else [],
            }

        # Create secure error response
        response = {
            "success": False,
            "message": _("Validation failed"),
            "error_count": len(validation_result.get("errors", [])),
        }

        if expose_details:
            # Full error details for admin users
            response["errors"] = validation_result.get("errors", [])
            response["warnings"] = validation_result.get("warnings", [])
            response["schema"] = validation_result.get("schema_name")
        else:
            # Generic error for regular users
            response["errors"] = [{"message": _("Invalid input data provided"), "code": "VALIDATION_ERROR"}]

        return response


# Global validator instance
_enhanced_validator = None


def get_enhanced_validator() -> EnhancedValidator:
    """Get global enhanced validator instance"""
    global _enhanced_validator
    if _enhanced_validator is None:
        _enhanced_validator = EnhancedValidator()
    return _enhanced_validator


# Decorator for schema-based validation
def validate_with_schema(schema_name: str, expose_errors: bool = False):
    """
    Decorator for automatic schema-based validation

    Usage:
        @frappe.whitelist()
        @validate_with_schema("member_data")
        def create_member(**data):
            # Function receives validated data
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            validator = get_enhanced_validator()

            # Validate input data
            validation_result = validator.validate_with_schema(kwargs, schema_name)

            # Check if validation passed
            if not validation_result["valid"]:
                # Create secure error response
                expose_details = expose_errors or frappe.has_permission("System Manager")
                error_response = validator.create_secure_error_response(validation_result, expose_details)

                if expose_details:
                    # Raise detailed validation error for admins
                    raise VValidationError(json.dumps(error_response, indent=2))
                else:
                    # Raise generic error for regular users
                    raise VValidationError(_("Invalid input data provided"))

            # Use sanitized data
            sanitized_kwargs = validation_result["sanitized_data"]

            return func(*args, **sanitized_kwargs)

        return wrapper

    return decorator


# Business rule validation decorators
def validate_business_rules(*rule_functions):
    """
    Decorator for business rule validation

    Usage:
        @validate_business_rules(check_member_age, check_membership_status)
        def process_member_application(**data):
            # Function implementation
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            validator = get_enhanced_validator()

            # Validate business rules
            validation_result = validator.validate_business_rules(kwargs, list(rule_functions))

            if not validation_result["valid"]:
                error_messages = [error["message"] for error in validation_result["errors"]]
                raise VValidationError("; ".join(error_messages))

            return func(*args, **kwargs)

        return wrapper

    return decorator


# API endpoints for validation management
@frappe.whitelist()
def get_validation_schemas():
    """Get list of available validation schemas"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Access denied"), frappe.PermissionError)

    registry = get_schema_registry()

    schemas = {}
    for name, schema in registry.schemas.items():
        schemas[name] = {
            "name": schema.schema_name,
            "description": schema.description,
            "fields": list(schema.fields.keys()),
            "global_rules": len(schema.global_rules),
        }

    return {"success": True, "schemas": schemas}


@frappe.whitelist()
def validate_data_with_schema(data: str, schema_name: str):
    """API endpoint to validate data against schema"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Access denied"), frappe.PermissionError)

    try:
        data_dict = json.loads(data) if isinstance(data, str) else data
        validator = get_enhanced_validator()

        result = validator.validate_with_schema(data_dict, schema_name)
        return validator.create_secure_error_response(result, expose_details=True)

    except Exception as e:
        return {"success": False, "error": str(e)}


def setup_enhanced_validation():
    """Setup enhanced validation framework"""
    # Initialize global components
    global _schema_registry, _enhanced_validator
    _schema_registry = SchemaRegistry()
    _enhanced_validator = EnhancedValidator()

    # Log setup completion
    _enhanced_validator.audit_logger.log_event(
        "enhanced_validation_initialized",
        AuditSeverity.INFO,
        details={
            "schemas_registered": len(_schema_registry.schemas),
            "default_schemas": list(_schema_registry.schemas.keys()),
        },
    )
