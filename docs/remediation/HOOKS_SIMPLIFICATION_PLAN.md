# Hooks.py Simplification Plan

## Executive Summary

This plan addresses the complexity and maintainability issues in `verenigingen/hooks.py`, a 1106-line configuration file that has grown to handle too many concerns. The goal is to create a thin hooks.py that imports from small, focused modules organized by concern.

## Current State Analysis

### File Metrics
- **Total lines:** 1106
- **Docstring:** 262 lines (23% of file - excessive documentation that belongs elsewhere)
- **doc_events:** 238 lines (21% - the largest functional section)
- **scheduler_events:** 103 lines (9%)
- **fixtures:** 200+ lines (18%)
- **permissions:** 32 lines
- **other config:** ~270 lines

### Problems Identified

1. **Single File Concentration**
   - All configuration concerns mixed in one file
   - Hard to find specific configurations
   - High merge conflict risk when multiple developers work on different concerns

2. **Excessive Documentation in Code**
   - 262-line docstring with usage examples belongs in documentation, not runtime code
   - Slows down import time slightly
   - Clutters the actual configuration

3. **Large Literal Dictionaries**
   - `doc_events` dictionary spans 238 lines
   - `scheduler_events` spans 103 lines
   - `fixtures` list spans 200+ lines
   - These make the file hard to navigate and maintain

4. **Mixed Concerns**
   - Asset configuration
   - DocType JavaScript mappings
   - Document event handlers
   - Scheduled tasks
   - Permissions
   - Portal configuration
   - Fixtures
   - Auth hooks
   - CLI commands
   - All in one place

### Existing Good Patterns

The codebase already has some decoupled patterns we can build on:

1. **`vereinigingen/events/`** - Event emitters and subscribers already exist
   - `invoice_events.py`, `chapter_events.py`, `member_events.py`, etc.
   - Good pattern for decoupling event handling

2. **`utils/background_jobs.py`** - `BackgroundJobManager` for async operations
   - Already handles smart enqueueing with status tracking
   - Queue handlers call this manager

3. **Handler functions in `utils/`** - Many handlers already in separate files
   - `utils/cache_invalidation.py`
   - `utils/performance_event_handlers.py`
   - `utils/chapter_role_events.py`

## Target Architecture

**Important:** Frappe loads hooks via `get_module(f"{app}.hooks")`, which works with both:
- `app/hooks.py` (module file)
- `app/hooks/__init__.py` (package)

We'll use the **package approach**: delete `hooks.py` and create `hooks/__init__.py` that imports from submodules.

```
verenigingen/
├── hooks/                      # PACKAGE: replaces hooks.py
│   ├── __init__.py             # ~100 lines: imports from submodules + metadata
│   ├── assets.py               # app_include_css/js, web_include_js, email_css
│   ├── doctypes.py             # doctype_js, doctype_list_js mappings
│   ├── doc_events.py           # doc_events dictionary
│   ├── scheduler.py            # scheduler_events, cron configuration
│   ├── permissions.py          # permission_query_conditions, has_permission
│   ├── fixtures.py             # fixtures list
│   ├── portal.py               # portal menu, website context
│   └── lifecycle.py            # after_install, after_migrate, before_tests
├── events/                     # Already exists - keep as-is
│   ├── invoice_events.py
│   ├── chapter_events.py
│   └── ...
├── utils/                      # Already exists - keep as-is
│   ├── background_jobs.py
│   └── ...
└── services/                   # Already exists - keep as-is
```

### hooks/__init__.py Example

After refactoring, `hooks/__init__.py` will look like:

