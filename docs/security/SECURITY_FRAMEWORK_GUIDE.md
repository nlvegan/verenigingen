# Verenigingen Security Framework Guide

**Version**: 2.0
**Last Updated**: September 15, 2025
**Status**: Production Ready

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Critical Operation Rules](#critical-operation-rules)
4. [API Security Framework](#api-security-framework)
5. [Security Monitoring](#security-monitoring)
6. [Implementation Guide](#implementation-guide)
7. [Configuration Management](#configuration-management)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

## Overview

The Verenigingen Security Framework implements a layered security approach for association management operations. Rather than attempting to secure every operation, it focuses on the 50-70 critical operations that represent 80% of security risk.

### Key Components

- **Critical Operation Rules**: Runtime-configurable security policies stored in database
- **API Security Framework**: Decorator-based security layers for API endpoints
- **Security Monitoring**: Business logic monitoring and anomaly detection
- **Audit Logging**: Tracking of security events

### Design Philosophy

The framework follows a **Selective Hardening** approach:
- **80/20 Principle**: Secure the 20% of operations that represent 80% of risk
- **Runtime Configuration**: Security policies managed via DocType without code deployment
- **Business Logic Awareness**: Security rules understand business context and thresholds
- **Performance Optimization**: Minimal overhead for non-critical operations

## Architecture

### Component Overview

```
┌─────────────────────┐    ┌─────────────────────────┐    ┌────────────────────┐
│ API Security        │    │ Critical Operations     │    │ Business Logic     │
│ Framework          │────│ Registry               │────│ Monitoring         │
│ (@critical_api)     │    │ (DocType Config)       │    │ (Anomaly Detection)│
└─────────────────────┘    └─────────────────────────┘    └────────────────────┘
           │                              │                              │
           └──────────────────────────────┼──────────────────────────────┘
                                          │
                             ┌─────────────────────────┐
                             │ Existing Infrastructure │
                             │ • secure_operations.py  │
                             │ • audit_logging.py      │
                             │ • rate_limiting.py      │
                             └─────────────────────────┘
```

### Security Levels

The framework defines five security levels with corresponding requirements:

#### CRITICAL
- **Use Cases**: Financial transactions, payment processing, system administration
- **Requirements**:
  - System Manager or Verenigingen Administrator roles
  - CSRF protection required
  - Rate limit: 10 calls/hour
  - Full audit logging
  - IP restrictions enabled
  - Business hours validation

#### HIGH
- **Use Cases**: Member data access, batch operations, administrative functions
- **Requirements**:
  - Verenigingen Manager role or higher
  - CSRF protection required
  - Rate limit: 50 calls/hour
  - Standard audit logging
  - Input validation required

#### MEDIUM
- **Use Cases**: Reporting, read-only operations, analytics
- **Requirements**:
  - Verenigingen Staff role or higher
  - Rate limit: 200 calls/hour
  - Selective audit logging
  - Input validation required

#### LOW
- **Use Cases**: Utility functions, health checks, status endpoints
- **Requirements**:
  - Any authenticated user
  - Rate limit: 500 calls/hour
  - Minimal audit logging

#### PUBLIC
- **Use Cases**: Public information, documentation, no authentication required
- **Requirements**:
  - No authentication required
  - Rate limit: 1000 calls/hour
  - Basic input validation

## Critical Operation Rules

### DocType Structure

Critical Operation Rules are stored in the database and provide runtime configuration for security policies. Each rule defines:

```python
{
    "operation_name": "create_financial_document",
    "operation_type": "financial",
    "security_level": "critical",
    "enabled": True,
    "required_roles": ["System Manager", "Accounts Manager"],
    "rate_limit_calls": 10,
    "rate_limit_period_seconds": 3600,
    "enable_business_validation": True,
    "amount_threshold": 1000.0,
    "audit_level": "detailed",
    "requires_justification": True,
    "alert_on_execution": True
}
```

### Field Reference

#### Operation Details
- **operation_name**: Unique identifier for the operation
- **operation_type**: Type classification (financial, member_data, admin, reporting, utility, public)
- **description**: Human-readable description of the operation
- **enabled**: Whether the rule is active
- **security_level**: Security classification (critical, high, medium, low, public)
- **doctype_targets**: Comma-separated list of target DocTypes
- **business_context**: Business justification for the operation

#### Permission Settings
- **required_roles**: Comma-separated list of required roles
- **required_permissions**: Comma-separated list of required permissions (format: "DocType:permission")
- **allow_system_user**: Whether to allow system user fallback
- **bypass_validations**: Allowed validation bypasses

#### Rate Limiting
- **rate_limit_calls**: Maximum calls allowed
- **rate_limit_period_seconds**: Time window for rate limiting
- **rate_limit_scope**: Scope (per_user, per_ip, global)
- **rate_limit_key_pattern**: Custom key pattern for rate limiting

#### Business Rules
- **enable_business_validation**: Enable business logic validation
- **amount_threshold**: Alert threshold for financial amounts
- **time_restrictions**: Business hours and time-based restrictions
- **ip_restrictions**: Allowed IP ranges

#### Audit Settings
- **audit_level**: Logging detail level (minimal, standard, detailed, critical)
- **requires_justification**: Whether operation requires justification
- **alert_on_execution**: Send alerts when operation executes
- **notification_recipients**: Email addresses for alerts

#### Monitoring
- **monitor_execution_time**: Track execution performance
- **execution_time_threshold_ms**: Performance threshold in milliseconds
- **monitor_failure_rate**: Track failure rates
- **failure_rate_threshold_percent**: Failure rate threshold

### Creating Critical Operation Rules

#### Via UI
1. Navigate to **Vereiningen Settings** → **Critical Operation Rule**
2. Click **New**
3. Fill in the operation details:
   - **Operation Name**: Use snake_case naming (e.g., `create_financial_document`)
   - **Operation Type**: Select appropriate type
   - **Security Level**: Choose based on risk assessment
4. Configure permissions, rate limiting, and business rules
5. Save and enable the rule

#### Via Fixtures
```json
{
  "doctype": "Critical Operation Rule",
  "name": "create_financial_document",
  "operation_name": "create_financial_document",
  "operation_type": "financial",
  "security_level": "critical",
  "enabled": 1,
  "required_roles": "System Manager,Accounts Manager",
  "rate_limit_calls": 10,
  "rate_limit_period_seconds": 3600,
  "enable_business_validation": 1,
  "amount_threshold": 1000.0,
  "audit_level": "detailed"
}
```

### Managing Rules

#### Viewing All Rules
```bash
# List all critical operation rules
bench --site dev.veganisme.net execute "
rules = frappe.get_all('Critical Operation Rule',
    fields=['operation_name', 'security_level', 'enabled', 'operation_type'])
for rule in rules:
    print(f'{rule.operation_name}: {rule.security_level} ({rule.operation_type})')
"
```

#### Testing Rule Configuration
```python
from verenigingen.utils.secure_operations import get_critical_operations_registry

registry = get_critical_operations_registry()
config = registry.get_operation_config("create_financial_document")
print(frappe.as_json(config, indent=2))
```

#### Clearing Rule Cache
```python
# Clear all rule caches
frappe.cache().delete_value("critical_operation_rules")

# Clear specific rule cache
frappe.cache().delete_value("critical_operation_rule:create_financial_document")
```

## API Security Framework

### Security Decorators

The API Security Framework provides convenient decorators for different security levels:

#### @critical_api
For critical operations like financial transactions and system administration:

```python
from verenigingen.utils.security.api_security_framework import critical_api, OperationType

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_member_payment(member_id, amount, payment_method):
    """Process member payment with critical security"""
    # Implementation here
    return {"status": "success", "payment_id": payment_id}
```

#### @high_security_api
For member data access and batch operations:

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def update_member_batch(member_updates):
    """Update multiple members with high security"""
    # Implementation here
    return {"updated_count": len(member_updates)}
```

#### @standard_api
For reporting and read operations:

```python
@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def generate_membership_report(filters=None):
    """Generate membership report with standard security"""
    # Implementation here
    return {"report_data": data}
```

#### @utility_api
For utility functions and health checks:

```python
@frappe.whitelist()
@utility_api()
def check_system_health():
    """Check system health with low security requirements"""
    return {"status": "healthy", "timestamp": frappe.utils.now()}
```

#### @public_api
For public information (no authentication required):

```python
@frappe.whitelist(allow_guest=True)
@public_api()
def get_public_chapter_info():
    """Get public chapter information"""
    return {"chapters": public_chapters}
```

### Environment-Aware Decorators

#### @development_only_api
Restrict access to development environment only:

```python
@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_member_data(member_id):
    """Debug function only available in development"""
    # This will only work in development environment
    return debug_data
```

#### @staging_and_dev_api
Allow access in staging and development:

```python
@frappe.whitelist()
@staging_and_dev_api(operation_type=OperationType.ADMIN)
def reset_test_data():
    """Reset test data - not available in production"""
    # Implementation here
    return {"status": "reset_complete"}
```

### Custom Security Configuration

#### Advanced Decorator Configuration
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
    rate_limit={"requests": 20, "window_seconds": 1800},
    audit_level="detailed",
    allowed_environments=[EnvironmentLevel.PRODUCTION, EnvironmentLevel.STAGING]
)
def custom_financial_operation(amount, account):
    """Custom financial operation with specific security requirements"""
    # Implementation here
    return result
```

### Integration with Critical Operations

The API Security Framework automatically integrates with Critical Operation Rules:

```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_sales_invoice(invoice_data):
    """
    This function will automatically:
    1. Check if 'create_sales_invoice' rule exists in Critical Operation Rules
    2. Apply business rule validation if configured
    3. Enforce rate limits and permissions from the rule
    4. Add critical operation context to audit logs
    """
    # Implementation here
    return {"invoice_name": invoice_name}
```

When a Critical Operation Rule exists for the function name, the framework will:
- Apply additional security requirements from the rule
- Validate business rules (amount thresholds, patterns)
- Add critical operation metadata to audit logs
- Enforce rule-specific rate limits and permissions

## Security Monitoring

### Business Logic Monitoring

The security framework includes business logic monitoring that goes beyond technical security to detect suspicious patterns:

#### High-Value Payment Detection
```python
def check_high_value_payments(threshold: float = 5000) -> List[Dict]:
    """Alert on payments exceeding threshold"""
    # Implementation detects payments over threshold in last 24 hours
    # Sends immediate alerts to administrators
```

#### Financial Pattern Anomalies
- **Round Amount Detection**: Alerts on invoices with round amounts (potential fraud indicator)
- **Excessive Discount Patterns**: Detects invoices with >30% discounts
- **Rapid Financial Operations**: Monitors for unusual financial activity patterns

#### Member Operation Anomalies
- **Bulk Member Updates**: Alerts when users update >10 members in one hour
- **Unusual Access Patterns**: Detects abnormal member data access

#### SEPA Operation Monitoring
- **Rapid Mandate Creation**: Alerts on >5 SEPA mandates created per hour by one user
- **Mandate Pattern Analysis**: Monitors SEPA mandate creation patterns

#### Policy Change Monitoring
Immediate alerts when Critical Operation Rules are modified:
```python
def monitor_policy_changes() -> List[Dict]:
    """Send immediate alert on any Critical Operation Rule changes"""
    # Sends email to all System Managers when rules are modified
```

### Running Monitoring

#### Background Job Setup
```bash
# Add to hooks.py or scheduler configuration
scheduler_events = {
    "cron": {
        "*/15 * * * *": [  # Every 15 minutes
            "verenigingen.utils.security.security_monitoring.run_business_rule_monitoring"
        ]
    }
}
```

#### Manual Monitoring Execution
```python
from verenigingen.utils.security.security_monitoring import run_business_rule_monitoring

# Run all business rule monitoring
run_business_rule_monitoring()

# Run specific monitoring
from verenigingen.utils.security.security_monitoring import get_security_monitor

monitor = get_security_monitor()
alerts = monitor.detect_business_rule_anomalies()
for alert in alerts:
    print(f"Alert: {alert['type']} - {alert['message']}")
```

### Security Dashboard

Access real-time security metrics:

```python
@frappe.whitelist()
def get_security_status():
    """Get current security status"""
    from verenigingen.utils.security.security_monitoring import get_security_monitor

    monitor = get_security_monitor()
    dashboard = monitor.get_security_dashboard()

    return {
        "current_metrics": dashboard["current_metrics"],
        "active_incidents": dashboard["active_incidents"],
        "threat_summary": dashboard["threat_summary"]
    }
```

## Implementation Guide

### Step 1: Create Critical Operation Rules

For each critical operation in your system:

1. **Identify the Operation**
   - Function name (e.g., `create_financial_document`)
   - Operation type (financial, member_data, admin, etc.)
   - Risk level assessment

2. **Create the Rule**
   ```python
   rule = frappe.get_doc({
       "doctype": "Critical Operation Rule",
       "operation_name": "create_financial_document",
       "operation_type": "financial",
       "security_level": "critical",
       "enabled": 1,
       "required_roles": "System Manager,Accounts Manager",
       "rate_limit_calls": 10,
       "rate_limit_period_seconds": 3600,
       "enable_business_validation": 1,
       "amount_threshold": 1000.0
   })
   rule.insert()
   ```

3. **Test the Rule**
   ```python
   from verenigingen.utils.secure_operations import get_critical_operations_registry

   registry = get_critical_operations_registry()
   config = registry.get_operation_config("create_financial_document")
   assert config is not None
   assert config["security_level"] == "critical"
   ```

### Step 2: Apply Security Decorators

Add appropriate security decorators to your API functions:

```python
# Before (unsecured)
@frappe.whitelist()
def create_financial_document(doctype, data):
    return frappe.get_doc(doctype, data).insert()

# After (secured)
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_financial_document(doctype, data):
    return frappe.get_doc(doctype, data).insert()
```

### Step 3: Configure Monitoring

Set up background monitoring jobs:

```python
# In hooks.py
scheduler_events = {
    "cron": {
        "*/15 * * * *": [
            "verenigingen.utils.security.security_monitoring.run_business_rule_monitoring"
        ],
        "0 */6 * * *": [  # Every 6 hours
            "verenigingen.utils.security.security_monitoring.analyze_security_trends"
        ]
    }
}
```

### Step 4: Validate Implementation

Run security analysis to verify coverage:

```python
@frappe.whitelist()
def analyze_security_coverage():
    """Analyze current security implementation"""
    from verenigingen.utils.security.api_security_framework import analyze_api_security_status

    analysis = analyze_api_security_status()

    print(f"Security Coverage: {analysis['summary']['security_coverage']}%")
    print(f"High Priority Endpoints: {analysis['summary']['high_priority_endpoints']}")

    for recommendation in analysis['analysis']['recommendations']:
        print(f"Recommendation: {recommendation['function']} -> {recommendation['suggested_level']}")
```

## Configuration Management

### Environment Detection

The framework automatically detects the deployment environment:

```python
from verenigingen.utils.security.api_security_framework import get_security_framework

framework = get_security_framework()
current_env = framework.get_current_environment()
print(f"Current environment: {current_env.value}")
```

Environment detection uses:
1. `frappe.conf.developer_mode` (Development)
2. `frappe.conf.deployment_environment` (Custom)
3. `frappe.conf.environment` (Site-specific)
4. Default: Production (secure by default)

### Security Level Overrides

Override security levels for specific environments:

```python
# Different security for development
@frappe.whitelist()
@api_security_framework(
    security_level=SecurityLevel.LOW,  # Relaxed for development
    allowed_environments=[EnvironmentLevel.DEVELOPMENT]
)
def debug_function():
    """Debug function only available in development"""
    pass
```

### Rule Management Commands

#### Import Rules from Fixtures
```bash
bench --site dev.veganisme.net import-doc \
    /home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/critical_operation_rule.json
```

#### Export Rules to Fixtures
```bash
bench --site dev.veganisme.net export-doc "Critical Operation Rule" \
    --path /home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/
```

#### Bulk Rule Operations
```python
# Enable all financial operation rules
frappe.db.sql("""
    UPDATE `tabCritical Operation Rule`
    SET enabled = 1
    WHERE operation_type = 'financial'
""")

# Update rate limits for all critical operations
frappe.db.sql("""
    UPDATE `tabCritical Operation Rule`
    SET rate_limit_calls = 5
    WHERE security_level = 'critical'
""")
```

## Best Practices

### Security Rule Design

#### 1. Follow Naming Conventions
- Use snake_case for operation names
- Include operation context: `create_financial_document`, `process_member_payment`
- Be specific: `submit_expense_claim` vs `submit_expense`

#### 2. Set Appropriate Security Levels
```python
# Financial operations should be critical or high
operation_type="financial" -> security_level="critical"

# Member data operations should be high or medium
operation_type="member_data" -> security_level="high"

# Reporting operations should be medium or low
operation_type="reporting" -> security_level="medium"
```

#### 3. Configure Business Rules
For financial operations, always configure:
- Amount thresholds for large transactions
- Business hours restrictions if applicable
- IP restrictions for sensitive operations

#### 4. Set Reasonable Rate Limits
```python
# Critical operations: 5-10 calls per hour
rate_limit_calls=10, rate_limit_period_seconds=3600

# High security: 20-50 calls per hour
rate_limit_calls=50, rate_limit_period_seconds=3600

# Standard operations: 100-200 calls per hour
rate_limit_calls=200, rate_limit_period_seconds=3600
```

### API Development

#### 1. Always Use Security Decorators
```python
# Good
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(amount, member_id):
    pass

# Bad - no security decorator
@frappe.whitelist()
def process_payment(amount, member_id):
    pass
```

#### 2. Choose Correct Operation Types
```python
# Financial operations
@critical_api(operation_type=OperationType.FINANCIAL)

# Member data access/modification
@high_security_api(operation_type=OperationType.MEMBER_DATA)

# Reporting and analytics
@standard_api(operation_type=OperationType.REPORTING)

# Utility functions
@utility_api(operation_type=OperationType.UTILITY)
```

#### 3. Handle Security Errors Gracefully
```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def financial_operation(data):
    try:
        # Implementation
        return {"success": True, "result": result}
    except frappe.PermissionError as e:
        return {"success": False, "error": "Access denied", "details": str(e)}
    except ValidationError as e:
        return {"success": False, "error": "Validation failed", "details": str(e)}
```

### Monitoring and Alerting

#### 1. Configure Appropriate Alert Recipients
```python
# System administrators for critical operations
notification_recipients = "admin@company.com,security@company.com"

# Department managers for specific operations
notification_recipients = "finance@company.com"  # For financial operations
```

#### 2. Set Meaningful Thresholds
```python
# Amount thresholds based on business context
amount_threshold = 1000.0  # For regular transactions
amount_threshold = 5000.0  # For large transactions
amount_threshold = 10000.0  # For exceptional transactions
```

#### 3. Monitor Execution Time
```python
# Set realistic execution time thresholds
execution_time_threshold_ms = 1000   # For simple operations
execution_time_threshold_ms = 5000   # For complex operations
execution_time_threshold_ms = 10000  # For batch operations
```

### Performance Optimization

#### 1. Use Caching Effectively
The framework automatically caches Critical Operation Rules for 5 minutes. For custom implementations:

```python
# Cache expensive security checks
@frappe.cache_method("check_user_permissions", timeout=300)
def check_user_permissions(user, operation):
    # Expensive permission check
    return has_permission
```

#### 2. Minimize Security Overhead
- Only apply security decorators to API endpoints (@frappe.whitelist functions)
- Use appropriate security levels (don't over-secure utility functions)
- Configure reasonable rate limits

#### 3. Optimize Business Rule Validation
```python
# Good - early return for non-financial operations
if operation_type != "financial":
    return True

# Good - cache business rule results
@frappe.cache_method("validate_amount_threshold")
def validate_amount_threshold(amount, threshold):
    return amount <= threshold
```

## Troubleshooting

### Common Issues

#### 1. Security Decorator Not Working
**Symptoms**: API calls succeed even when they should be blocked

**Diagnosis**:
```python
# Check if decorator is properly applied
func = frappe.get_attr("verenigingen.api.financial.process_payment")
print(f"Security protected: {hasattr(func, '_security_protected')}")
print(f"Security level: {getattr(func, '_security_level', 'None')}")
```

**Solutions**:
- Ensure `@frappe.whitelist()` comes before security decorator
- Verify function is properly imported
- Check that security framework is initialized

#### 2. Critical Operation Rule Not Found
**Symptoms**: Rule configured but not being applied

**Diagnosis**:
```python
from verenigingen.utils.secure_operations import get_critical_operations_registry

registry = get_critical_operations_registry()
config = registry.get_operation_config("operation_name")
print(f"Rule config: {config}")

# Check cache
cache_key = "critical_operation_rule:operation_name"
cached_config = frappe.cache().get_value(cache_key)
print(f"Cached config: {cached_config}")
```

**Solutions**:
- Verify rule is enabled
- Clear rule cache: `frappe.cache().delete_value("critical_operation_rules")`
- Check operation name matches exactly

#### 3. Rate Limiting Issues
**Symptoms**: Users getting rate limited unexpectedly

**Diagnosis**:
```python
from verenigingen.utils.security.rate_limiting import get_rate_limiter

limiter = get_rate_limiter()
# Check current rate limit status for user
status = limiter.get_rate_limit_status("operation_key", "user")
print(f"Rate limit status: {status}")
```

**Solutions**:
- Adjust rate limit settings in Critical Operation Rule
- Check rate limit scope (per_user vs per_ip vs global)
- Consider user workflow and adjust limits accordingly

#### 4. Business Rule Validation Failing
**Symptoms**: Valid operations being rejected by business rules

**Diagnosis**:
```python
from verenigingen.utils.secure_operations import get_critical_operations_registry

registry = get_critical_operations_registry()
violations = registry.validate_business_rules("operation_name", **kwargs)
print(f"Business rule violations: {violations}")
```

**Solutions**:
- Check amount thresholds are appropriate
- Verify business rule configuration
- Ensure operation data matches expected format

#### 5. Environment Detection Issues
**Symptoms**: Functions not available in expected environment

**Diagnosis**:
```python
from verenigingen.utils.security.api_security_framework import get_security_framework

framework = get_security_framework()
env_info = framework.validate_deployment_environment()
print(f"Environment validation: {env_info}")
```

**Solutions**:
- Set explicit environment in site config
- Check `developer_mode` setting
- Verify `deployment_environment` configuration

### Debugging Tools

#### 1. Security Analysis
```python
# Analyze API security status
@frappe.whitelist()
def debug_security_status():
    from verenigingen.utils.security.api_security_framework import analyze_api_security_status
    return analyze_api_security_status()
```

#### 2. Rule Configuration Dump
```python
# Get all rule configurations
@frappe.whitelist()
def debug_rules():
    from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import CriticalOperationRule
    return CriticalOperationRule.get_all_rules()
```

#### 3. Security Event Monitoring
```python
# Check recent security events
@frappe.whitelist()
def debug_security_events():
    events = frappe.get_all("Activity Log",
        filters={"reference_doctype": ["in", ["Critical Operation Rule", "Security Alert"]]},
        fields=["subject", "creation", "user"],
        order_by="creation desc",
        limit=20
    )
    return events
```

#### 4. Cache Inspection
```python
# Inspect cache contents
@frappe.whitelist()
def debug_cache():
    cache_info = {}

    # Rule cache
    rules_cache = frappe.cache().get_value("critical_operation_rules")
    cache_info["rules_cache"] = rules_cache is not None

    # Specific rule caches
    rule_names = ["create_financial_document", "process_payment", "submit_expense"]
    for rule_name in rule_names:
        cache_key = f"critical_operation_rule:{rule_name}"
        cached = frappe.cache().get_value(cache_key)
        cache_info[f"rule_{rule_name}"] = cached is not None

    return cache_info
```

### Performance Monitoring

#### 1. Security Overhead Measurement
```python
import time

@frappe.whitelist()
def measure_security_overhead():
    """Measure security framework overhead"""

    # Test without security
    start = time.time()
    for i in range(100):
        # Simulate basic operation
        pass
    baseline = time.time() - start

    # Test with security
    from verenigingen.utils.security.api_security_framework import get_security_framework
    framework = get_security_framework()

    start = time.time()
    for i in range(100):
        # Simulate security validation
        framework.validate_authentication(framework.get_security_profile("medium"))
    secured = time.time() - start

    overhead = ((secured - baseline) / baseline) * 100
    return {
        "baseline_ms": baseline * 1000,
        "secured_ms": secured * 1000,
        "overhead_percent": overhead
    }
```

#### 2. Rate Limit Performance
```python
@frappe.whitelist()
def debug_rate_limit_performance():
    """Check rate limit performance"""
    from verenigingen.utils.security.rate_limiting import get_rate_limiter

    limiter = get_rate_limiter()

    start = time.time()
    for i in range(100):
        limiter.check_rate_limit("test_operation")
    duration = time.time() - start

    return {
        "rate_limit_checks_per_second": 100 / duration,
        "avg_check_time_ms": (duration / 100) * 1000
    }
```

This guide provides everything needed to understand, implement, and maintain the Verenigingen Security Framework. For additional support, refer to the related documentation files or contact the development team.
