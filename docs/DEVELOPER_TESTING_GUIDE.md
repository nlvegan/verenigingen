# Developer Testing Guide

## Overview

This guide covers testing standards and best practices for the Verenigingen application. Tests are organized into domain-specific subdirectories and use two base classes depending on the testing scenario.

## Test Directory Structure

After the Phase 3 reorganization (2026-03-09), tests are organized into domain subdirectories under `verenigingen/tests/`:

```
vereinigingen/tests/
├── payment/              # 62 files -- Mollie, SEPA batches, payment entries, reconciliation
├── member/               # 37 files -- Member lifecycle, approval, merge, status transitions
├── sepa/                 # 32 files -- SEPA mandate, direct debit, XML generation
├── chapter/              # 21 files -- Chapter management, board, assignment, finance
├── security/             # 20 files -- API security, permissions, CSRF, auth
├── donor/                # 18 files -- Donation processing, donor management
├── financial/            # 9 files  -- Billing, invoicing, fee calculations
├── email/                # 9 files  -- Email templates, notifications
├── volunteer/            # 5 files  -- Volunteer portal, assignments
├── backend/              # Categorized backend tests
│   ├── business_logic/   #   Core business rule tests
│   ├── components/       #   Component-level tests
│   ├── comprehensive/    #   Full-coverage suites
│   ├── features/         #   Feature-specific tests
│   ├── integration/      #   Cross-module integration tests
│   ├── optimization/     #   Performance optimization tests
│   ├── performance/      #   Benchmarks and load tests
│   ├── portal/           #   Portal page tests
│   ├── security/         #   Backend security tests
│   ├── unit/             #   Isolated unit tests
│   ├── validation/       # 20 files -- IBAN, field, input validation
│   └── workflows/        #   Workflow state machine tests
├── fixtures/             # Test data factories
│   └── enhanced_test_factory.py  # EnhancedTestDataFactory + EnhancedTestCase
├── utils/                # Test utilities and base classes
│   └── base.py           # VereningingenTestCase
├── api/                  # API endpoint tests
├── contracts/            # API contract tests
├── e_boekhouden/         # eBoekhouden integration tests
├── e2e/                  # End-to-end tests
├── frontend/             # JavaScript/UI tests
├── integration/          # Cross-service integration tests
├── services/             # Service layer tests
├── unit/                 # Isolated unit tests
├── reports/              # Report tests
└── workflows/            # Workflow tests
```

Top-level `tests/` contains 8 cross-cutting files (e.g., `__init__.py`, `base_test_case.py`, test runners).

## Base Classes

### VereningingenTestCase (standard tests)

Use for most tests -- integration tests, UI/form testing, tests requiring extensive mocking:

```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyFeature(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member(
            first_name="Test", last_name="User", email="test@example.com"
        )
        # Document automatically tracked for cleanup

    def test_feature(self):
        self.assertTrue(some_condition)
    # No tearDown needed -- automatic cleanup handled by base class
```

Key features:
- Automatic document cleanup in reverse creation order
- Factory methods for consistent test data
- Customer record cleanup for member-related tests

### EnhancedTestCase (business logic validation)

Use for tests that must catch real production issues -- business rule validation, field safety, data integrity:

```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestCriticalLogic(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Test", last_name="User", email="test@example.com"
        )

    def test_business_rule(self):
        # Field references validated against DocType schemas
        # Business rules enforced (e.g., age validation for volunteers)
        self.assertFieldEqual(self.member, "status", "Active")
```

Key features:
- **Field Validator**: Validates all field references against DocType schemas before document creation
- **Business rule enforcement**: Age validation, required fields, etc.
- **Deterministic generation**: Uses configurable seeds for reproducible test scenarios
- **Faker integration**: Generates realistic but clearly marked test data
- Real database testing without inappropriate mocks

### When to Use Which

| Scenario | Base Class |
|----------|-----------|
| Standard feature tests | `VereningingenTestCase` |
| Integration tests with mocking | `VereningingenTestCase` |
| UI/form testing | `VereningingenTestCase` |
| Business rule validation | `EnhancedTestCase` |
| Field safety validation | `EnhancedTestCase` |
| Production bug discovery | `EnhancedTestCase` |
| Core business logic (Member lifecycle, SEPA) | `EnhancedTestCase` |

## Factory Methods

Both base classes provide factory methods for creating test data:

```python
# Member
member = self.create_test_member(
    first_name="John", last_name="Doe",
    email="john.doe@example.com", birth_date="1990-01-01"
)

# Volunteer (linked to member)
volunteer = self.create_test_volunteer(
    member=member.name,
    volunteer_name=member.full_name,
    email=member.email
)

# Chapter (auto-creates region)
chapter = self.create_test_chapter(
    chapter_name="Test Chapter",
    postal_codes="1000-9999"
)

# Membership (can control submission status)
membership = self.create_test_membership(
    member=member.name,
    membership_type="Standard",
    docstatus=1
)
```

### Mock Banking Support

```python
from verenigingen.utils.iban_validator import generate_test_iban

# Generate valid test IBANs with proper MOD-97 checksums
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

## Running Tests

**Tests must be run via Frappe's test runner, not direct Python execution.**

```bash
cd ~/frappe-bench

