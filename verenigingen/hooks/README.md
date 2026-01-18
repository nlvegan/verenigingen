# Hooks Package

This directory contains the Frappe hooks configuration for the Verenigingen app, organized by concern into focused submodules.

## Structure

```
hooks/
├── __init__.py      # Entry point - imports from submodules, app metadata
├── assets.py        # CSS/JS includes (app_include_css, app_include_js, etc.)
├── doctypes.py      # DocType JS mappings (doctype_js)
├── doc_events.py    # Document event handlers (validate, on_submit, etc.)
├── scheduler.py     # Scheduled tasks (daily, hourly, weekly, cron)
├── permissions.py   # Permission query conditions and has_permission
├── fixtures.py      # Fixture definitions for data export/import
├── portal.py        # Portal menu items and website context
├── lifecycle.py     # Install/migrate/auth hooks
└── README.md        # This file
```

## Adding New Hooks

### Document Events

Add handlers to `doc_events.py`:

```python
# In doc_events.py
doc_events = {
    "My DocType": {
        "validate": "verenigingen.module.my_handler.validate_my_doctype",
        "on_submit": "verenigingen.module.my_handler.on_my_doctype_submit",
    },
    # ... existing entries
}
```

**Handler contract:**
- Handlers must be module-level functions (not class methods)
- Signature: `def handler(doc, method=None)`
- Should be lightweight - enqueue heavy work via `frappe.enqueue()`
- Must not have side effects at import time

### Scheduled Tasks

Add tasks to `scheduler.py`:

```python
# In scheduler.py
scheduler_events = {
    "daily": [
        "verenigingen.module.my_task.run_daily_task",
        # ... existing entries
    ],
}
```

**Task requirements:**
- Must be idempotent (safe to run multiple times)
- Should handle own error recovery
- Log meaningful progress information

### Cron Jobs

We use **6-field cron format** (with seconds):

```python
# In scheduler.py
cron = {
    # Format: second minute hour day month day_of_week
    "*/10 * * * * *": ["verenigingen.module.task.run_every_10_seconds"],
    "0 0 2 * * *": ["verenigingen.module.task.run_at_2am"],
}
```

## Testing New Hooks

After adding hooks, run the hooks test suite:

```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests \
    --app verenigingen \
    --module verenigingen.tests.test_hooks_modules
```

The tests verify:
1. All handler strings resolve to callable functions
2. All submodules import without side effects (no DB/cache calls)
3. Override classes are importable and are actual classes
4. Cron expressions are valid format

## Import Safety

**Critical:** Hooks submodules must be purely declarative.

DO NOT:
- Call `frappe.db.*` at module level
- Call `frappe.get_doc()` at module level
- Call `frappe.cache()` at module level
- Import modules that have import-time side effects

DO:
- Define dicts, lists, and strings only
- Keep all logic in the handler functions themselves
- Use lazy imports inside handlers if needed

## DocType Class Overrides

Override classes in `__init__.py`:

```python
override_doctype_class = {
    "Payment Entry": "verenigingen.overrides.payment_entry.PaymentEntry"
}
```

The target must be an actual class that inherits from the original DocType controller.

## Migration from hooks.py

This package structure replaced the monolithic `hooks.py` file. The migration:

1. Split 1106-line file into 9 focused modules
2. Maintained all existing hook registrations
3. Added comprehensive test coverage
4. Fixed bugs (duplicate declarations, incorrect handlers)

See `docs/remediation/HOOKS_SIMPLIFICATION_PLAN.md` for full migration details.
