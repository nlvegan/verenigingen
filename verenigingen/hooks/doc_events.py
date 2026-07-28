# verenigingen/hooks/doc_events.py
"""Document event handler mappings.

Each handler string points to a function that receives (doc, method=None).
Handlers should be lightweight - heavy processing should be enqueued
via frappe.enqueue() to avoid blocking document operations.

Event Types and Execution Order:
================================

For NEW documents:
    before_validate -> validate -> before_save -> after_insert -> on_update -> on_change

For EXISTING documents:
    before_validate -> validate -> before_save -> on_update -> on_change

Key distinctions:
- after_insert: Only fires for new documents
- on_update: Fires for BOTH new and existing documents
- on_change: Fires for BOTH, and also on submit/cancel

`insert()` calls run_post_save_methods() (frappe/model/document.py), which runs
`on_update` because _action is "save" for a new draft. Its own docstring says it
executes "before_insert, validate, on_update, after_insert". Verified by trace:
insert fires after_insert THEN on_update; save fires on_update only.

This means:
- To run on ALL saves, register under on_update ALONE
- Use after_insert for handlers that should ONLY run on new document creation
- Do NOT register the same handler for both after_insert and on_update (runs twice
  on every insert)

THERE IS NO SERVER-SIDE `after_save` EVENT.
-------------------------------------------
It reads like one, but Document.run_method() is never called with that name and the
string appears nowhere in frappe's Python. Handlers registered under it resolve fine,
boot fine, and never run — no error, no log, just absence. Eight handlers sat here in
exactly that state, including every Member / Chapter Member / SEPA Mandate cache
invalidation. Likewise there is no server-side `after_validate`.

Scope note: `after_save` IS a real CLIENT-side form event (frappe/public/js/frappe/
form/form.js triggers it, and this app uses it in chapter.js, chapter_role.js,
member.js and volunteer.js). Nothing here applies to those — do not delete them.

`tests/test_hooks_modules.py::TestDocEventNamesAreDispatched` is the standing gate:
every key here must be an event the framework actually fires. Before adding a new
event name, confirm it against `grep -rn 'run_method("<name>")' apps/frappe/frappe/`.

Other events:
- validate: Before save, can modify doc or raise ValidationError
- before_save: After validate, before DB write
- on_submit: When document is submitted (docstatus 0->1)
- on_cancel: When document is cancelled (docstatus 1->2)
- on_trash: Before document deletion
- on_update_after_submit: When submitted document is modified

CHILD TABLES: doc_events on a child DocType (istable=1) do not fire for rows saved
via the parent document. They fire only when a child row is loaded and saved
directly (e.g. frappe.get_doc("Chapter Member", name).save()).
"""

