# SEPA Mandate Service Unit Tests

Comprehensive unit test suite for the SEPA Mandate services, focusing on testing individual service methods in isolation with realistic data generation and minimal dependency on mocks.

## Overview

This test suite provides thorough coverage of the four core SEPA Mandate services:

1. **SEPAMandateIdentityService** - Mandate ID generation and validation
2. **SEPAMandateValidationService** - Business rule validation and IBAN processing
3. **SEPAMandateLifecycleService** - Status management and workflow transitions
4. **SEPAMandateMemberIntegrationService** - Member-mandate relationship management

## Test Philosophy

### Realistic Data Generation Over Mocking

These tests prioritize **realistic data generation** and **actual business logic testing** rather than extensive mocking:

- Uses Enhanced Test Factory for Dutch association data
- Tests with valid Dutch IBANs and realistic member scenarios
- Generates test data that respects business rules and validation constraints
- Mocks only external dependencies (database, notifications, framework calls)

### Business Logic Focus

Tests validate actual service logic rather than framework integration:

- **Field validation** using real DocType schemas
- **Date calculations** with realistic scenarios
- **Business rule enforcement** with edge cases
- **Status transitions** following actual workflow rules

## Test Files and Coverage

### 1. SEPAMandateIdentityService Tests
**File**: `verenigingen/tests/test_sepa_mandate_identity_service.py`

**Coverage**:
- `generate_mandate_id()` with custom and default patterns
- `_generate_mandate_id_with_counter()` logic and date token replacement
- `validate_mandate_reference()` format validation (SEPA compliance)
- `ensure_mandate_uniqueness()` duplicate detection
- Settings caching and error handling

**Key Test Scenarios**:
```python
def test_generate_mandate_id_with_custom_pattern(self):
    # Tests Dutch association patterns like "VEG-{YYYY}-{MM}-{DD}-###"

def test_generate_mandate_id_with_counter_existing_mandates(self):
    # Tests counter increment based on existing mandates

def test_validate_mandate_reference_sepa_compliance(self):
    # Tests SEPA mandate reference format compliance
```

### 2. SEPAMandateValidationService Tests
**File**: `verenigingen/tests/test_sepa_mandate_validation_service.py`

**Coverage**:
- `validate_mandate_dates()` with various date scenarios
- `validate_mandate_iban()` with Dutch IBAN validation and BIC derivation
- `validate_mandate_business_rules()` constraint checking
- `validate_mandate_uniqueness()` conflict detection

**Key Test Scenarios**:
```python
def test_validate_mandate_iban_valid_dutch_iban(self):
    # Tests with realistic Dutch bank IBANs (ING, Rabobank, etc.)

def test_validate_mandate_business_rules_ooff_mandate_long_validity(self):
    # Tests one-off mandate business rules (30-day validity warning)

def test_realistic_dutch_mandate_validation(self):
    # End-to-end validation with realistic Dutch member data
```

### 3. SEPAMandateLifecycleService Tests
**File**: `verenigingen/tests/test_sepa_mandate_lifecycle_service.py`

**Coverage**:
- `set_status_based_on_dates()` automatic status calculation
- `handle_status_transition()` workflow validation
- `process_mandate_cancellation()` cancellation workflow
- `sync_status_and_active_flag()` consistency management
- Event handling: `handle_mandate_creation()` and `handle_mandate_update()`

**Key Test Scenarios**:
```python
def test_set_status_based_on_dates_expired_mandate(self):
    # Tests automatic expiration based on dates

def test_is_valid_status_transition_matrix(self):
    # Tests all valid/invalid status transition combinations

def test_complete_mandate_lifecycle_workflow(self):
    # Tests Draft -> Active -> Cancelled workflow
```

### 4. SEPAMandateMemberIntegrationService Tests
**File**: `verenigingen/tests/test_sepa_mandate_member_integration_service.py`

**Coverage**:
- `update_member_mandate_relationship()` core integration logic
- `_validate_sepa_mandate_permissions()` security validation
- `_validate_mandate_link_fields()` field existence validation
- `_execute_secure_mandate_link_update()` database operations
- `bulk_update_member_mandates()` bulk operations
- Audit logging and error handling

**Key Test Scenarios**:
```python
def test_execute_secure_mandate_link_update_existing_link(self):
    # Tests SQL operations for updating existing member-mandate links

def test_validate_sepa_mandate_permissions_with_resolver(self):
    # Tests security validation with clean permission resolver

def test_realistic_dutch_member_integration(self):
    # Tests with realistic Dutch association member data
```

## Running the Tests

### Test Runner Script
Use the comprehensive test runner for various execution modes:

```bash
# Run all SEPA service tests
python verenigingen/tests/run_sepa_service_tests.py --all

# Run specific service tests
python verenigingen/tests/run_sepa_service_tests.py --identity
python verenigingen/tests/run_sepa_service_tests.py --validation
python verenigingen/tests/run_sepa_service_tests.py --lifecycle
python verenigingen/tests/run_sepa_service_tests.py --integration

# Run with verbose output
python verenigingen/tests/run_sepa_service_tests.py --all --verbose

# Run with coverage (when available)
python verenigingen/tests/run_sepa_service_tests.py --all --coverage
```

