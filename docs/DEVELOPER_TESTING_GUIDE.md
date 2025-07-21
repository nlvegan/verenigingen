# Developer Testing Guide

## Overview

This guide provides comprehensive testing standards and best practices for the Verenigingen application, based on the enhanced testing framework implemented in 2025.

## Enhanced Testing Framework

### VereningingenTestCase: The New Standard

All tests should inherit from `VereningingenTestCase` instead of `unittest.TestCase` or `FrappeTestCase`:

```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyFeature(VereningingenTestCase):
    """Test suite for specific feature"""

    def setUp(self):
        """Set up test data using factory methods"""
        super().setUp()

        # Use factory methods for consistent test data
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="User",
            email="test@example.com"
        )
        # Document automatically tracked for cleanup

    def test_feature_functionality(self):
        """Test specific feature"""
        # Test implementation
        self.assertTrue(some_condition)

    # No tearDown needed - automatic cleanup handled by base class
```

### Key Benefits

#### Automatic Document Cleanup
- **All documents tracked**: Every document created is automatically tracked
- **Reverse dependency cleanup**: Documents cleaned up in reverse creation order
- **Customer cleanup**: Automatic customer record cleanup for member-related tests
- **No manual tearDown**: Base class handles all cleanup automatically

#### Factory Methods
Consistent test data generation with proper relationships:

```python
# Core entities with all required fields
member = self.create_test_member(
    first_name="John",
    last_name="Doe",
    email="john.doe@example.com",
    birth_date="1990-01-01"  # Automatically handles validation
)

# Related entities with proper linkage
volunteer = self.create_test_volunteer(
    member=member.name,
    volunteer_name=member.full_name,
    email=member.email
)

# Geographic entities
chapter = self.create_test_chapter(
    chapter_name="Test Chapter",
    postal_codes="1000-9999"  # Handles region creation automatically
)

# Financial entities
membership = self.create_test_membership(
    member=member.name,
    membership_type="Standard",
    docstatus=1  # Can control submission status
)
```

#### Mock Banking Support
Realistic test data with full validation compliance:

```python
# Generate valid test IBANs with proper MOD-97 checksums
from verenigingen.utils.iban_validator import generate_test_iban

# Test banks that pass full IBAN validation
test_iban = generate_test_iban("TEST")  # NL13TEST0123456789
mock_iban = generate_test_iban("MOCK")  # NL82MOCK0123456789
demo_iban = generate_test_iban("DEMO")  # NL93DEMO0123456789

# Use in SEPA mandate creation
mandate = self.create_sepa_mandate(
    member=member.name,
    iban=test_iban,
    bank_code="TEST"  # Auto-derives BIC: TESTNL2A
)
```

#### Enhanced Assertions
Domain-specific assertions for better test readability:

```python
# Standard assertions work as expected
self.assertTrue(condition)
self.assertEqual(expected, actual)

# Enhanced assertions for better error messages
self.assertFieldEqual(document, "field_name", expected_value)
self.assertDocumentValid(document)
```

#### Performance Monitoring
Built-in performance tracking:

```python
def test_performance_critical_operation(self):
    """Test that operation stays within performance bounds"""

    # Monitor query count
    with self.assertQueryCount(10):  # Fail if more than 10 queries
        result = perform_complex_operation()

    # Built-in timing available via base class
    # Execution time automatically logged
```

## Testing Standards and Requirements

### Mandatory Test Patterns

#### 1. Use VereningingenTestCase
```python
# ✅ Correct - Enhanced base class
class TestMyFeature(VereningingenTestCase):
    pass

# ❌ Never - Legacy patterns
class TestMyFeature(unittest.TestCase):  # Missing cleanup
class TestMyFeature(FrappeTestCase):     # No factory methods
```

#### 2. Use Factory Methods
```python
# ✅ Correct - Factory method with automatic cleanup
member = self.create_test_member(
    first_name="Test",
    email="test@example.com"
)

# ❌ Never - Manual document creation
member = frappe.get_doc({
    "doctype": "Member",
    "first_name": "Test"
    # Missing required fields, no cleanup
})
member.insert(ignore_permissions=True)  # Permission violation
```

#### 3. Read DocType JSON First
**CRITICAL**: Always read the DocType JSON file before writing any code that creates/modifies documents:

