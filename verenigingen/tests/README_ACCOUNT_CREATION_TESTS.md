# Account Creation Manager Test Suite

This comprehensive test suite validates the secure AccountCreationManager system for the Verenigingen application. The tests ensure zero unauthorized permission bypasses, robust error handling, and proper integration with Dutch association business logic.

## Test Coverage

### 1. Security Tests (`test_account_creation_security_deep.py`)
- **Zero Permission Bypass Validation**: Ensures no `ignore_permissions=True` usage except for system status tracking
- **SQL Injection Prevention**: Comprehensive SQL injection attack testing
- **XSS Prevention**: Cross-site scripting attack prevention validation
- **Authorization Matrix**: Role-based access control testing
- **Audit Trail Integrity**: Complete logging and traceability validation
- **Session Security**: Session hijacking and data exposure prevention

### 2. Functionality Tests (`test_account_creation_manager_comprehensive.py`)
- **Complete Pipeline Execution**: End-to-end account creation workflow
- **User Account Creation**: Proper user creation with permission validation
- **Role Assignment**: Secure role and role profile assignment
- **Employee Record Creation**: Employee creation for expense functionality
- **Error Handling**: Graceful failure handling and recovery
- **Integration Testing**: Member and Volunteer DocType integration

### 3. Background Processing Tests (`test_account_creation_background_processing.py`)
- **Redis Queue Integration**: Job queueing and execution validation
- **Retry Mechanisms**: Exponential backoff and retry limit enforcement
- **Concurrent Processing**: Race condition and resource locking tests
- **Timeout Handling**: Job timeout and cleanup procedures
- **Performance Testing**: High-volume processing and memory usage
- **Fault Tolerance**: Queue failure recovery and resilience

### 4. Dutch Business Logic Tests (`test_account_creation_dutch_business_logic.py`)
- **Age Validation**: 16+ requirement for volunteers
- **Role Hierarchy**: Verenigingen-specific role assignments
- **Employee Creation**: Dutch expense functionality integration
- **Name Handling**: Dutch name conventions with tussenvoegsel
- **Regulatory Compliance**: Dutch non-profit organization requirements
- **Edge Cases**: Leap year birthdays, timezone handling

## Enhanced Test Factory Integration

The test suite integrates with the `EnhancedTestFactory` to provide:
- **Realistic Test Data**: Dutch-specific names, addresses, and business scenarios
- **Business Rule Validation**: Prevents creation of invalid test scenarios
- **Permission Testing**: Multi-role user scenarios for security testing
- **Background Job Mocking**: Redis queue simulation for testing
- **Deterministic Data Generation**: Reproducible test scenarios

## Running the Tests

### Complete Test Suite
```bash
# Run all account creation tests
python -m unittest verenigingen.tests.test_account_creation_suite

# Or using the test suite runner
cd /home/frappe/frappe-bench/apps/verenigingen
python -m verenigingen.tests.test_account_creation_suite
```

### Individual Test Categories
```bash
# Security tests only
python -m verenigingen.tests.test_account_creation_suite security

# Functionality tests only
python -m verenigingen.tests.test_account_creation_suite functionality

# Background processing tests only
python -m verenigingen.tests.test_account_creation_suite background

# Dutch business logic tests only
python -m verenigingen.tests.test_account_creation_suite business
```

### Individual Test Files
```bash
# Run comprehensive functionality tests
python -m unittest verenigingen.tests.test_account_creation_manager_comprehensive

# Run deep security tests
python -m unittest verenigingen.tests.test_account_creation_security_deep

# Run background processing tests
python -m unittest verenigingen.tests.test_account_creation_background_processing

# Run Dutch business logic tests
python -m unittest verenigingen.tests.test_account_creation_dutch_business_logic
```

### Specific Test Classes
```bash
# Run only security tests from comprehensive suite
python -m unittest verenigingen.tests.test_account_creation_manager_comprehensive.TestAccountCreationManagerSecurity

# Run only SQL injection tests
python -m unittest verenigingen.tests.test_account_creation_security_deep.TestAccountCreationDeepSecurity.test_comprehensive_sql_injection_prevention
```

## Frappe Test Integration

### Using Frappe's Test Runner
```bash
# Run with Frappe's test framework
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_account_creation_manager_comprehensive

# Run specific test class
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_account_creation_security_deep --test-class TestAccountCreationDeepSecurity

# Run with coverage
bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_account_creation_suite --coverage
```

