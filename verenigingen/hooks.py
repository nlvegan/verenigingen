# -*- coding: utf-8 -*-
from __future__ import unicode_literals

app_name = "verenigingen"
app_title = "Verenigingen"
app_publisher = "Verenigingen"
app_description = "Association Management"
app_icon = "octicon octicon-organization"
app_color = "blue"
app_email = "info@verenigingen.org"
app_license = "AGPL-3"

# Required apps - Frappe will ensure these are installed before this app
required_apps = ["erpnext", "payments", "hrms", "alyf-de/banking"]

# Includes in <head>
# ------------------
# Updated to use dues schedule system instead of subscription overrides

# Boot session - runs when user session starts
boot_session = "verenigingen.boot.boot_session"

app_include_css = [
    "/assets/verenigingen/css/verenigingen_custom.css",
    "/assets/verenigingen/css/volunteer_portal.css",
    "/assets/verenigingen/css/iban-validation.css"
    # Note: brand_colors.css loaded per-template to avoid 404 errors
]
app_include_js = [
    # Removed termination_dashboard.js as it's a React component and causes import errors
    "/assets/verenigingen/js/member_portal_redirect.js",
    "/assets/verenigingen/js/utils/iban-validator.js",
]

# include js in doctype views
doctype_js = {
    "Member": "verenigingen/doctype/member/member.js",
    "Membership": "public/js/membership.js",
    "Membership Type": "public/js/membership_type.js",
    "SEPA Direct Debit Batch": "public/js/direct_debit_batch.js",
    "Membership Termination Request": "public/js/membership_termination_request.js",
    "Customer": "public/js/customer_member_link.js",
}

# doctype_list_js = {
#     "Membership Termination Request": "public/js/membership_termination_request_list.js",
#     "Termination Appeals Process": "public/js/termination_appeals_process_list.js",
# }

# Document Events
# ---------------
doc_events = {
    # Core membership system events
    "Membership": {
        "validate": "verenigingen.validations.validate_membership_grace_period",
        "on_submit": "verenigingen.verenigingen.doctype.membership.membership.on_submit",
        "on_cancel": "verenigingen.verenigingen.doctype.membership.membership.on_cancel",
    },
    # Updated to use dues schedule system instead of subscription hooks
    "Chapter": {
        "validate": "verenigingen.verenigingen.doctype.chapter.chapter.validate_chapter_access",
    },
    "Verenigingen Settings": {
        "validate": "verenigingen.validations.validate_verenigingen_settings",
        "on_update": "verenigingen.verenigingen.doctype.member.member_utils.sync_member_counter_with_settings",
    },
    "Payment Entry": {
        "on_submit": [
            "verenigingen.verenigingen.doctype.member.member_utils.update_member_payment_history",
            "verenigingen.utils.payment_notifications.on_payment_submit",
            "verenigingen.events.expense_events.emit_expense_payment_made",
            "verenigingen.utils.donor_auto_creation.process_payment_for_donor_creation",
        ],
        "on_cancel": "verenigingen.verenigingen.doctype.member.member_utils.update_member_payment_history",
        "on_trash": "verenigingen.verenigingen.doctype.member.member_utils.update_member_payment_history",
    },
    "Sales Invoice": {
        "before_validate": ["verenigingen.utils.apply_tax_exemption_from_source"],
        "validate": ["verenigingen.overrides.sales_invoice.custom_validate"],
        "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
        # Event-driven approach for payment history updates
        # This prevents validation errors from blocking invoice submission
        "on_submit": "verenigingen.events.invoice_events.emit_invoice_submitted",
        "on_update_after_submit": "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
        "on_cancel": "verenigingen.events.invoice_events.emit_invoice_cancelled",
    },
    # Termination system events
    "Membership Termination Request": {
        "validate": "verenigingen.validations.validate_termination_request",
        "on_update_after_submit": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.handle_status_change",
    },
    "Expulsion Report Entry": {
        "validate": "verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.validate",
        "after_insert": "verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.notify_governance_team",
        "before_save": "verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.update_status_based_on_appeals",
    },
    "Member": {
        "before_save": "verenigingen.verenigingen.doctype.member.member_utils.update_termination_status_display",
        "after_save": "verenigingen.verenigingen.doctype.member.member.handle_fee_override_after_save",
    },
    # Donation history tracking
    "Donation": {
        "after_insert": [
            "verenigingen.utils.donation_history_manager.on_donation_insert",
            "verenigingen.verenigingen.doctype.donation.donation.update_campaign_progress",
        ],
        "on_update": [
            "verenigingen.utils.donation_history_manager.on_donation_update",
            "verenigingen.verenigingen.doctype.donation.donation.update_campaign_progress",
        ],
        "on_submit": "verenigingen.utils.donation_history_manager.on_donation_submit",
        "on_cancel": "verenigingen.utils.donation_history_manager.on_donation_cancel",
        "on_trash": "verenigingen.utils.donation_history_manager.on_donation_delete",
    },
    # Donor-Customer integration
    "Donor": {
        "after_save": "verenigingen.utils.donor_customer_sync.sync_donor_to_customer",
        "on_update": "verenigingen.utils.donor_customer_sync.sync_donor_to_customer",
    },
    "Customer": {
        "after_save": "verenigingen.utils.donor_customer_sync.sync_customer_to_donor",
        "on_update": "verenigingen.utils.donor_customer_sync.sync_customer_to_donor",
    },
    # Volunteer expense approver sync (native ERPNext system)
    "Volunteer": {"on_update": "verenigingen.utils.native_expense_helpers.update_employee_approver"},
    # Brand Settings - regenerate CSS when colors change (Single doctype)
    "Brand Settings": {"on_update": "verenigingen.utils.brand_css_generator.generate_brand_css_file"},
    # Account Group Project Framework - validate and apply defaults
    "Journal Entry": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry",
        "on_submit": "verenigingen.utils.donor_auto_creation.process_payment_for_donor_creation",
    },
    "Expense Claim": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_expense_claim",
        "on_update_after_submit": "verenigingen.events.expense_events.emit_expense_claim_approved",
        "on_cancel": "verenigingen.events.expense_events.emit_expense_claim_cancelled",
    },
    "Purchase Invoice": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_purchase_invoice"
    },
}