doc_events = {
    # =========================================================================
    # COMMUNICATION / EMAIL
    # =========================================================================
    "Email Template": {
        # Invalidate the in-process EmailService template cache so edits and
        # deletions take effect immediately instead of being masked until the TTL.
        "on_update": "verenigingen.services.communication.email_service.on_email_template_change",
        "on_trash": "verenigingen.services.communication.email_service.on_email_template_change",
    },
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
        # These must run on ALL saves — on_update alone does that (it fires on insert
        # too). Registering them under after_insert as well would run them twice per
        # insert.
        #
        # DELIBERATELY NOT RESTORED: email_group_sync.sync_member_on_change.
        # It sat under the dead `after_save` key, so it has never run. Restoring it
        # would activate it on every Member save, and it has two open defects:
        #   1. remove_from_email_group() DELETES the Email Group Member row, which is
        #      where Frappe records an explicit newsletter unsubscribe. An
        #      opt-out -> opt-in toggle therefore silently clears that unsubscribe
        #      (add_to_email_group re-inserts with unsubscribed=0).
        #   2. It is not behind `enable_email_group_sync`, unlike its scheduled twin
        #      scheduled_email_group_sync, so it would add unconditional DB writes to
        #      a hot path.
        # Fix those first, then register it here alongside the cache handlers.
        "on_update": [
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_cache.on_member_update",
            # Update-only handlers below.
            "verenigingen.services.chapter.chapter_role_events.on_member_on_update",
            "verenigingen.services.field_sync_service.sync_fields",
            "verenigingen.services.member.account.member_user_email_sync.sync_user_email_on_member_update",
        ],
    },
    "Chapter Member": {
        # Chapter Member is a child table, so these do NOT fire for rows saved via
        # the parent Chapter. They do fire on direct saves — notably
        # member_subscribers._update_chapter_membership_status(), which
        # deactivates memberships on suspend/quit and is exactly the case where the
        # member's cached access must be invalidated.
        # on_update covers direct inserts too, so it is registered once.
        "on_update": "verenigingen.utils.performance_cache.on_chapter_member_update",
        "on_trash": "verenigingen.utils.performance_cache.on_chapter_member_update",
    },
    # =========================================================================
    # CHAPTER SYSTEM
    # =========================================================================
    "Chapter": {
        # validate: now handled in controller validate() method
        # Cache invalidation must run on ALL saves; on_update fires on insert too, so
        # one registration is enough. A Chapter save also covers its child rows (board
        # members, chapter members), which child-table hooks cannot see.
        "on_update": [
            "verenigingen.services.chapter.optimized_chapter_lookup.invalidate_chapter_lookup_cache",
            # Update-only handlers below.
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
        # NOTE: an "after_validate" entry was removed here — Frappe dispatches no
        # such event, so it never fired. Its target
        # (overrides.sales_invoice.after_validate) is a documented no-op placeholder,
        # so nothing behavioural changes; the dead registration is simply gone.
        "on_submit": [
            "verenigingen.events.invoice_events.emit_invoice_submitted",
            "verenigingen.utils.cache_invalidation.on_document_submit",
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
        # Cache invalidation must run on ALL saves; on_update fires on insert too, so
        # it is registered there only. after_insert keeps the insert-only audit hook.
        "after_insert": [
            "verenigingen.verenigingen_payments.doctype.sepa_mandate.sepa_mandate_audit_hooks.log_mandate_created",
        ],
        "on_update": [
            "verenigingen.verenigingen_payments.doctype.sepa_mandate.sepa_mandate_audit_hooks.log_mandate_status_change",
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
        ],
        # update_campaign_progress is NOT also on after_insert: on_update fires on
        # insert too, so listing it twice recomputed campaign progress twice per new
        # donation.
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
        # Clear the Customer.donor back-reference on delete so no Customer is
        # left pointing at a non-existent Donor (which would mis-link a future
        # donor via get_or_create_customer's {"donor": name} lookup).
        "on_trash": "verenigingen.services.member.donor.donor_customer_sync.clear_customer_link_on_donor_delete",
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
    # Note: "Membership Termination Request" on_update_after_submit hook removed -
    # it duplicated the controller's own on_update_after_submit method (which Frappe
    # calls automatically) and never fired anyway: the approval service persists via
    # .save() (docstatus stays 0), so no after-submit event is ever raised. Real
    # execution runs through the whitelisted execute_termination() doc method.
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
    # on_update fires on insert as well, so these need no after_insert twin — listing
    # them under both ran every one of them twice per newly created User/Role Profile/
    # Has Role. on_trash is a separate operation and is kept.
    "User": {
        "on_update": [
            "verenigingen.utils.security.cache_invalidation.invalidate_user_role_cache_on_user_update",
            "verenigingen.services.field_sync_service.sync_fields",
            "verenigingen.utils.user_desk_settings.ensure_desk_settings_for_role_profile",
            "verenigingen.events.subscribers.chapter_subscribers.cleanup_chapter_user_permissions_for_admins",
        ],
    },
    "Role Profile": {
        "on_update": "verenigingen.utils.security.cache_invalidation.invalidate_all_user_caches_on_role_profile_update",
        "on_trash": "verenigingen.utils.security.cache_invalidation.invalidate_all_user_caches_on_role_profile_update",
    },
    "Has Role": {
        "on_update": "verenigingen.utils.security.cache_invalidation.invalidate_user_cache_on_user_role_update",
        "on_trash": "verenigingen.utils.security.cache_invalidation.invalidate_user_cache_on_user_role_update",
    },
}
