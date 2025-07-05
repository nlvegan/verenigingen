# Testing Scripts

Test scripts and test runners organized by type and component.

## Test Runners (`runners/`)

- **`regression_test_runner.py`** - Comprehensive regression test runner
- **`run_erpnext_expense_tests.py`** - ERPNext expense integration test runner
- **`run_volunteer_portal_tests.py`** - Volunteer portal test runner
- **`run_expense_integration_tests.py`** - Expense integration test runner
- **`test_contact_request_workflow.py`** - Contact request workflow test runner
- **`run_chapter_membership_regression_tests.py`** - Chapter membership validation regression test runner

## Integration Tests (`integration/`)

### Expense Integration Tests
- **`test_expense_integration_complete.py`** - Complete expense system integration test
- **`simple_expense_test.py`** - Simple expense workflow integration test
- **`test_expense_functionality.py`** - ERPNext expense functionality integration test
- **`test_expense_integration_simple.py`** - Simple expense integration validation test
- **`test_expense_simple.py`** - Basic expense functionality test
- **`test_expense_submission_integration.py`** - Complete expense submission workflow integration test

### General Integration Tests
- **`test_integration_simple.py`** - Simple integration test
- **`test_sepa_scheduler.py`** - SEPA scheduler integration test

### Legacy Integration Tests (Moved from dev_scripts/)
- **`check_amendments.py`** - Amendment system check
- **`check_workspace.py`** - Workspace functionality check
- **`quick_fee_test.py`** - Quick fee testing
- **`simple_test.py`** - Simple system test

### Membership & Fee Tests (Moved from integration_tests/)
- **`test_amendment_filtering.py`** - Amendment filtering test
- **`test_custom_amount_flow.py`** - Custom amount workflow test
- **`test_expiring_memberships.py`** - Expiring membership handling test
- **`test_fee_override.py`** - Fee override functionality test
- **`test_fee_override_permissions.py`** - Fee override permissions test
- **`test_portal_summary.py`** - Portal summary integration test

### Team & Volunteer Tests (Moved from integration_tests/)
- **`test_assignment_simple.py`** - Simple assignment test
- **`test_team_removal.py`** - Team removal workflow test
- **`test_volunteer_creation.py`** - Volunteer creation integration test

### System Tests
- **`test_smoke.py`** - Smoke testing for system health

## Unit Tests (`unit/`)

### Board Tests (`unit/board/`)
- **`simple_board_test.py`** - Simple board functionality test
- **`test_board_manual.py`** - Manual board testing
- **`test_board_member_addition.py`** - Board member addition unit test

### Employee Tests (`unit/employee/`)
- **`test_auto_employee_creation.py`** - Automatic employee creation test
- **`test_employee_creation.py`** - Employee creation unit test
- **`test_employee_fix.py`** - Employee-related fixes test

### Volunteer Tests (`unit/volunteer/`)
- **`test_volunteer_creation_fix.py`** - Volunteer creation fix test
- **`test_volunteer_creation_unit.py`** - Volunteer creation unit test
- **`test_volunteer_permissions.py`** - Volunteer permissions test

### Permission Tests (`unit/permissions/`)
- **`test_permission_fix.py`** - Permission system fix test

### Expense Tests (`unit/expense/`)
- **`test_policy_expenses.py`** - Policy-covered expense functionality test

## Frontend Tests (`frontend/`)

- **`test_member_advanced.js`** - Advanced member functionality JavaScript tests
- **`test_member_comprehensive.js`** - Comprehensive member testing
- **`test_member_enhanced.js`** - Enhanced member feature tests
- **`test_member_validation.js`** - Member validation JavaScript tests

## Usage

### Run Test Suites
```bash
# Run all regression tests
python scripts/testing/runners/regression_test_runner.py

# Run ERPNext expense tests with options
python scripts/testing/runners/run_erpnext_expense_tests.py --suite all --verbose

# Run volunteer portal tests
python scripts/testing/runners/run_volunteer_portal_tests.py --suite core

# Run chapter membership regression tests
python scripts/testing/runners/run_chapter_membership_regression_tests.py
python scripts/testing/runners/run_chapter_membership_regression_tests.py --quick
```

### Run Individual Tests
```bash
# Run specific integration test
python scripts/testing/integration/test_expense_integration_complete.py

# Run specific unit test
python scripts/testing/unit/board/test_board_member_addition.py
```

## Test Organization

- **Runners** - Execute multiple tests and provide reporting
- **Integration** - Test component interactions and workflows
- **Unit** - Test individual components and functions

Each test category is further organized by component (board, employee, volunteer, permissions) for easy navigation.
