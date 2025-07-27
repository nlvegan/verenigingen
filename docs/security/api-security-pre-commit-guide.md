# API Security Pre-commit Validation Guide

This guide explains how to use the API security validation tools to ensure all new APIs follow security standards and prevent insecure endpoints from being committed.

## Overview

The Verenigingen application includes comprehensive pre-commit security validation that automatically scans API endpoints for security compliance. This prevents insecure APIs from being committed and maintains high security standards across the codebase.

## Security Validation Tools

### 1. Insecure API Detector (`insecure_api_detector.py`)

**Purpose**: Identifies API endpoints that lack proper security decorators
**When it runs**: On every commit that touches API files
**Exit behavior**: Fails commit if insecure APIs are detected

### 2. API Security Framework Validator (`api_security_validator.py`)

**Purpose**: Validates compliance with the security framework patterns
**When it runs**: On every commit
**Exit behavior**: Fails commit on critical security issues

### 3. Pre-commit Configuration

The `.pre-commit-config.yaml` file configures automatic validation on every commit:

```yaml
repos:
  - repo: local
    hooks:
      - id: insecure-api-detector
        name: 🔒 Insecure API Endpoint Detection
        entry: python scripts/validation/security/insecure_api_detector.py
        files: '^verenigingen/api/.*\.py$'
```

## Quick Start

### Installation

1. **Install pre-commit** (if not already installed):
   ```bash
   pip install pre-commit
   ```

2. **Install the hooks**:
   ```bash
   pre-commit install
   ```

3. **Test the setup**:
   ```bash
   pre-commit run --all-files
   ```

### Usage

Once installed, the validation runs automatically on every commit. If issues are found, the commit will be blocked with detailed error messages.

## Common Security Issues and Fixes

### Issue 1: Missing Security Decorator

**Error Message**:
```
❌ CRITICAL: create_member_payment
File: verenigingen/api/payment_processing.py:45
Issue: API endpoint 'create_member_payment' lacks security decorators.
Fix: Add @critical_api()
```

**Solution**:
```python
# Before (insecure)
@frappe.whitelist()
def create_member_payment(member_id, amount):
    # Implementation
    pass

# After (secure)
from verenigingen.utils.security.api_security_framework import critical_api

@frappe.whitelist()
@critical_api()
def create_member_payment(member_id, amount):
    # Implementation
    pass
```

### Issue 2: Wrong Security Level

**Error Message**:
```
⚠️ HIGH: get_member_data
Issue: Function handles sensitive data but uses @utility_api()
Recommended: @high_security_api()
```

**Solution**:
```python
# Before (under-secured)
@frappe.whitelist()
@utility_api()
def get_member_data(member_id):
    # Implementation
    pass

# After (properly secured)
@frappe.whitelist()
@high_security_api()
def get_member_data(member_id):
    # Implementation
    pass
```

### Issue 3: Missing Input Validation

**Error Message**:
```
⚠️ MEDIUM: update_member_details
Issue: Create/modify function should implement input validation
Recommendation: Add input validation using validate_required_fields
```

**Solution**:
```python
from verenigingen.utils.error_handling import validate_required_fields

@frappe.whitelist()
@high_security_api()
def update_member_details(member_id, details):
    # Add input validation
    validate_required_fields(
        {"member_id": member_id, "details": details},
        ["member_id", "details"]
    )

    # Implementation
    pass
```

### Issue 4: SQL Injection Risk

**Error Message**:
```
🔴 CRITICAL: search_members
Issue: Potential SQL injection vulnerability detected
Recommendation: Use parameterized queries with %s placeholders
```

**Solution**:
```python
# Before (vulnerable)
@frappe.whitelist()
@standard_api()
def search_members(search_term):
    return frappe.db.sql(f"""
        SELECT name, full_name
        FROM `tabMember`
        WHERE full_name LIKE '{search_term}%'
    """)

# After (secure)
@frappe.whitelist()
@standard_api()
def search_members(search_term):
    return frappe.db.sql("""
        SELECT name, full_name
        FROM `tabMember`
        WHERE full_name LIKE %s
    """, [f"{search_term}%"])
```