# Scheduled Tasks
# ---------------
scheduler_events = {
    "daily": [
        # Member financial history refresh - runs once daily
        "verenigingen.verenigingen.doctype.member.scheduler.refresh_all_member_financial_histories",
        # Membership duration updates - runs once daily
        "verenigingen.verenigingen.doctype.member.scheduler.update_all_membership_durations",
        # Core membership system
        "verenigingen.verenigingen.doctype.membership.scheduler.process_expired_memberships",
        "verenigingen.verenigingen.doctype.membership.scheduler.send_renewal_reminders",
        # "verenigingen.verenigingen.doctype.membership.scheduler.process_auto_renewals",  # Deprecated - renewal handled by billing system
        # Updated to use dues schedule system instead
        "verenigingen.verenigingen.doctype.membership.scheduler.notify_about_orphaned_records",
        "verenigingen.api.membership_application_review.send_overdue_notifications",
        # Amendment system processing
        "verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.process_pending_amendments",
        # Auto-create missing dues schedules
        "verenigingen.utils.dues_schedule_auto_creator.auto_create_missing_dues_schedules_scheduled",
        # Generate invoices from membership dues schedules
        "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.generate_dues_invoices",
        # Analytics and goals updates
        "verenigingen.verenigingen.doctype.membership_goal.membership_goal.update_all_goals",
        # Termination system maintenance
        "verenigingen.utils.termination_utils.process_overdue_termination_requests",
        "verenigingen.utils.termination_utils.audit_termination_compliance",
        # SEPA mandate synchronization
        "verenigingen.verenigingen.doctype.member.mixins.sepa_mixin.check_sepa_mandate_discrepancies",
        # SEPA mandate child table sync (catches cases where hooks didn't trigger)
        "verenigingen.api.sepa_mandate_management.periodic_sepa_mandate_child_table_sync",
        # Contact request automation
        "verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation.process_contact_request_automation",
        # E-Boekhouden dashboard updates
        "verenigingen.e_boekhouden.utils.eboekhouden_api.update_dashboard_data_periodically",
        # Board member role cleanup
        # "verenigingen.utils.board_member_role_cleanup.cleanup_expired_board_member_roles",
        # SEPA payment retry processing
        "verenigingen.utils.payment_retry.execute_payment_retry",
        # Bank transaction reconciliation
        "verenigingen.utils.sepa_reconciliation.reconcile_bank_transactions",
        # SEPA mandate expiry notifications
        "verenigingen.utils.sepa_notifications.check_and_send_expiry_notifications",
        # Native expense approver sync
        "verenigingen.utils.native_expense_helpers.refresh_all_expense_approvers",
        # SEPA Direct Debit batch optimization
        "verenigingen.api.dd_batch_scheduler.daily_batch_optimization",
        # Create daily analytics snapshots
        "verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot.create_scheduled_snapshots",
        # Membership dues collection processing
        "verenigingen.verenigingen.doctype.direct_debit_batch.sepa_processor.create_monthly_dues_collection_batch",
        # Payment plan processing
        "verenigingen.verenigingen.doctype.payment_plan.payment_plan.process_overdue_installments",
        # Security audit log cleanup
        "verenigingen.utils.security.audit_logging.get_audit_logger().cleanup_old_logs",
    ],
    "hourly": [
        # Check analytics alert rules
        "verenigingen.verenigingen.doctype.analytics_alert_rule.analytics_alert_rule.check_all_active_alerts",
    ],
    "weekly": [
        # Termination reports and reviews
        "verenigingen.utils.termination_utils.generate_weekly_termination_report",
        # Security system health check
        "verenigingen.utils.security.audit_logging.log_sepa_event('security_weekly_health_check', severity='info')",
    ],
}

