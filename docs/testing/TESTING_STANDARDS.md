# Testing Standards for Verenigingen
*Mandatory Patterns for Real Integration Testing*

## **Executive Summary**
These standards establish mandatory testing patterns to eliminate mock abuse and ensure genuine quality assurance. All new tests MUST follow these patterns. Existing tests should be migrated according to the Testing Reformation Plan.

---

## **Core Principles**

### **1. Real Business Logic Validation**
- Test actual business rules, not mocked approximations
- Use real database operations with proper transaction isolation
- Validate actual field references and schema constraints
- Test permission boundaries without bypasses

### **2. Strategic Mocking Only**
- Mock ONLY external services (email, SMS, external APIs)
- NEVER mock Frappe database operations (`frappe.db.*`)
- NEVER mock core business logic or validation functions
- Document every mock with explicit justification

### **3. Enhanced Test Factory Mandatory**
- All new tests MUST use `EnhancedTestCase` base class
- Use Enhanced Test Factory for realistic test data generation
- Leverage built-in field validation and business rule enforcement
- Maintain proper test isolation and cleanup
- **EXTEND the factory when gaps are discovered** - add missing methods rather than working around limitations

---

## **Mandatory Test Patterns**

### **Integration Test Pattern**
```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from unittest.mock import patch

class TestMyWorkflowIntegration(EnhancedTestCase):
    """Integration test following mandatory patterns"""

    def setUp(self):
        """Set up with Enhanced Test Factory"""
        super().setUp()

        # Use Enhanced Test Factory for realistic data
        self.member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            status="Active"
        )

        # Create admin user for workflow testing
        self.admin_user = self.create_test_user(
            "admin@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )

    def test_workflow_with_real_business_logic(self):
        """Test actual workflow without mocking business logic"""

        # ✅ GOOD: Mock only external services
        with patch('frappe.sendmail') as mock_sendmail:
            with self.as_user(self.admin_user.email):
                # ✅ GOOD: Call actual API, not mocked version
                result = my_business_workflow_api(self.member.name)

        # ✅ GOOD: Validate real database changes
        self.member.reload()
        self.assertEqual(self.member.status, "Expected Status")

        # ✅ GOOD: Verify external service was called
        mock_sendmail.assert_called_once()
```

### **❌ PROHIBITED Patterns**
```python
# ❌ NEVER mock database operations
with patch('frappe.db.get_value') as mock_db:
    mock_db.return_value = "fake_value"

# ❌ NEVER bypass permissions in tests
doc.insert(ignore_permissions=True)

# ❌ NEVER mock core business logic
with patch('my_validation_function') as mock_validation:
    mock_validation.return_value = True

# ❌ NEVER use manual field setting instead of API calls
member.status = "Active"  # Should call approval API instead
member.save()
```

---

## **Test Categories and Requirements**

### **1. Unit Tests**
- **Scope**: Individual functions and methods
- **Mocking**: Allowed for dependencies and external calls
- **Requirements**: Fast execution (<1 second), isolated, deterministic

```python
def test_iban_validation_unit():
    """Unit test for IBAN validation function"""
    from verenigingen.utils.iban_validator import validate_dutch_iban

    # Test valid Dutch IBAN
    result = validate_dutch_iban("NL91ABNA0417164300")
    self.assertTrue(result.valid)
    self.assertEqual(result.formatted, "NL91 ABNA 0417 1643 00")

    # Test invalid IBAN
    result = validate_dutch_iban("INVALID_IBAN")
    self.assertFalse(result.valid)
```

### **2. Integration Tests**
- **Scope**: Complete workflows and API endpoints
- **Mocking**: Only external services (email, SMS, external APIs)
- **Requirements**: Real database operations, transaction isolation

```python
def test_membership_approval_integration():
    """Integration test for complete approval workflow"""
    # Use real database operations, mock only external services
    # See test_membership_approval_real.py for complete example
```

### **3. API Security Tests**
- **Scope**: Authentication, authorization, permission validation
- **Mocking**: PROHIBITED - must test real permission boundaries
- **Requirements**: Real user contexts, actual role validation

```python
def test_api_security_real_permissions():
    """Test API security without permission bypasses"""
    limited_user = self.create_test_user(
        "limited@example.com",
        roles=["Verenigingen Member"]  # No admin permissions
    )

    with self.as_user(limited_user.email):
        # Should raise PermissionError for admin-only API
        with self.assertRaises(frappe.PermissionError):
            admin_only_api_function(self.member.name)
```

---

## **Enhanced Test Factory Usage**

### **Mandatory Base Class**
```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestMyFeature(EnhancedTestCase):
    """All new tests must inherit from EnhancedTestCase"""
```

### **Required Factory Methods**
- `self.create_test_member()` - Creates realistic member with business rule validation
- `self.create_test_chapter()` - Creates valid chapter with proper postal codes
- `self.create_test_membership_type()` - Creates membership type with valid amounts
- `self.create_test_user()` - Creates user with proper role assignment
- `self.create_test_volunteer()` - Creates volunteer with age validation

