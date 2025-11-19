# Debug Scripts

Debug and troubleshooting scripts organized by component.

## Expense System Debugging

- **`fix_expense_claim_accounts.py`** - Fix expense claim account configuration issues

## General Debugging

- **`debug_custom_amount.py`** - Debug custom amount functionality
- **`debug_team_assignment.py`** - Debug team assignment issues
- **`debug_volunteer_lookup.py`** - Debug volunteer lookup functionality

## Board Member Debugging (`board/`)

- **`debug_board_addition.py`** - Debug board member addition issues
- **`debug_board_console.py`** - Interactive board member debugging console
- **`debug_chapter_membership.py`** - Debug chapter membership issues

## Employee Debugging (`employee/`)

- **`debug_employee_creation.py`** - Debug employee record creation issues

## Chapter Debugging (`chapter/`)

- **`bench_debug_chapter.py`** - Debug chapter-related issues using bench context

## Usage

Run debug scripts to troubleshoot specific issues:

```bash
# Fix expense claim accounts
python scripts/debug/fix_expense_claim_accounts.py

# Debug general functionality
python scripts/debug/debug_custom_amount.py
python scripts/debug/debug_team_assignment.py
python scripts/debug/debug_volunteer_lookup.py

# Debug board member addition
python scripts/debug/board/debug_board_addition.py

# Debug employee creation
python scripts/debug/employee/debug_employee_creation.py

# Debug chapter issues
python scripts/debug/chapter/bench_debug_chapter.py
```

## Adding Debug Scripts

When adding new debug scripts:

1. Place in appropriate component subdirectory
2. Include clear documentation of what the script debugs
3. Add usage examples
4. Include error handling and informative output