```python
# Step 1: Use Read tool to examine DocType JSON
# Step 2: Identify required fields ("reqd": 1)
# Step 3: Use exact field names from JSON
# Step 4: Write code with proper field values

# ✅ Example after reading Member.json
member = self.create_test_member(
    first_name="Test",        # From JSON: "fieldname": "first_name", "reqd": 1
    last_name="User",         # From JSON: "fieldname": "last_name", "reqd": 1
    email="test@example.com", # From JSON: "fieldname": "email", "reqd": 1
    birth_date="1990-01-01"   # From JSON: "fieldname": "birth_date", "reqd": 1
)
```

#### 4. Never Bypass Validation
```python
# ✅ Correct - Let Frappe validate
doc = frappe.new_doc("DocType")
doc.field1 = "value"
doc.save()  # Frappe validation runs

# ❌ Never - Bypass validation
doc.save(ignore_validate=True)    # Skips business rules
doc.insert(ignore_permissions=True)  # Violates security model
frappe.db.sql("INSERT INTO ...")  # Bypasses ORM entirely
```

#### 5. Document Tracking
```python
# ✅ Automatic tracking with factory methods
member = self.create_test_member()  # Automatically tracked

# ✅ Manual tracking when needed
custom_doc = frappe.get_doc({...})
custom_doc.insert()
self.track_doc("DocType", custom_doc.name)  # Manual tracking
```

### Forbidden Patterns

#### Permission Violations
```python
# ❌ NEVER use these patterns
doc.insert(ignore_permissions=True)
doc.save(ignore_permissions=True)
doc.submit(ignore_permissions=True)

# ❌ NEVER bypass validation
doc.save(ignore_validate=True)
doc.insert(ignore_validate=True)

# ❌ NEVER use direct SQL for CRUD
frappe.db.sql("INSERT INTO tabDocType ...")
frappe.db.sql("UPDATE tabDocType SET ...")
frappe.db.sql("DELETE FROM tabDocType ...")
```

#### Legacy Test Patterns
```python
# ❌ NEVER use these base classes
class TestMyFeature(unittest.TestCase):     # No cleanup
class TestMyFeature(FrappeTestCase):        # No factory methods
class TestMyFeature(TestCase):              # Ambiguous

# ❌ NEVER use manual cleanup
def tearDown(self):
    frappe.db.sql("DELETE FROM ...")  # Direct SQL
    # Manual cleanup is error-prone and incomplete
```

## Test Organization Structure

### Current Directory Structure (2025)
```
verenigingen/tests/
├── backend/
│   ├── business_logic/          # ✅ Phase 1 Complete
│   │   ├── test_critical_business_logic.py
│   │   ├── test_fee_functionality.py
│   │   └── test_application_submission.py
│   ├── components/              # ✅ Phase 2 Complete
│   │   ├── test_member_portal_integration.py
│   │   ├── test_sepa_mandate_creation.py
│   │   └── [50+ component tests]
│   ├── integration/             # ✅ Phase 3 Complete
│   │   ├── test_suspension_integration.py  # ✅ Working
│   │   ├── test_member_contact_request_integration.py  # 🚧 Doctype missing
│   │   └── test_volunteer_portal_integration.py
│   ├── workflows/               # ✅ Phase 3 Complete
│   │   ├── test_member_lifecycle_simple.py  # ✅ Working
│   │   ├── test_volunteer_journey.py  # 🚧 Workflow methods missing
│   │   └── test_enhanced_membership_lifecycle.py
│   └── validation/              # Individual validation tests
├── fixtures/                    # Test data factories
│   ├── enhanced_test_factory.py
│   └── test_data_factory.py
├── frontend/                    # JavaScript tests
├── utils/                       # Test utilities and base classes
│   ├── base.py                  # VereningingenTestCase
│   └── test_runner.py
└── workflows/                   # Complex workflow tests
```

### Migration Status

#### ✅ Completed Phases:
- **Phase 1**: Critical business logic tests migrated to VereningingenTestCase
- **Phase 2**: Core component tests migrated with factory methods
- **Phase 3**: Workflow and integration tests migrated and tested

#### 🚧 Ongoing Work:
- **Permission Cleanup**: Remove remaining `ignore_permissions=True` violations
- **DocType Fixes**: Address tests for missing doctypes
- **Complex Workflows**: Fix advanced workflow framework dependencies

## Running Tests

### Test Execution Requirements

**CRITICAL**: Tests must be run via Frappe's test runner, not direct Python execution:

```bash
# ✅ Correct - Use Frappe test runner
bench --site dev.veganisme.net run-tests --app verenigingen --module test_module

# ✅ Run specific test suites
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.business_logic.test_critical_business_logic

# ❌ NEVER - Direct Python execution fails
python test_file.py  # Fails with "ModuleNotFoundError: No module named 'frappe'"
```

### Test Categories

