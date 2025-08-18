"""
Verenigingen Application Hooks Configuration
============================================

Comprehensive application configuration and integration hooks for the Verenigingen
association management system. This central configuration file orchestrates all
system integrations, event handlers, scheduled tasks, and framework customizations.

This critical infrastructure component serves as the nerve center of the application,
defining how the Verenigingen system integrates with the Frappe framework and
coordinates complex business processes across multiple modules and external systems.

Strategic Architecture
---------------------
The hooks configuration implements a sophisticated event-driven architecture that:

**Decouples System Components**: Enables modular development and maintenance
**Coordinates Business Processes**: Orchestrates complex multi-step workflows
**Manages External Integrations**: Handles connections to payment systems and accounting
**Ensures Data Consistency**: Maintains referential integrity across related entities
**Supports Scalable Operations**: Enables background processing and batch operations

Core Integration Categories
--------------------------

### 1. Application Lifecycle Management
- **Installation Hooks**: Setup procedures for new deployments
- **Migration Hooks**: Database schema and data updates during upgrades
- **Boot Session Hooks**: User session initialization and customization
- **Authentication Hooks**: Custom authentication and authorization workflows

### 2. Document Event Processing
- **Validation Hooks**: Business rule enforcement before document save
- **Lifecycle Events**: Actions triggered by document state changes
- **Cross-Document Synchronization**: Maintaining consistency across related records
- **Background Job Queuing**: Asynchronous processing for performance optimization

### 3. Scheduled Task Management
- **Financial Processing**: Daily dues collection and payment reconciliation
- **Member Lifecycle**: Membership status updates and renewal processing
- **Data Maintenance**: Cleanup, validation, and integrity checks
- **Notification Systems**: Automated communication and alerting

### 4. User Interface Customization
- **Portal Configuration**: Member and volunteer portal customization
- **Desktop Organization**: Module and feature organization
- **Asset Management**: CSS and JavaScript integration
- **Brand Customization**: Dynamic styling and theming

### 5. Security and Permissions
- **Role-Based Access Control**: Fine-grained permission management
- **Data Protection**: Privacy and security compliance features
- **Audit Logging**: Comprehensive activity tracking
- **Compliance Monitoring**: Regulatory requirement adherence

Framework Integration Patterns
-----------------------------

### Event-Driven Architecture
The system employs sophisticated event-driven patterns:

```python
doc_events = {
    "Sales Invoice": {
        "validate": ["custom_business_validation"],
        "on_submit": "emit_invoice_submitted_event",
        "on_cancel": "emit_invoice_cancelled_event"
    }
}
```

**Benefits**:
- **Loose Coupling**: Components can be modified independently
- **Extensibility**: New features can be added without modifying existing code
- **Maintainability**: Clear separation of concerns and responsibilities
- **Performance**: Background processing prevents UI blocking

### Background Job Processing
Critical for performance and user experience:

```python
"on_submit": [
    "queue_member_payment_history_update",     # Asynchronous processing
    "send_immediate_notification",             # Synchronous for speed
    "queue_external_system_sync"               # Background integration
]
```

**Processing Strategy**:
- **Immediate Actions**: Fast operations executed synchronously
- **Heavy Operations**: Complex processing queued for background execution
- **External Integrations**: API calls processed asynchronously
- **Batch Operations**: Bulk processing scheduled for off-peak hours

### Scheduled Task Architecture
Comprehensive automation framework:

```python
scheduler_events = {
    "daily": ["membership_renewal_processing"],
    "hourly": ["payment_status_monitoring"],
    "weekly": ["compliance_reporting"],
    "monthly": ["data_cleanup_maintenance"]
}
```

**Task Categories**:
- **Business Process Automation**: Membership renewals, payment processing
- **Data Maintenance**: Cleanup, validation, integrity checks
- **Monitoring and Alerting**: System health and business metric monitoring
- **Compliance and Reporting**: Automated compliance checks and report generation

Business Process Integration
---------------------------

### Membership Lifecycle Management
Complete automation of membership processes:

1. **Application Processing**: Automated review and approval workflows
2. **Payment Collection**: SEPA direct debit and invoice generation
3. **Status Management**: Automatic status updates based on payment status
4. **Renewal Processing**: Automated renewal reminders and processing
5. **Termination Handling**: Workflow-driven termination processes

### Financial Operations Integration
Sophisticated financial process automation:

1. **Invoice Generation**: Automated dues invoice creation from schedules
2. **Payment Processing**: SEPA batch creation and execution
3. **Reconciliation**: Automatic matching of payments to invoices
4. **Tax Compliance**: VAT handling and ANBI tax receipt generation
5. **External Sync**: Integration with e-Boekhouden accounting system

### Volunteer Management Automation
Comprehensive volunteer lifecycle support:

1. **Application Processing**: Volunteer registration and approval
2. **Assignment Management**: Team and role assignment workflows
3. **Expense Processing**: Native ERPNext expense claim integration
4. **Performance Tracking**: Volunteer activity monitoring and reporting
5. **Recognition Systems**: Automated volunteer appreciation workflows

### Communication and Notification Systems
Multi-channel communication automation:

1. **Email Templates**: Standardized communication templates
2. **Workflow Notifications**: Process-driven communication triggers
3. **Alert Systems**: Business metric and system health monitoring
4. **Member Portals**: Self-service communication interfaces
5. **Compliance Notifications**: Regulatory and policy communication

Technical Implementation Details
-------------------------------

### Asset Management Strategy
Optimized asset loading for performance:

```python
app_include_css = [
    "/assets/verenigingen/css/verenigingen_custom.css",
    "/assets/verenigingen/css/volunteer_portal.css",
    "/assets/verenigingen/css/iban-validation.css"
]
```

**Optimization Features**:
- **Conditional Loading**: Assets loaded only when needed
- **Minification**: Compressed assets for faster loading
- **Caching**: Browser caching optimization
- **CDN Support**: Content delivery network integration ready

### Permission System Architecture
Sophisticated role-based access control:

```python
permission_query_conditions = {
    "Member": "get_member_permission_query",
    "Chapter": "get_chapter_permission_query_conditions"
}
```

**Security Features**:
- **Row-Level Security**: Data access based on user context
- **Hierarchical Permissions**: Chapter and organizational boundaries
- **Dynamic Permissions**: Context-sensitive access control
- **Audit Integration**: Permission usage tracking and monitoring

### Workflow Integration
Complete workflow automation framework:

```python
workflow_action_handlers = {
    "Membership Termination Workflow": {
        "Approve": "on_termination_approval",
        "Execute": "on_termination_execution"
    }
}
```

**Workflow Features**:
- **State Management**: Automatic status transitions
- **Action Handlers**: Custom business logic for each workflow action
- **Notification Integration**: Automatic stakeholder notifications
- **Audit Trail**: Complete workflow history tracking

Performance Optimization Strategies
----------------------------------

### Background Processing Architecture
Critical for system performance:

1. **Immediate vs Deferred**: Smart classification of processing requirements
2. **Queue Management**: Intelligent job queuing and prioritization
3. **Error Recovery**: Robust error handling and retry mechanisms
4. **Resource Management**: CPU and memory usage optimization

### Caching and Optimization
Comprehensive performance optimization:

1. **Application Caching**: Intelligent caching of frequently accessed data
2. **Query Optimization**: Database query performance optimization
3. **Asset Optimization**: Minification and compression of static assets
4. **CDN Integration**: Content delivery network support

### Batch Processing Efficiency
Optimized bulk operations:

1. **Intelligent Batching**: Optimal batch sizes for different operations
2. **Progress Tracking**: Real-time progress monitoring for long operations
3. **Resource Throttling**: Prevents system overload during bulk operations
4. **Parallel Processing**: Multi-threaded processing where appropriate

Quality Assurance and Monitoring
-------------------------------

### System Health Monitoring
Comprehensive monitoring framework:

1. **Performance Metrics**: Real-time performance monitoring and alerting
2. **Error Tracking**: Comprehensive error logging and analysis
3. **Business Metrics**: Key performance indicator monitoring
4. **Compliance Monitoring**: Regulatory requirement adherence tracking

### Data Integrity Assurance
Robust data protection mechanisms:

1. **Validation Frameworks**: Multi-layer data validation
2. **Consistency Checks**: Regular data consistency verification
3. **Audit Logging**: Comprehensive change tracking
4. **Backup Integration**: Automated backup and recovery procedures

### Security and Compliance
Enterprise-grade security features:

1. **Access Control**: Role-based and context-sensitive permissions
2. **Data Protection**: Privacy regulation compliance (GDPR)
3. **Audit Requirements**: Complete audit trail maintenance
4. **Security Monitoring**: Real-time security event monitoring

This hooks configuration represents the operational backbone of the Verenigingen
association management system, enabling sophisticated business process automation
while maintaining enterprise-grade reliability, security, and performance.
"""

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
    "/assets/verenigingen/js/member_age_chart.js",
]