### Test Data Cleanup
The tests use `EnhancedTestCase` which extends `FrappeTestCase`, providing:
- Automatic database rollback after each test
- Test data isolation between test runs
- Proper cleanup of created records
- Session management and user context restoration

## Test Environment Setup

### Required Permissions
The test user needs the following permissions:
- User creation and management
- Account Creation Request read/write
- Member and Volunteer record access
- Role and Role Profile management

### Required DocTypes
Ensure these DocTypes exist:
- Account Creation Request
- Account Creation Request Role (child table)
- Member
- Volunteer
- User
- Employee
- Role Profile

### Background Job Testing
For background processing tests, ensure Redis is available:
```bash
# Check Redis status
redis-cli ping

# If Redis is not running, start it
sudo systemctl start redis

# Or use Docker for testing
docker run -d -p 6379:6379 redis:alpine
```

## Test Data Patterns

### Security Testing Data
- Malicious SQL injection payloads
- XSS attack vectors
- Invalid role assignment attempts
- Session hijacking scenarios

### Functionality Testing Data
- Valid member and volunteer records
- Complete account creation workflows
- Error scenarios and edge cases
- Integration test scenarios

### Dutch Business Logic Data
- Age validation test cases (15-17 year olds)
- Dutch names with tussenvoegsel
- Leap year birthday calculations
- Membership type variations

## Troubleshooting

### Common Issues

1. **Permission Errors**
   - Ensure test user has proper permissions
   - Check role assignments in test environment
   - Verify System Manager or Verenigingen Administrator access

2. **DocType Not Found Errors**
   - Run `bench migrate` to ensure all DocTypes exist
   - Check if Account Creation Request DocType is installed
   - Verify custom field installations

3. **Background Job Failures**
   - Check Redis connectivity
   - Verify queue configuration
   - Monitor Frappe job queue status with `bench show-jobs`

4. **Business Logic Validation Failures**
   - Check member age calculations
   - Verify volunteer creation business rules
   - Ensure proper date handling in test environment

### Debug Mode
```bash
# Run tests in verbose mode
python -m unittest verenigingen.tests.test_account_creation_suite -v

# Run with Python debugging
python -m pdb -m unittest verenigingen.tests.test_account_creation_manager_comprehensive.TestAccountCreationManagerSecurity.test_unauthorized_user_cannot_create_request
```

### Log Analysis
```bash
# Check Frappe error logs
bench --site dev.veganisme.net console
>>> frappe.get_traceback()

# Check specific test failures
tail -f /home/frappe/frappe-bench/logs/dev.veganisme.net.error.log
```

## Performance Benchmarks

### Expected Performance
- Security tests: ~30-60 seconds
- Functionality tests: ~45-90 seconds  
- Background processing tests: ~60-120 seconds
- Dutch business logic tests: ~30-60 seconds
- Complete suite: ~3-6 minutes

### Performance Tuning
For faster test execution:
```bash
# Use parallel test execution (if supported)
python -m pytest verenigingen/tests/test_account_creation_*.py -n auto

# Run specific failing tests first
python -m unittest verenigingen.tests.test_account_creation_manager_comprehensive.TestAccountCreationManagerSecurity --failfast
```

## Continuous Integration

### GitHub Actions Example
```yaml
name: Account Creation Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Frappe Environment
        run: |
          # Setup Frappe, install app, migrate
      - name: Run Account Creation Tests
        run: |
          cd apps/verenigingen
          python -m verenigingen.tests.test_account_creation_suite
```

### Test Coverage Goals
- **Security Tests**: 100% coverage of permission bypass prevention
- **Functionality Tests**: 95%+ coverage of core account creation pipeline
- **Background Processing**: 90%+ coverage of Redis queue integration
- **Business Logic**: 100% coverage of Dutch association requirements

## Contributing

### Adding New Tests
1. Follow existing test patterns in the appropriate test file
2. Use `EnhancedTestCase` for automatic cleanup
3. Include both positive and negative test cases
4. Add comprehensive docstrings explaining test purpose
5. Update this README with new test descriptions

### Test Naming Conventions
- Test methods: `test_descriptive_name_of_what_is_tested`
- Test classes: `TestSpecificFeatureOrComponent`
- Test files: `test_account_creation_specific_area.py`

### Code Quality Standards
- All tests must use proper permission validation (no `ignore_permissions=True`)
- Security tests must validate against real attack vectors
- Business logic tests must reflect actual Dutch association requirements
- Background processing tests must handle real-world failure scenarios