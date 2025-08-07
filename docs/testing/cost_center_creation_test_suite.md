# Cost Center Creation Test Suite Documentation

## Overview

This comprehensive test suite validates the Phase 2 Cost Center Creation implementation with a focus on realistic data generation, robust business logic testing, and complete integration validation. The test suite follows the project's Enhanced Test Factory patterns and emphasizes realistic data over mocking.

## Architecture

### Test Suite Components

```
verenigingen/tests/e_boekhouden/
├── test_cost_center_creation_comprehensive.py  # Main comprehensive test suite
├── test_cost_center_ui_integration.py         # UI integration tests
├── fixtures/
│   └── cost_center_test_factory.py            # Specialized test data factory
└── README.md                                   # This documentation
```

### Test Categories

1. **Dutch Accounting Data Generation** - Realistic RGS-based test patterns
2. **Business Logic Validation** - Account code intelligence and suggestions
3. **API Endpoint Integration** - Complete API testing with real data
4. **Error Handling** - Comprehensive error scenario coverage
5. **Performance Testing** - Large dataset processing validation
6. **UI Integration** - User interface workflow testing

## Key Features

### ✅ Realistic Data Generation
- **Dutch RGS Compliance**: Uses authentic Dutch accounting terminology and code structures
- **Business Rule Validation**: Prevents creation of impossible test scenarios
- **Deterministic Generation**: Same seed produces identical test data for reproducible tests
- **No Mocking**: Uses actual Frappe document creation instead of mocks

### ✅ Comprehensive Coverage
- **Happy Path Scenarios**: Ideal workflows with successful outcomes
- **Edge Cases**: Special characters, boundary conditions, large datasets
- **Error Scenarios**: Duplicate handling, validation failures, missing data
- **Performance Testing**: Scalability validation with 500+ account groups

### ✅ Enhanced Test Factory
- **Extends EnhancedTestCase**: Inherits automatic cleanup and validation
- **Field Validation**: Verifies all field references against DocType schemas
- **Business Logic**: Enforces Dutch accounting rules during data generation
- **Memory Efficiency**: Optimized for large dataset processing

## Usage Guide

### Running Tests

```bash
# Run complete test suite
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.e_boekhouden.test_cost_center_creation_comprehensive

# Run specific test categories
python scripts/testing/run_cost_center_tests.py --suite business_logic
python scripts/testing/run_cost_center_tests.py --suite integration
python scripts/testing/run_cost_center_tests.py --suite performance

# Run with detailed metrics
python scripts/testing/run_cost_center_tests.py --verbose --performance-metrics

# Run UI integration tests
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.e_boekhouden.test_cost_center_ui_integration
```

### Test Execution Options

| Option | Description | Example |
|--------|-------------|---------|
| `--suite` | Specific test category | `--suite business_logic` |
| `--verbose` | Detailed output | `--verbose` |
| `--performance-metrics` | Show timing data | `--performance-metrics` |
| `--stop-on-failure` | Stop on first failure | `--stop-on-failure` |
| `--save-results` | Save to JSON file | `--save-results results.json` |

## Test Data Factory

### CostCenterTestDataFactory

Specialized factory for Cost Center testing with Dutch accounting patterns:

```python
from verenigingen.tests.e_boekhouden.fixtures.cost_center_test_factory import CostCenterTestDataFactory

# Initialize factory
factory = CostCenterTestDataFactory(seed=12345, use_faker=True)

# Generate RGS-compliant account groups
expense_group = factory.generate_rgs_account_group("personnel_costs", 0)
revenue_group = factory.generate_rgs_account_group("revenue", 0)

# Generate complete test scenarios
scenario = factory.generate_cost_center_mapping_scenario("happy_path")
groups = scenario["groups"]
text_input = factory.format_groups_as_text_input(groups)
```

### Scenario Types

| Scenario | Description | Use Case |
|----------|-------------|----------|
| `happy_path` | Ideal expense/revenue groups | Basic functionality testing |
| `mixed_suggestions` | Mixed group types | Business logic validation |
| `hierarchical` | Parent-child structures | Hierarchy testing |
| `large_dataset` | 150+ groups | Performance validation |
| `edge_cases` | Special characters | Boundary testing |
| `error_prone` | Invalid data | Error handling |