# include js in doctype views
doctype_js = {
    "Member": "verenigingen/doctype/member/member.js",
    "Membership": "public/js/membership.js",
    "Membership Type": "public/js/membership_type.js",
    "Chapter": "public/js/chapter_email_integration.js",
    "Direct Debit Batch": "public/js/direct_debit_batch.js",
    "Membership Termination Request": "public/js/membership_termination_request.js",
    "Expense Claim": "public/js/expense_claim_custom.js",
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
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.payment_notifications.on_payment_submit",  # Keep synchronous - fast
            "verenigingen.utils.background_jobs.queue_expense_event_processing_handler",
            "verenigingen.utils.background_jobs.queue_donor_auto_creation_handler",
            "verenigingen.utils.cache_invalidation.on_document_submit",  # Cache invalidation
            "verenigingen.utils.performance_event_handlers.on_member_payment_update",  # Safe performance optimization
        ],
        "on_cancel": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.cache_invalidation.on_document_cancel",  # Cache invalidation
        ],
        "on_trash": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.cache_invalidation.on_document_update",  # Cache invalidation
        ],
    },
    "Sales Invoice": {
        "before_validate": [
            "verenigingen.utils.apply_tax_exemption_from_source",
            "verenigingen.utils.sales_invoice_hooks.set_member_from_customer",
        ],
        "validate": [
            "verenigingen.overrides.sales_invoice.custom_validate",
            "verenigingen.utils.sales_invoice_account_handler.set_membership_receivable_account",
        ],
        "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
        # Event-driven approach for payment history updates
        # This prevents validation errors from blocking invoice submission
        "on_submit": [
            "verenigingen.events.invoice_events.emit_invoice_submitted",
            "verenigingen.utils.cache_invalidation.on_document_submit",  # Cache invalidation
            "verenigingen.utils.performance_event_handlers.on_member_payment_update",  # Safe performance optimization
        ],
        "on_update_after_submit": [
            "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
            "verenigingen.utils.cache_invalidation.on_document_update",  # Cache invalidation
        ],
        "on_cancel": [
            "verenigingen.events.invoice_events.emit_invoice_cancelled",
            "verenigingen.utils.cache_invalidation.on_document_cancel",  # Cache invalidation
        ],
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
        "after_save": [
            "verenigingen.utils.donor_customer_sync.sync_customer_to_donor",
            "verenigingen.utils.cache_invalidation.on_document_update",  # Cache invalidation
        ],
        "on_update": [
            "verenigingen.utils.donor_customer_sync.sync_customer_to_donor",
            "verenigingen.utils.cache_invalidation.on_document_update",  # Cache invalidation
        ],
    },
    # Brand Settings - regenerate CSS when colors change (Single doctype)
    "Brand Settings": {"on_update": "verenigingen.utils.brand_css_generator.generate_brand_css_file"},
    # Account Group Project Framework - validate and apply defaults
    "Journal Entry": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry",
        "on_submit": "verenigingen.utils.donor_auto_creation.process_payment_for_donor_creation",
    },
    "Expense Claim": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_expense_claim",
        "after_save": "verenigingen.events.expense_events.emit_expense_claim_updated",
        "on_update_after_submit": "verenigingen.events.expense_events.emit_expense_claim_approved",
        "on_cancel": "verenigingen.events.expense_events.emit_expense_claim_cancelled",
    },
    "Purchase Invoice": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_purchase_invoice"
    },
    # Chapter Board Member permission automation
    "Verenigingen Chapter Board Member": {
        "after_insert": "verenigingen.utils.chapter_role_events.on_chapter_board_member_after_insert",
        "on_update": "verenigingen.utils.chapter_role_events.on_chapter_board_member_on_update",
        "on_trash": "verenigingen.utils.chapter_role_events.on_chapter_board_member_on_trash",
    },
    # Chapter Role changes affect board member permissions
    "Chapter Role": {
        "on_update": "verenigingen.utils.chapter_role_events.on_chapter_role_on_update",
    },
    # Volunteer updates can affect board member roles
    "Verenigingen Volunteer": {
        "on_update": [
            "verenigingen.utils.native_expense_helpers.update_employee_approver",
            "verenigingen.utils.chapter_role_events.on_volunteer_on_update",
            "verenigingen.utils.performance_event_handlers.on_volunteer_assignment_change",  # Safe performance optimization
        ]
    },
    # Member updates can affect board member roles and email groups
    "Member": {
        "before_save": "verenigingen.verenigingen.doctype.member.member_utils.update_termination_status_display",
        "after_save": [
            "verenigingen.verenigingen.doctype.member.member.handle_fee_override_after_save",
            "verenigingen.email.email_group_sync.sync_member_on_change",
            "verenigingen.utils.cache_invalidation.on_document_update",  # Cache invalidation
        ],
        "on_update": [
            "verenigingen.utils.chapter_role_events.on_member_on_update",
            "verenigingen.utils.cache_invalidation.on_document_update",  # Cache invalidation
        ],
    },
    # SEPA Mandate events for cache invalidation
    "SEPA Mandate": {
        "after_save": [
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_event_handlers.on_sepa_mandate_change",  # Safe performance optimization
        ],
        "on_update": [
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_event_handlers.on_sepa_mandate_change",  # Safe performance optimization
        ],
        "on_submit": "verenigingen.utils.cache_invalidation.on_document_submit",
        "on_cancel": "verenigingen.utils.cache_invalidation.on_document_cancel",
        "on_trash": "verenigingen.utils.cache_invalidation.on_document_update",
    },
    # Volunteer Expense approval validation
    "Volunteer Expense": {
        "before_submit": "verenigingen.utils.chapter_role_events.before_volunteer_expense_submit",
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
        # EMAIL SYSTEM INTEGRATION - Daily email system maintenance
        "verenigingen.email.email_group_sync.scheduled_email_group_sync",
        "verenigingen.email.analytics_tracker.cleanup_old_email_analytics",
        "verenigingen.email.automated_campaigns.process_scheduled_campaigns",
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
        # Check for stuck dues schedules and notify administrators
        "verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules",
        # Analytics and goals updates
        "verenigingen.verenigingen.doctype.membership_goal.membership_goal.update_all_goals",
        # Termination system maintenance
        "verenigingen.utils.termination_utils.process_overdue_termination_requests",
        "verenigingen.utils.termination_utils.audit_termination_compliance",
        # SEPA mandate synchronization
        "verenigingen.verenigingen.doctype.member.mixins.sepa_mixin.check_sepa_mandate_discrepancies",
        # SEPA mandate child table sync (catches cases where hooks didn't trigger)
        "verenigingen.verenigingen_payments.api.sepa_mandate_management.periodic_sepa_mandate_child_table_sync",
        # Contact request automation
        "verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation.process_contact_request_automation",
        # E-Boekhouden dashboard updates
        "verenigingen.e_boekhouden.utils.eboekhouden_api.update_dashboard_data_periodically",
        # Board member role cleanup
        # "verenigingen.utils.board_member_role_cleanup.cleanup_expired_board_member_roles",
        # SEPA payment retry processing
        "verenigingen.utils.payment_retry.execute_payment_retry",
        # Bank transaction reconciliation
        "verenigingen.verenigingen_payments.utils.sepa_reconciliation.reconcile_bank_transactions",
        # SEPA mandate expiry notifications
        "verenigingen.verenigingen_payments.utils.sepa_notifications.check_and_send_expiry_notifications",
        # Native expense approver sync
        "verenigingen.utils.native_expense_helpers.refresh_all_expense_approvers",
        # Expense history batch processing
        "verenigingen.utils.expense_history_batch_processor.process_pending_expense_history_updates",
        # SEPA Direct Debit batch optimization
        "verenigingen.verenigingen_payments.api.dd_batch_scheduler.daily_batch_optimization",
        # Create daily analytics snapshots
        "verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot.create_scheduled_snapshots",
        # Membership dues collection processing
        "verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor.create_monthly_dues_collection_batch",
        # Payment plan processing
        "verenigingen.verenigingen_payments.doctype.payment_plan.payment_plan.process_overdue_installments",
        # Security audit log cleanup
        "verenigingen.utils.security.audit_logging.cleanup_old_audit_logs",
        # Monitoring and alerting system
        "verenigingen.utils.alert_manager.run_daily_checks",
        # Address optimization maintenance
        "verenigingen.tasks.address_optimization.update_all_member_address_fingerprints",
    ],
    "hourly": [
        # Check analytics alert rules
        "verenigingen.verenigingen.doctype.analytics_alert_rule.analytics_alert_rule.check_all_active_alerts",
        # Monitoring and alerting system
        "verenigingen.utils.alert_manager.run_hourly_checks",
        # Payment history validation and repair (reduced from every 4 hours)
        "verenigingen.utils.payment_history_validator.validate_payment_history_integrity",
    ],
    "weekly": [
        # Termination reports and reviews
        "verenigingen.utils.termination_utils.generate_weekly_termination_report",
        # Security system health check
        "verenigingen.utils.security.audit_logging.weekly_security_health_check",
        # Address display refresh
        "verenigingen.tasks.address_optimization.refresh_member_address_displays",
        # Expense history integrity validation
        "verenigingen.utils.expense_history_batch_processor.validate_expense_history_integrity",
    ],
    "monthly": [
        # Address data cleanup
        "verenigingen.tasks.address_optimization.cleanup_orphaned_address_data",
        # Expense history cleanup
        "verenigingen.utils.expense_history_batch_processor.cleanup_orphaned_expense_history",
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

# Permission Query Methods
# ------------------------
permission_query_conditions = {
    "Member": "verenigingen.permissions.get_member_permission_query",
    "Membership": "verenigingen.permissions.get_membership_permission_query",
    "Membership Termination Request": "verenigingen.permissions.get_termination_permission_query",
    "Volunteer Expense": "verenigingen.permissions.get_volunteer_expense_permission_query",
    "Verenigingen Volunteer": "verenigingen.permissions.get_volunteer_permission_query",
    "Chapter Member": "verenigingen.permissions.get_chapter_member_permission_query",
    "Team Member": "verenigingen.permissions.get_team_member_permission_query",
    "Donor": "verenigingen.permissions.get_donor_permission_query",
    "Address": "verenigingen.permissions.get_address_permission_query",
}

has_permission = {
    "Member": "verenigingen.permissions.has_member_permission",
    "Membership": "verenigingen.permissions.has_membership_permission",
    "Membership Termination Request": "verenigingen.permissions.has_membership_termination_request_permission",
    "Volunteer Expense": "verenigingen.permissions.has_volunteer_expense_permission",
    "Verenigingen Volunteer": "verenigingen.permissions.has_volunteer_permission",
    "Donor": "verenigingen.permissions.has_donor_permission",
    "Address": "verenigingen.permissions.has_address_permission",
}

# Boot session hooks
# ------------------
boot_session = ["verenigingen.setup.document_links.setup_custom_document_links"]

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
    {
        "title": "Volunteer Portal",
        "route": "/volunteer_portal",
        "reference_doctype": "",
        "role": "Verenigingen Volunteer",
    },
]

