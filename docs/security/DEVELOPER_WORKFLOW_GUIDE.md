# Developer Workflow Guide - Verenigingen Security Framework

**Version**: 2.0
**Last Updated**: September 15, 2025
**Audience**: Developers, Technical Teams

## Overview

This guide provides practical workflows for developers working with the Verenigingen Security Framework. It covers day-to-day development tasks, security implementation patterns, testing procedures, and troubleshooting common issues.

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
2. [Security Implementation Workflow](#security-implementation-workflow)
3. [API Development Patterns](#api-development-patterns)
4. [Testing Security Implementation](#testing-security-implementation)
5. [Code Review Guidelines](#code-review-guidelines)
6. [Deployment and Migration](#deployment-and-migration)
7. [Troubleshooting Common Issues](#troubleshooting-common-issues)
8. [Performance Optimization](#performance-optimization)

## Development Environment Setup

### Prerequisites

Ensure your development environment has the security framework properly configured:

```bash
# 1. Verify security framework is loaded
bench --site dev.veganisme.net execute "
from verenigingen.utils.security.api_security_framework import get_security_framework
framework = get_security_framework()
print(f'Framework loaded: {framework is not None}')
print(f'Environment: {framework.get_current_environment().value}')
"

# 2. Check Critical Operation Rules table exists
bench --site dev.veganisme.net execute "
import frappe
exists = frappe.db.exists('DocType', 'Critical Operation Rule')
print(f'Critical Operation Rule DocType exists: {exists}')
"

# 3. Verify security monitoring is active
bench --site dev.veganisme.net execute "
from verenigingen.utils.security.security_monitoring import get_security_monitor
monitor = get_security_monitor()
print(f'Security monitor loaded: {monitor is not None}')
"
```

### Initial Configuration

Create a basic development security configuration:

```python
# Create development-specific security rules
def setup_dev_security_rules():
    """Create basic security rules for development"""

    rules = [
        {
            "operation_name": "create_test_member",
            "operation_type": "member_data",
            "security_level": "low",
            "enabled": 1,
            "rate_limit_calls": 100,
            "rate_limit_period_seconds": 60,
            "audit_level": "minimal"
        },
        {
            "operation_name": "debug_api_call",
            "operation_type": "utility",
            "security_level": "low",
            "enabled": 1,
            "rate_limit_calls": 200,
            "rate_limit_period_seconds": 60,
            "audit_level": "minimal"
        }
    ]

    for rule_data in rules:
        if not frappe.db.exists("Critical Operation Rule", rule_data["operation_name"]):
            rule = frappe.get_doc({
                "doctype": "Critical Operation Rule",
                **rule_data
            })
            rule.insert()
            print(f"Created rule: {rule_data['operation_name']}")

# Run setup
setup_dev_security_rules()
```

## Security Implementation Workflow

### Step 1: Analyze the Operation

Before implementing security, analyze your operation:

```python
def analyze_new_operation(function_name, description):
    """Analyze security requirements for new operation"""

    analysis = {
        "function_name": function_name,
        "description": description,
        "security_assessment": {}
    }

    # Determine operation type
    if any(keyword in function_name.lower() for keyword in ["payment", "invoice", "financial"]):
        analysis["operation_type"] = "financial"
        analysis["suggested_security_level"] = "critical"
    elif any(keyword in function_name.lower() for keyword in ["member", "personal", "update"]):
        analysis["operation_type"] = "member_data"
        analysis["suggested_security_level"] = "high"
    elif any(keyword in function_name.lower() for keyword in ["admin", "system", "config"]):
        analysis["operation_type"] = "admin"
        analysis["suggested_security_level"] = "critical"
    elif any(keyword in function_name.lower() for keyword in ["report", "list", "get", "view"]):
        analysis["operation_type"] = "reporting"
        analysis["suggested_security_level"] = "medium"
    else:
        analysis["operation_type"] = "utility"
        analysis["suggested_security_level"] = "low"

    # Determine required roles
    role_mapping = {
        "financial": ["System Manager", "Accounts Manager"],
        "member_data": ["System Manager", "Verenigingen Manager", "Verenigingen Staff"],
        "admin": ["System Manager"],
        "reporting": ["System Manager", "Verenigingen Manager", "Verenigingen Staff"],
        "utility": []  # Any authenticated user
    }

    analysis["suggested_roles"] = role_mapping.get(analysis["operation_type"], [])

    # Suggest rate limits
    rate_limits = {
        "critical": {"calls": 10, "period": 3600},
        "high": {"calls": 50, "period": 3600},
        "medium": {"calls": 200, "period": 3600},
        "low": {"calls": 500, "period": 3600}
    }

    analysis["suggested_rate_limit"] = rate_limits[analysis["suggested_security_level"]]

    return analysis

# Example usage
analysis = analyze_new_operation("process_member_payment", "Process monthly membership payment")
print(frappe.as_json(analysis, indent=2))
```

### Step 2: Create Critical Operation Rule

Based on your analysis, create the appropriate Critical Operation Rule:

```python
def create_operation_rule(analysis, business_rules=None):
    """Create Critical Operation Rule based on analysis"""

    rule_data = {
        "doctype": "Critical Operation Rule",
        "operation_name": analysis["function_name"],
        "operation_type": analysis["operation_type"],
        "description": analysis["description"],
        "security_level": analysis["suggested_security_level"],
        "enabled": 1,
        "required_roles": ",".join(analysis["suggested_roles"]),
        "rate_limit_calls": analysis["suggested_rate_limit"]["calls"],
        "rate_limit_period_seconds": analysis["suggested_rate_limit"]["period"],
        "audit_level": "detailed" if analysis["suggested_security_level"] in ["critical", "high"] else "standard"
    }

    # Add business rules if specified
    if business_rules:
        rule_data.update({
            "enable_business_validation": 1,
            "amount_threshold": business_rules.get("amount_threshold"),
            "time_restrictions": business_rules.get("time_restrictions"),
            "ip_restrictions": business_rules.get("ip_restrictions")
        })

    # Create the rule
    rule = frappe.get_doc(rule_data)
    rule.insert()

    print(f"Created Critical Operation Rule: {rule.operation_name}")
    return rule.name

# Example usage
business_rules = {
    "amount_threshold": 1000.0,  # Alert for payments over €1000
    "time_restrictions": "business_hours_only"
}

rule_name = create_operation_rule(analysis, business_rules)
```

### Step 3: Implement Security Decorator

Apply the appropriate security decorator to your function:

```python
from verenigingen.utils.security.api_security_framework import (
    critical_api, high_security_api, standard_api, utility_api,
    OperationType
)

# Critical security for financial operations
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_member_payment(member_id, amount, payment_method):
    """Process member payment with critical security"""

    # Validate input
    if not member_id or not amount:
        frappe.throw("Missing required parameters")

    # Business logic validation
    if float(amount) <= 0:
        frappe.throw("Payment amount must be positive")

    # Implementation
    payment_entry = frappe.get_doc({
        "doctype": "Payment Entry",
        "party_type": "Customer",
        "party": member_id,
        "paid_amount": amount,
        "payment_type": "Receive"
    })

    payment_entry.insert()
    payment_entry.submit()

    return {
        "success": True,
        "payment_entry": payment_entry.name,
        "amount": amount
    }

# High security for member data operations
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def update_member_batch(member_updates):
    """Update multiple members with high security"""

    results = []
    for update in member_updates:
        member = frappe.get_doc("Member", update["member_id"])

        # Apply updates
        for field, value in update.get("fields", {}).items():
            if hasattr(member, field):
                setattr(member, field, value)

        member.save()
        results.append({"member_id": member.name, "status": "updated"})

    return {"success": True, "results": results}

# Standard security for reporting
@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def generate_membership_report(filters=None):
    """Generate membership report with standard security"""

    # Build query based on filters
    conditions = []
    if filters:
        if filters.get("status"):
            conditions.append(f"status = '{filters['status']}'")
        if filters.get("chapter"):
            conditions.append(f"chapter = '{filters['chapter']}'")

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    data = frappe.db.sql(f"""
        SELECT name, first_name, last_name, status, chapter
        FROM `tabMember`
        {where_clause}
        ORDER BY last_name, first_name
    """, as_dict=True)

    return {
        "success": True,
        "data": data,
        "count": len(data)
    }

# Utility function for low security operations
@frappe.whitelist()
@utility_api()
def get_system_status():
    """Get system status with utility security"""

    return {
        "success": True,
        "status": "healthy",
        "timestamp": frappe.utils.now(),
        "version": frappe.__version__
    }
```

### Step 4: Test Security Implementation

Verify your security implementation works correctly:

```python
def test_security_implementation(function_name):
    """Test security implementation for a function"""

    print(f"Testing security for: {function_name}")

    # 1. Test Critical Operation Rule exists
    rule_exists = frappe.db.exists("Critical Operation Rule", function_name)
    print(f"✓ Critical Operation Rule exists: {rule_exists}")

    # 2. Test function has security decorator
    try:
        func = frappe.get_attr(f"verenigingen.api.{function_name}")
        has_security = hasattr(func, '_security_protected')
        security_level = getattr(func, '_security_level', 'None')
        print(f"✓ Function has security decorator: {has_security}")
        print(f"✓ Security level: {security_level}")
    except Exception as e:
        print(f"✗ Error accessing function: {e}")

    # 3. Test rule configuration
    from verenigingen.utils.secure_operations import get_critical_operations_registry
    registry = get_critical_operations_registry()
    config = registry.get_operation_config(function_name)

    if config:
        print(f"✓ Rule configuration loaded")
        print(f"  - Security level: {config['security_level']}")
        print(f"  - Required roles: {config['required_roles']}")
        print(f"  - Rate limit: {config['rate_limit']['calls']}/{config['rate_limit']['period_seconds']}s")
    else:
        print(f"✗ No rule configuration found")

    # 4. Test business rules if enabled
    if config and config.get('business_rules', {}).get('enabled'):
        print(f"✓ Business rules enabled")
        if config['business_rules'].get('amount_threshold'):
            print(f"  - Amount threshold: €{config['business_rules']['amount_threshold']}")

    print(f"Security test completed for {function_name}\n")

# Test your implementations
test_security_implementation("process_member_payment")
test_security_implementation("update_member_batch")
test_security_implementation("generate_membership_report")
```

## API Development Patterns

### Pattern 1: Financial Operations

```python
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_invoice_with_validation(customer, items, due_date):
    """Create invoice with comprehensive validation"""

    try:
        # Input validation
        if not customer or not items:
            return {"success": False, "error": "Missing required fields"}

        # Business rule validation
        total_amount = sum(item.get('amount', 0) for item in items)
        if total_amount > 10000:  # High-value transaction
            # Additional validation for high-value transactions
            frappe.log_error(f"High-value invoice creation: €{total_amount} for {customer}")

        # Create invoice
        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": customer,
            "due_date": due_date,
            "items": items
        })

        invoice.insert()

        # Submit if under threshold, otherwise require manual approval
        if total_amount <= 5000:
            invoice.submit()
            status = "submitted"
        else:
            status = "pending_approval"

        return {
            "success": True,
            "invoice_name": invoice.name,
            "status": status,
            "total_amount": total_amount
        }

    except frappe.ValidationError as e:
        return {"success": False, "error": f"Validation error: {str(e)}"}
    except Exception as e:
        frappe.log_error(f"Invoice creation failed: {str(e)}")
        return {"success": False, "error": "Internal error occurred"}
```

### Pattern 2: Member Data Operations

```python
@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def update_member_sensitive_data(member_id, updates):
    """Update sensitive member data with audit trail"""

    try:
        # Get member document
        member = frappe.get_doc("Member", member_id)

        # Log what's being changed for audit
        changes = []
        for field, new_value in updates.items():
            if hasattr(member, field):
                old_value = getattr(member, field)
                if old_value != new_value:
                    changes.append({
                        "field": field,
                        "old_value": old_value,
                        "new_value": new_value
                    })
                    setattr(member, field, new_value)

        if changes:
            # Save member
            member.save()

            # Create audit trail entry
            audit_entry = frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"Member data updated: {member.name}",
                "content": frappe.as_json(changes),
                "reference_doctype": "Member",
                "reference_name": member.name,
                "status": "Complete"
            })
            audit_entry.insert()

            return {
                "success": True,
                "member_id": member.name,
                "changes_count": len(changes),
                "audit_log": audit_entry.name
            }
        else:
            return {
                "success": True,
                "member_id": member.name,
                "changes_count": 0,
                "message": "No changes detected"
            }

    except frappe.DoesNotExistError:
        return {"success": False, "error": "Member not found"}
    except Exception as e:
        frappe.log_error(f"Member update failed: {str(e)}")
        return {"success": False, "error": "Update failed"}
```

### Pattern 3: Reporting Operations

```python
@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def export_member_data(filters=None, format="json"):
    """Export member data with privacy controls"""

    try:
        # Validate export permissions
        if not frappe.has_permission("Member", "export"):
            return {"success": False, "error": "Export permission required"}

        # Build secure query
        conditions = ["1=1"]  # Base condition

        if filters:
            if filters.get("chapter"):
                conditions.append("chapter = %(chapter)s")
            if filters.get("status"):
                conditions.append("status = %(status)s")
            if filters.get("date_range"):
                conditions.append("creation BETWEEN %(start_date)s AND %(end_date)s")

        # Select only allowed fields (exclude sensitive data)
        allowed_fields = [
            "name", "first_name", "last_name", "chapter",
            "status", "membership_start_date", "creation"
        ]

        query = f"""
            SELECT {', '.join(allowed_fields)}
            FROM `tabMember`
            WHERE {' AND '.join(conditions)}
            ORDER BY last_name, first_name
            LIMIT 10000
        """

        data = frappe.db.sql(query, filters or {}, as_dict=True)

        # Log export for audit
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"Member data export: {len(data)} records",
            "content": f"Exported by {frappe.session.user}",
            "status": "Complete"
        }).insert()

        return {
            "success": True,
            "data": data,
            "count": len(data),
            "format": format,
            "exported_fields": allowed_fields
        }

    except Exception as e:
        frappe.log_error(f"Export failed: {str(e)}")
        return {"success": False, "error": "Export failed"}
```

### Pattern 4: Utility Operations

```python
@frappe.whitelist()
@utility_api()
def validate_member_data(member_id):
    """Validate member data integrity"""

    try:
        member = frappe.get_doc("Member", member_id)

        validation_results = {
            "member_id": member_id,
            "validations": [],
            "errors": [],
            "warnings": []
        }

        # Required field validation
        required_fields = ["first_name", "last_name", "email"]
        for field in required_fields:
            value = getattr(member, field, None)
            if not value:
                validation_results["errors"].append(f"Missing required field: {field}")
            else:
                validation_results["validations"].append(f"✓ {field} present")

        # Email validation
        if member.email:
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, member.email):
                validation_results["errors"].append("Invalid email format")
            else:
                validation_results["validations"].append("✓ Email format valid")

        # SEPA mandate validation
        if member.sepa_mandate:
            mandate = frappe.get_doc("SEPA Mandate", member.sepa_mandate)
            if mandate.status != "Active":
                validation_results["warnings"].append("SEPA mandate not active")
            else:
                validation_results["validations"].append("✓ SEPA mandate active")

        validation_results["status"] = "valid" if not validation_results["errors"] else "invalid"
        validation_results["score"] = len(validation_results["validations"]) / (len(validation_results["validations"]) + len(validation_results["errors"]) + len(validation_results["warnings"]))

        return {"success": True, "validation": validation_results}

    except frappe.DoesNotExistError:
        return {"success": False, "error": "Member not found"}
    except Exception as e:
        return {"success": False, "error": f"Validation failed: {str(e)}"}
```

## Testing Security Implementation

### Unit Testing Security

Create comprehensive tests for your security implementation:

```python
# test_security_implementation.py
import frappe
import unittest
from unittest.mock import patch

class TestSecurityImplementation(unittest.TestCase):

    def setUp(self):
        """Set up test environment"""
        self.test_user = "test@example.com"
        self.test_member_id = "TEST-001"

        # Create test user with specific roles
        if not frappe.db.exists("User", self.test_user):
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.test_user,
                "first_name": "Test",
                "last_name": "User",
                "roles": [{"role": "Verenigingen Staff"}]
            })
            user.insert()

    def test_critical_api_security(self):
        """Test critical API security enforcement"""

        # Test with insufficient permissions
        frappe.set_user("Guest")

        with self.assertRaises(frappe.PermissionError):
            from verenigingen.api.financial import process_member_payment
            process_member_payment(self.test_member_id, 100.0, "bank_transfer")

    def test_rate_limiting(self):
        """Test rate limiting functionality"""

        frappe.set_user(self.test_user)

        # Make multiple calls to test rate limiting
        from verenigingen.api.utility import get_system_status

        # Should succeed initially
        result = get_system_status()
        self.assertTrue(result["success"])

        # Test rate limit by making many calls
        # Note: This would need to be adapted based on actual rate limits

    def test_business_rule_validation(self):
        """Test business rule validation"""

        frappe.set_user(self.test_user)

        # Test amount threshold validation
        from verenigingen.api.financial import create_invoice_with_validation

        # Test normal amount
        result = create_invoice_with_validation(
            customer="TEST-CUSTOMER",
            items=[{"item_code": "TEST", "amount": 500}],
            due_date="2025-01-01"
        )
        self.assertTrue(result["success"])

        # Test high amount (should trigger business rules)
        result = create_invoice_with_validation(
            customer="TEST-CUSTOMER",
            items=[{"item_code": "TEST", "amount": 15000}],
            due_date="2025-01-01"
        )
        # Should still succeed but with different status
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "pending_approval")

    def test_security_decorator_integration(self):
        """Test security decorator properly applied"""

        from verenigingen.api.financial import process_member_payment

        # Check decorator attributes
        self.assertTrue(hasattr(process_member_payment, '_security_protected'))
        self.assertEqual(getattr(process_member_payment, '_security_level'), 'critical')

    def tearDown(self):
        """Clean up test data"""
        frappe.set_user("Administrator")

        # Clean up test user
        if frappe.db.exists("User", self.test_user):
            frappe.delete_doc("User", self.test_user)

def run_security_tests():
    """Run all security tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSecurityImplementation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()

# Run tests
if __name__ == "__main__":
    success = run_security_tests()
    print(f"Security tests {'PASSED' if success else 'FAILED'}")
```

### Integration Testing

Test security in integration scenarios:

```python
def test_security_integration():
    """Test security framework integration"""

    # Test 1: Critical Operation Rule integration
    print("Testing Critical Operation Rule integration...")

    from verenigingen.utils.secure_operations import get_critical_operations_registry
    registry = get_critical_operations_registry()

    # Test rule exists and is properly configured
    config = registry.get_operation_config("process_member_payment")
    assert config is not None, "Critical Operation Rule not found"
    assert config["security_level"] == "critical", "Incorrect security level"

    print("✓ Critical Operation Rule integration working")

    # Test 2: API Security Framework integration
    print("Testing API Security Framework integration...")

    from verenigingen.utils.security.api_security_framework import get_security_framework
    framework = get_security_framework()

    # Test environment detection
    env = framework.get_current_environment()
    print(f"✓ Environment detected: {env.value}")

    # Test security profiles
    critical_profile = framework.get_security_profile("critical")
    assert critical_profile.level.value == "critical", "Security profile not working"

    print("✓ API Security Framework integration working")

    # Test 3: Security Monitoring integration
    print("Testing Security Monitoring integration...")

    from verenigingen.utils.security.security_monitoring import get_security_monitor
    monitor = get_security_monitor()

    # Test business rule monitoring
    alerts = monitor.detect_business_rule_anomalies()
    print(f"✓ Security monitoring working, {len(alerts)} alerts detected")

    print("All integration tests passed!")

# Run integration tests
test_security_integration()
```

### Performance Testing

Test security performance impact:

```python
def test_security_performance():
    """Test security framework performance impact"""

    import time

    print("Testing security performance impact...")

    # Test baseline performance (no security)
    start_time = time.time()
    for i in range(100):
        # Simulate basic operation
        pass
    baseline_time = time.time() - start_time

    # Test with security framework
    from verenigingen.utils.security.api_security_framework import get_security_framework
    framework = get_security_framework()

    start_time = time.time()
    for i in range(100):
        # Simulate security validation
        profile = framework.get_security_profile("medium")
        framework.validate_authentication(profile)
    security_time = time.time() - start_time

    # Calculate overhead
    overhead_percent = ((security_time - baseline_time) / baseline_time) * 100

    print(f"Baseline time: {baseline_time*1000:.2f}ms")
    print(f"Security time: {security_time*1000:.2f}ms")
    print(f"Overhead: {overhead_percent:.1f}%")

    # Performance should be acceptable (< 20% overhead)
    assert overhead_percent < 20, f"Security overhead too high: {overhead_percent:.1f}%"

    print("✓ Performance test passed")

# Run performance test
test_security_performance()
```

## Code Review Guidelines

### Security Review Checklist

When reviewing code with security implementation, check:

#### 1. Security Decorator Application

```python
# ✅ Good - Proper security decorator
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(amount, member_id):
    pass

# ❌ Bad - Missing security decorator
@frappe.whitelist()
def process_payment(amount, member_id):
    pass

# ❌ Bad - Wrong security level
@frappe.whitelist()
@utility_api()  # Should be critical_api for financial operations
def process_payment(amount, member_id):
    pass
```

#### 2. Input Validation

```python
# ✅ Good - Proper input validation
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(amount, member_id):
    if not amount or not member_id:
        frappe.throw("Missing required parameters")

    if float(amount) <= 0:
        frappe.throw("Amount must be positive")

    # Process payment

# ❌ Bad - No input validation
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(amount, member_id):
    # Direct processing without validation
    payment = create_payment(amount, member_id)
```

#### 3. Error Handling

```python
# ✅ Good - Secure error handling
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(amount, member_id):
    try:
        # Process payment
        return {"success": True, "payment_id": payment_id}
    except frappe.ValidationError as e:
        return {"success": False, "error": "Validation failed", "details": str(e)}
    except Exception as e:
        frappe.log_error(f"Payment processing failed: {str(e)}")
        return {"success": False, "error": "Processing failed"}

# ❌ Bad - Exposing internal errors
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_payment(amount, member_id):
    try:
        # Process payment
        return payment
    except Exception as e:
        return {"error": str(e)}  # Exposes internal error details
```

#### 4. Critical Operation Rule Correspondence

```python
# ✅ Good - Rule exists for critical operation
# Critical Operation Rule: "process_member_payment"
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_member_payment(amount, member_id):
    pass

# ❌ Bad - Missing Critical Operation Rule
@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def some_new_financial_function():  # No corresponding rule
    pass
```

### Code Review Template

```markdown
## Security Review Checklist

### Security Implementation

- [ ] Appropriate security decorator applied
- [ ] Security level matches operation risk
- [ ] Critical Operation Rule exists (for critical/high operations)
- [ ] Operation type correctly specified

### Input Validation

- [ ] All inputs validated before processing
- [ ] Proper data type validation
- [ ] Business rule validation implemented
- [ ] SQL injection prevention

### Error Handling

- [ ] Secure error messages (no internal details exposed)
- [ ] Proper exception handling
- [ ] Error logging for debugging
- [ ] Graceful degradation

### Performance

- [ ] Security overhead is acceptable
- [ ] No unnecessary security checks
- [ ] Proper caching where applicable
- [ ] Rate limits are reasonable

### Testing

- [ ] Security tests included
- [ ] Edge cases covered
- [ ] Permission tests included
- [ ] Integration tests pass

### Documentation

- [ ] Security requirements documented
- [ ] Usage examples provided
- [ ] Error conditions documented
- [ ] Rate limits documented
```

## Deployment and Migration

### Pre-Deployment Checklist

Before deploying security changes:

```bash
# 1. Run security analysis
bench --site production.site execute "
from verenigingen.utils.security.api_security_framework import analyze_api_security_status
analysis = analyze_api_security_status()
print(f'Security coverage: {analysis[\"summary\"][\"security_coverage\"]}%')
print(f'High priority endpoints: {analysis[\"summary\"][\"high_priority_endpoints\"]}')
"

# 2. Verify all Critical Operation Rules exist
bench --site production.site execute "
from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import CriticalOperationRule
rules = CriticalOperationRule.get_all_rules()
print(f'Total rules: {len(rules)}')
for name, config in rules.items():
    print(f'{name}: {config[\"security_level\"]} ({config[\"operation_type\"]})')
"

# 3. Test security framework initialization
bench --site production.site execute "
from verenigingen.utils.security.api_security_framework import get_security_framework
framework = get_security_framework()
env = framework.get_current_environment()
print(f'Environment: {env.value}')
print(f'Framework loaded: {framework is not None}')
"
```

### Migration Scripts

Create migration scripts for security updates:

```python
# migrate_security_rules.py
import frappe

def migrate_security_rules():
    """Migrate existing security rules to new format"""

    print("Starting security rules migration...")

    # Update existing rules with new fields
    existing_rules = frappe.get_all("Critical Operation Rule", fields=["name"])

    for rule in existing_rules:
        doc = frappe.get_doc("Critical Operation Rule", rule.name)

        # Add default monitoring settings if missing
        if not hasattr(doc, 'monitor_execution_time'):
            doc.monitor_execution_time = 1
            doc.execution_time_threshold_ms = 5000
            doc.monitor_failure_rate = 1
            doc.failure_rate_threshold_percent = 10
            doc.save()
            print(f"Updated monitoring settings for: {doc.name}")

    # Create missing rules for critical operations
    critical_operations = [
        {
            "operation_name": "create_financial_document",
            "operation_type": "financial",
            "security_level": "critical",
            "required_roles": "System Manager,Accounts Manager",
            "rate_limit_calls": 10,
            "enable_business_validation": 1,
            "amount_threshold": 1000.0
        },
        # Add more critical operations as needed
    ]

    for operation in critical_operations:
        if not frappe.db.exists("Critical Operation Rule", operation["operation_name"]):
            rule = frappe.get_doc({
                "doctype": "Critical Operation Rule",
                **operation
            })
            rule.insert()
            print(f"Created rule: {operation['operation_name']}")

    print("Security rules migration completed")

# Run migration
if __name__ == "__main__":
    migrate_security_rules()
```

### Environment-Specific Configuration

Configure security for different environments:

```python
# environment_config.py
import frappe

def configure_environment_security():
    """Configure security based on environment"""

    from verenigingen.utils.security.api_security_framework import get_security_framework
    framework = get_security_framework()
    env = framework.get_current_environment()

    print(f"Configuring security for environment: {env.value}")

    if env.value == "development":
        # Relaxed security for development
        dev_overrides = {
            "rate_limit_calls": 1000,  # Higher limits
            "rate_limit_period_seconds": 60,  # Shorter periods
            "alert_on_execution": 0  # No alerts
        }

        update_rules_for_environment(dev_overrides)

    elif env.value == "production":
        # Strict security for production
        prod_overrides = {
            "rate_limit_calls": 10,  # Lower limits
            "rate_limit_period_seconds": 3600,  # Longer periods
            "alert_on_execution": 1,  # Enable alerts
            "requires_justification": 1  # Require justification
        }

        update_rules_for_environment(prod_overrides, critical_only=True)

    print("Environment security configuration completed")

def update_rules_for_environment(overrides, critical_only=False):
    """Update rules with environment-specific overrides"""

    filters = {}
    if critical_only:
        filters["security_level"] = "critical"

    rules = frappe.get_all("Critical Operation Rule", filters=filters)

    for rule in rules:
        doc = frappe.get_doc("Critical Operation Rule", rule.name)

        for field, value in overrides.items():
            if hasattr(doc, field):
                setattr(doc, field, value)

        doc.save()
        print(f"Updated {doc.name} for environment")

# Run environment configuration
configure_environment_security()
```

## Troubleshooting Common Issues

### Issue 1: Security Decorator Not Applied

**Symptoms**: API function accessible without proper security checks

**Diagnosis**:

```python
# Check if decorator is applied
func = frappe.get_attr("verenigingen.api.module.function_name")
print(f"Has security: {hasattr(func, '_security_protected')}")
print(f"Security level: {getattr(func, '_security_level', 'None')}")
print(f"Whitelisted: {getattr(func, '__func_is_whitelisted__', False)}")
```

**Solutions**:

1. Ensure `@frappe.whitelist()` comes first
2. Import security decorators correctly
3. Restart bench after changes
4. Check for syntax errors in decorator usage

### Issue 2: Critical Operation Rule Not Loading

**Symptoms**: Rule exists in database but not being applied

**Diagnosis**:

```python
# Check rule exists and is enabled
rule = frappe.get_doc("Critical Operation Rule", "operation_name")
print(f"Enabled: {rule.enabled}")

# Check cache
from verenigingen.utils.secure_operations import get_critical_operations_registry
registry = get_critical_operations_registry()
config = registry.get_operation_config("operation_name")
print(f"Config loaded: {config is not None}")

# Check cache directly
cache_key = "critical_operation_rule:operation_name"
cached = frappe.cache().get_value(cache_key)
print(f"Cached: {cached is not None}")
```

**Solutions**:

1. Verify rule is enabled
2. Clear cache: `frappe.cache().delete_value("critical_operation_rules")`
3. Check operation name matches exactly
4. Verify database connection

### Issue 3: Rate Limiting Too Aggressive

**Symptoms**: Users getting blocked unexpectedly

**Diagnosis**:

```python
# Check current rate limit status
from verenigingen.utils.security.rate_limiting import get_rate_limiter
limiter = get_rate_limiter()

# Check specific user's rate limit status
user_status = limiter.get_rate_limit_status("operation_key", frappe.session.user)
print(f"User rate limit status: {user_status}")

# Check rule configuration
rule = frappe.get_doc("Critical Operation Rule", "operation_name")
print(f"Rate limit: {rule.rate_limit_calls}/{rule.rate_limit_period_seconds}s")
print(f"Scope: {rule.rate_limit_scope}")
```

**Solutions**:

1. Increase rate limit calls in rule
2. Adjust rate limit period
3. Change scope from per_user to per_ip if appropriate
4. Add user-specific exceptions

### Issue 4: Business Rules Failing Unexpectedly

**Symptoms**: Valid operations rejected by business rules

**Diagnosis**:

```python
# Test business rule validation
from verenigingen.utils.secure_operations import get_critical_operations_registry
registry = get_critical_operations_registry()

# Test with actual data
violations = registry.validate_business_rules("operation_name",
    amount=1500, member_id="TEST-001")
print(f"Violations: {violations}")

# Check rule configuration
rule = frappe.get_doc("Critical Operation Rule", "operation_name")
print(f"Amount threshold: {rule.amount_threshold}")
print(f"Business validation enabled: {rule.enable_business_validation}")
```

**Solutions**:

1. Adjust amount thresholds in rule
2. Check data format matches expected format
3. Verify business rule logic
4. Add debug logging to business rule validation

### Issue 5: Environment Detection Problems

**Symptoms**: Functions not available in expected environment

**Diagnosis**:

```python
# Check environment detection
from verenigingen.utils.security.api_security_framework import get_security_framework
framework = get_security_framework()

env_info = framework.validate_deployment_environment()
print(f"Detected environment: {env_info['detected_environment']}")
print(f"Expected environment: {env_info.get('expected_environment', 'None')}")
print(f"Validation passed: {env_info['validation_passed']}")
print(f"Config sources: {env_info['config_sources']}")
```

**Solutions**:

1. Set explicit environment in site_config.json
2. Check developer_mode setting
3. Verify deployment_environment configuration
4. Update allowed_environments in decorators

## Performance Optimization

### Caching Security Configurations

Implement efficient caching for security operations:

```python
def optimize_security_caching():
    """Optimize security configuration caching"""

    # 1. Pre-warm critical operation rule cache
    from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import CriticalOperationRule

    all_rules = CriticalOperationRule.get_all_rules()
    print(f"Pre-warmed {len(all_rules)} critical operation rules")

    # 2. Cache security profiles
    from verenigingen.utils.security.api_security_framework import get_security_framework
    framework = get_security_framework()

    for level in ["critical", "high", "medium", "low", "public"]:
        profile = framework.get_security_profile(level)
        print(f"Cached security profile: {level}")

    # 3. Pre-compute user permissions for common operations
    common_operations = [
        "create_financial_document",
        "process_member_payment",
        "update_member_batch",
        "generate_membership_report"
    ]

    current_user = frappe.session.user
    user_roles = frappe.get_roles(current_user)

    for operation in common_operations:
        config = CriticalOperationRule.get_rule_config(operation)
        if config:
            has_permission = any(role in user_roles for role in config.get('required_roles', []))
            cache_key = f"user_permission:{current_user}:{operation}"
            frappe.cache().set_value(cache_key, has_permission, expires_in_sec=300)

    print("Security caching optimization completed")

# Run optimization
optimize_security_caching()
```

### Monitoring Performance Impact

Monitor security framework performance:

```python
def monitor_security_performance():
    """Monitor security framework performance impact"""

    import time
    from contextlib import contextmanager

    @contextmanager
    def timer(operation_name):
        start = time.time()
        yield
        duration = (time.time() - start) * 1000
        print(f"{operation_name}: {duration:.2f}ms")

    # Test critical operation rule lookup
    with timer("Critical Operation Rule lookup"):
        from verenigingen.utils.secure_operations import get_critical_operations_registry
        registry = get_critical_operations_registry()
        config = registry.get_operation_config("create_financial_document")

    # Test security validation
    with timer("Security validation"):
        from verenigingen.utils.security.api_security_framework import get_security_framework
        framework = get_security_framework()
        profile = framework.get_security_profile("critical")
        framework.validate_authentication(profile)

    # Test business rule validation
    with timer("Business rule validation"):
        violations = registry.validate_business_rules("create_financial_document",
            amount=500, member_id="TEST-001")

    # Test rate limiting check
    with timer("Rate limiting check"):
        from verenigingen.utils.security.rate_limiting import get_rate_limiter
        limiter = get_rate_limiter()
        limiter.check_rate_limit("test_operation")

    print("Performance monitoring completed")

# Run performance monitoring
monitor_security_performance()
```

This comprehensive developer workflow guide provides practical guidance for implementing, testing, and maintaining security in the Verenigingen system. Use it as a reference for day-to-day development tasks and security implementation.