## Test Classes and Methods

### TestDutchAccountingDataGeneration

Tests realistic Dutch accounting data generation:

```python
def test_balance_sheet_groups_generation(self):
    """Test generation of realistic balance sheet account groups"""

def test_revenue_groups_generation(self):
    """Test generation of realistic revenue account groups"""

def test_hierarchical_groups_generation(self):
    """Test generation of hierarchical account group structures"""
```

### TestBusinessLogicValidation

Tests RGS-based business intelligence:

```python
def test_expense_groups_should_suggest_cost_centers(self):
    """Test that expense groups (5xx, 6xx) are suggested for cost centers"""

def test_revenue_groups_should_suggest_cost_centers(self):
    """Test that relevant revenue groups (3xx) are suggested"""

def test_balance_sheet_groups_should_not_suggest_cost_centers(self):
    """Test that balance sheet groups (1xx, 2xx) are not suggested"""
```

### TestAPIEndpointIntegration

Tests complete API functionality:

```python
def test_parse_groups_and_suggest_cost_centers_success(self):
    """Test successful parsing and suggestion generation"""

def test_create_cost_centers_from_mappings_success(self):
    """Test successful cost center creation from mappings"""

def test_preview_cost_center_creation(self):
    """Test cost center creation preview functionality"""
```

### TestErrorHandlingAndEdgeCases

Tests comprehensive error scenarios:

```python
def test_duplicate_cost_center_handling(self):
    """Test handling of duplicate cost center names"""

def test_invalid_parent_cost_center(self):
    """Test handling of invalid parent cost center references"""

def test_special_characters_in_names(self):
    """Test handling of special characters in account group names"""
```

### TestPerformanceAndScalability

Tests performance with large datasets:

```python
def test_performance_with_large_dataset(self):
    """Test performance with large dataset processing (500 groups)"""

def test_memory_usage_with_batch_processing(self):
    """Test memory efficiency with batch processing"""

def test_concurrent_processing_safety(self):
    """Test thread safety with concurrent operations"""
```

## Business Logic Validation

### RGS-Based Suggestions

The test suite validates Dutch accounting intelligence:

```python
# Expense groups (5xx, 6xx) → Suggest cost center
("510", "Lonen en salarissen") → True, "Expense group"
("600", "Algemene kosten") → True, "Expense group"
("621", "Telefoonkosten") → True, "Expense group"

# Revenue groups (3xx) → Suggest cost center
("310", "Netto-omzet") → True, "Revenue group"
("321", "Subsidies") → True, "Revenue group"

# Balance sheet (1xx, 2xx) → Do NOT suggest
("100", "Vaste activa") → False, "Balance sheet item"
("241", "Kas") → False, "Balance sheet item"
```

### Name Cleaning Algorithm

```python
# Input → Cleaned Output
"Personeelskosten rekeningen" → "Personeelskosten"
"Algemene kosten accounts" → "Algemene kosten"
"grootboek algemene kosten" → "Algemene kosten"
```

## Error Scenarios

### Comprehensive Error Coverage

The test suite validates error handling for:

1. **Empty Input**: No account group mappings provided
2. **Invalid Format**: Missing names, invalid codes
3. **Missing Company**: Company not configured
4. **Duplicate Names**: Same cost center name already exists
5. **Invalid Parents**: Non-existent parent cost centers
6. **Special Characters**: Unicode, symbols, formatting
7. **Large Datasets**: Memory and performance limits

### Error Response Structure

```python
{
    "success": False,
    "error": "Descriptive error message",
    "details": {
        "failed_groups": [...],
        "validation_errors": [...],
        "suggestions": [...]
    }
}
```

## Performance Expectations

### Benchmarks

| Dataset Size | Parse Time | Create Time | Memory Usage |
|--------------|------------|-------------|--------------|
| 10 groups | <0.1s | <0.5s | <10MB |
| 100 groups | <1.0s | <5.0s | <50MB |
| 500 groups | <5.0s | <25.0s | <100MB |

### Performance Tests