#### Quick Validation (30 seconds)
```bash
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_validation_regression
```

#### Core Functionality (1-2 minutes)
```bash
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_critical_business_logic
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_iban_validator
```

#### Workflow Tests (2-5 minutes)
```bash
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.workflows.test_member_lifecycle_simple
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.backend.integration.test_suspension_integration
```

#### Custom Test Runners
```bash
# Organized test runners from scripts/testing/runners/
python scripts/testing/runners/run_volunteer_portal_tests.py --suite core
python scripts/testing/runners/regression_test_runner.py
```

### Working Test Examples

#### Successfully Migrated Tests:
1. **test_member_lifecycle_simple.py** - ✅ Complete 10-stage lifecycle test
2. **test_suspension_integration.py** - ✅ All 8 integration tests pass
3. **test_critical_business_logic.py** - ✅ Core business logic validation
4. **test_fee_functionality.py** - ✅ Fee calculation and tracking

## Common Issues and Solutions

### Test Failures Due to Validation

#### Problem: Test fails with validation errors
```
frappe.exceptions.ValidationError: Missing required field 'birth_date'
```

#### Solution: Read DocType JSON and provide required fields
```python
# Step 1: Read DocType JSON file to identify required fields
# Step 2: Update factory method or test data

# ✅ Correct approach
member = self.create_test_member(
    first_name="Test",
    last_name="User",
    email="test@example.com",
    birth_date="1990-01-01"  # Required field from JSON
)
```

### Permission Errors

#### Problem: Permission denied errors in tests
```
frappe.exceptions.PermissionError: Not permitted to create Member
```

#### Solution: Use proper test user setup or factory methods
```python
# ✅ Factory methods handle permissions properly
member = self.create_test_member()  # Uses proper user context

# ✅ Or set up proper test user
with self.set_user("test@example.com"):
    # Test operations with specific user
    pass
```

### Database Schema Issues

#### Problem: Unknown column errors
```
pymysql.err.OperationalError: (1054, "Unknown column 'field_name' in 'SELECT'")
```

#### Solution: Check DocType exists and field names are correct
```python
# ✅ Verify DocType exists
if frappe.db.exists("DocType", "DocType Name"):
    # DocType exists, check field names in JSON

# ✅ Use correct field names from DocType JSON
```

## Creating New Tests

### Test Creation Checklist

1. **✅ Read DocType JSON** files for any documents you'll create
2. **✅ Inherit from VereningingenTestCase**
3. **✅ Use factory methods** for test data creation
4. **✅ Let base class handle cleanup** (no manual tearDown)
5. **✅ Use proper field names** from DocType JSON files
6. **✅ Avoid permission violations** (`ignore_permissions=True`)
7. **✅ Test via Frappe test runner** (not direct Python)

### Template for New Tests

```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyNewFeature(VereningingenTestCase):
    """Test suite for my new feature"""

    def setUp(self):
        """Set up test data using factory methods"""
        super().setUp()

        # Create test data using factory methods
        self.test_member = self.create_test_member(
            first_name="TestFeature",
            last_name="User",
            email="testfeature@example.com"
        )
        # Automatic cleanup handled by base class

    def test_feature_creation(self):
        """Test that feature can be created successfully"""
        # Arrange
        initial_count = frappe.db.count("My DocType")

        # Act
        result = create_my_feature(self.test_member.name)

        # Assert
        self.assertTrue(result.get("success"))
        self.assertEqual(frappe.db.count("My DocType"), initial_count + 1)

    def test_feature_validation(self):
        """Test feature validation rules"""
        # Test implementation with proper assertions
        with self.assertRaises(frappe.ValidationError):
            create_invalid_feature()

    def test_feature_edge_cases(self):
        """Test edge cases and error handling"""
        # Edge case testing
        pass

# No manual tearDown needed - automatic cleanup
```

## Best Practices Summary

### Do's ✅
- **Always** inherit from VereningingenTestCase
- **Always** read DocType JSON files before writing tests
- **Always** use factory methods for test data
- **Always** run tests via Frappe test runner
- **Always** use exact field names from DocType JSON
- **Always** let Frappe validation run (no bypassing)

### Don'ts ❌
- **Never** use `ignore_permissions=True` in tests
- **Never** use `ignore_validate=True` in tests
- **Never** use direct SQL for document CRUD
- **Never** guess field names (read JSON first)
- **Never** use manual tearDown methods
- **Never** run tests with direct Python execution

This enhanced testing framework provides robust, maintainable tests that follow Frappe best practices and ensure high code quality across the Verenigingen application.
