# API Security Framework - Comprehensive Implementation Guide

## Overview

The Verenigingen API Security Framework provides a comprehensive, production-ready security solution that standardizes security controls across all API endpoints. This framework addresses the challenge of securing 406 API endpoints with consistent, enforceable security patterns.

## Framework Architecture

### Core Components

1. **Security Decorator System** - Layered security controls via decorators
2. **Classification Engine** - Automatic security level determination
3. **Validation Framework** - Schema-based input validation and sanitization
4. **Monitoring System** - Real-time threat detection and security metrics
5. **Audit Logging** - Comprehensive security event tracking
6. **Testing Suite** - Automated security validation

### Security Levels

The framework defines five security classification levels:

| Level | Use Case | Controls Applied |
|-------|----------|------------------|
| **CRITICAL** | Financial transactions, system administration | Multi-factor auth, IP restrictions, CSRF, rate limiting, comprehensive audit |
| **HIGH** | Member data operations, batch processing | Role-based auth, CSRF, rate limiting, audit logging |
| **MEDIUM** | Reporting, analytics, read operations | Basic authentication, input validation, standard logging |
| **LOW** | Utility functions, health checks | Minimal authentication, basic validation |
| **PUBLIC** | Public information, documentation | No authentication required, rate limiting only |

### Operation Types

The framework classifies APIs by operation type for context-aware security:

- **FINANCIAL** - Payment processing, SEPA operations, invoicing
- **MEMBER_DATA** - Personal information access/modification
- **ADMIN** - System administration, configuration changes
- **REPORTING** - Data export, analytics, dashboards
- **UTILITY** - Health checks, status endpoints, debugging
- **PUBLIC** - Public information, documentation

## Implementation Guide

### Basic Implementation

#### 1. Import Required Components

```python
from verenigingen.utils.security.api_security_framework import (
    api_security_framework, SecurityLevel, OperationType
)
```

#### 2. Apply Security Framework

```python
@frappe.whitelist()
@api_security_framework(
    security_level=SecurityLevel.HIGH,
    operation_type=OperationType.MEMBER_DATA,
    audit_level="detailed"
)
def update_member_profile(member_id, **data):
    # Function implementation
    member = frappe.get_doc("Member", member_id)
    member.update(data)
    member.save()
    return {"success": True}
```

#### 3. Schema-Based Validation

```python
from verenigingen.utils.security.enhanced_validation import validate_with_schema

@frappe.whitelist()
@validate_with_schema("member_data")
@api_security_framework(
    security_level=SecurityLevel.HIGH,
    operation_type=OperationType.MEMBER_DATA
)
def create_member(**data):
    # Data is automatically validated and sanitized
    member = frappe.new_doc("Member")
    member.update(data)
    member.save()
    return {"success": True, "member_id": member.name}
```

### Advanced Implementation

#### Custom Security Profiles

```python
@api_security_framework(
    security_level=SecurityLevel.CRITICAL,
    operation_type=OperationType.FINANCIAL,
    roles=["System Manager", "Financial Controller"],
    rate_limit={"requests": 5, "window_seconds": 3600},
    audit_level="detailed"
)
def process_sepa_batch(batch_id):
    # Critical financial operation
    pass
```

#### Business Rule Validation

```python
from verenigingen.utils.security.enhanced_validation import validate_business_rules

def check_member_eligibility(data):
    """Business rule: Members must be 16+ for voting rights"""
    if data.get("voting_rights") and data.get("age", 0) < 16:
        return {
            "valid": False,
            "message": "Voting rights require minimum age of 16"
        }
    return {"valid": True}

@frappe.whitelist()
@validate_business_rules(check_member_eligibility)
@api_security_framework(
    security_level=SecurityLevel.HIGH,
    operation_type=OperationType.MEMBER_DATA
)
def update_member_rights(**data):
    # Function implementation
    pass
```

### Convenience Decorators

The framework provides convenience decorators for common patterns:

```python
from verenigingen.utils.security.api_security_framework import (
    critical_api, high_security_api, standard_api, utility_api, public_api
)

# Financial operations
@frappe.whitelist()
@critical_api(OperationType.FINANCIAL)
def process_payment(amount, iban):
    pass

# Member data operations
@frappe.whitelist()
@high_security_api(OperationType.MEMBER_DATA)
def get_member_profile(member_id):
    pass

# Reporting
@frappe.whitelist()
@standard_api(OperationType.REPORTING)
def generate_membership_report():
    pass

# Health checks
@frappe.whitelist()
@utility_api()
def health_check():
    pass

# Public information
@frappe.whitelist()
@public_api()
def get_public_chapters():
    pass
```

## Security Features

### 1. Authentication & Authorization

- **Role-based access control** with granular permissions
- **Session management** with timeout and concurrent session limits
- **Multi-factor authentication** support for critical operations
- **IP restrictions** for administrative functions

### 2. Input Validation & Sanitization

- **Schema-based validation** with predefined schemas for common operations
- **XSS prevention** through automatic HTML sanitization
- **SQL injection protection** via parameterized queries
- **File upload security** with type and size restrictions

### 3. Rate Limiting & Abuse Prevention

- **Adaptive rate limiting** based on user roles and operation types
- **Sliding window algorithms** for accurate rate calculation
- **Distributed rate limiting** with Redis support
- **Automatic blocking** of suspicious IP addresses

### 4. CSRF Protection

- **Token-based CSRF protection** for state-changing operations
- **SameSite cookie attributes** for additional protection
- **Referer validation** for critical endpoints
- **Custom token validation** for API calls

### 5. Audit Logging & Monitoring

- **Comprehensive audit trails** for all security events
- **Real-time threat detection** with automated incident response
- **Performance monitoring** with anomaly detection
- **Compliance reporting** for regulatory requirements

## Migration Strategy

### Phase 1: Critical Security (Week 1-2)

**Priority 1 - Financial & Administrative APIs**

```bash
# Analyze current security status
bench --site dev.veganisme.net execute verenigingen.utils.security.api_classifier.classify_all_api_endpoints

# Generate migration report
bench --site dev.veganisme.net execute verenigingen.utils.security.api_classifier.generate_migration_report
```

**Target APIs:**
- All SEPA batch operations (`vereinigingen/api/sepa_*`)
- Payment processing (`verenigingen/api/payment_*`)
- Administrative functions (`verenigingen/api/*admin*`, `verenigingen/api/*manage*`)

**Implementation:**
```python
# Example: Secure SEPA batch creation
@frappe.whitelist()
@critical_api(OperationType.FINANCIAL)
def create_sepa_batch_validated(**batch_data):
    # Implementation with full security
    pass
```

### Phase 2: High Security (Week 3-4)

**Priority 2 - Member Data & Core Operations**

**Target APIs:**
- Member creation/modification operations
- Volunteer management functions
- Chapter administration
- Membership application processing

### Phase 3: Standard Security (Week 5-6)

**Priority 3 - Reporting & Analytics**

**Target APIs:**
- Report generation endpoints
- Analytics dashboards
- Data export functions
- Search and filtering operations

### Phase 4: Utility & Public (Week 7-8)

**Priority 4 - Remaining Operations**

**Target APIs:**
- Health check endpoints
- Utility functions
- Public information APIs
- Development/debugging tools

## Security Validation

### Automated Classification

```python
# Get classification for specific endpoint
classifier = get_api_classifier()
endpoint_info = classifier.classify_endpoint(
    function_obj,
    OperationType.MEMBER_DATA
)

# Generate implementation code
implementation = classifier.generate_implementation_code(endpoint_info)
```

### Security Testing

```python
# Run comprehensive security tests
security_results = run_security_tests()

# Check specific endpoint security
validation_result = validate_endpoint_security("my_api_function")
```

### Monitoring & Dashboards

```python
# Get real-time security dashboard
dashboard = get_security_dashboard()

# Review security incidents
incidents = get_security_incidents(severity="high")
```

## Best Practices

### 1. Security-First Development

- **Always apply security framework** to new API endpoints
- **Use appropriate security level** based on data sensitivity
- **Implement input validation** for all user inputs
- **Log security events** for audit trails

### 2. Performance Considerations