### Individual Test Execution
Run individual test files using Python unittest:

```bash
# Run specific test file
python -m unittest verenigingen.tests.test_sepa_mandate_identity_service

# Run specific test class
python -m unittest verenigingen.tests.test_sepa_mandate_identity_service.TestSEPAMandateIdentityService

# Run specific test method
python -m unittest verenigingen.tests.test_sepa_mandate_identity_service.TestSEPAMandateIdentityService.test_generate_mandate_id_with_custom_pattern
```

### Frappe Environment Execution
For full integration with Frappe framework:

```bash
# Run through Frappe bench
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_sepa_mandate_identity_service

# Execute test runner through Frappe
bench --site dev.veganisme.net execute verenigingen.tests.run_sepa_service_tests.main
```

## Test Data and Scenarios

### Realistic Dutch Association Data

Tests use realistic data patterns for Dutch associations:

- **Member Names**: Include tussenvoegsel (van, de, der, etc.)
- **IBANs**: Valid Dutch bank IBANs (ING, Rabobank, ABN AMRO, etc.)
- **BIC Codes**: Accurate BIC derivation from IBAN bank codes
- **Mandate IDs**: Dutch naming patterns like `VEG-2024-001`, `ROOD-2409-001`
- **Dates**: Realistic scenarios including weekends, holidays, year boundaries

### Edge Cases and Business Rules

- **Age Validation**: Members must be 16+ for volunteer roles
- **Date Constraints**: Sign dates cannot be in future, expiry validation
- **SEPA Compliance**: Mandate reference format validation
- **Status Transitions**: Only valid workflow transitions allowed
- **Uniqueness**: Mandate ID uniqueness across the system
- **Permission Validation**: Proper access control for member data

## Mock Strategy

### What We Mock
- **External Services**: Database operations, notifications, logging
- **Framework Calls**: Frappe-specific methods and utilities
- **Time-Dependent Operations**: Date/time functions for predictable tests

### What We Don't Mock
- **Business Logic**: Actual service methods and validation logic
- **Data Structures**: Real DocType field validation and constraints
- **Calculations**: Date calculations, counter increments, format validation

## Performance Considerations

### Test Performance
- **Fast Execution**: Minimal database interaction through mocking
- **Isolated Tests**: Each test runs independently with clean state
- **Efficient Mocking**: Only mock what's necessary for isolation

### Query Monitoring
```python
def test_database_performance(self):
    with self.assertQueryCount(5):  # Monitor database queries
        result = self.service.update_member_mandate_relationship(mandate)
```

## Integration with Testing Infrastructure

### Enhanced Test Factory Integration
```python
class TestMyService(EnhancedTestCase):
    def test_with_realistic_data(self):
        # Automatic field validation and business rule enforcement
        member = self.create_test_member(
            first_name="Jan",
            last_name="van der Berg",  # Dutch tussenvoegsel
            birth_date="1990-01-01"
        )
```

### Continuous Integration
- Tests run as part of the comprehensive test suite
- Coverage reporting when coverage tools are available
- Performance benchmarking for service methods
- Automatic validation of realistic data scenarios

## Error Handling and Edge Cases

### Exception Testing
- Network timeouts and database connection failures
- Invalid data input and malformed requests
- Permission denied scenarios
- Concurrent access and race conditions

### Boundary Testing
- Date boundaries (year changes, leap years)
- Maximum field lengths and data limits
- Counter overflow and wraparound scenarios
- Status transition edge cases

## Documentation and Maintenance

### Test Documentation
- Each test file includes comprehensive docstrings
- Test methods have descriptive names explaining the scenario
- Complex test scenarios include inline comments
- Edge cases are documented with business context

### Maintenance Guidelines
- Add new tests when adding service methods
- Update existing tests when business rules change
- Ensure realistic data patterns match production usage
- Maintain mock boundaries to preserve business logic testing

## Best Practices

### Test Design
1. **Test One Thing**: Each test method focuses on a single scenario
2. **Descriptive Names**: Test names clearly describe the scenario being tested
3. **Realistic Data**: Use data that resembles production scenarios
4. **Minimal Mocking**: Mock only external dependencies

### Data Generation
1. **Business Rule Compliance**: Generated data must respect all business rules
2. **Deterministic**: Same test should produce same results every time
3. **Edge Case Coverage**: Include boundary conditions and unusual scenarios
4. **Dutch Context**: Data patterns appropriate for Dutch associations

### Error Scenarios
1. **Graceful Failure**: Test that services handle errors appropriately
2. **Error Messages**: Validate that error messages are helpful and accurate
3. **State Consistency**: Ensure partial failures don't leave inconsistent state
4. **Audit Trail**: Verify that operations are properly logged for compliance

This comprehensive test suite ensures that SEPA Mandate services maintain high reliability and correctness while supporting the complex needs of Dutch association management.
