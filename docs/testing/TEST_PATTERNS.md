# Verenigingen Test Patterns and Best Practices

## Table of Contents
1. [Overview](#overview)
2. [Test Organization](#test-organization)
3. [Test Data Management](#test-data-management)
4. [Common Test Patterns](#common-test-patterns)
5. [Testing Frappe Specifics](#testing-frappe-specifics)
6. [Performance Testing](#performance-testing)
7. [Security Testing](#security-testing)
8. [Edge Case Testing](#edge-case-testing)
9. [Continuous Integration](#continuous-integration)
10. [Troubleshooting](#troubleshooting)

## Overview

The Verenigingen app follows a comprehensive testing strategy that ensures reliability, performance, and security across all components. This guide documents the patterns and practices that should be followed when writing tests.

### Testing Philosophy

- **Test Early, Test Often**: Write tests as you develop features
- **Comprehensive Coverage**: Aim for >80% code coverage
- **Real-World Scenarios**: Test with realistic data and workflows
- **Performance Aware**: Monitor and test for performance regressions
- **Security First**: Include security tests for all user-facing features

## Test Organization

### Directory Structure

```
verenigingen/
├── tests/                          # Main test suite
│   ├── test_*.py                  # Individual test modules
│   ├── test_data_factory.py       # Base test data utilities
│   ├── test_data_factory_extended.py  # Extended utilities
│   └── test_utils.py              # Common test helpers
├── scripts/
│   ├── testing/                   # Test scripts and runners
│   │   ├── runners/              # Test execution scripts
│   │   ├── integration/          # Integration tests
│   │   └── unit/                 # Unit tests by component
│   ├── debug/                    # Debug utilities
│   └── validation/               # Validation scripts
└── frontend_tests/               # JavaScript tests
    └── *.spec.js                 # Jest test files
```

### Naming Conventions

- Test files: `test_[component]_[type].py`
- Test classes: `Test[Component][Type]`
- Test methods: `test_[specific_behavior]`
- Test data: Prefix with `TEST-` or `Test`

### Test Categories

1. **Unit Tests**: Test individual functions/methods
2. **Integration Tests**: Test component interactions
3. **End-to-End Tests**: Test complete workflows
4. **Performance Tests**: Test response times and scalability
5. **Security Tests**: Test access control and data protection
6. **Edge Case Tests**: Test boundary conditions and error handling

## Test Data Management

### Using TestDataFactory

```python
from verenigingen.tests.test_data_factory_extended import ExtendedTestDataFactory

class TestExample(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = ExtendedTestDataFactory(cleanup_on_exit=False)

    def setUp(self):
        self.member = self.factory.create_member()
        self.volunteer = self.factory.create_volunteer(member=self.member.name)

    def tearDown(self):
        # Cleanup is automatic with factory
        pass

    @classmethod
    def tearDownClass(cls):
        cls.factory.cleanup()
        super().tearDownClass()
```

### Test Data Patterns

#### 1. Lifecycle Testing

```python
def test_member_lifecycle(self):
    """Test complete member lifecycle"""
    # Create members at different stages
    lifecycle = self.factory.create_member_lifecycle()

    # Test transitions
    prospect = lifecycle["prospect"]
    self.assertEqual(prospect.status, "Pending")

    # Transition to active
    prospect.status = "Active"
    prospect.save()

    # Verify workflow
    self.assertTrue(prospect.has_active_membership())
```

#### 2. Bulk Data Testing

```python
def test_bulk_operations(self):
    """Test with large datasets"""
    # Create performance test data
    data = self.factory.create_performance_test_data("medium")

    # Test bulk operations
    start_time = time.time()
    result = bulk_update_members(data["members"])
    duration = time.time() - start_time

    # Assert performance
    self.assertLess(duration, 10.0)  # Should complete in 10 seconds
    self.assertEqual(len(result), len(data["members"]))
```

#### 3. Edge Case Data

```python
def test_edge_cases(self):
    """Test with edge case data"""
    edge_data = self.factory.create_edge_case_data()

    # Test unicode handling
    unicode_member = edge_data["unicode_member"]
    self.assertIn("测试", unicode_member.full_name)

    # Test field limits
    long_name = edge_data["long_name_member"]
    self.assertEqual(len(long_name.full_name), 140)
```

## Common Test Patterns

### 1. Permission Testing

```python
def test_permissions(self):
    """Test access control"""
    # Create test users
    admin = self.factory.create_user(role="Verenigingen Administrator")
    member = self.factory.create_user(role="Verenigingen Member")

    # Test as admin
    frappe.set_user(admin.name)
    doc = frappe.get_doc("Member", self.member.name)
    self.assertTrue(doc.has_permission("write"))

    # Test as member
    frappe.set_user(member.name)
    self.assertRaises(
        frappe.PermissionError,
        frappe.get_doc,
        "Member",
        self.member.name
    )
```

### 2. Workflow Testing

```python
def test_approval_workflow(self):
    """Test multi-step approval workflow"""
    # Create expense
    expense = self.factory.create_volunteer_expense(amount=500)

    # Submit for approval
    expense.submit_for_approval()
    self.assertEqual(expense.status, "Pending Approval")

    # Chapter approval
    frappe.set_user(self.chapter_treasurer.name)
    expense.approve_chapter()
    self.assertEqual(expense.status, "Chapter Approved")

    # National approval
    frappe.set_user(self.national_treasurer.name)
    expense.approve_national()
    self.assertEqual(expense.status, "Approved")
```

### 3. Event Testing

```python
def test_document_events(self):
    """Test document lifecycle events"""
    # Track events
    events_fired = []

    def track_event(doc, method):
        events_fired.append(method)

    # Monkey patch for testing
    original_on_update = Member.on_update
    Member.on_update = track_event

    try:
        # Create and update
        member = self.factory.create_member()
        member.status = "Active"
        member.save()

        # Verify events
        self.assertIn("on_update", events_fired)
    finally:
        Member.on_update = original_on_update
```

### 4. API Testing

```python
def test_api_endpoint(self):
    """Test REST API endpoints"""
    # Login as test user
    self.login_as_test_user()

    # Test GET
    response = self.get("/api/method/verenigingen.api.member.get_member_list")
    self.assertEqual(response.status_code, 200)
    self.assertIsInstance(response.json["message"], list)

    # Test POST
    data = {"member": self.member.name, "amount": 100}
    response = self.post("/api/method/verenigingen.api.donation.create", data)
    self.assertEqual(response.status_code, 200)
    self.assertIn("donation_id", response.json["message"])
```

## Testing Frappe Specifics

### 1. Testing with Fixtures

```python
class TestWithFixtures(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Load fixtures
        frappe.db.sql("DELETE FROM `tabMember` WHERE name LIKE 'TEST-%'")
        cls.load_fixture_data()

    @classmethod
    def load_fixture_data(cls):
        """Load test fixtures"""
        fixtures = [
            {"doctype": "Member", "name": "TEST-001", "full_name": "Test Member"},
            {"doctype": "Chapter", "name": "TEST-CHAPTER", "chapter_name": "Test Chapter"}
        ]

        for fixture in fixtures:
            doc = frappe.new_doc(fixture["doctype"])
            doc.update(fixture)
            doc.insert(ignore_permissions=True)
```

### 2. Testing Scheduled Jobs

```python
def test_scheduled_job(self):
    """Test scheduled job execution"""
    from verenigingen.tasks import process_membership_renewals

    # Create expiring memberships
    for i in range(5):
        member = self.factory.create_member()
        member.membership_expiry = add_days(getdate(), -1)
        member.save()

    # Run scheduled job
    process_membership_renewals()

    # Verify processing
    expired = frappe.get_all("Member",
        filters={"membership_expiry": ["<", getdate()], "status": "Expired"})
    self.assertEqual(len(expired), 5)
```

### 3. Testing Document Links

```python
def test_document_links(self):
    """Test document relationships"""
    # Create linked documents
    member = self.factory.create_member()
    volunteer = self.factory.create_volunteer(member=member.name)
    expense = self.factory.create_volunteer_expense(volunteer=volunteer.name)

    # Test link integrity
    linked_docs = frappe.get_all("Volunteer Expense",
        filters={"volunteer": volunteer.name})
    self.assertEqual(len(linked_docs), 1)

    # Test cascade behavior
    self.assertRaises(
        frappe.LinkExistsError,
        frappe.delete_doc,
        "Volunteer",
        volunteer.name
    )
```

## Performance Testing

### 1. Response Time Testing

```python
def test_response_times(self):
    """Test API response times"""
    import time

    # Warm up
    self.get("/api/method/verenigingen.api.member.get_member_list")

    # Measure
    times = []
    for _ in range(10):
        start = time.time()
        response = self.get("/api/method/verenigingen.api.member.get_member_list")
        times.append(time.time() - start)

    avg_time = sum(times) / len(times)
    self.assertLess(avg_time, 0.5)  # Should respond in < 500ms
```

### 2. Load Testing

```python
def test_concurrent_access(self):
    """Test concurrent user access"""
    import concurrent.futures

    def simulate_user_request(user_id):
        frappe.set_user(f"test_user_{user_id}@example.com")
        return frappe.get_all("Member", limit=10)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(simulate_user_request, i) for i in range(50)]
        results = [f.result() for f in futures]

    self.assertEqual(len(results), 50)
```

### 3. Memory Testing

```python
def test_memory_usage(self):
    """Test memory consumption"""
    import psutil
    import os

    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB

    # Create large dataset
    members = []
    for i in range(1000):
        members.append(self.factory.create_member())

    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    memory_increase = final_memory - initial_memory

    self.assertLess(memory_increase, 100)  # Should use < 100MB
```

## Security Testing

### 1. SQL Injection Testing

```python
def test_sql_injection_protection(self):
    """Test SQL injection protection"""
    malicious_inputs = [
        "'; DROP TABLE tabMember; --",
        "1' OR '1'='1",
        "admin'--",
        "1; UPDATE tabMember SET status='Active'"
    ]

    for payload in malicious_inputs:
        # Test through API
        response = self.get(
            "/api/method/verenigingen.api.member.search_members",
            {"query": payload}
        )

        # Should handle safely
        self.assertIn(response.status_code, [200, 400, 403])

        # Verify no damage
        self.assertTrue(frappe.db.table_exists("Member"))
```

### 2. XSS Testing

```python
def test_xss_protection(self):
    """Test XSS protection"""
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "javascript:alert('XSS')",
        "<svg onload=alert('XSS')>"
    ]

    for payload in xss_payloads:
        member = self.factory.create_member(full_name=payload)

        # Fetch and verify sanitization
        doc = frappe.get_doc("Member", member.name)
        self.assertNotIn("<script>", doc.full_name)
        self.assertNotIn("javascript:", doc.full_name)
```

### 3. Permission Bypass Testing

```python
def test_permission_bypass_attempts(self):
    """Test permission bypass attempts"""
    # Create restricted document
    sensitive_doc = self.factory.create_member()
    sensitive_doc.add_comment("Internal", "Sensitive information")

    # Try to access as unauthorized user
    frappe.set_user("test_user@example.com")

    # Direct access should fail
    self.assertRaises(
        frappe.PermissionError,
        frappe.get_doc,
        "Member",
        sensitive_doc.name
    )

    # API access should fail
    response = self.get(
        f"/api/resource/Member/{sensitive_doc.name}"
    )
    self.assertEqual(response.status_code, 403)
```

## Edge Case Testing

### 1. Boundary Value Testing

```python
def test_boundary_values(self):
    """Test boundary conditions"""
    # Test minimum values
    expense = self.factory.create_volunteer_expense(amount=0.01)
    self.assertEqual(expense.amount, 0.01)

    # Test maximum values
    large_expense = self.factory.create_volunteer_expense(amount=999999.99)
    self.assertEqual(large_expense.amount, 999999.99)

    # Test invalid values
    self.assertRaises(
        frappe.ValidationError,
        self.factory.create_volunteer_expense,
        amount=-1
    )
```

### 2. Concurrency Testing

```python
def test_concurrent_modifications(self):
    """Test concurrent document modifications"""
    member = self.factory.create_member()

    def modify_member(field, value):
        doc = frappe.get_doc("Member", member.name)
        setattr(doc, field, value)
        doc.save()

    # Simulate concurrent updates
    import threading
    threads = [
        threading.Thread(target=modify_member, args=("status", "Active")),
        threading.Thread(target=modify_member, args=("remarks", "Updated"))
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify final state
    final_doc = frappe.get_doc("Member", member.name)
    self.assertIsNotNone(final_doc.modified)
```

### 3. Data Corruption Testing

```python
def test_data_corruption_handling(self):
    """Test handling of corrupted data"""
    # Create valid document
    member = self.factory.create_member()

    # Corrupt data directly in database
    frappe.db.sql("""
        UPDATE tabMember
        SET email = NULL
        WHERE name = %s
    """, member.name)

    # Test recovery
    try:
        doc = frappe.get_doc("Member", member.name)
        doc.validate()
    except frappe.ValidationError as e:
        self.assertIn("email", str(e).lower())
```

## Continuous Integration

### 1. GitHub Actions Configuration

```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run Tests
        run: |
          bench --site test_site run-tests --app verenigingen --coverage

      - name: Upload Coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

### 2. Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: run-tests
        name: Run Tests
        entry: bench --site test_site run-tests --app verenigingen --module
        language: system
        pass_filenames: false
        always_run: true
```

### 3. Coverage Requirements

```python
# In test configuration
COVERAGE_REQUIREMENTS = {
    "lines": 80,
    "branches": 70,
    "functions": 80,
    "statements": 80
}
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Import Errors

```python
# Problem: ModuleNotFoundError: No module named 'frappe'
# Solution: Run tests through bench
bench --site test_site run-tests --app verenigingen
```

#### 2. Permission Errors

```python
# Problem: frappe.PermissionError in tests
# Solution: Use appropriate test user
def setUp(self):
    frappe.set_user("Administrator")
```

#### 3. Database Locks

```python
# Problem: Database locked errors
# Solution: Use proper transaction management
def test_with_transaction(self):
    frappe.db.begin()
    try:
        # Test code
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
```

#### 4. Slow Tests

```python
# Problem: Tests taking too long
# Solution: Use test data factories and caching
@classmethod
def setUpClass(cls):
    super().setUpClass()
    # Create shared test data once
    cls.shared_member = cls.factory.create_member()
```

### Debug Helpers

```python
# Debug helper functions
def print_sql_queries():
    """Print all SQL queries for debugging"""
    for query in frappe.db.query_log:
        print(query)

def inspect_permissions(doctype, user):
    """Inspect user permissions"""
    frappe.set_user(user)
    perms = frappe.get_permissions(doctype)
    print(f"Permissions for {user} on {doctype}:")
    for perm in perms:
        print(f"  {perm}")
```

## Best Practices Summary

1. **Always use test factories** for consistent test data
2. **Clean up test data** in tearDown or use factories with auto-cleanup
3. **Test both success and failure paths**
4. **Include performance assertions** in critical path tests
5. **Use descriptive test names** that explain what is being tested
6. **Group related tests** in test classes
7. **Mock external dependencies** (email, SMS, payment gateways)
8. **Test with different user roles** to ensure proper access control
9. **Include edge cases** in your test suite
10. **Monitor test execution time** and optimize slow tests

## Additional Resources

- [Frappe Testing Documentation](https://frappeframework.com/docs/user/en/testing)
- [Python unittest Documentation](https://docs.python.org/3/library/unittest.html)
- [Jest Testing Documentation](https://jestjs.io/docs/getting-started)
- [Test Coverage Best Practices](https://martinfowler.com/bliki/TestCoverage.html)
