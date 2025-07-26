# Test Creation Guide - Verenigingen Testing Infrastructure

This guide helps developers create high-quality tests using our sophisticated testing infrastructure, including the **VereningingenTestCase** base class and advanced features like edge case testing, mock banks, and automatic cleanup.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Test Base Classes](#test-base-classes)
3. [Test Data Factory](#test-data-factory)
4. [Advanced Features](#advanced-features)
5. [Performance Guidelines](#performance-guidelines)
6. [Best Practices](#best-practices)

## Quick Start

### Basic Test Template

```python
"""
Test module for [Component Name]
Covers [brief description of what this tests]
"""

from verenigingen.tests.utils.base import VereningingenTestCase


class Test[ComponentName](VereningingenTestCase):
    """Test suite for [Component Name] functionality"""
    
    @classmethod
    def setUpClass(cls):
        """One-time setup for entire test class"""
        super().setUpClass()
        # Additional class-level setup if needed
    
    def test_[feature]_happy_path(self):
        """Test normal successful scenario for [feature]"""
        # Arrange
        member = self.create_test_member()
        
        # Act
        result = perform_action(member)
        
        # Assert
        self.assertTrue(result.success)
        self.assertFieldEqual(result, "status", "completed")
    
    def test_[feature]_edge_case(self):
        """Test edge case: [describe the edge case]"""
        # Use edge case testing methods
        member = self.create_test_member()
        self.clear_member_auto_schedules(member.name)
        
        # Create controlled test scenario
        schedule = self.create_controlled_dues_schedule(
            member.name, "Monthly", 25.0
        )
        
        # Test validation logic
        result = schedule.validate_consistency()
        self.assertFalse(result["valid"])
```

### Test File Naming Convention

- **File names**: `test_[component]_[type].py`
- **Class names**: `Test[Component][Type]`
- **Method names**: `test_[feature]_[scenario]`

**Examples**:
- `test_member_creation.py` → `TestMemberCreation`
- `test_sepa_mandate_validation.py` → `TestSepaMandateValidation`
- `test_volunteer_portal_security.py` → `TestVolunteerPortalSecurity`

## Test Base Classes

### VereningingenTestCase (Primary Base Class)

**Location**: `verenigingen/tests/utils/base.py`

**Key Features**:
- **Automatic cleanup** - Tracks all created records and cleans them up automatically
- **Customer cleanup** - Automatically handles customers created by membership applications
- **Built-in test data factory** - Consistent test data generation
- **Enhanced assertions** - Domain-specific assertions for common patterns
- **Performance tracking** - Built-in timing and query count monitoring
- **Edge case testing** - Methods for comprehensive edge case validation

**Usage**:
```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyFeature(VereningingenTestCase):
    def test_something(self):
        # Factory available via self.factory
        member = self.create_test_member()
        self.track_doc("Member", member.name)  # Automatic cleanup
        
        # Enhanced assertions
        self.assertFieldEqual(member, "status", "Active")
        
        # Performance tracking
        with self.assertQueryCount(100):
            result = expensive_operation()
```

### Available Factory Methods

The `VereningingenTestCase` includes a comprehensive factory via `self.factory`:

```python
# Member creation with all required fields
member = self.create_test_member(
    first_name="Test",
    email="test@example.com",
    chapter="Test Chapter"
)

# Volunteer with automatic member creation if needed
volunteer = self.create_test_volunteer()

# Complete membership application workflow
application = self.create_membership_application(
    auto_approve=True,
    create_member=True
)

# SEPA mandate with mock bank
mandate = self.create_sepa_mandate(
    member=member.name,
    bank_code="TEST"  # Uses mock bank
)

# Chapter with all required fields
chapter = self.create_test_chapter()

# Membership with proper relationships
membership = self.create_test_membership(member=member.name)
```

## Test Data Factory

### Mock Bank Testing

The system includes comprehensive mock bank support:

```python
# Generate test IBAN with specific bank
from verenigingen.utils.iban_validator import generate_test_iban

# Available mock banks
test_iban = generate_test_iban("TEST")  # TEST Bank
mock_iban = generate_test_iban("MOCK")  # MOCK Bank  
demo_iban = generate_test_iban("DEMO")  # DEMO Bank

# In test factory
iban = self.factory.generate_test_iban()  # Random mock bank

# Features:
# - Full MOD-97 checksum validation (pass all IBAN validation)
# - BIC auto-derivation (TESTNL2A, MOCKNL2A, DEMONL2A)
# - Compatible with SEPA mandate creation
```

### Edge Case Testing Methods

**Comprehensive edge case testing** based on enhanced framework:

```python
def test_billing_frequency_conflict(self):
    # 1. Create normal test data
    member = self.create_test_member()
    membership = self.create_test_membership(member=member.name)
    
    # 2. Enable edge case testing (cancels auto-schedules)
    self.clear_member_auto_schedules(member.name)
    
    # 3. Create controlled test scenarios
    monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
    annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)
    
    # 4. Test validation logic
    result = annual.validate_billing_frequency_consistency()
    self.assertFalse(result["valid"])  # Should detect conflict
```

**Key Methods**:
- `clear_member_auto_schedules(member_name)` - Cancel auto-created schedules
- `create_controlled_dues_schedule(member, frequency, rate, **kwargs)` - Create specific schedules
- `setup_edge_case_testing(member_name)` - Complete setup for edge case scenarios

## Advanced Features

### Automatic Cleanup System

The **VereningingenTestCase** automatically tracks and cleans up:

```python
def test_complex_workflow(self):
    # All these will be automatically cleaned up
    chapter = self.create_test_chapter()
    member = self.create_test_member(chapter=chapter.name)
    application = self.create_membership_application(member=member.name)
    
    # Approve creates member AND customer automatically
    approved_member = self.approve_application(application)
    
    # Customer cleanup happens automatically in tearDown!
    # No manual cleanup needed
```

**Cleanup Order**: The system cleans up in reverse dependency order to handle relationships properly.

### Performance Monitoring

```python
def test_performance_sensitive_operation(self):
    # Monitor query count
    with self.assertQueryCount(50):  # Ensure no more than 50 queries
        result = batch_process_members()
    
    # Monitor execution time
    with self.assertMaxExecutionTime(2.0):  # Max 2 seconds
        result = complex_calculation()
        
    # Access performance metrics
    duration = self.get_last_test_duration()
    query_count = self.get_last_query_count()
```

### Enhanced Assertions

```python
# Field-specific assertions
self.assertFieldEqual(doc, "field_name", expected_value)
self.assertFieldNotEmpty(doc, "field_name")

# Status assertions
self.assertDocumentExists("DocType", doc_name)
self.assertDocumentStatus(doc, "Active")

# Relationship assertions
self.assertDocumentLinked(parent_doc, child_doc, "link_field")

# Validation assertions
self.assertValidationError(lambda: doc.save(), "Expected error message")
```

## Performance Guidelines

### Query Optimization

```python
# ❌ Bad - N+1 queries
for member in members:
    member_details = frappe.get_doc("Member", member.name)
    process_member(member_details)

# ✅ Good - Single query
member_data = frappe.get_all("Member", 
    filters={"name": ["in", member_names]},
    fields=["name", "first_name", "email"])
```

### Test Performance Targets

- **Unit tests**: < 0.1 seconds per test
- **Integration tests**: < 1.0 seconds per test  
- **Workflow tests**: < 5.0 seconds per test
- **Query limits**: < 10 queries for simple operations, < 50 for complex workflows

### Performance Monitoring

```python
# Monitor test performance
with self.assertQueryCount(10):
    with self.assertMaxExecutionTime(1.0):
        result = optimized_function()
```

## Best Practices

### 1. Test Organization

```python
class TestMemberCreation(VereningingenTestCase):
    """Group related tests in focused test classes"""
    
    def test_create_member_happy_path(self):
        """Test normal member creation"""
        pass
        
    def test_create_member_duplicate_email(self):
        """Test member creation with duplicate email"""
        pass
        
    def test_create_member_invalid_data(self):
        """Test member creation with invalid data"""
        pass
```

### 2. Test Documentation

```python
def test_complex_business_rule(self):
    """
    Test complex business rule: Members cannot have overlapping memberships
    
    Scenario:
    1. Create member with active membership
    2. Attempt to create overlapping membership
    3. Should raise validation error
    
    Edge cases covered:
    - Same start date
    - Overlapping date ranges
    - Adjacent date ranges (should be allowed)
    """
```

### 3. Test Data Management

```python
def test_realistic_scenario(self):
    """Use realistic test data for better coverage"""
    # ✅ Good - realistic data
    member = self.create_test_member(
        first_name="Alice",
        last_name="Johnson", 
        email="alice.johnson@example.com",
        birth_date="1985-03-15"
    )
    
    # ❌ Avoid - meaningless data
    member = self.create_test_member(
        first_name="Test",
        last_name="User",
        email="test@test.com"
    )
```

### 4. Error Testing

```python
def test_validation_errors(self):
    """Test all validation scenarios"""
    # Test required field validation
    with self.assertRaisesRegex(frappe.ValidationError, "First name is required"):
        member = frappe.new_doc("Member")
        member.save()
    
    # Test business rule validation
    with self.assertValidationError("Email already exists"):
        self.create_test_member(email="existing@example.com")
        self.create_test_member(email="existing@example.com")  # Should fail
```

### 5. Integration Testing

```python
def test_end_to_end_workflow(self):
    """Test complete workflows"""
    # Application → Approval → Member Creation → Customer Creation
    application = self.create_membership_application()
    
    # Approve application
    approved_member = self.approve_application(application)
    
    # Verify member created
    self.assertDocumentExists("Member", approved_member.name)
    
    # Verify customer created automatically
    customer = frappe.get_value("Customer", {"member": approved_member.name})
    self.assertIsNotNone(customer)
    
    # Verify relationships
    self.assertDocumentLinked(approved_member, customer, "customer")
```

## Common Patterns

### Testing Permissions

```python
def test_permissions(self):
    """Test role-based access control"""
    # Test with different user roles
    with self.set_user("member@example.com"):
        # Test member-level permissions
        result = access_member_data()
        self.assertTrue(result.success)
    
    with self.set_user("admin@example.com"):
        # Test admin-level permissions
        result = access_admin_data()
        self.assertTrue(result.success)
```

### Testing API Endpoints

```python
def test_api_endpoint(self):
    """Test API endpoint functionality"""
    # Prepare test data
    member = self.create_test_member()
    
    # Test API call
    response = self.client.post("/api/member/update", {
        "member": member.name,
        "field": "value"
    })
    
    # Verify response
    self.assertEqual(response.status_code, 200)
    self.assertTrue(response.json()["success"])
```

### Testing Scheduled Jobs

```python
def test_scheduled_job(self):
    """Test scheduled job execution"""
    # Prepare test data
    members = [self.create_test_member() for _ in range(5)]
    
    # Run scheduled job
    from verenigingen.scheduled_jobs import process_renewals
    result = process_renewals()
    
    # Verify results
    self.assertEqual(result["processed"], 5)
    
    # Verify side effects
    for member in members:
        updated_member = frappe.get_doc("Member", member.name)
        self.assertEqual(updated_member.status, "Renewed")
```

---

## Quick Reference

### Essential Imports
```python
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.iban_validator import generate_test_iban
import frappe
```

### Essential Methods
```python
# Test creation
member = self.create_test_member()
volunteer = self.create_test_volunteer() 
chapter = self.create_test_chapter()

# Edge case testing
self.clear_member_auto_schedules(member.name)
schedule = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)

# Assertions
self.assertFieldEqual(doc, "field", "value")
self.assertDocumentExists("DocType", "name")

# Performance monitoring
with self.assertQueryCount(10):
    result = operation()
```

### Mock Banks
```python
test_iban = generate_test_iban("TEST")  # TESTNL2A
mock_iban = generate_test_iban("MOCK")  # MOCKNL2A  
demo_iban = generate_test_iban("DEMO")  # DEMONL2A
```

For more advanced usage, see the existing test files in `verenigingen/tests/` and the comprehensive documentation in the base classes.