# Verenigingen Security Framework API Reference

**Version**: 2.0
**Last Updated**: September 15, 2025
**Audience**: Developers, Technical Reference

## Table of Contents

1. [Security Decorators](#security-decorators)
2. [Security Levels and Profiles](#security-levels-and-profiles)
3. [Operation Types](#operation-types)
4. [Critical Operation Rules API](#critical-operation-rules-api)
5. [Security Monitoring API](#security-monitoring-api)
6. [Utility Functions](#utility-functions)
7. [Configuration Classes](#configuration-classes)
8. [Error Handling](#error-handling)

## Security Decorators

### @critical_api

Decorator for critical security operations (financial, administrative).

```python
from verenigingen.utils.security.api_security_framework import critical_api, OperationType

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def function_name(param1, param2):
    """Function documentation"""
    pass
```

**Parameters:**
- `operation_type` (OperationType, optional): Type of operation being performed
  - Default: `OperationType.FINANCIAL`
  - Options: `FINANCIAL`, `MEMBER_DATA`, `ADMIN`, `REPORTING`, `UTILITY`, `PUBLIC`

**Security Level:** `CRITICAL`

**Default Requirements:**
- **Roles:** System Manager, Verenigingen Administrator
- **Rate Limit:** 10 calls per hour
- **CSRF Protection:** Required
- **Audit Logging:** Detailed
- **Input Validation:** Required
- **IP Restrictions:** Enabled

### @high_security_api

Decorator for high security operations (member data, batch operations).

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def function_name(param1, param2):
    """Function documentation"""
    pass
```

**Parameters:**
- `operation_type` (OperationType, optional): Type of operation being performed
  - Default: `OperationType.MEMBER_DATA`

**Security Level:** `HIGH`

**Default Requirements:**
- **Roles:** System Manager, Verenigingen Administrator, Verenigingen Manager
- **Rate Limit:** 50 calls per hour
- **CSRF Protection:** Required
- **Audit Logging:** Standard
- **Input Validation:** Required

### @standard_api

Decorator for standard security operations (reporting, read operations).

```python
# Usage patterns:
@frappe.whitelist()
@standard_api
def function_name():
    pass

@frappe.whitelist()
@standard_api()
def function_name():
    pass

@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def function_name():
    pass
```

**Parameters:**
- `operation_type` (OperationType, optional): Type of operation being performed
  - Default: `OperationType.REPORTING`

**Security Level:** `MEDIUM`

**Default Requirements:**
- **Roles:** System Manager, Verenigingen Administrator, Verenigingen Manager, Verenigingen Staff
- **Rate Limit:** 200 calls per hour
- **CSRF Protection:** Not required
- **Audit Logging:** Selective
- **Input Validation:** Required

### @utility_api

Decorator for utility operations (health checks, status endpoints).

```python
# Usage patterns:
@frappe.whitelist()
@utility_api
def function_name():
    pass

@frappe.whitelist()
@utility_api()
def function_name():
    pass

@frappe.whitelist()
@utility_api(operation_type=OperationType.UTILITY)
def function_name():
    pass
```

**Parameters:**
- `operation_type` (OperationType, optional): Type of operation being performed
  - Default: `OperationType.UTILITY`

**Security Level:** `LOW`

**Default Requirements:**
- **Roles:** Any authenticated user
- **Rate Limit:** 500 calls per hour
- **CSRF Protection:** Not required
- **Audit Logging:** Minimal
- **Input Validation:** Required

### @public_api

Decorator for public operations (no authentication required).

```python
# Usage patterns:
@frappe.whitelist(allow_guest=True)
@public_api
def function_name():
    pass

@frappe.whitelist(allow_guest=True)
@public_api()
def function_name():
    pass

@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def function_name():
    pass
```

**Parameters:**
- `operation_type` (OperationType, optional): Type of operation being performed
  - Default: `OperationType.PUBLIC`

**Security Level:** `PUBLIC`

**Default Requirements:**
- **Roles:** None (guest access allowed)
- **Rate Limit:** 1000 calls per hour
- **CSRF Protection:** Not required
- **Audit Logging:** Minimal
- **Input Validation:** Basic

### Environment-Aware Decorators

#### @development_only_api

Restricts access to development environment only.

```python
@frappe.whitelist()
@development_only_api(
    operation_type=OperationType.UTILITY,
    security_level=SecurityLevel.LOW
)
def debug_function():
    """Only available in development environment"""
    pass
```

**Parameters:**
- `operation_type` (OperationType, optional): Type of operation
  - Default: `OperationType.UTILITY`
- `security_level` (SecurityLevel, optional): Security level override
  - Default: `SecurityLevel.LOW`

#### @staging_and_dev_api

Allows access in staging and development environments.

```python
@frappe.whitelist()
@staging_and_dev_api(
    operation_type=OperationType.ADMIN,
    security_level=SecurityLevel.MEDIUM
)
def test_function():
    """Available in staging and development"""
    pass
```

#### @non_production_api

Restricts access to non-production environments (staging and development).

```python
@frappe.whitelist()
@non_production_api(
    operation_type=OperationType.ADMIN,
    security_level=SecurityLevel.HIGH
)
def admin_test_function():
    """Not available in production"""
    pass
```

### Advanced Decorator Configuration

#### @api_security_framework

Low-level decorator with full customization options.

```python
from verenigingen.utils.security.api_security_framework import (
    api_security_framework,
    SecurityLevel,
    OperationType,
    EnvironmentLevel
)

@frappe.whitelist()
@api_security_framework(
    security_level=SecurityLevel.HIGH,
    operation_type=OperationType.FINANCIAL,
    roles=["Custom Role"],
    permissions=["Sales Invoice:create"],
    rate_limit={"requests": 20, "window_seconds": 1800},
    validation_schema={"amount": "float", "member_id": "string"},
    audit_level="detailed",
    custom_validators=[custom_validation_function],
    allowed_environments=[EnvironmentLevel.PRODUCTION, EnvironmentLevel.STAGING]
)
def custom_function(amount, member_id):
    """Custom function with specific security requirements"""
    pass
```

**Parameters:**
- `security_level` (SecurityLevel, optional): Override security classification
- `operation_type` (OperationType, optional): Type of operation for automatic classification
- `roles` (List[str], optional): Additional role requirements
- `permissions` (List[str], optional): Additional permission requirements
- `rate_limit` (Dict[str, int], optional): Custom rate limit configuration
- `validation_schema` (Dict[str, Any], optional): Custom validation schema
- `audit_level` (str, optional): Audit logging level (standard, detailed, minimal)
- `custom_validators` (List[Callable], optional): Additional custom validation functions
- `allowed_environments` (List[EnvironmentLevel], optional): Allowed environments

## Security Levels and Profiles

### SecurityLevel Enum

```python
from verenigingen.utils.security.api_security_framework import SecurityLevel

class SecurityLevel(Enum):
    CRITICAL = "critical"  # Financial transactions, system administration
    HIGH = "high"          # Member data access, batch operations
    MEDIUM = "medium"      # Reporting, read-only operations
    LOW = "low"            # Utility functions, health checks
    PUBLIC = "public"      # No authentication required
```

### SecurityProfile Class

```python
class SecurityProfile:
    def __init__(
        self,
        level: SecurityLevel,
        required_roles: List[str] = None,
        required_permissions: List[str] = None,
        rate_limit_config: Dict[str, int] = None,
        requires_csrf: bool = True,
        requires_audit: bool = True,
        input_validation: bool = True,
        ip_restrictions: bool = False,
        business_hours_only: bool = False,
        max_request_size: int = 1024 * 1024,
        allowed_methods: List[str] = None,
        allowed_environments: List[EnvironmentLevel] = None,
    ):
        pass
```

**Attributes:**
- `level`: Security level classification
- `required_roles`: List of required user roles
- `required_permissions`: List of required permissions
- `rate_limit_config`: Rate limiting configuration
- `requires_csrf`: Whether CSRF protection is required
- `requires_audit`: Whether audit logging is required
- `input_validation`: Whether input validation is required
- `ip_restrictions`: Whether IP-based restrictions apply
- `business_hours_only`: Whether operation is restricted to business hours
- `max_request_size`: Maximum request size in bytes
- `allowed_methods`: Allowed HTTP methods
- `allowed_environments`: Environments where operation is allowed

### Getting Security Profiles

```python
from verenigingen.utils.security.api_security_framework import get_security_framework

framework = get_security_framework()

# Get predefined security profile
critical_profile = framework.get_security_profile(SecurityLevel.CRITICAL)
high_profile = framework.get_security_profile(SecurityLevel.HIGH)

# Profile attributes
print(f"Required roles: {critical_profile.required_roles}")
print(f"Rate limit: {critical_profile.rate_limit_config}")
print(f"Requires CSRF: {critical_profile.requires_csrf}")
```

## Operation Types

### OperationType Enum

```python
from verenigingen.utils.security.api_security_framework import OperationType

class OperationType(Enum):
    FINANCIAL = "financial"      # Payment processing, invoicing, SEPA operations
    MEMBER_DATA = "member_data"  # Member information access/modification
    ADMIN = "admin"              # System administration, settings
    REPORTING = "reporting"      # Data export, analytics, dashboards
    UTILITY = "utility"          # Health checks, status endpoints
    PUBLIC = "public"            # Public information, documentation
```

### Operation Type to Security Level Mapping

```python
OPERATION_SECURITY_MAPPING = {
    OperationType.FINANCIAL: SecurityLevel.CRITICAL,
    OperationType.MEMBER_DATA: SecurityLevel.HIGH,
    OperationType.ADMIN: SecurityLevel.CRITICAL,
    OperationType.REPORTING: SecurityLevel.MEDIUM,
    OperationType.UTILITY: SecurityLevel.LOW,
    OperationType.PUBLIC: SecurityLevel.PUBLIC,
}
```

## Critical Operation Rules API

### CriticalOperationRule DocType

#### Getting Rule Configuration

```python
from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import CriticalOperationRule

# Get specific rule configuration
config = CriticalOperationRule.get_rule_config("operation_name")

if config:
    print(f"Security level: {config['security_level']}")
    print(f"Required roles: {config['required_roles']}")
    print(f"Rate limit: {config['rate_limit']}")
    print(f"Business rules: {config['business_rules']}")
```

#### Getting All Rules

```python
# Get all enabled rules
all_rules = CriticalOperationRule.get_all_rules()

for operation_name, config in all_rules.items():
    print(f"{operation_name}: {config['security_level']}")
```

### CriticalOperationsRegistry

```python
from verenigingen.utils.secure_operations import get_critical_operations_registry

registry = get_critical_operations_registry()

# Get operation configuration
config = registry.get_operation_config("operation_name")

# Validate business rules
violations = registry.validate_business_rules("operation_name",
    amount=1500, member_id="TEST-001")

# Execute critical operation
result = registry.execute_critical_operation("operation_name",
    operation_data={"amount": 1000},
    justification="Monthly payment processing")
```

**Methods:**

#### get_operation_config(operation_name: str) -> dict

Returns configuration for a specific critical operation.

**Parameters:**
- `operation_name` (str): Name of the operation

**Returns:**
- `dict`: Operation configuration or None if not found

**Example:**
```python
config = registry.get_operation_config("create_financial_document")
# Returns:
# {
#     "operation_name": "create_financial_document",
#     "security_level": "critical",
#     "required_roles": ["System Manager", "Accounts Manager"],
#     "rate_limit": {"calls": 10, "period_seconds": 3600},
#     "business_rules": {"enabled": True, "amount_threshold": 1000.0}
# }
```

#### validate_business_rules(operation_name: str, **kwargs) -> List[str]

Validates business rules for an operation.

**Parameters:**
- `operation_name` (str): Name of the operation
- `**kwargs`: Operation parameters for validation

**Returns:**
- `List[str]`: List of business rule violations (empty if no violations)

**Example:**
```python
violations = registry.validate_business_rules("create_financial_document",
    amount=15000, doctype="Sales Invoice")
# Returns: ["Amount €15000 exceeds threshold €1000"]
```

#### execute_critical_operation(operation_name: str, **kwargs) -> dict

Executes a critical operation with full security validation.

**Parameters:**
- `operation_name` (str): Name of the operation
- `**kwargs`: Operation parameters

**Returns:**
- `dict`: Operation result with success status

**Example:**
```python
result = registry.execute_critical_operation("create_financial_document",
    doctype="Sales Invoice",
    data={"customer": "CUST-001", "grand_total": 500},
    justification="Monthly billing")
# Returns: {"success": True, "document": "SINV-001"}
```

## Security Monitoring API

### SecurityMonitor Class

```python
from verenigingen.utils.security.security_monitoring import get_security_monitor

monitor = get_security_monitor()
```

#### Business Rule Monitoring

```python
# Detect all business rule anomalies
alerts = monitor.detect_business_rule_anomalies()

# Specific anomaly checks
high_value_alerts = monitor.check_high_value_payments(threshold=5000)
member_alerts = monitor.check_unusual_member_operations()
financial_alerts = monitor.check_financial_pattern_anomalies()
policy_alerts = monitor.monitor_policy_changes()
sepa_alerts = monitor.check_sepa_operation_anomalies()
```

#### Security Event Recording

```python
from verenigingen.utils.security.security_monitoring import MonitoringMetric

# Record security events
monitor.record_security_event(
    event_type=MonitoringMetric.AUTHENTICATION_FAILURES,
    user="user@example.com",
    endpoint="/api/method/financial_operation",
    details={"reason": "invalid_password"},
    ip_address="192.168.1.100"
)

# Record API calls
monitor.record_api_call(
    endpoint="/api/method/process_payment",
    user="user@example.com",
    response_time=0.15,
    status="success",
    ip_address="192.168.1.100"
)
```

#### Security Dashboard

```python
# Get real-time security dashboard
dashboard = monitor.get_security_dashboard()

print(f"Current metrics: {dashboard['current_metrics']}")
print(f"Active incidents: {len(dashboard['active_incidents'])}")
print(f"Threat summary: {dashboard['threat_summary']}")
```

### Monitoring Functions

#### run_business_rule_monitoring()

Background job function for business rule monitoring.

```python
from verenigingen.utils.security.security_monitoring import run_business_rule_monitoring

# Run business rule monitoring (typically scheduled)
run_business_rule_monitoring()
```

#### analyze_security_trends(days: int = 7) -> Dict[str, Any]

Analyze security trends over time.

```python
from verenigingen.utils.security.security_monitoring import analyze_security_trends

# Analyze last 7 days
trends = analyze_security_trends(days=7)

print(f"Analysis period: {trends['analysis_period']}")
print(f"Average daily API calls: {trends['summary']['avg_daily_api_calls']}")
print(f"Active security rules: {trends['summary']['active_security_rules']}")
```

### API Endpoints for Security Monitoring

#### get_security_dashboard()

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_security_dashboard():
    """Get real-time security dashboard"""
    # Implementation provided by framework
    pass
```

#### resolve_security_incident(incident_id: str, resolution_notes: str)

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def resolve_security_incident(incident_id: str, resolution_notes: str):
    """Resolve security incident"""
    # Implementation provided by framework
    pass
```

#### run_security_tests()

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def run_security_tests():
    """Run automated security tests"""
    # Implementation provided by framework
    pass
```

## Utility Functions

### Environment Detection

```python
from verenigingen.utils.security.api_security_framework import get_security_framework

framework = get_security_framework()

# Get current environment
current_env = framework.get_current_environment()
print(f"Environment: {current_env.value}")  # development, staging, production

# Validate environment access
try:
    framework.validate_environment_access(security_profile, current_env)
    print("Environment access allowed")
except VPermissionError as e:
    print(f"Environment access denied: {e}")
```

### Security Analysis

#### analyze_api_security_status()

Analyze current API security status across all endpoints.

```python
@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def analyze_api_security_status():
    """Analyze current API security status"""
    # Returns security analysis
    pass

# Usage
analysis = analyze_api_security_status()
print(f"Security coverage: {analysis['summary']['security_coverage']}%")
print(f"Unsecured endpoints: {analysis['analysis']['unsecured_endpoints']}")
```

#### get_security_framework_status()

Get current security framework configuration and status.

```python
@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def get_security_framework_status():
    """Get current security framework status"""
    # Returns framework configuration and component status
    pass

# Usage
status = get_security_framework_status()
print(f"Framework version: {status['framework_version']}")
print(f"Current environment: {status['current_environment']}")
```

### Cache Management

```python
# Clear Critical Operation Rules cache
frappe.cache().delete_value("critical_operation_rules")

# Clear specific rule cache
frappe.cache().delete_value("critical_operation_rule:operation_name")

# Get cached rule
from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import CriticalOperationRule

config = CriticalOperationRule.get_rule_config("operation_name")  # Uses cache
```

## Configuration Classes

### EnvironmentLevel Enum

```python
from verenigingen.utils.security.api_security_framework import EnvironmentLevel

class EnvironmentLevel(Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
```

### ThreatLevel Enum (Monitoring)

```python
from verenigingen.utils.security.security_monitoring import ThreatLevel

class ThreatLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

### MonitoringMetric Enum

```python
from verenigingen.utils.security.security_monitoring import MonitoringMetric

class MonitoringMetric(Enum):
    API_CALLS = "api_calls"
    AUTHENTICATION_FAILURES = "auth_failures"
    AUTHORIZATION_FAILURES = "authz_failures"
    RATE_LIMIT_VIOLATIONS = "rate_limit_violations"
    CSRF_FAILURES = "csrf_failures"
    VALIDATION_ERRORS = "validation_errors"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    PERFORMANCE_ANOMALIES = "performance_anomalies"
```

## Error Handling

### Security Exception Types

```python
from verenigingen.utils.error_handling import (
    PermissionError as VPermissionError,
    ValidationError as VValidationError
)

# Permission errors
try:
    # Security-protected operation
    pass
except VPermissionError as e:
    # Handle permission denied
    return {"success": False, "error": "Access denied", "details": str(e)}

# Validation errors
try:
    # Input validation
    pass
except VValidationError as e:
    # Handle validation failure
    return {"success": False, "error": "Validation failed", "details": str(e)}
```

### Standard Error Response Format

```python
# Success response
{
    "success": True,
    "data": {...},
    "message": "Operation completed successfully"
}

# Error response
{
    "success": False,
    "error": "Error description",
    "details": "Detailed error information",
    "error_code": "VALIDATION_ERROR"  # Optional
}

# Security error response
{
    "success": False,
    "error": "Access denied",
    "details": "Insufficient permissions for this operation",
    "required_roles": ["System Manager", "Accounts Manager"]
}
```

### Error Logging

```python
# Log security errors
from verenigingen.utils.error_handling import log_error

try:
    # Security operation
    pass
except Exception as e:
    log_error(e, module="verenigingen.api.security")
    return {"success": False, "error": "Internal error occurred"}
```

## Framework Initialization

### Setup Functions

```python
# Initialize API security framework
from verenigingen.utils.security.api_security_framework import setup_api_security_framework

setup_api_security_framework()

# Initialize security monitoring
from verenigingen.utils.security.security_monitoring import setup_security_monitoring

setup_security_monitoring()

# Validate deployment environment
from verenigingen.utils.security.api_security_framework import validate_deployment_environment

env_validation = validate_deployment_environment()
print(f"Environment validation: {env_validation}")
```

### Global Instance Access

```python
# Get global security framework instance
from verenigingen.utils.security.api_security_framework import get_security_framework

framework = get_security_framework()

# Get global security monitor instance
from verenigingen.utils.security.security_monitoring import get_security_monitor

monitor = get_security_monitor()

# Get global security tester instance
from verenigingen.utils.security.security_monitoring import get_security_tester

tester = get_security_tester()
```

## Usage Examples

### Complete API Function Example

```python
from verenigingen.utils.security.api_security_framework import critical_api, OperationType
import frappe

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_member_payment(member_id, amount, payment_method, description=None):
    """
    Process member payment with critical security

    Args:
        member_id (str): Member identifier
        amount (float): Payment amount
        payment_method (str): Payment method (bank_transfer, credit_card, etc.)
        description (str, optional): Payment description

    Returns:
        dict: Payment processing result

    Raises:
        VPermissionError: If user lacks required permissions
        VValidationError: If input validation fails
    """
    try:
        # Input validation (automatically handled by security framework)
        if not member_id or not amount or not payment_method:
            return {"success": False, "error": "Missing required parameters"}

        if float(amount) <= 0:
            return {"success": False, "error": "Amount must be positive"}

        # Business logic
        payment_entry = frappe.get_doc({
            "doctype": "Payment Entry",
            "party_type": "Customer",
            "party": member_id,
            "paid_amount": amount,
            "payment_type": "Receive",
            "mode_of_payment": payment_method,
            "reference_no": description or f"Payment from {member_id}"
        })

        payment_entry.insert()
        payment_entry.submit()

        return {
            "success": True,
            "payment_entry": payment_entry.name,
            "amount": amount,
            "status": "completed"
        }

    except frappe.ValidationError as e:
        return {"success": False, "error": "Validation failed", "details": str(e)}
    except Exception as e:
        frappe.log_error(f"Payment processing failed: {str(e)}")
        return {"success": False, "error": "Payment processing failed"}
```

### Security Testing Example

```python
def test_api_security():
    """Test API security implementation"""

    # Test security decorator application
    from verenigingen.api.financial import process_member_payment

    assert hasattr(process_member_payment, '_security_protected'), "Security decorator not applied"
    assert process_member_payment._security_level == SecurityLevel.CRITICAL, "Wrong security level"

    # Test Critical Operation Rule exists
    from verenigingen.utils.secure_operations import get_critical_operations_registry

    registry = get_critical_operations_registry()
    config = registry.get_operation_config("process_member_payment")

    assert config is not None, "Critical Operation Rule not found"
    assert config['security_level'] == 'critical', "Rule security level mismatch"

    # Test business rule validation
    violations = registry.validate_business_rules("process_member_payment",
        amount=15000, member_id="TEST-001")

    if violations:
        print(f"Business rule violations detected: {violations}")

    print("Security test completed successfully")

# Run security test
test_api_security()
```

This API reference provides documentation for all security framework components, enabling developers to effectively implement and maintain secure operations in the Verenigingen system.
