# Script Organization Plan

This document outlines the reorganization of debug and test scripts from the root directory into a proper organized structure.

## Current Root-Level Scripts (26 total)

### Debug Scripts (5):
- `bench_debug_chapter.py`
- `debug_board_addition.py`
- `debug_board_console.py`
- `debug_chapter_membership.py`
- `debug_employee_creation.py`

### Test Scripts (16):
- `simple_board_test.py`
- `test_auto_employee_creation.py`
- `test_board_manual.py`
- `test_board_member_addition.py`
- `test_employee_creation.py`
- `test_employee_fix.py`
- `test_expense_integration_complete.py`
- `test_integration_simple.py`
- `test_permission_fix.py`
- `test_sepa_scheduler.py`
- `test_volunteer_creation_fix.py`
- `test_volunteer_creation_unit.py`
- `test_volunteer_permissions.py`

### Test Runners (3):
- `regression_test_runner.py`
- `run_erpnext_expense_tests.py`
- `run_volunteer_portal_tests.py`

### Validation Scripts (5):
- `validate_bank_details.py`
- `validate_configurable_email.py`
- `validate_contribution_amendment_rename.py`
- `validate_member_portal.py`
- `validate_personal_details.py`
- `validation_check.py`

### Setup/Migration Scripts (8):
- `add_chapter_tracking_fields.py`
- `claude_regression_helper.py`
- `console_commands.py`
- `fix_team_assignment_history.py`
- `manual_employee_creation.py`
- `migrate_amendment_data.py`
- `migration_commands.py`
- `setup_member_portal_home.py`

## Proposed Organization Structure

```
verenigingen/
├── scripts/                           # NEW: All scripts organized here
│   ├── debug/                        # Debug and troubleshooting scripts
│   │   ├── __init__.py
│   │   ├── board/                    # Board-related debugging
│   │   │   ├── __init__.py
│   │   │   ├── debug_board_addition.py
│   │   │   ├── debug_board_console.py
│   │   │   └── debug_chapter_membership.py
│   │   ├── employee/                 # Employee-related debugging
│   │   │   ├── __init__.py
│   │   │   └── debug_employee_creation.py
│   │   ├── chapter/                  # Chapter-related debugging
│   │   │   ├── __init__.py
│   │   │   └── bench_debug_chapter.py
│   │   └── README.md                 # Debug script documentation
│   ├── testing/                      # Test scripts and runners
│   │   ├── __init__.py
│   │   ├── runners/                  # Test runners
│   │   │   ├── __init__.py
│   │   │   ├── regression_test_runner.py
│   │   │   ├── run_erpnext_expense_tests.py
│   │   │   └── run_volunteer_portal_tests.py
│   │   ├── integration/              # Integration tests
│   │   │   ├── __init__.py
│   │   │   ├── test_expense_integration_complete.py
│   │   │   ├── test_integration_simple.py
│   │   │   └── test_sepa_scheduler.py
│   │   ├── unit/                     # Unit tests
│   │   │   ├── __init__.py
│   │   │   ├── board/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── simple_board_test.py
│   │   │   │   ├── test_board_manual.py
│   │   │   │   └── test_board_member_addition.py
│   │   │   ├── employee/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── test_auto_employee_creation.py
│   │   │   │   ├── test_employee_creation.py
│   │   │   │   └── test_employee_fix.py
│   │   │   ├── volunteer/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── test_volunteer_creation_fix.py
│   │   │   │   ├── test_volunteer_creation_unit.py
│   │   │   │   └── test_volunteer_permissions.py
│   │   │   └── permissions/
│   │   │       ├── __init__.py
│   │   │       └── test_permission_fix.py
│   │   └── README.md                 # Testing documentation
│   ├── validation/                   # Validation and verification scripts
│   │   ├── __init__.py
│   │   ├── features/                 # Feature validation
│   │   │   ├── __init__.py
│   │   │   ├── validate_bank_details.py
│   │   │   ├── validate_configurable_email.py
│   │   │   ├── validate_member_portal.py
│   │   │   └── validate_personal_details.py
│   │   ├── migrations/               # Migration validation
│   │   │   ├── __init__.py
│   │   │   └── validate_contribution_amendment_rename.py
│   │   ├── validation_check.py       # General validation
│   │   └── README.md                 # Validation documentation
│   ├── setup/                        # Setup and configuration scripts
│   │   ├── __init__.py
│   │   ├── setup_member_portal_home.py
│   │   ├── add_chapter_tracking_fields.py
│   │   └── README.md
│   ├── migration/                    # Data migration scripts
│   │   ├── __init__.py
│   │   ├── migrate_amendment_data.py
│   │   ├── migration_commands.py
│   │   ├── fix_team_assignment_history.py
│   │   ├── manual_employee_creation.py
│   │   └── README.md
│   ├── tools/                        # Developer tools and helpers
│   │   ├── __init__.py
│   │   ├── claude_regression_helper.py
│   │   ├── console_commands.py
│   │   └── README.md
│   └── README.md                     # Main scripts documentation
├── debug_utils/                      # EXISTING: Keep as is (focused utilities)
├── dev_scripts/                      # EXISTING: Keep as is (dev helpers)
├── integration_tests/                # EXISTING: Keep as is (integration tests)
└── [rest of existing structure]
```

## Benefits of This Organization

1. **Clear Separation**: Debug, test, validation, setup, and migration scripts are clearly separated
2. **Logical Grouping**: Related scripts are grouped by functionality (board, employee, volunteer, etc.)
3. **Discoverability**: Easy to find the right script for the task
4. **Maintainability**: Clear structure makes maintenance easier
5. **Documentation**: Each category has its own README
6. **Scalability**: Easy to add new scripts in the right location

## Migration Strategy

1. Create the new directory structure
2. Move scripts to appropriate locations
3. Update any imports or references
4. Create README files for each category
5. Update main project documentation
6. Test that all scripts still work after moving
7. Remove old files from root directory

## Backward Compatibility

- Keep imports working by adding compatibility shims if needed
- Update any documentation that references old paths
- Ensure CI/CD scripts are updated
