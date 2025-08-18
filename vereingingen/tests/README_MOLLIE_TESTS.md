# Mollie Backend API Test Suite

This comprehensive test suite validates the Mollie Backend API integration with a focus on realistic data generation and testing the specific bug fixes that were implemented.

## Overview

The test suite consists of 6 main test modules with **72 test methods** across **14 test classes** that provide comprehensive coverage of:

### Critical Bug Fixes Tested

1. **Timezone Comparison Fix**: Tests timezone-aware date comparison in revenue analysis that was causing crashes
2. **Settlements Caching**: Tests the caching mechanism that prevents redundant API calls
3. **API Parameter Filtering**: Tests in-memory filtering instead of unsupported date parameters
4. **Encryption Key Storage**: Tests encryption key storage for Single DocTypes
5. **Webhook Signature Validation**: Tests webhook signature validation security
6. **Decimal Conversion Accuracy**: Tests decimal to float conversion accuracy

### Edge Cases Covered

- Empty settlements data handling
- Malformed API response resilience
- Mixed timezone format handling
- Extreme settlement amounts
- Unicode and special character support
- API error scenarios (400, 429, 500, etc.)
- Concurrent access thread safety

## Test Modules

### 1. `test_mollie_api_data_factory.py`

**Purpose**: Realistic test data generation factory

**Key Features**:
- Generates Mollie API response data matching exact formats
- Handles timezone variations that were causing bugs
- Creates edge case scenarios for testing
- Provides deterministic data generation with seeds

**Example Usage**:
```python
from verenigingen.tests.test_mollie_api_data_factory import MollieApiDataFactory

factory = MollieApiDataFactory(seed=42)
settlement = factory.generate_settlement_data(status="paidout")
print(f"Generated settlement: {settlement['id']}")
```

### 2. `test_mollie_financial_dashboard.py`

**Purpose**: Tests for FinancialDashboard with focus on timezone and caching fixes

**Key Test Classes**:
- `TestMollieFinancialDashboard`: Core dashboard functionality
- `TestMollieFinancialDashboardApiEndpoints`: API endpoint testing
- `TestMollieFinancialDashboardPerformance`: Performance validation

**Critical Tests**:
- `test_timezone_aware_revenue_analysis()`: Tests the timezone comparison fix
- `test_settlements_data_caching()`: Tests caching prevents redundant API calls
- `test_empty_settlements_data_handling()`: Tests graceful empty data handling

### 3. `test_mollie_api_clients.py`

**Purpose**: Tests for API clients with focus on parameter handling fixes

**Key Test Classes**:
- `TestMollieSettlementsClient`: Settlements API client testing
- `TestMollieChargebacksClient`: Chargebacks API client testing
- `TestMollieBalancesClient`: Balances API client testing
- `TestMollieApiClientErrorHandling`: Error handling across clients
- `TestMollieApiClientIntegration`: Integration testing

**Critical Tests**:
- `test_list_settlements_without_date_parameters()`: Tests fix for unsupported API parameters
- `test_in_memory_date_filtering_with_settled_at()`: Tests in-memory filtering
- `test_timezone_handling_in_date_filtering()`: Tests timezone parsing fixes

### 4. `test_mollie_security_manager.py`

**Purpose**: Tests for security manager with focus on encryption and key storage fixes

**Key Test Classes**:
- `TestMollieSecurityManager`: Core security functionality
- `TestMollieSecurityManagerEdgeCases`: Edge cases and error scenarios
- `TestMollieSecurityManagerFallbackCleanup`: Fallback key management

**Critical Tests**:
- `test_encryption_key_creation_for_single_doctype()`: Tests Single DocType storage fix
- `test_webhook_signature_validation_success()`: Tests webhook security
- `test_api_key_rotation_success()`: Tests zero-downtime key rotation

### 5. `test_mollie_edge_cases_integration.py`

**Purpose**: Integration tests and edge case validation

**Key Test Classes**:
- `TestMollieEdgeCasesIntegration`: Cross-component integration
- `TestMollieApiParameterValidation`: Parameter validation

**Critical Tests**:
- `test_timezone_handling_across_components()`: Tests consistent timezone handling
- `test_malformed_settlement_data_resilience()`: Tests resilience against bad data
- `test_unicode_and_special_characters()`: Tests Unicode support

### 6. `test_mollie_comprehensive_suite.py`

**Purpose**: Test runner and comprehensive reporting

**Key Features**:
- Executes all test modules in sequence
- Provides detailed performance metrics
- Validates critical fix coverage
- Generates comprehensive reports

## Running the Tests

### Through Frappe Test Framework

```bash
# Run all Mollie tests
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_mollie_comprehensive_suite

# Run specific test module
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_mollie_financial_dashboard

# Run with verbose output
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_mollie_financial_dashboard --verbose
```

### Using the Comprehensive Suite

```python
# In Frappe console or script
from verenigingen.tests.test_mollie_comprehensive_suite import run_mollie_tests

# Run all tests with reporting
success = run_mollie_tests(verbose=True)
print(f"All tests passed: {success}")
```

### Direct Module Testing

```python
# Test specific functionality
from verenigingen.tests.test_mollie_api_data_factory import MollieApiDataFactory
from verenigingen.tests.test_mollie_financial_dashboard import TestMollieFinancialDashboard

# Create test instance
test_case = TestMollieFinancialDashboard()
test_case.setUp()

# Run specific test
test_case.test_timezone_aware_revenue_analysis()
```

## Test Data and Mocking Strategy