```python
def test_performance_with_large_dataset(self):
    """Test with 500 groups - should complete within 10 seconds"""

def test_memory_usage_with_batch_processing(self):
    """Test memory efficiency with 10 batches of 50 groups each"""

def test_concurrent_processing_safety(self):
    """Test with 5 concurrent threads processing 20 groups each"""
```

## Integration Testing

### API Endpoint Coverage

| Endpoint | Test Coverage | Scenarios |
|----------|---------------|-----------|
| `parse_groups_and_suggest_cost_centers` | ✅ Complete | Success, validation, errors |
| `preview_cost_center_creation` | ✅ Complete | Valid preview, empty mappings |
| `create_cost_centers_from_mappings` | ✅ Complete | Success, duplicates, failures |
| `create_single_cost_center` | ✅ Complete | Individual creation, validation |

### UI Workflow Testing

```python
def test_complete_happy_path_workflow(self):
    """Test complete user workflow from input to creation"""
    # Step 1: User inputs account groups
    # Step 2: Parse and generate suggestions
    # Step 3: Preview cost centers
    # Step 4: Create cost centers
    # Step 5: Verify creation success
```

## Data Cleanup and Isolation

### Automatic Cleanup

```python
class TestCostCenterCreationComprehensive(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Create test data

    def tearDown(self):
        # Automatic cleanup via EnhancedTestCase
        super().tearDown()
```

### Document Tracking

```python
# Track created documents for cleanup
self.track_doc("Company", company_doc.name)
self.track_doc("Cost Center", cost_center_doc.name)
```

## Extending the Test Suite

### Adding New Test Cases

```python
def test_new_functionality(self):
    """Test new feature"""
    # 1. Generate test data using factory
    scenario = self.factory.generate_cost_center_mapping_scenario("custom")

    # 2. Set up test environment
    settings = self.factory.create_test_eboekhouden_settings()

    # 3. Execute functionality
    result = api_call(test_data)

    # 4. Validate results
    self.assertTrue(result["success"])
    self.assertGreater(result["created_count"], 0)

    # 5. Cleanup is automatic via EnhancedTestCase
```

### Custom Test Scenarios

```python
def _generate_custom_scenario(self) -> Dict[str, Any]:
    """Generate custom test scenario"""
    groups = [
        {"code": "999", "name": "Custom Test Group"},
        # ... more test groups
    ]

    return {
        "scenario_type": "custom",
        "groups": groups,
        "expected_suggestions": len(groups),
        "description": "Custom scenario for specific testing"
    }
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure running in Frappe environment
   ```bash
   bench --site dev.veganisme.net execute verenigingen.scripts.testing.run_cost_center_tests
   ```

2. **Database Permissions**: Ensure proper test user permissions
   ```python
   frappe.set_user("Administrator")
   ```

3. **Field Validation Errors**: Check DocType JSON files for field names
   ```python
   # Always read DocType JSON before creating test data
   meta = frappe.get_meta("Cost Center")
   ```

4. **Memory Issues**: Use smaller test datasets
   ```python
   scenario = factory.generate_cost_center_mapping_scenario("happy_path")  # Small dataset
   ```

### Debug Mode

```python
# Enable debug logging
frappe.flags.in_test = True
frappe.flags.debug = True

# Add debug prints
print(f"Test data: {test_data}")
print(f"API result: {result}")
```

## Contributing

### Guidelines

1. **Follow Existing Patterns**: Use EnhancedTestCase and CostCenterTestDataFactory
2. **Realistic Data**: Generate realistic test data, avoid mocking
3. **Business Rules**: Validate actual business logic
4. **Documentation**: Document new test scenarios and edge cases
5. **Performance**: Consider performance impact of new tests

### Code Review Checklist

- [ ] Uses EnhancedTestCase base class
- [ ] Generates realistic test data
- [ ] Validates business rules
- [ ] Includes error scenarios
- [ ] Proper cleanup and isolation
- [ ] Clear test names and documentation
- [ ] Performance considerations

## Conclusion

This comprehensive test suite ensures the Cost Center Creation feature works reliably with realistic Dutch accounting data, handles edge cases gracefully, and performs well under load. The emphasis on realistic data generation over mocking provides confidence that the feature will work correctly in production environments.

The test suite serves as both validation and documentation of the feature's capabilities, making it easier for future developers to understand and maintain the Cost Center Creation functionality.