```python
# verenigingen/hooks/__init__.py
"""Verenigingen application hooks configuration.

This package organizes hooks by concern:
- assets.py: CSS/JS includes
- doctypes.py: DocType JS mappings
- doc_events.py: Document event handlers
- scheduler.py: Scheduled tasks
- permissions.py: Permission queries
- fixtures.py: Fixture definitions
- portal.py: Portal configuration
- lifecycle.py: Install/migrate hooks
"""
from __future__ import unicode_literals

# App metadata
app_name = "verenigingen"
app_title = "Verenigingen"
app_publisher = "Verenigingen"
app_description = "Association Management"
app_icon = "octicon octicon-organization"
app_color = "blue"
app_email = "info@verenigingen.org"
app_license = "AGPL-3"

# Home page
home_page = "verenigingen"

# Boot session
boot_session = "verenigingen.boot.boot_session"

# Import hook configurations from submodules
from verenigingen.hooks.assets import (
    app_include_css,
    app_include_js,
    web_include_js,
    email_css,
)
from verenigingen.hooks.doctypes import doctype_js
from verenigingen.hooks.doc_events import doc_events
from verenigingen.hooks.scheduler import scheduler_events, cron
from verenigingen.hooks.permissions import permission_query_conditions, has_permission
from verenigingen.hooks.fixtures import fixtures
from verenigingen.hooks.portal import (
    standard_portal_menu_items,
    website_context,
    update_website_context,
)
from verenigingen.hooks.lifecycle import (
    after_install,
    after_migrate,
    before_tests,
    on_logout,
)

# Jinja
jinja = {
    "methods": ["verenigingen.utils.jinja_methods"],
    "filters": ["verenigingen.utils.jinja_filters"],
}

# Workflow action handlers
workflow_action_handlers = {
    "Membership Termination Workflow": {
        "Approve": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.on_workflow_action",
        "Execute": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.on_workflow_action",
        "Reject": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.on_workflow_action",
    }
}

# DocType class overrides
override_doctype_class = {
    "Payment Entry": "verenigingen.overrides.payment_entry.PaymentEntry"
}

# CLI commands
commands = [
    "verenigingen.commands.workspace.workspace",
    "verenigingen.commands.workspace_health.workspace_health",
    "verenigingen.commands.workspace_maintenance.workspace_maintenance",
]
```

## Detailed Module Specifications

### 1. `hooks/assets.py`

```python
# verenigingen/hooks/assets.py
"""Asset include configuration for CSS and JavaScript."""

app_include_css = [
    "/assets/verenigingen/css/verenigingen_custom.css",
    "/assets/verenigingen/css/volunteer_portal.css",
    "/assets/verenigingen/css/iban-validation.css",
]

app_include_js = [
    "/assets/verenigingen/js/utils/operation-result-helpers.js",
    "/assets/verenigingen/js/member_portal_redirect.js",
    "/assets/verenigingen/js/utils/iban-validator.js",
    "/assets/verenigingen/js/member_age_chart.js",
]

web_include_js = [
    "/assets/verenigingen/js/utils/operation-result-helpers.js",
]

email_css = [
    "/assets/verenigingen/css/email_brand.css",
]
```

### 2. `hooks/doctypes.py`

```python
# verenigingen/hooks/doctypes.py
"""DocType JavaScript mappings."""

doctype_js = {
    "Member": "verenigingen/doctype/member/member.js",
    "Membership": "public/js/membership.js",
    "Membership Type": "public/js/membership_type.js",
    "Chapter": "public/js/chapter_email_integration.js",
    "Direct Debit Batch": "public/js/direct_debit_batch.js",
    "Membership Termination Request": "public/js/membership_termination_request.js",
    "Expense Claim": "public/js/expense_claim_custom.js",
    "Customer": "public/js/customer_member_link.js",
    "Sales Invoice": "public/js/sales_invoice_ing_checkout.js",
}
```

### 3. `hooks/doc_events.py`

```python
# verenigingen/hooks/doc_events.py
"""Document event handler mappings.

Each handler string points to a function that receives (doc, method=None).
Keep handlers lightweight - heavy processing should be enqueued.
"""

doc_events = {
    # Core membership system events
    "Membership": {
        "on_submit": [
            "verenigingen.verenigingen.doctype.membership.membership.on_submit",
            "verenigingen.utils.performance_cache.on_membership_update",
        ],
        "on_cancel": [
            "verenigingen.verenigingen.doctype.membership.membership.on_cancel",
            "verenigingen.utils.performance_cache.on_membership_update",
        ],
        "on_update": "verenigingen.utils.performance_cache.on_membership_update",
    },
    # ... rest of doc_events
}
```

### 4. `hooks/scheduler.py`