# Override functions removed - only affecting website/portal, not desk

# Portal context processors
website_context = {"get_member_context": "verenigingen.utils.portal_customization.get_member_context"}

# Website context update hook - adds body classes for brand styling
update_website_context = ["verenigingen.utils.portal_customization.add_brand_body_classes"]

# Installation
# ------------
after_install = [
    "verenigingen.setup.execute_after_install",
    "verenigingen.setup.security_setup.setup_all_security",
]

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
    "Verenigingen Volunteer": "verenigingen.permissions.get_volunteer_permission_query",
    "Address": "verenigingen.permissions.get_address_permission_query",
    "Donor": "verenigingen.permissions.get_donor_permission_query",
    "Membership Dues Schedule": "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.get_permission_query_conditions",
    "Project": "verenigingen.utils.project_permissions.get_project_permission_query_conditions",
}

has_permission = {
    "Member": "verenigingen.permissions.has_member_permission",
    "Membership": "verenigingen.permissions.has_membership_permission",
    "Address": "verenigingen.permissions.has_address_permission",
    "Donor": "verenigingen.permissions.has_donor_permission",
    "Verenigingen Volunteer": "verenigingen.permissions.has_volunteer_permission",
    "Membership Dues Schedule": "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.has_permission",
    "Project": "verenigingen.utils.project_permissions.has_project_permission_via_team",
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
                    "Verenigingen Governance Auditor",
                    "Verenigingen Chapter Board Member",
                    "Verenigingen Member",
                    "Verenigingen Volunteer",
                    "Verenigingen Volunteer Manager",
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
        "filters": [["name", "in", ["Monthly Membership", "Quarterly Membership", "Annual Membership"]]],
    },
    # Membership Dues Schedule Templates
    {
        "doctype": "Membership Dues Schedule",
        "filters": [
            [
                "name",
                "in",
                [
                    "Monthly Membership Template",
                    "Quarterly Membership Template",
                    "Annual Membership Template",
                ],
            ]
        ],
    },
    # Item Groups
    {
        "doctype": "Item Group",
        "filters": [["name", "=", "Memberships"]],
    },
    # Items
    {
        "doctype": "Item",
        "filters": [["item_code", "=", "MEMBERSHIP"]],
    },
    # Updated to use dues schedule system instead of subscription plans
    # Team Roles
    {
        "doctype": "Team Role",
        "filters": [["name", "in", ["Team Leader", "Team Member", "Coordinator", "Secretary", "Treasurer"]]],
    },
    # Workspaces
    {
        "doctype": "Workspace",
        "filters": [["name", "in", ["E-Boekhouden", "Verenigingen"]]],
    },
    # Dashboard Charts
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
    # Dashboards
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
    # Custom HTML Blocks
    {"doctype": "Custom HTML Block", "filters": [["name", "=", "Page Links"]]},
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

# Command Registration
# -------------------
# Register custom commands with Frappe CLI
commands = [
    "verenigingen.commands.workspace.workspace",
]

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
