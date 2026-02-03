# verenigingen/hooks/fixtures.py
"""Fixture definitions for data export/import.

Fixtures define which documents should be exported with the app
and imported when the app is installed on a new site.

Note: Reference data (Membership Types, Email Templates, etc.) is
created via execute_after_install() which only runs once on app install.
This prevents migrations from overwriting user customizations.

Schema items (Property Setters, Custom Fields, etc.) are safe to
include as fixtures since they define structure, not user data.
"""

fixtures = [
    # =========================================================================
    # SCHEMA ITEMS
    # =========================================================================
    # Property Setters (customize ERPNext DocTypes)
    "Property Setter",
    # Custom DocPerms (permissions for core DocTypes)
    "Custom DocPerm",
    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================
    # NOTE: Frappe Notifications are NOT included in fixtures.
    # All notifications are handled by custom code that respects Email Configuration:
    # - Member approval/rejection: member_subscribers.py, membership_application_review.py
    # - SEPA mandate: sepa_notifications.py
    # - Member status change: member_subscribers.py
    # - Invoice overdue: payment_processing.py
    # - New application (admin): application_notifications.py
    # - Expense approval: expense_handlers.py
    #
    # This ensures the Email Configuration DocType is the single source of truth
    # for all notification settings (enable/disable, cooldowns, recipients).
    # =========================================================================
    # WORKFLOWS
    # =========================================================================
    {
        "doctype": "Workflow",
        "filters": [["name", "in", ["Membership Termination Workflow"]]],
    },
    {
        "doctype": "Workflow State",
        "filters": [
            [
                "workflow_state_name",
                "in",
                [
                    "Draft",
                    "Pending",
                    "Pending Verification",
                    "Under Review",
                    "Approved",
                    "Rejected",
                    "Active",
                    "Inactive",
                    "Completed",
                    "Cancelled",
                    "Expired",
                    "Payment Pending",
                    "Processing",
                    "Submitted",
                    "Executed",
                ],
            ]
        ],
    },
    {
        "doctype": "Workflow Action Master",
        "filters": [["workflow_action_name", "in", ["Execute"]]],
    },
    # =========================================================================
    # ROLES AND PROFILES
    # =========================================================================
    {
        "doctype": "Role",
        "filters": [
            [
                "name",
                "in",
                [
                    "Verenigingen Administrator",
                    "Verenigingen Staff",
                    "Verenigingen Governance Auditor",
                    "Verenigingen Chapter Board Member",
                    "Verenigingen Member",
                    "Verenigingen Volunteer",
                ],
            ]
        ],
    },
    {
        "doctype": "Role Profile",
        "filters": [
            [
                "name",
                "in",
                [
                    "Verenigingen Member",
                    "Verenigingen Volunteer",
                    "Verenigingen Team Leader",
                    "Verenigingen Chapter Board Member",
                    "Verenigingen Treasurer",
                    "Verenigingen Staff",
                    "Verenigingen System Administrator",
                    "Verenigingen Auditor",
                ],
            ]
        ],
    },
    # NOTE: Module Profile is intentionally NOT included here.
    # Module Profile's on_update hook queues a background job with a document lock.
    # During migrations, this can cause DocumentLockedError if migration fails and retries.
    # Module Profiles are synced via patch: v2_1.sync_module_profiles_safely
    # See: https://github.com/frappe/frappe/issues/36368
    # =========================================================================
    # REPORTS
    # =========================================================================
    {
        "doctype": "Report",
        "filters": [
            [
                "name",
                "in",
                [
                    "Termination Audit Report",
                    "Termination Compliance Report",
                    "Membership Revenue Projection",
                ],
            ]
        ],
    },
    # =========================================================================
    # CUSTOM FIELDS
    # =========================================================================
    {
        "doctype": "Custom Field",
        "filters": [
            ["fieldname", "like", "btw_%"],
        ],
    },
    {
        "doctype": "Custom Field",
        "filters": [
            ["fieldname", "=", "custom_eboekhouden_grootboek_nummer"],
        ],
    },
    # =========================================================================
    # WORKSPACES AND DASHBOARDS
    # =========================================================================
    # NOTE: Desktop Icons and Workspace Sidebars are NOT included here.
    # Frappe 16 syncs these from app-level folders during migration:
    # - verenigingen/desktop_icon/*.json (auto-synced by frappe.model.sync)
    # - verenigingen/workspace_sidebar/*.json (auto-synced by frappe.model.sync)
    {
        "doctype": "Workspace",
        "filters": [["name", "in", ["E-Boekhouden", "Verenigingen", "Verenigingen Payments"]]],
    },
    {
        "doctype": "Dashboard Chart",
        "filters": [
            [
                "name",
                "in",
                [
                    "Member Count by Chapter",
                    "Member Count Trends",
                    "Member Applications & Exits",
                    "Member Age Distribution",
                    "Member Pronoun Distribution",
                    "Members with Outstanding Invoices",
                    "SEPA Payment Status",
                    "Monthly Revenue Trends",
                    "Outstanding Invoices by Month",
                    "Revenue by Payment Status",
                    "Revenue by Quarter",
                ],
            ]
        ],
    },
    {
        "doctype": "Dashboard",
        "filters": [
            [
                "name",
                "in",
                [
                    "Member Analytics",
                    "Member payment development",
                ],
            ]
        ],
    },
    {
        "doctype": "Custom HTML Block",
        "filters": [["name", "=", "Page Links"]],
    },
    # =========================================================================
    # SYSTEM USERS AND SETTINGS
    # =========================================================================
    # Background Service User (uses Webhook User role for consolidated service account permissions)
    {
        "doctype": "User",
        "filters": [["email", "=", "background.service@verenigingen.local"]],
    },
    # Verenigingen Settings singleton
    {"doctype": "Verenigingen Settings"},
    # NOTE: Critical Operation Rules are NOT included here.
    # They are created once during app install via setup.critical_operation_rules_setup
    # to prevent migrations from overwriting user customizations to rate limits, roles, etc.
]
