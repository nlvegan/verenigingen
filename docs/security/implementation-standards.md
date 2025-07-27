# API Security Implementation Standards

## Overview

This document defines the technical implementation standards for the API Security Framework based on the July 2025 comprehensive security review findings. It provides specific requirements for consistent, secure, and maintainable API security implementations.

**Review Context**: Based on 82/100 security score with identified areas requiring standardization.

## Table of Contents

1. [Immediate Fixes Required](#immediate-fixes-required)
2. [Import Path Standards](#import-path-standards)
3. [Decorator Application Rules](#decorator-application-rules)
4. [Error Handling Patterns](#error-handling-patterns)
5. [Performance Standards](#performance-standards)
6. [Testing Requirements](#testing-requirements)

## Immediate Fixes Required

### Critical Import Conflicts (15-minute fix)

**Files requiring immediate attention**:

#### 1. `get_user_chapters.py`

**Current problematic imports**:
```python
# ❌ BROKEN: Non-existent decorators
from verenigingen.utils.security.authorization import high_security_api, standard_api
```

**Required fix**:
```python
# ✅ CORRECT: Use framework imports
from verenigingen.utils.security.api_security_framework import high_security_api, standard_api, OperationType
```

**Validation command**:
```bash
python -c "from verenigingen.api.get_user_chapters import *; print('✅ Import fix successful')"
```

#### 2. Additional files with mixed import patterns

**Search for problematic patterns**:
```bash
# Find deprecated authorization imports
grep -r "from verenigingen.utils.security.authorization" verenigingen/api/

# Find deprecated csrf_protection imports
grep -r "from verenigingen.utils.security.csrf_protection" verenigingen/api/

# Find deprecated rate_limiting imports
grep -r "from verenigingen.utils.security.rate_limiting" verenigingen/api/
```

## Import Path Standards

### Standard Import Template

**Use this exact template for all new and migrated API files**:

```python
"""
API Module: [Module Name]
Security Level: [CRITICAL|HIGH|MEDIUM|LOW|PUBLIC]
Last Updated: [Date]
Review Status: [Compliant with July 2025 standards]
"""

import frappe
from typing import Dict, List, Optional, Any

# ✅ REQUIRED: Standardized security framework imports
from verenigingen.utils.security.api_security_framework import (
    critical_api,           # For financial/admin operations
    high_security_api,      # For member data operations
    standard_api,           # For reporting/read operations
    utility_api,           # For health checks/utilities
    public_api,            # For public information
    SecurityLevel,         # For custom configurations
    OperationType,         # For operation classification
    api_security_framework # For advanced custom security
)

# ✅ OPTIONAL: Enhanced validation (when needed)
from verenigingen.utils.security.enhanced_validation import (
    validate_with_schema,
    ValidationError
)

# ✅ OPTIONAL: Error handling utilities (recommended)
from verenigingen.utils.api_response import (
    handle_api_error,
    performance_monitor
)
```

### Forbidden Import Patterns

**Never use these deprecated imports**:

```python
# ❌ DEPRECATED: Individual security component imports
from verenigingen.utils.security.authorization import *
from verenigingen.utils.security.csrf_protection import *
from verenigingen.utils.security.rate_limiting import *
from verenigingen.utils.security.audit_logging import *

# ❌ DEPRECATED: Old security decorators
from verenigingen.utils.dd_security_enhancements import *

# ❌ DEPRECATED: Direct component access
from verenigingen.utils.security.components.rate_limiter import RateLimiter
```

### Import Validation Rules

1. **Single Source Principle**: All security decorators must come from `api_security_framework`
2. **No Mixed Patterns**: Don't mix new and old import styles in the same file
3. **Explicit Imports**: Use explicit imports, avoid `import *`
4. **Version Consistency**: All security imports must be from the same framework version

## Decorator Application Rules

### Rule 1: Decorator Order (Mandatory)

**Correct order (top to bottom)**:

```python
@frappe.whitelist(allow_guest=False)  # 1. Frappe whitelist (required)
@critical_api(operation_type=OperationType.FINANCIAL)  # 2. Security decorator (required)
@validate_with_schema("payment_data")  # 3. Validation (optional)
@handle_api_error  # 4. Error handling (recommended)
@performance_monitor(threshold_ms=2000)  # 5. Monitoring (optional)
def api_function(**kwargs):
    """API function with proper decorator order"""
    pass
```

**Validation**: Decorators must be applied in this exact order for consistent behavior.

### Rule 2: Security Level Mapping (Mandatory)

**Operation Type → Security Level mapping**:

```python
# Financial operations → CRITICAL security
@critical_api(operation_type=OperationType.FINANCIAL)

# Member data → HIGH security
@high_security_api(operation_type=OperationType.MEMBER_DATA)

# Administrative → CRITICAL security
@critical_api(operation_type=OperationType.ADMIN)

# Reporting → STANDARD security
@standard_api(operation_type=OperationType.REPORTING)

# Utilities → LOW security
@utility_api(operation_type=OperationType.UTILITY)

# Public → PUBLIC access
@public_api(operation_type=OperationType.PUBLIC)
```

### Rule 3: Operation Type Specification (Mandatory)

**Every security decorator must specify operation type**:

```python
# ✅ CORRECT: Operation type specified
@critical_api(operation_type=OperationType.FINANCIAL)

# ❌ WRONG: Missing operation type
@critical_api()
```

### Rule 4: Consistent Naming Patterns

**Function naming must indicate security level**:

```python
# ✅ CORRECT: Clear security indication in docstring
@critical_api(operation_type=OperationType.FINANCIAL)
def process_sepa_batch(**batch_data):
    """
    Process SEPA batch with CRITICAL security

    Security Level: CRITICAL
    Rate Limit: 10/hour
    CSRF Required: Yes
    Audit Level: Comprehensive
    """
    pass
```

## Error Handling Patterns

### Standard Error Response Format

**All secured APIs must use consistent error responses**:

```python
from verenigingen.utils.api_response import handle_api_error

@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
def secure_api_function(**kwargs):
    """API with standardized error handling"""
    try:
        # Business logic
        result = process_data(kwargs)
        return {"success": True, "data": result}
    except ValidationError as e:
        # Validation errors are automatically handled by @handle_api_error
        raise
    except Exception as e:
        # System errors are automatically handled by @handle_api_error
        raise
```

**Error response format**:
```json
{
    "success": false,
    "error_type": "PermissionError",
    "message": "Access denied. Required roles: System Manager",
    "error_code": "INSUFFICIENT_PERMISSIONS",
    "timestamp": "2025-07-26T10:30:00Z",
    "request_id": "req_abc123",
    "security_context": {
        "security_level": "critical",
        "operation_type": "financial",
        "rate_limit_remaining": 9
    }
}
```

### Exception Handling Standards

1. **Never suppress security exceptions**: Let security framework handle authentication/authorization errors
2. **Use structured logging**: Include security context in error logs
3. **Provide meaningful messages**: Help users understand security requirements
4. **Include recovery guidance**: Tell users how to resolve security issues

## Performance Standards

### Security Overhead Limits

**Maximum acceptable overhead per security level**:

- **Critical APIs**: <10ms additional overhead
- **High Security APIs**: <7ms additional overhead
- **Standard APIs**: <5ms additional overhead
- **Utility APIs**: <3ms additional overhead
- **Public APIs**: <2ms additional overhead

### Performance Monitoring

**Required for high-traffic APIs**:

```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@performance_monitor(threshold_ms=2000)  # Alert if over 2 seconds
def high_traffic_api(**kwargs):
    """High-traffic API with performance monitoring"""
    pass
```

### Optimization Guidelines

1. **Cache Security Metadata**: Security decisions are cached for performance
2. **Batch Security Checks**: Use batch validation for bulk operations
3. **Async Logging**: Audit logging uses async processing
4. **Minimal Validation**: Only validate required fields at API boundary

## Testing Requirements

### Security Test Coverage

**Every secured API must have these test types**:

#### 1. Security Configuration Tests

```python
def test_api_security_configuration(self):
    """Test security decorator configuration"""
    # Test correct security level is applied
    # Test operation type is classified correctly
    # Test rate limits are enforced
    pass
```

#### 2. Authorization Tests

```python
def test_api_authorization(self):
    """Test role-based access control"""
    # Test with insufficient roles (should fail)
    # Test with correct roles (should succeed)
    # Test with guest access (if applicable)
    pass
```

#### 3. Input Validation Tests

```python
def test_api_input_validation(self):
    """Test input validation and sanitization"""
    # Test with valid input (should succeed)
    # Test with invalid input (should fail)
    # Test with malicious input (should be sanitized)
    pass
```

#### 4. Rate Limiting Tests

```python
def test_api_rate_limiting(self):
    """Test rate limiting enforcement"""
    # Test within rate limit (should succeed)
    # Test exceeding rate limit (should fail)
    # Test rate limit headers are present
    pass
```

### Automated Security Testing

**Use these test commands for validation**:

```bash
# Test security framework integrity
python verenigde/tests/test_security_framework_comprehensive.py

# Test specific API security
python verenigingen/tests/test_api_security_individual.py --api-name your_api_name

# Validate import patterns
python scripts/validation/validate_security_imports.py

# Check performance impact
python scripts/testing/benchmark_security_overhead.py
```

## Validation and Compliance

### Pre-Commit Validation

**Required checks before committing secured APIs**:

```bash
#!/bin/bash
# Pre-commit hook for security validation

# 1. Check imports
python scripts/validation/check_security_imports.py
if [ $? -ne 0 ]; then
    echo "❌ Security import validation failed"
    exit 1
fi

# 2. Validate decorator patterns
python scripts/validation/validate_decorator_patterns.py
if [ $? -ne 0 ]; then
    echo "❌ Decorator pattern validation failed"
    exit 1
fi

# 3. Test security functionality
python verenigingen/tests/test_security_framework_smoke.py
if [ $? -ne 0 ]; then
    echo "❌ Security functionality test failed"
    exit 1
fi

echo "✅ All security validation checks passed"
```

### Compliance Checklist

**For each secured API, verify**:

- [ ] Uses standardized imports from `api_security_framework`
- [ ] Applies appropriate security level for operation type
- [ ] Specifies correct operation type in decorator
- [ ] Follows mandatory decorator order
- [ ] Includes comprehensive docstring with security info
- [ ] Has error handling with `@handle_api_error`
- [ ] Passes all security tests
- [ ] Performance overhead is within limits
- [ ] Audit logging is functioning correctly

### Security Health Monitoring

**Continuous monitoring endpoints**:

```python
# Check overall security implementation health
GET /api/method/verenigingen.utils.security.api_security_framework.get_implementation_health

# Response format:
{
    "success": true,
    "implementation_score": 95.2,
    "compliance_status": {
        "import_standardization": 98.5,
        "decorator_consistency": 92.3,
        "error_handling": 96.7,
        "performance_compliance": 94.1
    },
    "issues": [
        {
            "file": "get_user_chapters.py",
            "issue": "deprecated_imports",
            "severity": "high",
            "fix_time": "5 minutes"
        }
    ]
}
```

## Migration Assistance

### Automated Migration Tools

**Use these tools to help with standardization**:

```bash
# Auto-fix import patterns
python scripts/migration/auto_fix_security_imports.py --dry-run
python scripts/migration/auto_fix_security_imports.py --apply

# Generate migration plan for file
python scripts/migration/analyze_api_security.py --file payment_processing.py

# Validate migration results
python scripts/migration/validate_migration.py --check-all
```

### Manual Migration Checklist

**For each API file**:

1. **Backup original file**
2. **Update imports** to standardized pattern
3. **Apply appropriate security decorators**
4. **Add error handling** if missing
5. **Update docstrings** with security information
6. **Test functionality** works correctly
7. **Validate security** controls are active
8. **Check performance** impact is acceptable
9. **Update documentation** if needed
10. **Commit changes** with descriptive message

## Conclusion

These implementation standards ensure:

- **Consistency**: Uniform security implementation across all APIs
- **Reliability**: Reduced configuration errors and security gaps
- **Maintainability**: Clear patterns for ongoing development
- **Performance**: Optimized security overhead
- **Compliance**: Standards alignment for auditing

**Implementation Priority**:
1. **Immediate**: Fix import conflicts (15 minutes)
2. **Short-term**: Standardize existing secured APIs (2 hours)
3. **Ongoing**: Apply standards to new API development
4. **Continuous**: Monitor compliance with automated tools

Following these standards will resolve the inconsistencies identified in the security review while maintaining the excellent security posture achieved.
