# Test and Development File Organization

This document describes the reorganized test and development file structure for the Verenigingen app.

## Directory Structure

### 🧪 Core Testing Infrastructure
- **`verenigingen/tests/`** - Main test suite with comprehensive coverage
  - Core test runner (`test_runner.py`)
  - Test data factory (`test_data_factory.py`)
  - Environment validator (`test_environment_validator.py`)
  - 26 comprehensive test files following proper naming conventions

### 🔍 Development Utilities
- **`debug_utils/`** - Debug and troubleshooting scripts
  - `debug_custom_amount.py` - Debug custom membership amounts
  - `debug_team_assignment.py` - Debug team assignment issues
  - `debug_volunteer_lookup.py` - Debug volunteer lookup functionality

- **`dev_scripts/`** - Development and validation scripts
  - `check_amendments.py` - Validate amendment system
  - `check_workspace.py` - Validate workspace configuration
  - `simple_test.py` - Quick validation script
  - `quick_fee_test.py` - Rapid fee testing

- **`integration_tests/`** - Focused integration and component tests
  - `test_amendment_filtering.py` - Amendment system filtering logic
  - `test_assignment_simple.py` - Basic assignment testing
  - `test_custom_amount_flow.py` - Custom amount workflow testing
  - `test_expiring_memberships.py` - Membership expiration testing
  - `test_fee_override.py` - Fee override functionality
  - `test_fee_override_permissions.py` - Fee override permission testing
  - `test_portal_summary.py` - Portal functionality testing
  - `test_smoke.py` - Basic smoke tests
  - `test_team_removal.py` - Team removal functionality
  - `test_volunteer_creation.py` - Volunteer creation workflow

- **`frontend_tests/`** - JavaScript/Frontend test files
  - `test_member_advanced.js` - Advanced member form testing
  - `test_member_comprehensive.js` - Comprehensive member testing
  - `test_member_enhanced.js` - Enhanced member functionality
  - `test_member_validation.js` - Member validation testing

### 🏃‍♂️ Test Runners
- **`run_volunteer_portal_tests.py`** - Volunteer portal test suite runner
- **`claude_regression_helper.py`** - Regression and performance testing
- **`regression_test_runner.py`** - Git change-based testing

## Test Running Commands

### Comprehensive Test Suites
```bash
# Main test runner with multiple modes
python verenigingen/tests/test_runner.py smoke
python verenigingen/tests/test_runner.py diagnostic
python verenigingen/tests/test_runner.py all

# Volunteer portal testing
python run_volunteer_portal_tests.py --suite core
python run_volunteer_portal_tests.py --suite security
python run_volunteer_portal_tests.py --suite edge
python run_volunteer_portal_tests.py --coverage

# Regression testing
python claude_regression_helper.py pre-change
python claude_regression_helper.py targeted member
python claude_regression_helper.py post-change
python regression_test_runner.py
```

### Development Testing
```bash
# Quick validation
python dev_scripts/simple_test.py
python dev_scripts/quick_fee_test.py

# System validation
python dev_scripts/check_amendments.py
python dev_scripts/check_workspace.py

# Debug utilities
python debug_utils/debug_volunteer_lookup.py
python debug_utils/debug_team_assignment.py
python debug_utils/debug_custom_amount.py
```

### Integration Testing
```bash
# Individual component tests
python integration_tests/test_amendment_filtering.py
python integration_tests/test_volunteer_creation.py
python integration_tests/test_fee_override_permissions.py

# Smoke testing
python integration_tests/test_smoke.py
```

### Frappe Native Testing
```bash
# Run specific test modules
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_volunteer_portal_working
bench --site dev.veganisme.net run-tests --app verenigingen --module verenigingen.tests.test_termination_system
```

## File Organization Benefits

1. **Clear Separation of Concerns**
   - Core test infrastructure remains in the proper `tests/` folder
   - Development utilities are separated from production tests
   - Debug scripts are easily accessible but not part of main test runs

2. **Maintained Automation**
   - Existing automated test runners continue to work
   - Path references preserved for critical test infrastructure
   - No breaking changes to established workflows

3. **Better Developer Experience**
   - Easy to find relevant debugging tools
   - Clear distinction between different types of testing
   - Reduced clutter in root directory

4. **Future Maintenance**
   - Easier to add new tests in appropriate categories
   - Clear patterns for new contributors
   - Better organization for CI/CD integration

## Migration Notes

- **Removed duplicate:** `test_team_assignment_history.py` (kept comprehensive version in `verenigingen/tests/`)
- **Preserved automation:** All existing test runners work without modification
- **Safe organization:** No breaking changes to critical testing infrastructure
- **Documentation:** Added examples for running different test categories

## Next Steps (Optional)

Future improvements could include:
- Consolidating `verenigingen/verenigingen/tests/` content into main test folder
- Adding test categories to main test runner
- Creating unified test configuration
- Adding automated test organization validation