# Jinja
# -----
jinja = {"methods": ["verenigingen.utils.jinja_methods"], "filters": ["verenigingen.utils.jinja_filters"]}

# Installation and Migration Hooks
# ---------------------------------
after_migrate = [
    "verenigingen.verenigingen.doctype.brand_settings.brand_settings.create_default_brand_settings",
    "verenigingen.setup.membership_application_workflow_setup.setup_membership_application_workflow",
    "verenigingen.utils.security.setup_all_security",
]

# Portal Configuration
# --------------------
# Custom portal menu items for association members (overrides ERPNext defaults)
standard_portal_menu_items = [
    {
        "title": "Member Portal",
        "route": "/member_portal",
        "reference_doctype": "",
        "role": "Verenigingen Member",
    },
    {"title": "Volunteer Portal", "route": "/volunteer_portal", "reference_doctype": "", "role": "Volunteer"},
]

# Override functions removed - only affecting website/portal, not desk

# Portal context processors
website_context = {"get_member_context": "verenigingen.utils.portal_customization.get_member_context"}

# Website context update hook - adds body classes for brand styling
update_website_context = ["verenigingen.utils.portal_customization.add_brand_body_classes"]

# Installation
# ------------
after_install = ["verenigingen.setup.execute_after_install", "verenigingen.utils.security.setup_all_security"]

# Permissions
# -----------
permission_query_conditions = {
    "Member": "verenigingen.permissions.get_member_permission_query",
    "Membership": "verenigingen.permissions.get_membership_permission_query",
    "Chapter": "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_permission_query_conditions",
    "Chapter Member": "verenigingen.permissions.get_chapter_member_permission_query",
    "Team": "verenigingen.verenigingen.doctype.team.team.get_team_permission_query_conditions",
    "Team Member": "verenigingen.permissions.get_team_member_permission_query",
    "Membership Termination Request": "verenigingen.permissions.get_termination_permission_query",
    "Volunteer": "verenigingen.permissions.get_volunteer_permission_query",
    "Address": "verenigingen.permissions.get_address_permission_query",
}

has_permission = {
    "Member": "verenigingen.permissions.has_member_permission",
    "Membership": "verenigingen.permissions.has_membership_permission",
    "Address": "verenigingen.permissions.has_address_permission",
}

# Workflow Action Handlers
# -------------------------
workflow_action_handlers = {
    "Membership Termination Workflow": {
        "Approve": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.on_workflow_action",
        "Execute": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.on_workflow_action",
        "Reject": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.on_workflow_action",
    }
}

# Domain setting removed - was hiding desk modules

