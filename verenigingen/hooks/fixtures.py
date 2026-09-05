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
    # (#196) frappe/utils/fixtures.py derives the export filename for an entry
    # as frappe.scrub(<doctype>) UNLESS the entry gives an explicit "prefix" --
    # so any two "Custom Field" entries that both omit "prefix" write to the
    # same fixtures/custom_field.json, and only the LAST one written survives
    # an export. This app had exactly that: three unprefixed "Custom Field"
    # entries below, so `bench export-fixtures --app verenigingen` (as
    # docs/ROLE_PROFILES.md instructs) silently kept only the last one's
    # fields and discarded the other two groups'. Each entry now has a
    # distinct "prefix" so each writes its own file and none of them can
    # overwrite another. Do NOT add a fourth unprefixed "Custom Field" entry
    # (or any other unprefixed doctype already declared above) -- that
    # recreates this exact defect; see test_fixture_export.py.
    #
    # The pre-existing, unprefixed fixtures/custom_field.json is intentionally
    # left in place, NOT deleted, by this fix. It measured 64 entries at the
    # time of the fix. Most of those fields (e.g. Sales Invoice.member,
    # Customer.member, Payment Entry.custom_sepa_batch,
    # Bank Transaction.custom_sepa_batch, every Ponto field) match none of
    # the three filters below at all. None of the entries below target that
    # filename anymore, so it can no longer be clobbered by this app's own
    # fixture list -- but it is also no longer regenerated by
    # `bench export-fixtures`, since nothing here declares those fields.
    # Deleting it would silently drop all 64 of them from a fresh site
    # install (import walks every file in fixtures/, regardless of what
    # hooks.py declares). Giving that remaining set of fields proper,
    # explicit fixture coverage is a separate piece of work, tracked apart
    # from this collision fix.
    #
    # Measured overlap: 7 of those 64 rows (the Bank Transaction / Payment
    # Entry / Journal Entry Mollie fields, below) ARE also matched by the
    # Mollie filter, so they exist in BOTH custom_field.json and
    # mollie_custom_field.json. `import_fixtures` imports files in
    # sorted(os.listdir(...)) order with force=True (last write for a given
    # record wins), and "custom_field.json" sorts before
    # "mollie_custom_field.json" alphabetically, so the fresh Mollie export
    # currently always wins on import. That is an alphabetical accident, not
    # a guarantee: a future prefix that sorts before "custom_field" (e.g.
    # anything starting "a" through "c") would invert this and let the
    # frozen, undeclared copy win instead. Re-check this ordering before
    # adding one.
    {
        "doctype": "Custom Field",
        "prefix": "btw",
        "filters": [
            ["fieldname", "like", "btw_%"],
        ],
    },
    # Matches ZERO records on every site checked (measured on test_site_1):
    # the field this filter names, custom_eboekhouden_grootboek_nummer, does
    # not exist. The real field is Account.eboekhouden_grootboek_nummer --
    # no "custom_" prefix -- so this entry's own export file,
    # eboekhouden_grootboek_custom_field.json, is legitimately always empty.
    # That is a pre-existing, separate defect (wrong fieldname, not a
    # collision) and is deliberately not fixed here -- #196 is about the
    # collision only.
    {
        "doctype": "Custom Field",
        "prefix": "eboekhouden_grootboek",
        "filters": [
            ["fieldname", "=", "custom_eboekhouden_grootboek_nummer"],
        ],
    },
    # Mollie fields that must survive `bench export-fixtures` (see
    # fixtures/mollie_custom_field.json):
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
    # (These 4 fieldnames also still exist, for 7 rows total, in the stale
    # custom_field.json above -- see the "Measured overlap" note.)
    {
        "doctype": "Custom Field",
        "prefix": "mollie",
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
