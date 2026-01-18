# verenigingen/hooks/doc_events.py
"""Document event handler mappings.

Each handler string points to a function that receives (doc, method=None).
Handlers should be lightweight - heavy processing should be enqueued
via frappe.enqueue() to avoid blocking document operations.

Event Types:
- validate: Before save, can modify doc or raise ValidationError
- before_save: After validate, before DB write
- after_save: After DB write (for both insert and update)
- on_update: After save for existing documents
- after_insert: After save for new documents only
- on_submit: When document is submitted (docstatus 0->1)
- on_cancel: When document is cancelled (docstatus 1->2)
- on_trash: Before document deletion
- on_update_after_submit: When submitted document is modified
"""

doc_events = {
    # =========================================================================
    # CORE MEMBERSHIP SYSTEM
    # =========================================================================
    "Membership": {
        # validate: now handled in controller validate() method
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
    "Member": {
        "before_save": "verenigingen.verenigingen.doctype.member.member_utils.update_termination_status_display",
        "after_save": [
            "verenigingen.email.email_group_sync.sync_member_on_change",
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_cache.on_member_update",
        ],
        "on_update": [
            "verenigingen.utils.chapter_role_events.on_member_on_update",
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_cache.on_member_update",
            "verenigingen.services.field_sync_service.sync_fields",
        ],
    },
    "Chapter Member": {
        "after_save": "verenigingen.utils.performance_cache.on_chapter_member_update",
        "on_update": "verenigingen.utils.performance_cache.on_chapter_member_update",
        "on_trash": "verenigingen.utils.performance_cache.on_chapter_member_update",
    },
    # =========================================================================
    # CHAPTER SYSTEM
    # =========================================================================
    "Chapter": {
        # validate: now handled in controller validate() method
        "on_update": [
            "verenigingen.utils.optimized_chapter_lookup.invalidate_chapter_lookup_cache",
            "verenigingen.utils.chapter_role_profile_hooks.on_chapter_board_members_change",
            "verenigingen.utils.chapter_role_profile_hooks.invalidate_chapter_profile_cache",
        ],
        "after_save": "verenigingen.utils.optimized_chapter_lookup.invalidate_chapter_lookup_cache",
    },
    "Verenigingen Chapter Board Member": {
        "after_insert": [
            "verenigingen.utils.chapter_role_events.on_chapter_board_member_after_insert",
            "verenigingen.utils.department_approver_sync.on_board_member_change",
        ],
        "on_update": [
            "verenigingen.utils.chapter_role_events.on_chapter_board_member_on_update",
            "verenigingen.utils.department_approver_sync.on_board_member_change",
        ],
        "on_trash": [
            "verenigingen.utils.chapter_role_events.on_chapter_board_member_on_trash",
            "verenigingen.utils.department_approver_sync.on_board_member_change",
        ],
    },
    "Chapter Role": {
        "on_update": "verenigingen.utils.chapter_role_events.on_chapter_role_on_update",
    },
    "Chapter Board Member": {
        "after_insert": "verenigingen.utils.chapter_role_profile_manager.on_chapter_board_member_add",
        "on_update": "verenigingen.utils.chapter_role_profile_manager.on_chapter_board_member_update",
    },
    # =========================================================================
    # TEAM SYSTEM
    # =========================================================================
    "Team": {
        "on_update": [
            "verenigingen.utils.team_role_profile_hooks.on_team_lead_change",
            "verenigingen.utils.team_role_profile_hooks.on_team_members_change",
            "verenigingen.utils.team_role_profile_hooks.invalidate_team_profile_cache",
        ],
    },
    "Team Member": {
        "after_insert": "verenigingen.utils.team_role_profile_manager.on_team_member_add",
        "on_update": "verenigingen.utils.team_role_profile_manager.on_team_member_update",
    },
    # =========================================================================
    # VOLUNTEER SYSTEM
    # =========================================================================
    "Verenigingen Volunteer": {
        "on_update": [
            "verenigingen.utils.native_expense_helpers.update_employee_approver",
            "verenigingen.utils.chapter_role_events.on_volunteer_on_update",
            "verenigingen.utils.performance_event_handlers.on_volunteer_assignment_change",
            "verenigingen.utils.volunteer_role_profile_hooks.on_volunteer_status_change",
        ],
    },
    # =========================================================================
    # FINANCIAL SYSTEM - PAYMENTS
    # =========================================================================
    "Payment Entry": {
        "on_submit": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.payment_notifications.on_payment_submit",
            "verenigingen.utils.background_jobs.queue_expense_event_processing_handler",
            "verenigingen.utils.background_jobs.queue_donor_auto_creation_handler",
            "verenigingen.utils.cache_invalidation.on_document_submit",
            "verenigingen.utils.performance_event_handlers.on_member_payment_update",
        ],
        "on_cancel": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.cache_invalidation.on_document_cancel",
        ],
        "on_trash": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.utils.cache_invalidation.on_document_update",
        ],
    },
    "Sales Invoice": {
        "before_validate": [
            "verenigingen.utils.apply_tax_exemption_from_source",
            "verenigingen.utils.sales_invoice_hooks.set_member_from_customer",
            "verenigingen.utils.sales_invoice_hooks.populate_member_chapter",
        ],
        "validate": [
            "verenigingen.overrides.sales_invoice.custom_validate",
            "verenigingen.utils.sales_invoice_account_handler.set_membership_receivable_account",
        ],
        "after_validate": ["verenigingen.overrides.sales_invoice.after_validate"],
        "on_submit": [
            "verenigingen.events.invoice_events.emit_invoice_submitted",
            "verenigingen.utils.cache_invalidation.on_document_submit",
            "verenigingen.utils.performance_event_handlers.on_member_payment_update",
        ],
        "on_update_after_submit": [
            "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
            "verenigingen.utils.cache_invalidation.on_document_update",
        ],
        "on_cancel": [
            "verenigingen.events.invoice_events.emit_invoice_cancelled",
            "verenigingen.utils.cache_invalidation.on_document_cancel",
        ],
        "on_trash": [
            "verenigingen.utils.sales_invoice_hooks.on_trash",
        ],
    },
    "Journal Entry": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry",
        "on_submit": "verenigingen.utils.donor_auto_creation.process_payment_for_donor_creation",
    },
    "Bank Transaction": {
        "on_submit": "verenigingen.utils.donor_auto_creation.process_payment_for_donor_creation",
    },
    # =========================================================================
    # FINANCIAL SYSTEM - EXPENSES
    # =========================================================================
    "Expense Claim": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_expense_claim",
        "on_update_after_submit": "verenigingen.events.delayed_expense_hooks.schedule_member_expense_history_update",
        "on_submit": "verenigingen.utils.expense_handlers.update_member_expense_history",
        "on_cancel": [
            "verenigingen.events.delayed_expense_hooks.schedule_member_expense_history_removal",
            "verenigingen.utils.expense_handlers.on_expense_claim_cancel",
        ],
    },
    "Purchase Invoice": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_purchase_invoice",
    },
    # =========================================================================
    # FINANCIAL SYSTEM - SEPA
    # =========================================================================
    "SEPA Mandate": {
        "after_save": [
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_event_handlers.on_sepa_mandate_change",
        ],
        "on_submit": "verenigingen.utils.cache_invalidation.on_document_submit",
        "on_cancel": "verenigingen.utils.cache_invalidation.on_document_cancel",
        "on_trash": "verenigingen.utils.cache_invalidation.on_document_update",
    },
    # =========================================================================
    # DONATION SYSTEM
    # =========================================================================
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
    "Donor": {
        "after_save": "verenigingen.utils.donor_customer_sync.sync_donor_to_customer",
        "on_update": "verenigingen.utils.donor_customer_sync.sync_donor_to_customer",
    },
    # =========================================================================
    # CUSTOMER INTEGRATION
    # =========================================================================
    "Customer": {
        "validate": "verenigingen.verenigingen_payments.mollie.utils.data_validator.validate_mollie_customer_data",
        "after_save": [
            "verenigingen.utils.donor_customer_sync.sync_customer_to_donor",
            "verenigingen.utils.cache_invalidation.on_document_update",
        ],
        "on_update": [
            "verenigingen.utils.donor_customer_sync.sync_customer_to_donor",
            "verenigingen.utils.cache_invalidation.on_document_update",
        ],
    },
    # =========================================================================
    # TERMINATION SYSTEM
    # =========================================================================
    "Membership Termination Request": {
        # validate: now handled in controller validate() method
        "on_update_after_submit": "verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.handle_status_change",
    },
    # Note: Expulsion Report Entry hooks removed - these were incorrectly
    # referencing controller methods (validate, before_save, after_insert)
    # which are already called automatically by Frappe via the controller.
    # =========================================================================
    # SETTINGS
    # =========================================================================
    "Verenigingen Settings": {
        # validate: now handled in controller validate() method
        "on_update": [
            "verenigingen.verenigingen.doctype.member.member_utils.sync_member_counter_with_settings",
            "verenigingen.utils.optimized_chapter_lookup.invalidate_chapter_lookup_cache",
        ],
    },
    # =========================================================================
    # SECURITY & USER MANAGEMENT
    # =========================================================================
    "User": {
        "on_update": [
            "verenigingen.utils.security.cache_invalidation.invalidate_user_role_cache_on_user_update",
            "verenigingen.services.field_sync_service.sync_fields",
        ],
        "after_insert": "verenigingen.utils.security.cache_invalidation.invalidate_user_role_cache_on_user_update",
    },
    "Role Profile": {
        "on_update": "verenigingen.utils.security.cache_invalidation.invalidate_all_user_caches_on_role_profile_update",
        "after_insert": "verenigingen.utils.security.cache_invalidation.invalidate_all_user_caches_on_role_profile_update",
        "on_trash": "verenigingen.utils.security.cache_invalidation.invalidate_all_user_caches_on_role_profile_update",
    },
    "Has Role": {
        "on_update": "verenigingen.utils.security.cache_invalidation.invalidate_user_cache_on_user_role_update",
        "after_insert": "verenigingen.utils.security.cache_invalidation.invalidate_user_cache_on_user_role_update",
        "on_trash": "verenigingen.utils.security.cache_invalidation.invalidate_user_cache_on_user_role_update",
    },
}
