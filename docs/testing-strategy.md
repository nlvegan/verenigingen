# Verenigingen Testing Strategy

## Overview

This document outlines the comprehensive testing strategy for the Verenigingen app, designed to ensure code quality, prevent regressions, and maintain system reliability through automated testing.

## Testing Philosophy

1. **Shift Left**: Catch issues early in development
2. **Automate Everything**: Reduce manual testing burden
3. **Fast Feedback**: Quick tests run frequently, comprehensive tests run regularly
4. **Coverage Matters**: Aim for >80% code coverage
5. **Test Categories**: Different test suites for different purposes

## Test Structure

### Test Categories

#### 1. Quick Tests (< 30 seconds)
- Basic validation tests
- Critical path testing
- Smoke tests
- Run on every commit via pre-commit hooks

#### 2. Comprehensive Tests (< 5 minutes)
- Full feature testing
- Integration tests
- Security tests
- Run on every push/PR via CI/CD

#### 3. Scheduled Tests (< 30 minutes)
- Performance tests
- Edge case scenarios
- Load testing
- Run nightly or on schedule

### Test Organization

```
verenigingen/tests/
├── unit/               # Unit tests for individual functions
├── integration/        # Integration tests
├── workflows/          # End-to-end workflow tests
├── fixtures/           # Test data and personas
├── test_runner.py      # Enhanced test runner
└── test_*.py          # Feature-specific test files
```

## Automated Testing Implementation

### 1. Local Development (Pre-commit Hooks)

**Installation:**
```bash
cd /home/frappe/frappe-bench/apps/verenigingen
./scripts/install_pre_commit.sh
```

**What runs on commit:**
- Code formatting (Black, isort)
- Linting (Flake8)
- File validation
- Quick validation tests

**Skip hooks when needed:**
```bash
git commit --no-verify
```

### 2. Continuous Integration (GitHub Actions)

**Triggers:**
- Every push to main/develop branches
- Every pull request
- Daily scheduled runs

**Test Matrix:**
- Python versions: 3.10, 3.11
- Frappe versions: v14, v15
- Databases: MariaDB 10.6

**Workflow stages:**
1. Environment setup
2. App installation
3. Test execution
4. Coverage reporting
5. Result artifacts

### 3. Local Testing Commands

**Using Make:**
```bash
make test          # Run comprehensive tests
make test-quick    # Run quick tests only
make test-all      # Run all test categories
make coverage      # Generate coverage report
make lint          # Run linters
make format        # Format code
```

**Using Bench directly:**
```bash
# Run specific test module
bench --site dev.veganisme.net run-tests --app verenigingen --module test_member

# Run with coverage
bench --site dev.veganisme.net run-tests --app verenigingen --coverage

# Run custom test runner
bench --site dev.veganisme.net execute verenigingen.tests.utils.test_runner_simple.run_comprehensive_tests
```

## Test Writing Guidelines

### 1. Test Structure

```python
class TestFeatureName(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        """One-time setup for test class"""
        super().setUpClass()
        # Create test data

    def setUp(self):
        """Setup before each test"""
        # Reset state

    def test_feature_happy_path(self):
        """Test normal operation"""
        # Arrange
        # Act
        # Assert

    def test_feature_edge_case(self):
        """Test edge cases"""
        # Test boundary conditions

    def tearDown(self):
        """Cleanup after each test"""
        # Clean test data
```

### 2. Test Data Management

- Use test factories for consistent data
- Prefix test records with "TEST-"
- Clean up in reverse dependency order
- Use transactions where possible

### 3. Assertion Best Practices

```python
# Be specific with assertions
self.assertEqual(member.status, "Active", "Member should be active after approval")

# Test error conditions
with self.assertRaises(ValidationError):
    invalid_operation()

# Check multiple conditions
self.assertTrue(all([
    condition1,
    condition2,
    condition3
]), "All conditions should be met")
```

## Coverage Goals

### Minimum Coverage Requirements

- Overall: 80%
- Critical paths: 95%
- New code: 90%
- API endpoints: 100%

### Coverage Reports

Coverage reports are generated in:
- Local: `htmlcov/index.html`
- CI/CD: Uploaded to Codecov
- JSON: `sites/[site]/test-results/coverage.json`

## Performance Testing

### Benchmarks

Key operations should complete within:
- Member creation: < 200ms
- Expense submission: < 500ms
- Report generation: < 2s
- Bulk operations: < 10s for 1000 records

### Load Testing

Scheduled tests verify system handles:
- 100 concurrent users
- 10,000 members
- 1,000 expenses/day
- 50 simultaneous report generations

## Security Testing

### Automated Security Checks

1. **Permission Tests**: Verify role-based access
2. **SQL Injection**: Test input sanitization
3. **XSS Prevention**: Validate output encoding
4. **CSRF Protection**: Verify token validation
5. **Authentication**: Test session management

### Security Test Example

```python
def test_unauthorized_access(self):
    """Test that unauthorized users cannot access protected resources"""
    # Login as regular user
    frappe.set_user("test_user@example.com")

    # Try to access admin function
    with self.assertRaises(PermissionError):
        admin_only_function()
```

## Monitoring and Alerts

### Test Failure Notifications

1. **GitHub Actions**: Email/Slack on failure
2. **Daily Reports**: Summary of nightly runs
3. **Coverage Drops**: Alert if coverage decreases
4. **Performance Regression**: Alert on slowdowns

### Dashboard

Test results available at:
- Local: `/test-results/test_report.html`
- CI/CD: GitHub Actions artifacts
- Metrics: Codecov dashboard

## Best Practices

### Do's
- Write tests for new features
- Run tests before committing
- Keep tests fast and focused
- Use descriptive test names
- Test edge cases
- Mock external dependencies

### Don'ts
- Don't test framework features
- Don't use production data
- Don't skip cleanup
- Don't ignore flaky tests
- Don't test implementation details

## Troubleshooting

### Common Issues

**Tests fail locally but pass in CI:**
- Check Python version
- Verify database state
- Clear cache: `bench clear-cache`

**Import errors:**
- Run from bench directory
- Check PYTHONPATH
- Verify app installation

**Permission errors:**
- Run as Administrator in tests
- Check test user permissions
- Verify role assignments

**Slow tests:**
- Use test factories
- Minimize database operations
- Mock expensive operations
- Run in parallel where possible

## Future Enhancements

1. **Visual Regression Testing**: Screenshot comparisons
2. **API Contract Testing**: OpenAPI validation
3. **Mutation Testing**: Test quality verification
4. **Chaos Engineering**: Failure injection
5. **A/B Testing**: Feature flag testing

## Resources

- [Frappe Testing Guide](https://frappeframework.com/docs/user/en/testing)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Pre-commit Documentation](https://pre-commit.com/)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