```python
# verenigingen/hooks/scheduler.py
"""Scheduled task configuration.

Tasks are organized by frequency. Each task should:
- Be idempotent (safe to run multiple times)
- Handle its own error recovery
- Log meaningful progress information
"""
import os

def _get_scheduler_events():
    """Build scheduler events dict.

    Can be extended to support environment-specific configuration.
    """
    return {
        "daily": [
            "verenigingen.verenigingen.doctype.member.scheduler.refresh_all_member_financial_histories",
            "verenigingen.email.email_group_sync.scheduled_email_group_sync",
            # ... rest of daily tasks
        ],
        "hourly": [
            "verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule.send_security_policy_change_digest",
            # ... rest of hourly tasks
        ],
        "weekly": [
            "verenigingen.utils.termination_utils.generate_weekly_termination_report",
            # ... rest of weekly tasks
        ],
        "monthly": [
            "verenigingen.tasks.address_optimization.cleanup_orphaned_address_data",
            # ... rest of monthly tasks
        ],
    }

scheduler_events = _get_scheduler_events()

cron = {
    "*/10 * * * * *": [
        "verenigingen.utils.financial_history_batch_processor.schedule_financial_history_processing"
    ]
}
```

### 5. `hooks/permissions.py`

```python
# verenigingen/hooks/permissions.py
"""Permission query conditions and has_permission handlers."""

permission_query_conditions = {
    "Member": "verenigingen.permissions.get_member_permission_query",
    "Membership": "verenigingen.permissions.get_membership_permission_query",
    # ... rest of permission_query_conditions
}

has_permission = {
    "Member": "verenigingen.permissions.has_member_permission",
    "Membership": "verenigingen.permissions.has_membership_permission",
    # ... rest of has_permission
}
```

### 6. `hooks/fixtures.py`

```python
# verenigingen/hooks/fixtures.py
"""Fixture definitions for data export/import.

Note: Reference data (Membership Types, etc.) is created via
execute_after_install() which only runs once on app install.
"""

fixtures = [
    "Property Setter",
    "Custom DocPerm",
    {
        "doctype": "Notification",
        "filters": [
            ["name", "in", [
                "Member Application Approved",
                "Member Application Rejected",
                # ... rest of notifications
            ]]
        ],
    },
    # ... rest of fixtures
]
```

### 7. `hooks/portal.py`

```python
# verenigingen/hooks/portal.py
"""Portal and website configuration."""

standard_portal_menu_items = [
    {
        "title": "Member Portal",
        "route": "/member_portal",
        "reference_doctype": "",
        "role": "Verenigingen Member",
    },
    # ... rest of menu items
]

website_context = {
    "get_member_context": "verenigingen.utils.portal_customization.get_member_context"
}

update_website_context = [
    "verenigingen.utils.portal_customization.add_brand_body_classes"
]
```

### 8. `hooks/lifecycle.py`

```python
# verenigingen/hooks/lifecycle.py
"""Application lifecycle hooks: install, migrate, tests."""

after_install = [
    "verenigingen.setup.execute_after_install",
    "verenigingen.setup.security_setup.setup_all_security",
]

after_migrate = [
    "verenigingen.verenigingen.doctype.brand_settings.brand_settings.create_default_brand_settings",
    "verenigingen.setup.membership_application_workflow_setup.setup_membership_application_workflow",
    "verenigingen.utils.security.setup_all_security",
    "verenigingen.patches.v1_0.add_coverage_duplicate_check_indexes.execute",
    "verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup.run_performance_optimization",
    "verenigingen.patches.v2_1.backfill_membership_commitment_end_date.execute",
    "verenigingen.patches.v2_1.add_chapter_dashboard_performance_indexes.execute",
]

before_tests = "verenigingen.tests.setup.before_tests"

on_logout = "verenigingen.auth_hooks.on_logout"
```

## Migration Strategy

### Phase 1: Create Module Structure (Low Risk)

1. Create `hooks/` directory
2. Create each submodule file with content extracted from hooks.py:
   - `hooks/assets.py`
   - `hooks/doctypes.py`
   - `hooks/doc_events.py`
   - `hooks/scheduler.py`
   - `hooks/permissions.py`
   - `hooks/fixtures.py`
   - `hooks/portal.py`
   - `hooks/lifecycle.py`
3. **Keep hooks.py intact** - the directory and file can coexist temporarily

### Phase 2: Validate Module Isolation (Low Risk)

