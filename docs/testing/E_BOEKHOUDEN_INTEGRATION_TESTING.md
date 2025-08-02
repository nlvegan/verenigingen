# E-Boekhouden Migration Integration Testing Guide

This document provides comprehensive guidance for testing the E-Boekhouden migration pipeline integration system.

## Overview

The E-Boekhouden integration tests validate the complete migration pipeline from security permissions to payment processing and data integrity. These tests use realistic data generation and respect Frappe's validation system without bypassing security or validation checks.

## Test Architecture

### Test Categories

1. **Security Permission Tests** (`TestEBoekhoudenSecurityIntegration`)
   - Tests the security_helper.py module
   - Validates migration_context functionality
   - Tests validate_and_insert/validate_and_save functions
   - Verifies permission checks and user switching
   - Tests audit logging and cleanup operations

2. **Payment Processing Tests** (`TestPaymentProcessingIntegration`)
   - Tests PaymentEntryHandler with realistic API data
   - Validates bank account determination logic
   - Tests multi-invoice payment allocation strategies
   - Verifies API row ledger data priority
   - Tests error handling and edge cases

3. **Migration Pipeline Tests** (`TestMigrationPipelineIntegration`)
   - Tests complete end-to-end migration workflows
   - Validates transaction atomicity
   - Tests document creation with proper permissions
   - Verifies progress tracking and error handling
   - Tests event-driven payment history updates

4. **Data Integrity Tests** (`TestDataIntegrityAndEdgeCases`)
   - Validates idempotency of migration operations
   - Tests edge cases and error recovery
   - Verifies data consistency validation
   - Tests duplicate entry handling
   - Validates data corruption prevention

5. **Performance Tests** (`TestPerformanceAndScalability`)
   - Tests batch operation performance
   - Validates memory usage during large operations
   - Tests concurrent operation simulation
   - Measures performance benchmarks

### Test Data Strategy

#### Enhanced Test Factory Usage

All tests use the Enhanced Test Factory pattern:

```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestMyFeature(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.test_company = self._ensure_test_company()

    def test_something(self):
        # Factory available via self.factory
        member = self.create_test_member(
            first_name="Test",
            last_name="User",
            birth_date="1990-01-01"
        )
```

#### Realistic Data Generation

- **No Mocking**: Tests use actual system behavior with realistic data
- **Business Rule Compliance**: All generated data respects validation rules
- **Deterministic**: Uses seeds for reproducible test scenarios
- **Edge Case Coverage**: Tests boundary conditions with realistic variations

#### Security Compliance

- **No `ignore_permissions=True`**: Uses proper role-based permissions
- **No `ignore_validate=True`**: Respects all validation rules
- **No Direct SQL**: Uses Frappe ORM for all document operations
- **Proper Error Handling**: Tests actual error scenarios, not bypassed ones

## Running the Tests

### Prerequisites

1. **Environment Setup**:
   ```bash
   # Ensure you're in the Frappe environment
   cd /home/frappe/frappe-bench

   # Activate the environment
   source env/bin/activate
   ```

2. **Required DocTypes**: Tests validate these exist:
   - E-Boekhouden Migration
   - E-Boekhouden Ledger Mapping
   - Company, Account, Customer, Supplier
   - Payment Entry, Sales Invoice, Purchase Invoice

3. **Test Data**: Basic test data is created automatically

### Execution Methods

#### 1. Complete Test Suite

```bash
# Run all integration tests
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests

# Run with verbose output and save report
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --verbose --report-file integration_test_report.json
```

#### 2. Individual Test Suites

```bash
# Run security tests only
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite security

# Run payment processing tests
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite payment

# Run pipeline tests
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite pipeline

# Run integrity tests
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite integrity

# Run performance tests
bench --site dev.veganisme.net execute scripts.testing.run_e_boekhouden_integration_tests --suite performance
```

#### 3. Native Frappe Testing

```bash
# Run specific test class
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_e_boekhouden_migration_integration.TestEBoekhoudenSecurityIntegration

# Run complete integration test module
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_e_boekhouden_migration_integration
```

#### 4. Python Direct Execution

```bash
# From project root (for development/debugging)
cd /home/frappe/frappe-bench/apps/verenigingen
python scripts/testing/run_e_boekhouden_integration_tests.py --suite all --verbose
```

