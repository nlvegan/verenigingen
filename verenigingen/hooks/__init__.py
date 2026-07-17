# verenigingen/hooks/__init__.py
"""Verenigingen application hooks configuration.

This package organizes hooks by concern into focused submodules:
- assets.py: CSS/JS includes
- doctypes.py: DocType JS mappings
- doc_events.py: Document event handlers
- scheduler.py: Scheduled tasks
- permissions.py: Permission queries
- fixtures.py: Fixture definitions
- portal.py: Portal configuration
- lifecycle.py: Install/migrate hooks

This structure makes the configuration easier to navigate, maintain,
and test compared to a monolithic hooks.py file.
"""

# =============================================================================
# IMPORTS FROM SUBMODULES
# =============================================================================
from verenigingen.hooks.assets import (
    app_include_css,
    app_include_js,
    email_css,
    web_include_css,
    web_include_js,
)
from verenigingen.hooks.doc_events import doc_events
from verenigingen.hooks.doctypes import doctype_js
from verenigingen.hooks.fixtures import fixtures
from verenigingen.hooks.lifecycle import (
    after_install,
    after_migrate,
    before_tests,
    boot_session,
    on_logout,
    on_startup,
)
from verenigingen.hooks.permissions import has_permission, permission_query_conditions
from verenigingen.hooks.portal import update_website_context
from verenigingen.hooks.scheduler import scheduler_events

# =============================================================================
# APP METADATA
# =============================================================================
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

# =============================================================================
# JINJA CONFIGURATION
# =============================================================================
jinja = {
    "methods": ["verenigingen.utils.jinja_methods"],
    "filters": ["verenigingen.utils.jinja_filters"],
}

# =============================================================================
# DOCTYPE CLASS OVERRIDES
# =============================================================================
override_doctype_class = {"Payment Entry": "verenigingen.overrides.payment_entry.PaymentEntry"}

# =============================================================================
# CLI COMMANDS
# =============================================================================
commands = [
    "verenigingen.commands.workspace.workspace",
    "verenigingen.commands.workspace_health.workspace_health",
    "verenigingen.commands.workspace_maintenance.workspace_maintenance",
]