1. Write import-time tests for each hooks/* submodule
2. Verify no DB calls or side effects on import
3. Verify all handler strings resolve to callable functions
4. Test that each submodule can be imported independently

### Phase 3: Switchover (Medium Risk)

1. Create `hooks/__init__.py` that imports from submodules
2. Rename `hooks.py` to `hooks.py.backup`
3. Run full test suite
4. Test Frappe loads hooks correctly: `bench --site veg11.veganisme.org console` then `frappe.get_hooks()`
5. Deploy to staging

### Phase 4: Cleanup

1. Remove `hooks.py.backup` after successful staging validation
2. Move the 262-line docstring to `docs/HOOKS_ARCHITECTURE.md`
3. Update CLAUDE.md with new structure

## Testing Strategy

### 1. Import-Time Safety Tests

```python
# tests/test_hooks_import.py
import time
import unittest
from unittest.mock import patch

class TestHooksImportSafety(unittest.TestCase):
    """Verify hooks modules don't have side effects on import."""

    def test_hooks_import_time(self):
        """Import should complete in under 100ms."""
        start = time.time()
        import verenigingen.hooks
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1, f"Import took {elapsed:.3f}s")

    def test_no_db_calls_on_import(self):
        """No database calls should happen during import."""
        with patch('frappe.get_doc') as mock_get_doc, \
             patch('frappe.get_all') as mock_get_all, \
             patch('frappe.db.sql') as mock_sql:

            # Force reimport
            import importlib
            import verenigingen.hooks
            importlib.reload(verenigingen.hooks)

            mock_get_doc.assert_not_called()
            mock_get_all.assert_not_called()
            mock_sql.assert_not_called()
```

### 2. Handler Resolution Tests

```python
# tests/test_hooks_handlers.py
import importlib
import unittest

class TestHandlerResolution(unittest.TestCase):
    """Verify all handler strings resolve to callable functions."""

    def test_doc_event_handlers_exist(self):
        """All doc_events handlers should be importable and callable."""
        from verenigingen.hooks.doc_events import doc_events

        for doctype, events in doc_events.items():
            for event_name, handlers in events.items():
                if isinstance(handlers, str):
                    handlers = [handlers]
                for handler in handlers:
                    module_path, func_name = handler.rsplit('.', 1)
                    try:
                        module = importlib.import_module(module_path)
                        func = getattr(module, func_name)
                        self.assertTrue(
                            callable(func),
                            f"{handler} is not callable"
                        )
                    except (ImportError, AttributeError) as e:
                        self.fail(f"Handler {handler} not found: {e}")

    def test_scheduler_handlers_exist(self):
        """All scheduler_events handlers should be importable."""
        from verenigingen.hooks.scheduler import scheduler_events

        for frequency, handlers in scheduler_events.items():
            for handler in handlers:
                module_path, func_name = handler.rsplit('.', 1)
                try:
                    module = importlib.import_module(module_path)
                    func = getattr(module, func_name)
                    self.assertTrue(callable(func))
                except (ImportError, AttributeError) as e:
                    self.fail(f"Scheduler handler {handler} not found: {e}")
```

### 3. Integration Test

```python
# tests/test_hooks_integration.py
import frappe
import unittest

class TestHooksIntegration(unittest.TestCase):
    """Verify hooks work correctly when loaded by Frappe."""

    def test_frappe_loads_hooks(self):
        """Frappe should successfully load our hooks."""
        from frappe import get_hooks

        # Verify key hooks are loaded
        doc_events = get_hooks('doc_events')
        self.assertIn('Member', doc_events)

        scheduler = get_hooks('scheduler_events')
        self.assertIn('daily', scheduler)

    def test_doc_event_fires(self):
        """Test that a document event actually fires the hook."""
        # Create and save a test document, verify hook was called
        # (implementation depends on what's safe to test)
        pass
```

## CI Checks

### 1. Hooks Module Validation Job

```yaml
# .github/workflows/hooks-validation.yml
name: Hooks Validation

on: [push, pull_request]

jobs:
  validate-hooks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Check hooks.py line count
        run: |
          LINES=$(wc -l < verenigingen/hooks.py)
          if [ "$LINES" -gt 150 ]; then
            echo "ERROR: hooks.py has $LINES lines, should be under 150"
            exit 1
          fi
          echo "hooks.py has $LINES lines - OK"

      - name: Verify no function definitions in hooks.py
        run: |
          if grep -E "^def |^class " verenigingen/hooks.py; then
            echo "ERROR: hooks.py should not contain function or class definitions"
            exit 1
          fi
          echo "No function definitions found - OK"

      - name: Import test for hooks modules
        run: |
          python -c "
          import sys
          sys.path.insert(0, '.')

          # Test each hooks module imports without error
          modules = [
              'verenigingen.hooks',
              'verenigingen.hooks.assets',
              'verenigingen.hooks.doctypes',
              'verenigingen.hooks.doc_events',
              'verenigingen.hooks.scheduler',
              'verenigingen.hooks.permissions',
              'verenigingen.hooks.fixtures',
              'verenigingen.hooks.portal',
              'verenigingen.hooks.lifecycle',
          ]

          for mod in modules:
              try:
                  __import__(mod)
                  print(f'✓ {mod}')
              except ImportError as e:
                  print(f'✗ {mod}: {e}')
                  sys.exit(1)
          "
```

### 2. Pre-commit Hook

```yaml
# .pre-commit-config.yaml (add to existing)
  - repo: local
    hooks:
      - id: hooks-size-check
        name: Check hooks.py size
        entry: bash -c 'test $(wc -l < verenigingen/hooks.py) -lt 150'
        language: system
        files: hooks\.py$
```

## Documentation Updates

### Move Docstring to Documentation

The 262-line docstring from hooks.py should be moved to `docs/HOOKS_ARCHITECTURE.md`:

```markdown
# Verenigingen Hooks Architecture

This document describes the hooks configuration architecture for the
Verenigingen association management system...

[Content from current docstring, properly formatted as documentation]
```

### Update CLAUDE.md

Add section about hooks structure:

```markdown
## Hooks Architecture

The `hooks.py` file is kept thin and imports configuration from `hooks/` submodules:

- `hooks/assets.py` - CSS/JS includes
- `hooks/doctypes.py` - DocType JS mappings
- `hooks/doc_events.py` - Document event handlers
- `hooks/scheduler.py` - Scheduled tasks
- `hooks/permissions.py` - Permission queries
- `hooks/fixtures.py` - Fixture definitions
- `hooks/portal.py` - Portal configuration
- `hooks/lifecycle.py` - Install/migrate hooks

When adding new hooks:
1. Add to appropriate submodule
2. Import in hooks.py if needed
3. Run handler resolution tests
```

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| Create hooks/ modules | Low | Doesn't change behavior, just adds files |
| Import from modules | Medium | Extensive testing before switchover |
| Remove old hooks.py | Low | Keep backup until staging validates |
| Remove docstring | Low | Move to docs/ for reference |

## Success Criteria

1. **hooks.py under 150 lines** (from 1106)
2. **All existing tests pass**
3. **No import-time side effects**
4. **All handler strings resolve**
5. **CI validates structure**
6. **Documentation updated**

## Timeline

| Phase | Tasks | Status |
|-------|-------|--------|
| 1 | Create hooks/ directory structure | Pending |
| 2 | Write import-time safety tests | Pending |
| 3 | Write handler resolution tests | Pending |
| 4 | Create thin hooks.py | Pending |
| 5 | Run full test suite | Pending |
| 6 | Deploy to staging | Pending |
| 7 | Cleanup and documentation | Pending |

## Notes and Decisions

### Why Not Create a Separate handlers/ Directory?

The audit suggested creating a `handlers/` directory, but the codebase already has:
- `events/` with event emitters and subscribers
- `utils/` with handler functions
- `services/` for business logic

Creating another `handlers/` directory would add confusion. Instead, we keep the existing patterns and only restructure the hooks.py configuration itself.

### Environment-Specific Scheduler Configuration

The audit suggested making scheduler configuration environment-aware. This is a good idea but should be a separate enhancement after the basic restructuring is complete. The `hooks/scheduler.py` module is prepared to support this pattern via `_get_scheduler_events()`.

### Handler Lightness Principle

The audit correctly emphasizes that hook handlers should be lightweight. This is already partially implemented via `BackgroundJobManager` in `utils/background_jobs.py`. Handlers that do heavy work should call `frappe.enqueue()` rather than processing synchronously.