# Fixtures
# --------
fixtures = [
    # Donation Types
    {
        "doctype": "Donation Type",
        "filters": [
            [
                "name",
                "in",
                ["General", "Monthly", "One-time", "Campaign", "Emergency Relie", "Membership Support"],
            ]
        ],
    },
    # Email Templates
    {"doctype": "Email Template", "filters": [["name", "like", "membership_%"]]},
    {
        "doctype": "Email Template",
        "filters": [
            [
                "name",
                "in",
                [
                    "expense_approval_request",
                    "expense_approved",
                    "expense_rejected",
                    "donation_confirmation",
                    "donation_payment_confirmation",
                    "anbi_tax_receipt",
                    "termination_overdue_notification",
                    "member_contact_request_received",
                ],
            ]
        ],
    },
    {
        "doctype": "Email Template",
        "filters": [["name", "in", ["Termination Approval Required", "Termination Execution Notice"]]],
    },
    # Workflows
    {"doctype": "Workflow", "filters": [["name", "in", ["Membership Termination Workflow"]]]},
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
    {"doctype": "Workflow Action Master", "filters": [["workflow_action_name", "in", ["Execute"]]]},
    # Roles
    {
        "doctype": "Role",
        "filters": [
            [
                "name",
                "in",
                [
                    "Verenigingen Administrator",
                    "Verenigingen Manager",
                    "Verenigingen Staff",
                    "Governance Auditor",
                    "Chapter Board Member",
                    "Verenigingen Member",
                    "Volunteer",
                ],
            ]
        ],
    },
    # Role Profiles
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
                    "Verenigingen Chapter Board",
                    "Verenigingen Treasurer",
                    "Verenigingen Chapter Administrator",
                    "Verenigingen Manager",
                    "Verenigingen System Administrator",
                    "Verenigingen Auditor",
                ],
            ]
        ],
    },
    # Module Profiles
    {
        "doctype": "Module Profile",
        "filters": [
            [
                "name",
                "in",
                [
                    "Verenigingen Basic Access",
                    "Verenigingen Volunteer Access",
                    "Verenigingen Financial Access",
                    "Verenigingen Management Access",
                    "Verenigingen Audit Access",
                ],
            ]
        ],
    },
    # Reports
    {
        "doctype": "Report",
        "filters": [["name", "in", ["Termination Audit Report", "Termination Compliance Report"]]],
    },
    # Custom Fields (if you want to export them)
    {
        "doctype": "Custom Field",
        "filters": [
            ["fieldname", "like", "btw_%"],
        ],
    },
    {
        "doctype": "Custom Field",
        "filters": [
            ["fieldname", "=", "eboekhouden_grootboek_nummer"],
        ],
    },
    # Membership Types
    {
        "doctype": "Membership Type",
        "filters": [["name", "in", ["Monthly Membership", "Annual Membership"]]],
    },
    # Membership Dues Schedule Templates
    {
        "doctype": "Membership Dues Schedule",
        "filters": [["name", "in", ["Monthly Membership Template", "Annual Membership Template"]]],
    },
    # Items
    {
        "doctype": "Item",
        "filters": [["item_code", "=", "MEMBERSHIP"]],
    },
    # Updated to use dues schedule system instead of subscription plans
    # Workspaces
    {
        "doctype": "Workspace",
        "filters": [["name", "in", ["E-Boekhouden", "Verenigingen"]]],
    },
]

# Authentication and authorization
# --------------------------------

# Session hooks for member portal redirects
on_session_creation = "verenigingen.auth_hooks.on_session_creation"
on_logout = "verenigingen.auth_hooks.on_logout"

# Optional: Request hooks to enforce member portal access
# before_request = "verenigingen.auth_hooks.before_request"

# Custom auth validation (if needed)
# auth_hooks = [
#     "verenigingen.auth_hooks.validate_auth_via_api"
# ]

# Automatically update python controller files
# override_whitelisted_methods = {
# 	"frappe.desk.query_report.export_query": "verenigingen.verenigingen.report.termination_audit_report.termination_audit_report.export_audit_report"
# }

# Whitelisted API Methods
# ----------------------
# These methods are automatically whitelisted due to @frappe.whitelist() decorators
# Listed here for documentation purposes:
#
# Termination API:
# - verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_impact_preview
# - verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.execute_safe_member_termination
# - verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_member_termination_status
# - verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_member_termination_history
#
# Permission API:
# - verenigingen.permissions.can_terminate_member_api
# - verenigingen.permissions.can_access_termination_functions_api
#
# Expulsion Report API:
# - verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.get_expulsion_statistics
# - verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.generate_expulsion_governance_report
# - verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.reverse_expulsion_entry
# - verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.get_member_expulsion_history

# Each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Member": "verenigingen.verenigingen.dashboard.member_dashboard.get_dashboard_data"
# }

# Exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# DocType Class Overrides
# -----------------------
# Override core ERPNext doctypes with custom functionality

# override_doctype_class = {
# 	"Payment Entry": "verenigingen.overrides.payment_entry.PaymentEntry"
# }
# Note: Payment Entry override removed - now using standard Sales Invoice flow for donations

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "Member",
# 		"filter_by": "user",
# 		"redact_fields": ["full_name", "email"],
# 		"partial": 1,
# 	}
# ]