- **Use Redis for rate limiting** in production environments
- **Implement caching** for authorization checks
- **Monitor response times** for security overhead
- **Optimize validation schemas** for performance

### 3. Error Handling

```python
# Secure error responses (don't expose sensitive information)
try:
    result = process_sensitive_operation()
except ValidationError as e:
    # Log detailed error for admins
    log_security_event("validation_error", details=str(e))
    # Return generic error to user
    return {"success": False, "message": "Invalid input provided"}
```

### 4. Testing Security

```python
# Test security implementation
class TestAPISecurityFramework(unittest.TestCase):
    def test_authentication_required(self):
        # Test that unauthenticated requests are rejected
        pass

    def test_role_based_access(self):
        # Test that users without required roles are rejected
        pass

    def test_input_validation(self):
        # Test that invalid inputs are rejected
        pass
```

## Configuration

### Environment Settings

```python
# site_config.json
{
    "sepa_business_hours_enabled": true,
    "sepa_business_hours_start": 9,
    "sepa_business_hours_end": 17,
    "sepa_allowed_ips": ["192.168.1.0/24", "10.0.0.0/8"],
    "disable_csrf_protection": false,
    "rate_limit_backend": "redis"
}
```

### Custom Security Profiles

```python
# Override default security profiles
custom_profile = SecurityProfile(
    level=SecurityLevel.HIGH,
    required_roles=["Custom Role"],
    rate_limit_config={"requests": 20, "window_seconds": 3600},
    requires_csrf=True,
    max_request_size=2 * 1024 * 1024  # 2MB
)

framework.SECURITY_PROFILES[SecurityLevel.HIGH] = custom_profile
```

## Troubleshooting

### Common Issues

1. **Permission Denied Errors**
   - Check user roles and security level requirements
   - Verify IP restrictions for administrative functions
   - Review business hours restrictions

2. **Rate Limit Exceeded**
   - Check rate limit configuration for user role
   - Verify Redis connection for distributed rate limiting
   - Review rate limit headers in response

3. **CSRF Validation Failed**
   - Ensure CSRF token is included in requests
   - Check token expiry (default 1 hour)
   - Verify CSRF protection is not disabled

4. **Input Validation Errors**
   - Review validation schema requirements
   - Check for special characters in input
   - Verify data types match schema expectations

### Debug Tools

```python
# Check endpoint security status
@frappe.whitelist()
def debug_endpoint_security(endpoint_name):
    return analyze_endpoint_security(endpoint_name)

# Validate security configuration
@frappe.whitelist()
def validate_security_config():
    return run_security_validation_tests()
```

## Compliance & Reporting

### Audit Trail Requirements

The framework automatically creates audit trails for:
- All authentication events
- Authorization failures
- Data access and modifications
- Security configuration changes
- Incident detection and resolution

### Compliance Reports

```python
# Generate compliance report
compliance_report = generate_compliance_report(
    start_date="2024-01-01",
    end_date="2024-12-31",
    standards=["GDPR", "ISO27001"]
)
```

### Data Retention

- **Security logs**: 7 years (configurable)
- **Audit trails**: 10 years for critical events
- **Incident reports**: Permanent retention
- **Performance metrics**: 1 year

## Support & Maintenance

### Regular Security Reviews

1. **Weekly**: Review security incidents and metrics
2. **Monthly**: Audit role assignments and permissions
3. **Quarterly**: Update security policies and configurations
4. **Annually**: Comprehensive security assessment

### Framework Updates

- **Security patches**: Applied immediately
- **Feature updates**: Tested in development environment
- **Configuration changes**: Reviewed by security team
- **Documentation updates**: Maintained with each release

### Emergency Procedures

In case of security incidents:
1. **Immediate response**: Block malicious IPs/users
2. **Investigation**: Review audit logs and incident details
3. **Remediation**: Apply security patches and configuration changes
4. **Documentation**: Update security procedures and lessons learned

## Conclusion

The Verenigingen API Security Framework provides a comprehensive, production-ready solution for securing all API endpoints in the association management system. By following this implementation guide and best practices, you can ensure robust security while maintaining system performance and usability.

For additional support or questions, refer to the API documentation or contact the development team.