### **Transaction Isolation**
```python
def setUp(self):
    """Enhanced Test Factory provides automatic transaction isolation"""
    super().setUp()
    # Transaction isolation is handled automatically
    # Tests are isolated from each other

def tearDown(self):
    """Automatic cleanup of test data"""
    # Cleanup is handled automatically by Enhanced Test Factory
    super().tearDown()
```

---

## **Field Reference Validation**

### **Mandatory Field Validation**
All field references MUST be validated against actual DocType schemas:

```python
# ✅ GOOD: Enhanced Test Factory validates fields automatically
member = self.create_test_member(
    first_name="Test",       # ✅ Validated against Member DocType
    last_name="User",        # ✅ Validated against Member DocType
    status="Active"          # ✅ Validated against Member DocType
)

# ❌ BAD: Manual field reference without validation
member.non_existent_field = "value"  # Will cause runtime error
```

### **Pre-Commit Field Validation**
- Pre-commit hooks validate all field references
- Tests with invalid field references will be blocked
- Use `scripts/validation/field_reference_validator.py`

---

## **Performance Requirements**

### **Test Execution Time Limits**
- **Unit Tests**: <1 second per test
- **Integration Tests**: <30 seconds per test
- **Full Critical Workflow Suite**: <5 minutes
- **Complete Test Suite**: <15 minutes

### **Database Operation Guidelines**
- Use transaction isolation for cleanup (automatic in EnhancedTestCase)
- Minimize database queries through efficient test data setup
- Reuse test data within test classes where possible
- Clean up orphaned data automatically

---

## **Documentation Requirements**

### **Test Documentation Standards**
```python
class TestMembershipWorkflow(EnhancedTestCase):
    """
    Integration tests for membership workflow

    Tests the complete member lifecycle from application to termination
    including approval, account creation, and payment processing.

    Key Business Rules Tested:
    - Member age requirements (16+ for volunteers)
    - SEPA mandate validation for Dutch banking
    - Permission boundaries for approval workflow

    External Services Mocked:
    - Email sending (frappe.sendmail)
    - SMS notifications (external SMS API)

    Real Integrations Tested:
    - Database operations and constraints
    - Permission system validation
    - Business rule enforcement
    """
```

### **Mock Justification Required**
Every mock MUST include justification comment:

```python
# ✅ GOOD: Justified external service mock
with patch('frappe.sendmail') as mock_sendmail:
    # Mock justified: External email service, not business logic
    result = approval_workflow(member.name)

# ❌ BAD: Unjustified business logic mock
with patch('validate_member_age'):  # No justification provided
    result = create_volunteer(member.name)
```

---

## **Enforcement and Compliance**

### **Pre-Commit Validation**
- Block new database operation mocks
- Require justification for all mocks
- Validate field references against DocType schemas
- Enforce Enhanced Test Factory usage

### **Code Review Requirements**
- All tests must pass Enhanced Test Factory validation
- Mock usage must be justified and minimal
- Integration tests must demonstrate real business logic validation
- Performance requirements must be met

### **Migration Timeline**
- **New Tests**: Must follow these standards immediately
- **Existing Tests**: Migrate according to Testing Reformation Plan
- **Legacy Patterns**: Will be deprecated and eventually removed

---

## **Examples and Templates**

### **Complete Integration Test Template**
See `/verenigingen/tests/integration/test_membership_approval_real.py` for complete example.

### **Real vs Mocked Comparison**

#### ❌ Old Mock-Heavy Pattern (PROHIBITED)
```python
@patch('frappe.db.get_value')
@patch('frappe.sendmail')
@patch('validate_business_rules')
def test_approval_mocked(self, mock_rules, mock_email, mock_db):
    # Mocks everything - validates nothing
    mock_db.return_value = "fake_data"
    mock_rules.return_value = True

    result = approve_member("fake_id")
    # Test validates nothing about real system
```

#### ✅ New Integration Pattern (REQUIRED)
```python
def test_approval_real(self):
    """Real integration test validating actual business logic"""
    member = self.create_test_member(status="Pending")

    # Mock only external services
    with patch('frappe.sendmail') as mock_email:
        # Test real business logic
        result = approve_membership_application(member.name)

    # Validate real database changes
    member.reload()
    self.assertEqual(member.status, "Approved")
    mock_email.assert_called_once()  # Verify external service called
```

---

## **Support and Training**

### **Getting Help**
- Consult existing integration test examples in `/tests/integration/`
- Review Enhanced Test Factory documentation
- Ask questions in development team meetings

### **Migration Support**
- Use migration helpers in Enhanced Test Factory
- Gradual migration timeline in Testing Reformation Plan
- Performance monitoring during transition

These standards ensure that tests provide genuine quality assurance rather than false confidence through extensive mocking. All developers must follow these patterns to maintain system integrity and catch real bugs before production deployment.
