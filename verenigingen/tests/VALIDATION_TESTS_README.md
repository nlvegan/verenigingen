# Validation Tests Documentation

This document describes the comprehensive validation test suite added to prevent field validation bugs and catch issues early in development.

## Overview

The validation test suite consists of three main test files that comprehensively test field validations, application submission flows, and regression scenarios:

1. **`test_validation_regression.py`** - Core regression tests to prevent known issues
2. **`test_application_submission_validation.py`** - Application submission flow validation
3. **`test_doctype_validation_comprehensive.py`** - Comprehensive doctype field validation

## Test Files

### 1. test_validation_regression.py

**Purpose**: Prevent regression of specific validation bugs that have been fixed.

**Key Tests**:
- `test_critical_doctype_select_fields()`: Tests that select fields use only valid options
- `test_application_flow_volunteer_status_regression()`: Specific test for the volunteer status bug that was fixed
- `test_helper_function_validations()`: Tests that helper functions use valid field values
- `test_api_error_handling()`: Tests graceful error handling

**Whitelisted Function**: `run_validation_regression_suite()`

### 2. test_application_submission_validation.py

**Purpose**: Comprehensive testing of the membership application submission flow.

**Key Tests**:
- `test_application_with_volunteer_interest_valid_status()`: Tests volunteer creation with correct status
- `test_volunteer_status_options_are_valid()`: Validates volunteer status field options
- `test_application_submission_edge_cases()`: Tests various edge cases in submission
- `test_special_character_handling_in_volunteer_creation()`: Tests special character handling

**Whitelisted Function**: `run_application_submission_tests()`

### 3. test_doctype_validation_comprehensive.py

**Purpose**: Comprehensive validation of doctype field configurations and options.

**Key Tests**:
- `test_volunteer_status_validation()`: Tests all valid/invalid volunteer status values
- `test_member_status_validation()`: Tests member status field validation
- `test_complete_application_submission_with_volunteer()`: End-to-end application test

**Whitelisted Function**: `run_doctype_validation_tests()`

## Running the Tests

### Command Line Usage

```bash
# Run all validation tests
python verenigingen/tests/test_runner.py validation

# Run specific test suites
bench --site dev.veganisme.net execute verenigingen.tests.test_validation_regression.run_validation_regression_suite
bench --site dev.veganisme.net execute verenigingen.tests.test_application_submission_validation.run_application_submission_tests
bench --site dev.veganisme.net execute verenigingen.tests.test_doctype_validation_comprehensive.run_doctype_validation_tests

# Run integrated validation tests via test runner
bench --site dev.veganisme.net execute verenigingen.tests.test_runner.run_validation_tests
```

### Integration with Main Test Suite

The validation tests are integrated into the main test runner (`test_runner.py`) and will be executed as part of comprehensive testing:

```bash
# Run all tests including validation
python verenigingen/tests/test_runner.py all
```

## What These Tests Catch

### 1. Field Validation Issues
- **Select Field Options**: Ensures select fields have proper options defined
- **Invalid Status Values**: Catches attempts to use invalid status values
- **Field Type Mismatches**: Detects when fields expect different data types

### 2. Application Flow Issues
- **Volunteer Creation Errors**: Catches status validation errors in volunteer creation
- **Name Handling**: Tests special character handling in names
- **Database Constraints**: Detects primary key violations and constraint issues

### 3. Helper Function Issues
- **Function Return Values**: Ensures helper functions return valid data
- **Error Handling**: Tests that functions handle errors gracefully
- **Data Consistency**: Validates that functions use consistent field values

### 4. Regression Prevention
- **Fixed Bug Detection**: Specifically tests for bugs that have been previously fixed
- **Edge Case Coverage**: Comprehensive edge case testing
- **API Error Handling**: Ensures APIs fail gracefully with proper error messages

## Example Test Results

### Successful Test Run
```json
{
  "success": true,
  "tests_run": 5,
  "failures": 0,
  "errors": 0,
  "message": "Validation regression tests: 5 run, 0 failures, 0 errors"
}
```

### Failed Test (Issue Detected)
```json
{
  "success": false,
  "tests_run": 6,
  "failures": 1,
  "errors": 0,
  "failure_details": [
    "test_application_validation: Invalid status value should be rejected"
  ],
  "message": "Application validation tests completed: 6 tests, 1 failures, 0 errors"
}
```

## Issues Caught by These Tests

### 1. Volunteer Status Bug (Fixed)
- **Issue**: Volunteer creation using invalid "Pending" status
- **Test**: `test_application_flow_volunteer_status_regression()`
- **Fix**: Changed status from "Pending" to "New"

### 2. Field Name Inconsistencies
- **Issue**: Tests trying to access non-existent fields (`first_name` in Volunteer doctype)
- **Test**: `test_special_character_handling_in_volunteer_creation()`
- **Detection**: Helps identify schema mismatches

### 3. Duplicate Name Handling
- **Issue**: Volunteer names used as primary keys causing duplicates
- **Test**: Application submission tests with identical names
- **Detection**: Reveals database constraint issues

## Adding New Validation Tests

### For New Doctypes
1. Add doctype to `critical_doctypes` list in `test_doctype_field_consistency()`
2. Define valid/invalid values for select fields
3. Add specific validation tests for critical fields

### For New Application Flows
1. Add test cases to `test_application_submission_validation.py`
2. Test both success and failure scenarios
3. Include edge cases and error conditions

### For Bug Regression Prevention
1. Add specific regression tests to `test_validation_regression.py`
2. Document the original bug and fix
3. Ensure test would fail without the fix

## Best Practices

### Test Naming
- Use descriptive test names that explain what is being tested
- Include the expected outcome in the test name
- Group related tests in the same test class

### Test Structure
- Use `setUp()` and `tearDown()` for test fixtures
- Clean up test data to avoid interference between tests
- Use `self.add_cleanup_record()` pattern for automatic cleanup

### Error Testing
- Test both valid and invalid inputs
- Verify that proper exceptions are raised for invalid data
- Check error messages are meaningful

### Data Isolation
- Use unique identifiers to avoid test interference
- Clean up all created records
- Use transactions where appropriate

## Maintenance

### Regular Updates
- Review and update tests when adding new features
- Add regression tests for any bugs found and fixed
- Keep test data current with schema changes

### Performance
- Keep tests fast by using minimal test data
- Use mocking where appropriate to avoid external dependencies
- Run validation tests frequently during development

### Documentation
- Update this documentation when adding new test categories
- Document any special setup requirements
- Explain the purpose of complex test scenarios