### Issue 5: Permission Bypass

**Error Message**:
```
🔴 CRITICAL: force_update_member
Issue: Function bypasses permission checks
Recommendation: Remove ignore_permissions and implement proper authorization
```

**Solution**:
```python
# Before (insecure)
@frappe.whitelist()
@high_security_api()
def force_update_member(member_id, data):
    member = frappe.get_doc("Member", member_id)
    member.update(data)
    member.save(ignore_permissions=True)  # ❌ Security bypass

# After (secure)
@frappe.whitelist()
@high_security_api()
def update_member(member_id, data):
    # Check permissions properly
    if not can_update_member(member_id):
        raise PermissionError("You don't have permission to update this member")

    member = frappe.get_doc("Member", member_id)
    member.update(data)
    member.save()  # ✅ Proper permission checking
```

## Security Decorator Reference

### `@critical_api()`
- **Use for**: Financial operations, admin functions, data deletion
- **Security**: Highest security, CSRF protection, audit logging, rate limiting
- **Examples**: Payment processing, SEPA operations, system administration

```python
@frappe.whitelist()
@critical_api()
def process_sepa_payment(payment_data):
    # Critical financial operation
    pass
```

### `@high_security_api()`
- **Use for**: Member data operations, batch operations
- **Security**: High security, audit logging, input validation
- **Examples**: Member creation, data modification, batch processing

```python
@frappe.whitelist()
@high_security_api()
def create_member(member_data):
    # Member data operation
    pass
```

### `@standard_api()`
- **Use for**: Reporting, read operations, analytics
- **Security**: Standard security, basic validation
- **Examples**: Reports, dashboards, data export

```python
@frappe.whitelist()
@standard_api()
def get_member_report(filters):
    # Reporting operation
    pass
```

### `@utility_api()`
- **Use for**: Health checks, status endpoints, utility functions
- **Security**: Basic security, minimal overhead
- **Examples**: System status, health checks, validation utilities

```python
@frappe.whitelist()
@utility_api()
def check_system_health():
    # System utility
    pass
```

### `@public_api()`
- **Use for**: Public information, no authentication required
- **Security**: Minimal security, no authentication
- **Examples**: Public data, documentation endpoints

```python
@frappe.whitelist()
@public_api()
def get_public_info():
    # Public information
    pass
```

## Advanced Configuration

### Custom Security Levels

You can specify custom security levels and operation types:

```python
from verenigingen.utils.security.api_security_framework import (
    api_security_framework, SecurityLevel, OperationType
)

@frappe.whitelist()
@api_security_framework(
    security_level=SecurityLevel.HIGH,
    operation_type=OperationType.MEMBER_DATA,
    roles=["Verenigingen Administrator"],
    audit_level="detailed"
)
def custom_secure_function():
    pass
```

### Input Validation Schemas

For complex input validation:

```python
from verenigingen.utils.security.enhanced_validation import validate_with_schema

@frappe.whitelist()
@high_security_api()
@validate_with_schema('member_data')
def create_member_with_validation(member_data):
    # Automatic schema validation
    pass
```

## Manual Validation

### Run Security Scan Manually

Test your changes before committing:

```bash
# Scan all API files
python scripts/validation/security/insecure_api_detector.py

# Scan specific file
python scripts/validation/security/insecure_api_detector.py verenigingen/api/my_new_api.py

# Verbose output with detailed fixes
python scripts/validation/security/insecure_api_detector.py --verbose

# Generate JSON report
python scripts/validation/security/insecure_api_detector.py --json-output security_report.json
```

### Framework Compliance Check

Validate framework compliance:

```bash
# Check framework compliance
python scripts/validation/security/api_security_validator.py

# Check specific files
python scripts/validation/security/api_security_validator.py verenigingen/api/member_management.py

# Generate detailed report
python scripts/validation/security/api_security_validator.py --verbose --json-output compliance_report.json
```

## Whitelisting Exceptions

If you have a legitimate reason to exempt a function from security requirements, you can add it to the whitelist:

1. **Edit the detector configuration**:
   ```python
   # In scripts/validation/security/insecure_api_detector.py
   WHITELIST_FUNCTIONS = {
       'my_special_function',  # Add your function here
       'get_public_status',    # Example
   }
   ```

2. **Add justification comment**:
   ```python
   @frappe.whitelist()
   def my_special_function():
       """
       Special function that doesn't need security decorators because:
       - It only returns public configuration data
       - No sensitive operations performed
       - Explicitly whitelisted in security validator
       """
       pass
   ```

## Troubleshooting

### Common Issues

1. **"Module not found" errors**:
   - Ensure you're running from the app root directory
   - Check that all security framework modules are properly installed

2. **"Permission denied" errors**:
   - Make sure the scripts have execute permissions
   - Run: `chmod +x scripts/validation/security/*.py`

3. **Pre-commit not running**:
   - Reinstall hooks: `pre-commit install`
   - Check configuration: `pre-commit run --all-files`

### Debug Mode

For troubleshooting, use verbose mode:

```bash
python scripts/validation/security/insecure_api_detector.py --verbose
```

This will show:
- Detailed analysis of each function
- Complete suggested fixes
- Classification reasoning
- Performance metrics

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Security Validation
on: [push, pull_request]

jobs:
  security-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.x'
      - name: Run Security Validation
        run: |
          python scripts/validation/security/insecure_api_detector.py
          python scripts/validation/security/api_security_validator.py
```

### Jenkins Pipeline

```groovy
pipeline {
    agent any
    stages {
        stage('Security Validation') {
            steps {
                sh 'python scripts/validation/security/insecure_api_detector.py'
                sh 'python scripts/validation/security/api_security_validator.py'
            }
        }
    }
}
```

## Best Practices

### 1. **Security by Default**
- Always add security decorators to new APIs
- Start with higher security and adjust down if needed
- Never commit APIs without security decorators

### 2. **Input Validation**
- Validate all user inputs
- Use schema validation for complex data
- Sanitize text inputs to prevent XSS

### 3. **Error Handling**
- Use `@handle_api_error` decorator
- Never expose internal errors to users
- Log errors for debugging

### 4. **Documentation**
- Document security requirements in function docstrings
- Explain why specific security levels are chosen
- Include usage examples

### 5. **Testing**
- Test APIs with different user roles
- Verify permission enforcement
- Test with invalid inputs

## Security Checklist

Before committing new API endpoints:

- [ ] Added appropriate security decorator
- [ ] Implemented input validation
- [ ] Added error handling
- [ ] Documented the function
- [ ] Tested with different user roles
- [ ] Verified no hardcoded secrets
- [ ] Used parameterized SQL queries
- [ ] Avoided permission bypasses
- [ ] Added audit logging for sensitive operations
- [ ] Tested rate limiting behavior

## Support and Resources

### Documentation
- [API Security Framework Reference](./sepa-security-implementation.md)
- [Security Best Practices](../technical/security-best-practices.md)
- [Testing Security APIs](../testing/security-testing-guide.md)

### Getting Help
- Check existing secure APIs for examples
- Review security framework documentation
- Ask the development team for guidance
- Use verbose mode for detailed analysis

### Reporting Security Issues
If you discover a security vulnerability:
1. **Do not commit the code**
2. Report to the security team immediately
3. Include detailed description and potential impact
4. Provide suggested remediation

Remember: Security is everyone's responsibility. These tools help maintain our high security standards automatically, but understanding the principles behind them is equally important.