# Run all tests for the app
bench --site veg11.veganisme.org run-tests --app verenigingen

# Run a specific domain directory
bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.member

# Run a specific test file
bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.payment.test_mollie_payment

# Run tests for a DocType
bench --site veg11.veganisme.org run-tests --doctype "Member"

# Run parallel tests for faster execution
bench --site veg11.veganisme.org run-parallel-tests --app verenigingen
```

### Custom Test Runners

```bash
cd ~/frappe-bench/apps/verenigingen
./run_controller_tests.sh       # Run controller tests
./run_mollie_e2e_tests.sh       # Run Mollie integration tests
```

## Mandatory Test Patterns

### Use Factory Methods (not manual document creation)

```python
# CORRECT -- factory method with automatic cleanup
member = self.create_test_member(first_name="Test", email="test@example.com")

# WRONG -- manual creation, no cleanup, missing fields
member = frappe.get_doc({"doctype": "Member", "first_name": "Test"})
member.insert(ignore_permissions=True)
```

### Read DocType JSON Before Writing Tests

Always check the DocType JSON to identify required fields (`"reqd": 1`) and exact field names before writing test code.

### Let Frappe Validate

```python
# CORRECT
doc = frappe.new_doc("Member")
doc.field = "value"
doc.save()  # Frappe validation runs

# WRONG
doc.save(ignore_validate=True)
doc.insert(ignore_permissions=True)
frappe.db.sql("INSERT INTO ...")
```

### Track Custom Documents

```python
# Factory methods auto-track. For custom documents:
custom_doc = frappe.get_doc({...})
custom_doc.insert()
self.track_doc("DocType", custom_doc.name)  # Manual tracking
```

## Forbidden Patterns

```python
# NEVER use these in tests:
doc.insert(ignore_permissions=True)
doc.save(ignore_permissions=True)
doc.save(ignore_validate=True)
frappe.db.sql("INSERT INTO tabDocType ...")
frappe.db.sql("UPDATE tabDocType SET ...")
frappe.db.sql("DELETE FROM tabDocType ...")
```

The `test-quality-enforcer` and `block-inappropriate-mocks` pre-commit hooks will reject:
- Inappropriate business logic mocking
- Mock abuse patterns
- Tests that bypass validation

## Writing New Tests

### Template

```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyNewFeature(VereningingenTestCase):
    """Test suite for my new feature."""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member(
            first_name="TestFeature",
            last_name="User",
            email="testfeature@example.com"
        )

    def test_feature_creation(self):
        """Test that feature can be created successfully."""
        initial_count = frappe.db.count("My DocType")
        result = create_my_feature(self.test_member.name)
        self.assertTrue(result.get("success"))
        self.assertEqual(frappe.db.count("My DocType"), initial_count + 1)

    def test_feature_validation(self):
        """Test feature validation rules."""
        with self.assertRaises(frappe.ValidationError):
            create_invalid_feature()
```

### Where to Put New Tests

Place new test files in the appropriate domain subdirectory:

| Domain | Directory | Examples |
|--------|-----------|---------|
| Member lifecycle, approval | `tests/member/` | Signup, merge, status |
| Payments, Mollie | `tests/payment/` | Payment entries, reconciliation |
| SEPA mandates, batches | `tests/sepa/` | Mandate creation, XML export |
| Chapter management | `tests/chapter/` | Board, assignments, finance |
| Donations | `tests/donor/` | Donor CRUD, reporting |
| Email/notifications | `tests/email/` | Templates, delivery |
| Volunteer management | `tests/volunteer/` | Assignments, portal |
| Security/permissions | `tests/security/` | Auth, CSRF, API guards |
| Financial/billing | `tests/financial/` | Invoices, fees |
| IBAN, field validation | `tests/backend/validation/` | Validators |
| Cross-module integration | `tests/backend/integration/` | Multi-service flows |
| eBoekhouden | `tests/e_boekhouden/` | Accounting sync |

### Checklist

1. Read DocType JSON files for any documents you will create
2. Inherit from `VereningingenTestCase` or `EnhancedTestCase`
3. Use factory methods for test data creation
4. Let the base class handle cleanup (no manual tearDown)
5. Use exact field names from DocType JSON files
6. Do not bypass permissions or validation
7. Run tests via Frappe test runner (not direct Python)

## Common Issues and Solutions

### Validation Error: Missing Required Field

```
frappe.exceptions.ValidationError: Missing required field 'birth_date'
```

Read the DocType JSON and provide all required fields to the factory method.

### Permission Denied

```
frappe.exceptions.PermissionError: Not permitted to create Member
```

Use factory methods (they handle permissions) or set up a proper test user context.

### Unknown Column

```
pymysql.err.OperationalError: (1054, "Unknown column 'field_name'")
```

Check that the DocType exists and field names match the JSON schema exactly.

## Related Documentation

- `docs/development/ERROR_HANDLING_CONVENTIONS.md` -- Error handling patterns
- `docs/development/SERVICE_INFRASTRUCTURE_USAGE_GUIDE.md` -- Service layer usage
- `CLAUDE.md` -- Transaction handling, coding standards, naming conventions
