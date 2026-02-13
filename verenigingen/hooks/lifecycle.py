# verenigingen/hooks/lifecycle.py
"""Application lifecycle hooks: install, migrate, tests, auth.

These hooks are called at specific points in the application lifecycle:
- after_install: After app is first installed on a site
- after_migrate: After database migrations complete
- before_tests: Before running test suite
- on_logout: When user logs out
- on_startup: When the application starts
"""

# Run after app is first installed on a site
# Used to create initial reference data that shouldn't be overwritten by migrations
after_install = [
    "verenigingen.setup.execute_after_install",
    "verenigingen.setup.security_setup.setup_all_security",
    "verenigingen.setup.critical_operation_rules_setup.setup_critical_operation_rules",
]

# Run after database migrations complete
# Used for schema updates, index creation, and data backfills
after_migrate = [
    # Ensure required payment modes exist (needed for membership applications)
    "verenigingen.setup.ensure_required_payment_modes",
    # Brand settings initialization
    "verenigingen.verenigingen.doctype.brand_settings.brand_settings.create_default_brand_settings",
    # Workflow setup - DISABLED: Workflow not in use, has bugs in action master creation
    # "verenigingen.setup.membership_application_workflow_setup.setup_membership_application_workflow",
    # Security framework
    "verenigingen.utils.security.setup_all_security",
    # Database indexes
    "verenigingen.patches.v1_0.add_coverage_duplicate_check_indexes.execute",
    # Performance optimization
    "verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup.run_performance_optimization",
    # Data backfills
    "verenigingen.patches.v2_1.add_chapter_dashboard_performance_indexes.execute",
    # Sync document category options from Settings into DocField meta
    "verenigingen.utils.document_categories.sync_category_options_to_doctypes",
]

# Run before test suite executes
# Ensures ERPNext test fixtures (Company, etc.) are created before our tests run
before_tests = "verenigingen.tests.setup.before_tests"

# Run when user logs out
on_logout = "verenigingen.auth_hooks.on_logout"

# Run when the application starts
# Used for startup verification of critical infrastructure
on_startup = [
    "verenigingen.startup_checks.run_all_startup_checks",
]

# Boot session hooks - run when user session starts
# Note: Original hooks.py had two declarations that overwrote each other.
# Consolidated here to include both handlers.
boot_session = [
    "verenigingen.boot.boot_session",
    "verenigingen.setup.document_links.setup_custom_document_links",
]

# Note: The following hooks are DISABLED due to issues:
#
# on_session_creation: Disabled because it interferes with session resumption.
# The hook gets called during session.resume() before user is properly set.
# on_session_creation = "verenigingen.auth_hooks.on_session_creation"
#
# before_request: Disabled because it was causing "User None is disabled" errors
# by interfering with Frappe's core session initialization process.
# before_request = "verenigingen.auth_hooks.validate_session_before_request"
