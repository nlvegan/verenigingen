# verenigingen/hooks/doc_events.py
"""Document event handler mappings.

Each handler string points to a function that receives (doc, method=None).
Handlers should be lightweight - heavy processing should be enqueued
via frappe.enqueue() to avoid blocking document operations.

Event Types and Execution Order:
================================

For NEW documents:
    validate -> before_save -> after_insert -> after_save

For EXISTING documents:
    validate -> before_save -> after_save -> on_update

Key distinctions:
- after_insert: Only fires for new documents
- on_update: Only fires for existing documents (after after_save)
- after_save: Fires for BOTH new and existing documents

This means:
- Use after_save for handlers that should run on ALL saves
- Use on_update for handlers that should ONLY run on updates to existing docs
- Use after_insert for handlers that should ONLY run on new document creation
- Do NOT register the same handler for both after_save and on_update (runs twice)

Other events:
- validate: Before save, can modify doc or raise ValidationError
- before_save: After validate, before DB write
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
        # after_save fires for both new and existing documents
        "after_save": [
            "verenigingen.email.email_group_sync.sync_member_on_change",
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_cache.on_member_update",
        ],
        # on_update fires only for existing documents (after after_save)
        # Only include handlers that need to run specifically for updates, not inserts
        "on_update": [
            "verenigingen.services.chapter.chapter_role_events.on_member_on_update",
            "verenigingen.services.field_sync_service.sync_fields",
        ],
    },
    "Chapter Member": {
        # after_save fires for both new and existing documents
        "after_save": "verenigingen.utils.performance_cache.on_chapter_member_update",
        # on_trash for deletion events
        "on_trash": "verenigingen.utils.performance_cache.on_chapter_member_update",
    },
    # =========================================================================
    # CHAPTER SYSTEM
    # =========================================================================
    "Chapter": {
        # validate: now handled in controller validate() method
        # after_save: runs for BOTH new and existing - use for cache invalidation
        "after_save": "verenigingen.services.chapter.optimized_chapter_lookup.invalidate_chapter_lookup_cache",
        # on_update: runs ONLY for existing documents - use for update-specific logic
        "on_update": [
            "verenigingen.services.chapter.chapter_role_profile_hooks.invalidate_chapter_profile_cache",
        ],
        # NOTE: Role assignment and role profile sync for board members is handled
        # explicitly by BoardManager.handle_board_member_additions/changes/deletions
        # (called from Chapter.before_save). Child table doc_events (after_insert,
        # on_update, on_trash) never fire for rows managed via parent save, so those
        # hooks were removed.
    },
    "Chapter Role": {
        "on_update": "verenigingen.services.chapter.chapter_role_events.on_chapter_role_on_update",
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
    # NOTE: Team Member is a child table (istable=1). Child table doc_events
    # (after_insert, on_update, on_trash) never fire when rows are managed via
    # parent save. Role profile sync is handled by Team.on_update hooks above.
    # =========================================================================
    # VOLUNTEER SYSTEM
    # =========================================================================
    "Verenigingen Volunteer": {
        "on_update": [
            "verenigingen.services.volunteer.native_expense_helpers.update_employee_approver",
            "verenigingen.services.chapter.chapter_role_events.on_volunteer_on_update",
            "verenigingen.utils.performance_event_handlers.on_volunteer_assignment_change",
            "verenigingen.services.volunteer.volunteer_role_profile_hooks.on_volunteer_status_change",
        ],
    },
    # =========================================================================
    # FINANCIAL SYSTEM - PAYMENTS
    # =========================================================================
    "Payment Entry": {
        "on_submit": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
            "verenigingen.verenigingen_payments.utils.payment_notifications.on_payment_submit",
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
            "verenigingen.services.billing.sales_invoice_hooks.set_member_from_customer",
            "verenigingen.services.billing.sales_invoice_hooks.populate_member_chapter",
        ],
        "validate": [
            "verenigingen.overrides.sales_invoice.custom_validate",
            "verenigingen.services.billing.sales_invoice_account_handler.set_membership_receivable_account",
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
            "verenigingen.services.billing.sales_invoice_hooks.on_trash",
        ],
    },
    "Journal Entry": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry",
        "on_submit": "verenigingen.services.member.donor.donor_auto_creation.process_payment_for_donor_creation",
    },
    "Bank Transaction": {
        "on_submit": "verenigingen.services.member.donor.donor_auto_creation.process_payment_for_donor_creation",
    },
    # =========================================================================
    # FINANCIAL SYSTEM - EXPENSES
    # =========================================================================
    "Expense Claim": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_expense_claim",
        "on_update_after_submit": "verenigingen.events.delayed_expense_hooks.schedule_member_expense_history_update",
        "on_submit": [
            "verenigingen.services.volunteer.expense_handlers.update_member_expense_history",
            "verenigingen.services.volunteer.expense_handlers.notify_expense_approvers",
        ],
        "on_cancel": [
            "verenigingen.events.delayed_expense_hooks.schedule_member_expense_history_removal",
            "verenigingen.services.volunteer.expense_handlers.on_expense_claim_cancel",
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
        # Note: on_update fires after after_save, so we only register once
        "on_update": "verenigingen.services.member.donor.donor_customer_sync.sync_donor_to_customer",
    },
    # =========================================================================
    # CUSTOMER INTEGRATION
    # =========================================================================
    "Customer": {
        "validate": "verenigingen.verenigingen_payments.mollie.utils.data_validator.validate_mollie_customer_data",
        # Note: on_update fires after after_save, so we only register once
        "on_update": [
            "verenigingen.services.member.donor.donor_customer_sync.sync_customer_to_donor",
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
            "verenigingen.services.chapter.optimized_chapter_lookup.invalidate_chapter_lookup_cache",
        ],
    },
    # =========================================================================
    # SECURITY & USER MANAGEMENT
    # =========================================================================
    "User": {
        "on_update": [
            "verenigingen.utils.security.cache_invalidation.invalidate_user_role_cache_on_user_update",
            "verenigingen.services.field_sync_service.sync_fields",
            "verenigingen.utils.user_desk_settings.ensure_desk_settings_for_role_profile",
        ],
        "after_insert": [
            "verenigingen.utils.security.cache_invalidation.invalidate_user_role_cache_on_user_update",
            "verenigingen.utils.user_desk_settings.ensure_desk_settings_for_role_profile",
        ],
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
