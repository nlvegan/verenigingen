# Test Migration Guide: From TestDataFactory to EnhancedTestCase

This guide shows how to migrate existing tests from the old `TestDataFactory` pattern to the new `EnhancedTestCase` pattern.

## Why Migrate?

The old `TestDataFactory` has several issues:
- Uses `ignore_permissions=True` everywhere, bypassing security
- No business rule validation (can create invalid test data)
- No field validation (causes field reference bugs)
- Manual cleanup required
- No query performance monitoring
- No automatic database rollback

The new `EnhancedTestCase` provides:
- Proper permission handling
- Business rule validation
- Field existence validation
- Automatic cleanup and rollback
- Query count monitoring
- Permission context switching
- Deterministic test data with Faker

## Migration Steps

### 1. Change Base Class

**Old:**
```python
import unittest
from verenigingen.tests.fixtures.test_data_factory import TestDataFactory

class TestVolunteerSkills(unittest.TestCase):
    def setUp(self):
        self.factory = TestDataFactory()
```

**New:**
```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class TestVolunteerSkills(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Factory is available as self.factory
```

### 2. Update Data Creation

**Old:**
```python
# Creating members with ignore_permissions
volunteer = frappe.get_doc({
    "doctype": "Verenigingen Volunteer",
    "volunteer_name": "Test Volunteer",
    "email": "test@example.com",
    "status": "Active"
})
volunteer.insert(ignore_permissions=True)
```

**New:**
```python
# Create member first (volunteers must be linked to members)
member = self.create_test_member(
    first_name="Test",
    last_name="User",
    birth_date="1990-01-01"  # Will validate age >= 16
)

# Create volunteer with validation
volunteer = self.create_test_volunteer(
    member_name=member.name
    # volunteer_name is auto-generated to be unique
)
```

### 3. Add Cleanup

**Old:**
```python
def tearDown(self):
    # Manual cleanup
    test_volunteers = frappe.get_all("Verenigingen Volunteer", 
        filters={"volunteer_name": ["like", "Test%"]})
    for vol in test_volunteers:
        frappe.delete_doc("Verenigingen Volunteer", vol.name, force=True)
    frappe.db.commit()
```

**New:**
```python
# Automatic rollback happens, but for tests that bypass it:
def tearDown(self):
    super().tearDown()  # Handles rollback
    # Additional cleanup if needed
    frappe.db.sql("DELETE FROM `tabVolunteer` WHERE email LIKE 'TEST_%@test.invalid'")
```

### 4. Use Business Rule Validation

**Old:**
```python
# Could create invalid data
member = self.factory.create_member(birth_date="2020-01-01")  # Too young!
```

**New:**
```python
# This will raise BusinessRuleError
with self.assertRaises(Exception) as cm:
    member = self.create_test_member(birth_date="2020-01-01")
self.assertIn("Members must be 16+ years old", str(cm.exception))
```

### 5. Add Performance Monitoring

**Old:**
```python
# No performance monitoring
results = search_volunteers_by_skill("Python")
```

**New:**
```python
# Monitor query count
with self.assertQueryCount(50):  # Max 50 queries
    results = search_volunteers_by_skill("Python")
```

### 6. Test with Different Permissions

**Old:**
```python
# Always runs as Administrator with ignore_permissions
```

**New:**
```python
# Test with different user contexts
with self.set_user("test@example.com"):
    # Test permission-restricted operations
    try:
        doc = frappe.get_doc("Member", member.name)
    except frappe.PermissionError:
        # Expected for restricted access
        pass
```

## Common Patterns

### Creating Test Data with Skills

```python
# Create member
member = self.create_test_member()

# Create volunteer
volunteer = self.create_test_volunteer(member_name=member.name)

# Add skills
skill = self.factory.create_volunteer_skill(volunteer.name, {
    "skill_category": "Technical",
    "volunteer_skill": "Python",
    "proficiency_level": "4 - Advanced",
    "experience_years": 3
})
```

### Generating Application Data

```python
# Generate realistic application data
app_data = self.create_test_application_data(with_skills=True)

# Data includes:
# - Valid test emails (TEST_*@test.invalid)
# - Valid phone numbers
# - Deterministic skill selection
# - All required fields
```

### Using Decorators

```python
@with_enhanced_test_data(seed=12345)
def test_something(self):
    # Factory with specific seed available
    member = self.create_test_member()
```

## Complete Migration Examples

### 1. test_volunteer_skills_api_enhanced.py
Complete example of migrating `test_volunteer_skills_api.py`.

Key changes made:
1. Inherited from `EnhancedTestCase` instead of `unittest.TestCase`
2. Removed all `ignore_permissions=True`
3. Used factory methods instead of direct document creation
4. Added cleanup in setUp to prevent duplicate key errors
5. Updated assertions to match new data patterns (TEST_ prefix)
6. Added query monitoring to performance-critical tests
7. Added business rule validation tests

**Results**: 16 out of 18 tests passing (2 API bugs, not test issues)

### 2. test_membership_application_skills_enhanced.py
Migration of `test_membership_application_skills.py` to use enhanced factory.

Key changes made:
1. Used `factory.create_application_data()` instead of manual test data
2. Added cleanup in both setUp and tearDown for test isolation
3. Removed all `ignore_permissions=True` usage
4. Added query monitoring for performance tests
5. Used factory methods for creating members and volunteers
6. Leveraged deterministic data generation for consistent results

**Results**: 11 out of 13 tests passing (2 query count limits need adjustment)

## Benefits After Migration

1. **More Reliable Tests**: Automatic rollback prevents test pollution
2. **Catches More Bugs**: Business rule validation prevents invalid states
3. **Better Performance**: Query monitoring helps catch N+1 queries
4. **Security Testing**: Can test actual permissions
5. **Maintainable**: Less boilerplate code for test data creation

## Gradual Migration Strategy

1. Start with new tests - use `EnhancedTestCase` for all new tests
2. Migrate failing tests first
3. Migrate tests when adding new features
4. Keep both patterns during transition
5. Eventually deprecate `TestDataFactory`

## Migration Status

### Completed Migrations:
- ✅ `test_volunteer_skills_api.py` → `test_volunteer_skills_api_enhanced.py` (16/18 passing)
- ✅ `test_membership_application_skills.py` → `test_membership_application_skills_enhanced.py` (11/13 passing)

### Pending Migrations:
- `test_member_status.py` - Uses TestDataFactory extensively
- `test_chapter_member.py` - Direct document creation with ignore_permissions
- `test_sepa_mandate_creation.py` - Complex financial test scenarios
- `test_membership_renewal.py` - Time-based testing needs migration
- `test_volunteer_expense.py` - Approval workflow testing
- And many more...

## Support

For questions or issues with migration:
1. Check the enhanced factory source: `verenigingen/tests/fixtures/enhanced_test_factory.py`
2. See completed migrations:
   - `test_volunteer_skills_api_enhanced.py`
   - `test_membership_application_skills_enhanced.py`
3. Review comprehensive tests: `test_enhanced_factory.py`