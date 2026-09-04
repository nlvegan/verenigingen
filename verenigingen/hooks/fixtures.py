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
    # All notifications are handled by custom code that respects Verenigingen Email Configuration:
    # - Member approval/rejection: member_subscribers.py, membership_application_review.py
    # - SEPA mandate: sepa_notifications.py
    # - Member status change: member_subscribers.py
    # - Invoice overdue: payment_processing.py
    # - New application (admin): application_notifications.py
    # - Expense approval: expense_handlers.py
    #
    # This ensures the Verenigingen Email Configuration DocType is the single source of truth
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
    # NOTE: Standard reports are NOT included as fixtures. They are backed by
    # .json + .py files under verenigingen/<module>/report/<name>/ and are
    # auto-synced by Frappe's module sync during `bench migrate`. Re-importing
    # them as fixtures runs Report.validate_standard_report(), which blocks
    # insert outside developer mode and breaks production migrations.
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
    # Mollie fields that must survive `bench export-fixtures` (see
    # fixtures/custom_field.json):
    #   * custom_mollie_payment_id / custom_mollie_settlement_id on Payment Entry --
    #     the settlement dedup guard reads them;
    #   * custom_mollie_settlement_id on Journal Entry -- the settlement-level
    #     idempotency guard reads it to decide whether a settlement's fee entry is
    #     already on the ledger; losing it re-books the fee Journal Entry, for the
    #     ENTIRE settlement amount, on every scheduled run;
    #   * custom_processing_status on Bank Transaction -- its Select options carry
    #     "Mollie Settlement Processed", and without that option the Mollie branch of
    #     create_reconciliation throws on save() *after* it has submitted every
    #     Payment Entry.
    #
    # The filter is by fieldname, so the Bank Transaction / Payment Entry / Journal
    # Entry copies of custom_mollie_settlement_id are all covered by the one clause.
    #
    # These share ONE entry on purpose. frappe/utils/fixtures.py derives the output
    # filename as frappe.scrub(<doctype>) unless a "prefix" is given, so all three
    # unprefixed "Custom Field" entries in this list write to custom_field.json and
    # only the LAST one's contents survive an export. Adding a fourth entry would
    # therefore delete the Mollie dedup fields instead of saving this one. The real
    # fix -- the three entries clobbering a single file -- is issue #196 and is
    # deliberately not attempted here.
    #
    # Measured cost of that defect, correcting the earlier "drops the btw_* and
    # eboekhouden fields" note, which named the wrong victims and understated the
    # scale: custom_field.json holds 63 entries and this Mollie filter matches 6, so
    # an export drops the other 57 -- among them Sales Invoice.member, Customer.member,
    # Payment Entry.custom_sepa_batch, Bank Transaction.custom_sepa_batch and every
    # Ponto field. (The btw_* fields are not in this file at all; they are created at
    # install time by setup.get_custom_fields(). The eboekhouden fields ARE in it, but
    # under bare `eboekhouden_*` names that the `custom_eboekhouden_...` filter above
    # never matched either -- so those 17 are part of the 57, not a separate case.)
    {
        "doctype": "Custom Field",
        "filters": [
            [
                "fieldname",
                "in",
                [
                    "custom_mollie_idempotency_key",
                    "custom_mollie_payment_id",
                    "custom_mollie_settlement_id",
                    "custom_processing_status",
                ],
            ],
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
                    "Monthly Dues Revenue",
                    "Outstanding Dues Invoices by Month",
                    "Dues Revenue by Payment Status",
                    "Dues Revenue by Quarter",
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
    # =========================================================================
    # PAYMENT MODES
    # =========================================================================
    # Mollie payment modes. The Mollie payment flow requires these records to
    # exist (payment_entry_factory validates "Mollie"; the refund flow uses
    # "Mollie Refund"), and donation/refund Journal Entry creation references
    # them. They are not standard ERPNext data, so ship them as fixtures so a
    # fresh install / CI site has them. Filtered so `bench export-fixtures`
    # does not pull in standard ERPNext modes of payment.
    {
        "doctype": "Mode of Payment",
        "filters": [["name", "in", ["Mollie", "Mollie Refund"]]],
    },
    # NOTE: Critical Operation Rules are NOT included here.
    # They are created once during app install via setup.critical_operation_rules_setup
    # to prevent migrations from overwriting user customizations to rate limits, roles, etc.
]