### Test Options

- `--suite [security|payment|pipeline|integrity|performance|all]`: Select test suite
- `--verbose`: Detailed output during test execution
- `--report-file [filename]`: Save detailed JSON report
- `--setup-test-data`: Setup additional test data before running
- `--cleanup-after`: Clean up test data after completion

## Test Implementation Details

### Security Permission Testing

Tests the new security framework that replaces `ignore_permissions=True`:

```python
def test_migration_context_permission_validation(self):
    """Test migration_context properly validates permissions"""
    with migration_context("account_creation"):
        account = frappe.new_doc("Account")
        account.account_name = "TEST Migration Account"
        account.company = self.test_company
        account.account_type = "Asset"
        account.is_group = 1
        account.insert()  # No ignore_permissions needed!
```

### Payment Processing Testing

Tests realistic E-Boekhouden API data patterns:

```python
def test_customer_payment_processing_single_invoice(self):
    """Test processing customer payment for single invoice"""
    mutation_data = {
        "id": 12345,
        "type": 3,  # Customer payment
        "date": nowdate(),
        "amount": 100.00,
        "relationId": "CUST001",
        "invoiceNumber": self.test_sales_invoice,
        "ledgerId": 1001,  # Bank account
        "rows": [{
            "ledgerId": 1300,  # Receivable account
            "amount": 100.00,
            "description": "Customer payment"
        }]
    }

    payment_entry_name = self.handler.process_payment_mutation(mutation_data)
    # Validates complete payment processing workflow
```

### Data Integrity Testing

Tests edge cases and error scenarios:

```python
def test_idempotent_migration_operations(self):
    """Test that migration operations are idempotent"""
    # Create account first time
    account1 = self._create_account("TEST Idempotent Account")

    # Try to create same account again
    account2 = self._create_account("TEST Idempotent Account")

    # Should handle gracefully (different name or proper error)
    self.assertNotEqual(account2.name, account1.name)
```

### Performance Testing

Tests scalability and performance:

```python
def test_batch_operations_performance(self):
    """Test performance of batch operations"""
    accounts = [self._create_account_doc(f"PERF Account {i}") for i in range(20)]

    start_time = now_datetime()
    inserted_accounts = batch_insert(accounts, "account_creation", batch_size=5)
    duration = (now_datetime() - start_time).total_seconds()

    # Performance assertion
    self.assertLess(duration, 30.0)
    self.assertEqual(len(inserted_accounts), 20)
```

## Test Data Patterns

### Realistic E-Boekhouden Mutation Data

The tests include utilities for generating realistic API data:

```python
def create_realistic_eboekhouden_mutation_data(mutation_type: int = 3) -> Dict[str, Any]:
    """Create realistic E-Boekhouden mutation data for testing"""
    return {
        "id": random.randint(10000, 99999),
        "type": mutation_type,
        "date": (datetime.now() - timedelta(days=random.randint(0, 30))).strftime("%Y-%m-%d"),
        "amount": round(random.uniform(50.0, 500.0), 2),
        "relationId": f"REL{random.randint(1000, 9999)}",
        "invoiceNumber": ",".join([f"INV-{random.randint(1000, 9999)}" for _ in range(random.randint(1, 3))]),
        "rows": [
            {
                "ledgerId": random.randint(1300, 1400),
                "amount": random.uniform(10.0, 100.0),
                "description": f"Payment detail {i+1}"
            }
            for i in range(random.randint(1, 3))
        ]
    }
```

### Test Company Setup

Each test class creates isolated test companies:

```python
def _ensure_test_company(self):
    """Ensure test company exists with proper setup"""
    company_name = "TEST-EBoekhouden-Integration-Company"

    if not frappe.db.exists("Company", company_name):
        company = frappe.new_doc("Company")
        company.company_name = company_name
        company.abbr = "TEBIC"
        company.default_currency = "EUR"
        company.country = "Netherlands"
        # Set up default accounts...
        company.insert()

    return company_name
```

## Expected Test Results

### Success Criteria

1. **All Security Tests Pass**: Permission validation and user switching work correctly
2. **Payment Processing Works**: Realistic API data is processed correctly
3. **Pipeline Integration Works**: End-to-end workflows complete successfully
4. **Data Integrity Maintained**: No corruption, proper validation, idempotency
5. **Performance Acceptable**: Batch operations complete within reasonable time

