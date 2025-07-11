# Verenigingen Scripts

This directory contains organized debug, test, validation, setup, and migration scripts for the Verenigingen app.

## Directory Structure

- **`admin/`** - Administrative operations and system management
- **`api_maintenance/`** - API maintenance scripts (moved from API directory)
- **`debug/`** - Debug and troubleshooting scripts organized by component
- **`testing/`** - Test scripts and test runners organized by type
- **`validation/`** - Feature and migration validation scripts
- **`setup/`** - Setup and configuration scripts
- **`migration/`** - Data migration scripts
- **`tools/`** - Developer tools and helpers
- **`optimization/`** - Performance optimization and monitoring scripts
- **`deployment/`** - Deployment-related scripts and checks
- **`monitoring/`** - System monitoring integration scripts

## Usage

### Debug Scripts
```bash
# Debug board member issues
python scripts/debug/board/debug_board_addition.py

# Debug employee creation
python scripts/debug/employee/debug_employee_creation.py

# Debug chapter-related issues
python scripts/debug/chapter/bench_debug_chapter.py

# Fix expense claim account configuration
python scripts/debug/fix_expense_claim_accounts.py
```

### Test Runners
```bash
# Run comprehensive regression tests
python scripts/testing/runners/regression_test_runner.py

# Run ERPNext expense integration tests
python scripts/testing/runners/run_erpnext_expense_tests.py

# Run volunteer portal tests
python scripts/testing/runners/run_volunteer_portal_tests.py

# Test contact request workflow
python scripts/testing/runners/test_contact_request_workflow.py
```

### Validation Scripts
```bash
# Validate specific features
python scripts/validation/features/validate_bank_details.py
python scripts/validation/features/validate_member_portal.py
python scripts/validation/features/validate_contact_request_implementation.py

# General validation check
python scripts/validation/validation_check.py
```

### Setup Scripts
```bash
# Set up member portal home page
python scripts/setup/setup_member_portal_home.py

# Add chapter tracking fields
python scripts/setup/add_chapter_tracking_fields.py

# Set up policy-covered expense categories
python scripts/setup/setup_policy_expenses.py
```

### Migration Scripts
```bash
# Migrate amendment data
python scripts/migration/migrate_amendment_data.py

# Fix team assignment history
python scripts/migration/fix_team_assignment_history.py
```

### Developer Tools
```bash
# Regression helper for Claude Code
python scripts/tools/claude_regression_helper.py

# Console commands
python scripts/tools/console_commands.py
```

## Script Categories

Each subdirectory contains scripts focused on specific aspects of the Verenigingen system:

1. **Debug** - Troubleshooting and diagnostic scripts
2. **Testing** - Unit tests, integration tests, and test runners
3. **Validation** - Feature validation and migration verification
4. **Setup** - System configuration and setup scripts
5. **Migration** - Data migration and structure updates
6. **Tools** - Development utilities and helpers

## Adding New Scripts

When adding new scripts, place them in the appropriate subdirectory based on their purpose:

- Debug/troubleshooting → `debug/[component]/`
- Tests → `testing/[type]/[component]/`
- Feature validation → `validation/features/`
- Setup/configuration → `setup/`
- Data migration → `migration/`
- Development tools → `tools/`

Each script should include proper documentation and error handling.