### Realistic Data Generation

The test suite prioritizes **realistic data over brittle mocks**:

- **Real API Response Formats**: Test data matches exact Mollie API response structures
- **Proper Timezone Handling**: Generates various timezone formats that were causing issues
- **Edge Case Scenarios**: Creates realistic edge cases rather than artificial test conditions
- **Deterministic Generation**: Uses seeds for reproducible test runs

### Mock Usage Guidelines

**When We Mock**:
- External API calls (to avoid hitting real Mollie API)
- Database operations (for isolated unit testing)
- System resources (file system, network)

**When We Don't Mock**:
- Internal business logic
- Data transformation and calculations
- Validation rules and constraints
- Date parsing and timezone handling

### Example: Realistic vs. Mocked Data

```python
# ✅ Good: Realistic data that exercises actual business logic
settlement_data = {
    "id": "stl_abc123",
    "status": "paidout",
    "settledAt": "2025-08-01T13:00:00Z",  # Real timezone format
    "amount": {"value": "1643.82", "currency": "EUR"},  # Real decimal format
    "periods": {
        "2025-08": {
            "revenue": [...],  # Real nested structure
            "costs": [...]
        }
    }
}

# ❌ Avoid: Oversimplified mocks that bypass business logic
mock_settlement = Mock()
mock_settlement.amount = 1000  # Bypasses decimal handling
mock_settlement.get_revenue.return_value = 500  # Bypasses calculation logic
```

## Performance Benchmarks

### Expected Performance

- **Individual Tests**: < 0.1 seconds per test method
- **Complete Suite**: < 30 seconds for all 72 tests
- **Memory Usage**: < 100MB for large dataset tests (1000+ settlements)
- **Cache Performance**: Cached calls should be 2x+ faster than initial calls

### Performance Tests

```python
# Large dataset performance test
def test_large_dataset_performance(self):
    # Process 100 settlements
    start_time = time.time()
    summary = self.dashboard.get_dashboard_summary()
    processing_time = time.time() - start_time

    # Should complete within 5 seconds
    self.assertLess(processing_time, 5.0)
```

## Continuous Integration

### Pre-commit Validation

```bash
# Add to .pre-commit-config.yaml
- repo: local
  hooks:
    - id: mollie-tests
      name: Mollie Backend API Tests
      entry: python -m verenigingen.tests.test_mollie_comprehensive_suite
      language: system
      pass_filenames: false
```

### CI Pipeline Integration

```yaml
# Example GitHub Actions workflow
- name: Run Mollie Tests
  run: |
    bench --site test.site run-tests --module verenigingen.tests.test_mollie_comprehensive_suite

- name: Check Test Coverage
  run: |
    python -c "from verenigingen.tests.test_mollie_comprehensive_suite import run_mollie_tests; assert run_mollie_tests()"
```

## Troubleshooting

### Common Issues

1. **Import Errors**
   ```bash
   # Ensure Frappe environment is activated
   source /home/frappe/frappe-bench/env/bin/activate
   ```

2. **Timezone Test Failures**
   ```python
   # Check system timezone settings
   import datetime
   print(datetime.datetime.now().astimezone().tzinfo)
   ```

3. **Mock Configuration Issues**
   ```python
   # Reset mocks between tests
   def setUp(self):
       self.mock_client.reset_mock()
   ```

### Debug Mode

```python
# Enable debug logging for tests
import logging
logging.basicConfig(level=logging.DEBUG)

# Run tests with debug output
results = runner.run_comprehensive_suite(verbose=True)
```

## Contributing

### Adding New Tests

1. **Follow Naming Convention**: `test_specific_functionality_description()`
2. **Use Realistic Data**: Leverage `MollieApiDataFactory` for test data
3. **Test Edge Cases**: Include error scenarios and boundary conditions
4. **Document Critical Fixes**: Add comments explaining what bugs are being prevented
5. **Performance Considerations**: Ensure tests complete quickly

### Test Structure Template

```python
class TestNewMollieFeature(FrappeTestCase):
    """
    Test suite for new Mollie feature

    Tests the critical functionality and edge cases for [feature name].
    Focuses on preventing regression of [specific bug or issue].
    """

    def setUp(self):
        """Set up test environment with realistic data"""
        self.factory = MollieApiDataFactory(seed=42)
        # Setup mocks and test data

    def test_core_functionality(self):
        """Test the main feature functionality"""
        # Use realistic data from factory
        test_data = self.factory.generate_test_data()

        # Test actual business logic (minimal mocking)
        result = feature.process(test_data)

        # Assert specific outcomes
        self.assertEqual(result.status, "success")

    def test_edge_case_scenario(self):
        """Test specific edge case that was causing issues"""
        # Create edge case data
        edge_data = self.factory.generate_edge_case_data()

        # Should handle gracefully
        result = feature.process(edge_data)
        self.assertIsNotNone(result)
```

## Validation Report

This test suite provides comprehensive validation of the Mollie Backend API integration:

✅ **72 test methods** across **6 test modules**
✅ **Critical bug fixes tested**: Timezone handling, caching, API parameters, encryption
✅ **Edge cases covered**: Empty data, malformed responses, Unicode, concurrency
✅ **Performance validated**: Large datasets, memory usage, caching efficiency
✅ **Security tested**: Webhook validation, key rotation, audit logging
✅ **Integration verified**: Cross-component compatibility, error recovery

The test suite ensures that the Mollie Backend API integration is robust, maintainable, and prevents regression of the critical issues that were fixed during implementation.