### Performance Benchmarks

- **Batch Account Creation**: 20 accounts in < 30 seconds
- **Payment Processing**: Complex mutations processed < 10 seconds
- **Memory Usage**: Stable during large batch operations
- **Concurrent Operations**: Multiple operations complete successfully

### Common Issues and Solutions

#### 1. Permission Errors

**Issue**: Tests fail with permission errors
**Solution**: Ensure test user has required roles (Accounts Manager, System Manager)

```python
# Add required roles to test user
roles = ["Accounts Manager", "System Manager", "Accounts User"]
for role in roles:
    user.append("roles", {"role": role})
user.save()
```

#### 2. Validation Failures

**Issue**: Document creation fails validation
**Solution**: Use Enhanced Test Factory to generate compliant data

```python
# Use factory instead of manual creation
member = self.create_test_member(
    first_name="Test",
    last_name="User",
    birth_date="1990-01-01"  # Complies with age validation
)
```

#### 3. Missing DocTypes

**Issue**: Required DocTypes don't exist
**Solution**: Ensure all E-Boekhouden modules are installed

```bash
# Install/update the app
bench --site dev.veganisme.net install-app verenigingen
bench --site dev.veganisme.net migrate
```

#### 4. Test Data Conflicts

**Issue**: Tests interfere with each other
**Solution**: Use unique naming with test run IDs

```python
# Enhanced Test Factory automatically handles this
account_name = f"TEST Account {self.factory.get_next_sequence('account')}"
```

## Maintenance and Extension

### Adding New Test Cases

1. **Follow Enhanced Test Factory Pattern**:
   ```python
   class TestNewFeature(EnhancedTestCase):
       def setUp(self):
           super().setUp()
           # Setup test prerequisites

       def test_new_functionality(self):
           # Use self.factory for data creation
           # Use proper validation and permissions
           # Test realistic scenarios
   ```

2. **Add to Test Runner**:
   ```python
   # In run_e_boekhouden_integration_tests.py
   self.test_suites = {
       "security": TestEBoekhoudenSecurityIntegration,
       "payment": TestPaymentProcessingIntegration,
       "pipeline": TestMigrationPipelineIntegration,
       "integrity": TestDataIntegrityAndEdgeCases,
       "performance": TestPerformanceAndScalability,
       "new_feature": TestNewFeature,  # Add here
   }
   ```

### Updating for New Features

1. **Security Changes**: Update `TestEBoekhoudenSecurityIntegration`
2. **Payment Processing**: Update `TestPaymentProcessingIntegration`
3. **Migration Workflow**: Update `TestMigrationPipelineIntegration`
4. **Data Models**: Update data integrity tests
5. **Performance Requirements**: Update performance benchmarks

### Test Data Evolution

As the system evolves, update test data patterns:

1. **New DocType Fields**: Update Enhanced Test Factory field defaults
2. **New Business Rules**: Add validation tests
3. **New API Patterns**: Update realistic data generators
4. **New Error Scenarios**: Add edge case tests

## Integration with CI/CD

### Automated Testing

```bash
# Add to CI pipeline
bench --site $SITE_NAME execute scripts.testing.run_e_boekhouden_integration_tests --report-file ci_report.json
```

### Test Quality Gates

1. **All Integration Tests Must Pass**: No failures allowed
2. **Performance Benchmarks**: Must meet time/memory requirements
3. **Coverage Requirements**: Key workflows must be tested
4. **No Security Bypasses**: No `ignore_permissions=True` in new code

### Monitoring and Alerting

- **Failed Test Notifications**: Alert on test failures
- **Performance Regressions**: Alert on benchmark violations
- **Test Environment Health**: Monitor test data and system state

## Conclusion

This comprehensive integration testing framework ensures the E-Boekhouden migration pipeline works correctly with realistic data and proper security. The tests provide confidence that the system will work in production while maintaining data integrity and security standards.

Key principles:
- **Realistic Data**: Tests use actual business scenarios
- **No Security Bypasses**: Proper permissions and validation
- **Comprehensive Coverage**: All critical paths tested
- **Performance Validation**: Scalability requirements verified
- **Maintainable**: Clear patterns for extension and maintenance
