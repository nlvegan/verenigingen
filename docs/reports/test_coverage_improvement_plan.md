# Test Coverage Improvement Plan

## Issues Identified

1. **Test Suite Fragmentation**: Tests exist but don't run in a cohesive way that catches missing methods
2. **Schema Mismatches**: Tests fail due to database schema differences between test and production
3. **Mock vs Real Execution**: Tests may be mocking critical business logic paths
4. **No End-to-End Integration**: Tests don't validate the complete workflow from UI to database

## Immediate Actions

### 1. Fix Current Test Issues

**Missing Schema Elements:**
- Sales Invoice is missing `membership` field that tests expect
- Other doctypes may be missing expected fields

**Action:** Create a schema validation script to ensure test and production schemas match

### 2. Add Business Logic Integration Tests

**Create comprehensive integration tests that:**
- Test complete workflows (create member → create membership → submit → verify all effects)
- Don't mock critical business logic methods
- Validate database state changes
- Test error conditions

### 3. Improve Test Reliability

**Current Problems:**
- Tests pass when methods are missing (shouldn't happen)
- Tests fail due to schema issues (infrastructure problems)
- Tests are not representative of production behavior

**Solutions:**
- Add assertion helpers that verify method existence
- Create production-like test environment
- Add smoke tests that validate core functionality

### 4. Add Regression Test Categories

**Add these test categories:**
- `test_critical_business_logic`: Tests that must pass for basic functionality
- `test_schema_requirements`: Tests that validate database schema matches expectations
- `test_integration_workflows`: End-to-end tests that mirror user workflows
- `test_error_scenarios`: Tests that validate error handling and edge cases

## Specific Test Improvements

### For Membership Doctype

```python
def test_membership_submission_calls_required_methods(self):
    """Test that membership submission calls all required methods"""
    # Create membership
    membership = create_test_membership()

    # Verify method exists before testing
    self.assertTrue(hasattr(membership, 'update_member_status'),
                   "update_member_status method must exist")

    # Mock the method to verify it's called
    with patch.object(membership, 'update_member_status') as mock_method:
        membership.submit()
        mock_method.assert_called_once()

    # Verify actual effects
    membership.reload()
    self.assertEqual(membership.status, 'Active')
    # ... other assertions
```

### For Schema Validation

```python
def test_required_fields_exist(self):
    """Test that all required fields exist in database"""
    # Test Sales Invoice has membership field
    meta = frappe.get_meta("Sales Invoice")
    self.assertTrue(any(f.fieldname == 'membership' for f in meta.fields),
                   "Sales Invoice must have membership field")

    # Test Member has required fields
    meta = frappe.get_meta("Member")
    required_fields = ['interested_in_volunteering', 'status', 'email']
    for field in required_fields:
        self.assertTrue(any(f.fieldname == field for f in meta.fields),
                       f"Member must have {field} field")
```

### For Integration Testing

```python
def test_complete_membership_workflow(self):
    """Test complete workflow from member creation to membership submission"""
    # Create member
    member = create_test_member()

    # Create membership
    membership = create_test_membership(member=member.name)

    # Submit membership
    membership.submit()

    # Verify all effects
    membership.reload()
    member.reload()

    # Check membership status
    self.assertEqual(membership.status, 'Active')

    # Check subscription was created
    self.assertIsNotNone(membership.subscription)

    # Check member status was updated
    self.assertEqual(member.status, 'Active')

    # Check invoice was created
    invoices = frappe.get_all("Sales Invoice",
                             filters={"customer": member.customer})
    self.assertEqual(len(invoices), 1)
```

## Implementation Priority

1. **High Priority**: Fix schema mismatches causing test failures
2. **High Priority**: Add method existence checks to prevent missing method issues
3. **Medium Priority**: Add comprehensive integration tests
4. **Medium Priority**: Improve test data management and cleanup
5. **Low Priority**: Add performance testing for business logic

## Test Execution Strategy

**Daily Regression Tests:**
- Run critical business logic tests
- Run schema validation tests
- Run integration workflow tests

**Pre-deployment Tests:**
- Run complete test suite
- Run performance tests
- Run error scenario tests

**Development Tests:**
- Run unit tests for changed components
- Run integration tests for affected workflows
- Run smoke tests for overall functionality
