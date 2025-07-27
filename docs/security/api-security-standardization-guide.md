# API Security Standardization Guide

## Overview

This guide establishes standardized patterns for consistent security decorator usage across the Verenigingen application, based on findings from the July 2025 comprehensive security review.

**Security Review Results**: 82/100 score with identified areas for standardization improvement.

## Table of Contents

1. [Import Standardization](#import-standardization)
2. [Decorator Application Patterns](#decorator-application-patterns)
3. [Common Mistakes to Avoid](#common-mistakes-to-avoid)
4. [Code Examples](#code-examples)
5. [Validation and Testing](#validation-and-testing)

## Import Standardization

### Required Import Pattern

**Always use this standardized import pattern**:

```python
# ✅ CORRECT: Standardized imports (July 2025)
from verenigingen.utils.security.api_security_framework import (
    critical_api, high_security_api, standard_api, utility_api, public_api,
    SecurityLevel, OperationType, api_security_framework
)
from verenigingen.utils.security.enhanced_validation import validate_with_schema
```

### Deprecated Import Patterns

**Never use these deprecated imports**:

```python
# ❌ DEPRECATED: Causes import conflicts
from verenigingen.utils.security.authorization import high_security_api, standard_api
from verenigingen.utils.security.csrf_protection import csrf_required
from verenigingen.utils.security.rate_limiting import rate_limit
from verenigingen.utils.security.audit_logging import audit_event
```

### Migration from Deprecated Imports

**Step-by-step conversion process**:

1. **Identify deprecated imports**:
   ```bash
   grep -r "from verenigingen.utils.security.authorization" verenigingen/api/
   grep -r "from verenigingen.utils.security.csrf_protection" verenigingen/api/
   grep -r "from verenigingen.utils.security.rate_limiting" verenigingen/api/
   ```

2. **Replace with standardized imports**:
   ```python
   # Before
   from verenigingen.utils.security.authorization import high_security_api

   # After
   from verenigingen.utils.security.api_security_framework import high_security_api
   ```

3. **Validate changes**:
   ```bash
   python -c "from verenigingen.utils.security.api_security_framework import *; print('✅ Import successful')"
   ```

## Decorator Application Patterns

### Standard Decorator Patterns

#### Pattern 1: Financial Operations (Critical Security)

```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error  # Optional but recommended
@performance_monitor(threshold_ms=2000)  # Optional for monitoring
def process_payment(**payment_data):
    """Process payment with highest security level"""
    # Implementation
    pass
```

**Security Profile Applied**:
- Rate limit: 10 requests/hour
- CSRF protection: Required
- Audit logging: Comprehensive
- Input validation: Strict
- Role requirements: System Manager, Admin

#### Pattern 2: Member Data Operations (High Security)

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
@validate_with_schema("member_data")  # Recommended for data validation
def update_member_profile(**profile_data):
    """Update member profile with GDPR compliance"""
    # Implementation
    pass
```

**Security Profile Applied**:
- Rate limit: 50 requests/hour
- CSRF protection: Required
- Audit logging: Detailed
- Input validation: Schema-based
- Role requirements: Manager+

#### Pattern 3: Reporting Operations (Standard Security)

```python
@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def generate_member_report(filters=None):
    """Generate member report with standard security"""
    # Implementation
    pass
```

**Security Profile Applied**:
- Rate limit: 200 requests/hour
- CSRF protection: Not required (read-only)
- Audit logging: Basic
- Input validation: Standard
- Role requirements: Staff+

#### Pattern 4: Utility Functions (Low Security)

```python
@frappe.whitelist()
@utility_api(operation_type=OperationType.UTILITY)
def health_check():
    """System health check with basic security"""
    # Implementation
    pass
```

**Security Profile Applied**:
- Rate limit: 500 requests/hour
- CSRF protection: Not required
- Audit logging: Minimal
- Input validation: Basic
- Role requirements: Any authenticated user

#### Pattern 5: Public Information (No Authentication)

```python
@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_public_information():
    """Get public information - no authentication required"""
    # Implementation
    pass
```

**Security Profile Applied**:
- Rate limit: 1000 requests/hour
- CSRF protection: Not required
- Audit logging: None
- Input validation: Basic sanitization
- Role requirements: None

### Advanced Decorator Patterns

#### Custom Security Configuration

For specialized requirements:

```python
@frappe.whitelist()
@api_security_framework(
    security_level=SecurityLevel.HIGH,
    operation_type=OperationType.MEMBER_DATA,
    roles=["System Manager", "Data Protection Officer"],
    custom_rate_limit=25,  # Custom rate limit
    audit_level="detailed",
    custom_validators=[gdpr_compliance_check],
    ip_restrictions=["192.168.1.0/24"]  # Optional IP restrictions
)
def export_member_data(**params):
    """Export member data with custom GDPR validation"""
    pass
```

#### Chained Decorators (Recommended Order)

```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)  # Security first
@validate_with_schema("payment_data")  # Validation second
@handle_api_error  # Error handling third
@performance_monitor(threshold_ms=1500)  # Monitoring last
def process_sepa_batch(**batch_data):
    """Process SEPA batch with full security stack"""
    pass
```

## Common Mistakes to Avoid

### 1. Mixed Import Patterns

❌ **Wrong**:
```python
# Mixing old and new imports
from verenigingen.utils.security.authorization import high_security_api
from verenigingen.utils.security.api_security_framework import OperationType
```

✅ **Correct**:
```python
# Consistent imports from framework
from verenigingen.utils.security.api_security_framework import (
    high_security_api, OperationType
)
```

### 2. Incorrect Decorator Order

❌ **Wrong**:
```python
@performance_monitor()
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(**data):
    pass
```

✅ **Correct**:
```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@performance_monitor()
def process_payment(**data):
    pass
```

### 3. Over-Securing Low-Risk Operations

❌ **Wrong**:
```python
@critical_api(operation_type=OperationType.UTILITY)  # Too restrictive
def get_system_status():
    pass
```

✅ **Correct**:
```python
@utility_api(operation_type=OperationType.UTILITY)  # Appropriate level
def get_system_status():
    pass
```

### 4. Under-Securing Critical Operations

❌ **Wrong**:
```python
@utility_api(operation_type=OperationType.FINANCIAL)  # Insufficient security
def process_payment(**data):
    pass
```

✅ **Correct**:
```python
@critical_api(operation_type=OperationType.FINANCIAL)  # Appropriate security
def process_payment(**data):
    pass
```

### 5. Missing Operation Type

❌ **Wrong**:
```python
@critical_api()  # Missing operation type
def process_payment(**data):
    pass
```

✅ **Correct**:
```python
@critical_api(operation_type=OperationType.FINANCIAL)  # Clear operation type
def process_payment(**data):
    pass
```

## Code Examples

### Example 1: Migrating from Deprecated Pattern

**Before (deprecated)**:
```python
from verenigingen.utils.security.authorization import high_security_api
from verenigingen.utils.security.csrf_protection import csrf_required

@frappe.whitelist()
@csrf_required
@high_security_api
def update_member_data(**data):
    pass
```

**After (standardized)**:
```python
from verenigingen.utils.security.api_security_framework import (
    high_security_api, OperationType
)

@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def update_member_data(**data):
    pass
```

### Example 2: Comprehensive Security Implementation

```python
from verenigingen.utils.security.api_security_framework import (
    critical_api, OperationType
)
from verenigingen.utils.security.enhanced_validation import validate_with_schema

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@validate_with_schema("sepa_batch")
@handle_api_error
@performance_monitor(threshold_ms=2000)
def create_sepa_batch(**batch_data):
    """
    Create SEPA batch with comprehensive security

    Security Level: CRITICAL
    - Rate limit: 10/hour
    - CSRF protection: Required
    - Audit logging: Comprehensive
    - Schema validation: sepa_batch
    - Performance monitoring: 2s threshold
    """
    try:
        # batch_data is automatically validated and sanitized
        batch = process_batch_creation(batch_data)
        return {"success": True, "batch_id": batch.name}
    except Exception as e:
        # Error handling is automatic with @handle_api_error
        raise
```

### Example 3: Multi-Level API Security

```python
from verenigingen.utils.security.api_security_framework import (
    high_security_api, standard_api, OperationType
)

@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_member_details(member_id):
    """Get detailed member information - high security"""
    pass

@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_member_summary_stats():
    """Get member summary statistics - standard security"""
    pass
```

## Validation and Testing

### Pre-Commit Validation

Use these commands to validate standardization compliance:

```bash
# 1. Check for deprecated imports
scripts/validation/check_deprecated_security_imports.sh

# 2. Validate decorator patterns
python scripts/validation/validate_security_decorator_patterns.py

# 3. Test security framework integrity
python scripts/validation/test_security_framework_imports.py
```

### Automated Testing

```bash
# Run security framework tests
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_security_framework_comprehensive

# Test specific standardization compliance
python verenigingen/tests/test_security_standardization.py
```

### Security Health Check

```python
# API endpoint to validate security standardization
GET /api/method/verenigingen.utils.security.api_security_framework.validate_security_standardization

# Response includes:
{
    "success": true,
    "standardization_score": 95.2,
    "issues_found": {
        "deprecated_imports": 0,
        "inconsistent_patterns": 1,
        "missing_operation_types": 0
    },
    "recommendations": [
        "Standardize decorator order in payment_processing.py"
    ]
}
```

## Implementation Checklist

### For New APIs

- [ ] Use standardized imports from `api_security_framework`
- [ ] Apply appropriate security level decorator
- [ ] Specify correct operation type
- [ ] Follow recommended decorator order
- [ ] Include comprehensive docstring with security level
- [ ] Test security controls work correctly
- [ ] Validate performance impact is acceptable

### For Existing APIs (Migration)

- [ ] Identify current security implementation
- [ ] Replace deprecated imports with standardized ones
- [ ] Update decorator patterns to follow standards
- [ ] Test that security controls still work
- [ ] Verify no functionality is broken
- [ ] Update documentation if needed
- [ ] Run security validation tests

### Code Review Checklist

- [ ] Imports follow standardized pattern
- [ ] Security level matches operation risk
- [ ] Operation type is specified and correct
- [ ] Decorator order follows recommendations
- [ ] No deprecated security patterns used
- [ ] Documentation includes security information
- [ ] Tests validate security functionality

## Monitoring and Maintenance

### Continuous Monitoring

1. **Weekly Security Reviews**: Check for new deprecated import usage
2. **Monthly Pattern Analysis**: Validate decorator consistency across codebase
3. **Quarterly Standards Updates**: Review and update standardization guidelines

### Automated Maintenance

```bash
# Daily: Check for standardization compliance
python scripts/monitoring/daily_security_standardization_check.py

# Weekly: Generate standardization report
python scripts/reporting/weekly_security_standardization_report.py
```

### Metrics to Track

- **Import Standardization**: % of files using correct imports
- **Decorator Consistency**: % of APIs following standard patterns
- **Security Coverage**: % of APIs with appropriate security levels
- **Performance Impact**: Average security overhead per API call

## Support and Resources

### Quick Reference

**Standard Security Levels**:
- `critical_api`: Financial, admin operations (10/hour)
- `high_security_api`: Member data, sensitive operations (50/hour)
- `standard_api`: Reporting, standard operations (200/hour)
- `utility_api`: Health checks, utilities (500/hour)
- `public_api`: Public information (1000/hour)

**Operation Types**:
- `OperationType.FINANCIAL`: Payment processing, invoicing
- `OperationType.MEMBER_DATA`: Member information access
- `OperationType.ADMIN`: System administration
- `OperationType.REPORTING`: Analytics, reports
- `OperationType.UTILITY`: Health checks, status
- `OperationType.PUBLIC`: Public information

### Documentation Links

- [API Security Framework Migration Guide](./api-security-framework-migration-guide.md)
- [Security Framework API Reference](./api-security-framework-guide.md)
- [Security Testing Guide](../testing/security-testing-guide.md)

### Getting Help

1. **Check standardization status**: Use security health check endpoint
2. **Run validation tools**: Use provided validation scripts
3. **Review examples**: Follow patterns in this guide
4. **Test thoroughly**: Use comprehensive security test suite

## Conclusion

Following these standardization guidelines ensures:

- **Consistency**: Uniform security patterns across the codebase
- **Maintainability**: Easy to understand and modify security implementations
- **Reliability**: Reduced chance of security configuration errors
- **Performance**: Optimized security overhead through consistent patterns
- **Compliance**: Standards alignment for auditing and certification

The standardization guidelines are designed to eliminate the import conflicts and inconsistent patterns identified in the security review while maintaining the excellent security posture achieved.

**Next Steps**:
1. Apply immediate import conflict fixes (30 minutes)
2. Standardize existing secured APIs (2 hours)
3. Implement validation automation (4 hours)
4. Monitor ongoing compliance (continuous)
