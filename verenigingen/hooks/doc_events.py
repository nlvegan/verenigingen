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
    # The DocType is "Volunteer". Four handlers sat under the key "Verenigingen
    # Volunteer" -- a Role name, not a DocType -- from the commit that created
    # volunteer.json (2dbea04eb, 2025-11-20), so none of them ever ran.
    # get_doc_hooks() keys on doctype name and never looks a stray key up: no
    # error, no log. ALL FOUR are retired; Volunteer dispatches no doc_events (#688).
    #
    # volunteer_role_profile_hooks.on_volunteer_status_change was going to be
    # RESTORED under "Volunteer" -- Volunteer.status really is an input to
    # calculate_user_role_profile() via is_active_volunteer(), and nothing else live
    # recalculates on a status change, so the profile goes stale. Restoring it was
    # MEASURED to be destructive and was withdrawn:
    #
    #   origin/develop  tests/security/test_permissions_doc_checks_coverage  31 OK
    #   with the handler wired under "Volunteer"                             5 FAILED
    #
    # It loses board users their role. sync_user_role_profile() REPLACES
    # User.role_profiles, and User.populate_role_profile_roles() then resets
    # User.roles from that profile -- so the directly-assigned "Verenigingen Chapter
    # Board Member" role is stripped and _users_with_chapter_board_role() returns
    # ['Administrator']. That is the same ordering hazard
    # BoardManager.flush_pending_board_profile_syncs documents (apply the profile
    # FIRST, then the role, because a later profile sync undoes a role granted before
    # it): the handler is a second writer of the role profile, firing at an
    # uncontrolled time.
    #
    # #688's blast-radius measurement said 0 of 15 board users would lose the role.
    # That number was real but did not discriminate: 14 of the 15 were protected by
    # an early return (no Member record), not by the logic. Fixtures DO have Member
    # records and take the real path.
    #
    # The staleness gap is therefore still open and is tracked separately -- closing
    # it means changing how sync_user_role_profile and directly-assigned roles
    # interact, which is not a doc_events change. The function is deliberately left
    # in place for that work rather than deleted.
    #
    # The other three, and why none of them is a gap:
    #
    # chapter_role_events.on_volunteer_on_update. It called
    # permissions.assign_chapter_board_role(), whose else-branch raw-deletes the
    # Has Role row. BoardManager.handle_board_member_additions/changes/deletions
    # already owns that decision and orders it deliberately: role profile first,
    # then role withdrawal, because User.populate_role_profile_roles() resets
    # User.roles from the assigned profile on every save and would undo a removal
    # performed before it. A Volunteer-side second writer does only the removal,
    # so its effect is undone by the next User save. The function was deleted
    # along with this registration; it had no other caller. The defect itself is
    # still live in on_member_on_update ("Member") and on_chapter_role_on_update
    # ("Chapter Role"), which call the same function -- #702, which also carries the
    # Volunteer.member re-link case BoardManager cannot see.
    #
    # performance_event_handlers.on_volunteer_assignment_change. Inert even when
    # registered correctly: its body branches on doc.doctype == "Verenigingen
    # Volunteer", so a real Volunteer save falls through every branch. Measured
    # on test_site_1 (2026-08-31): 0 bulk-loader calls for doctype "Volunteer",
    # 1 for the string the body tests. A speculative cache warm, same shape as
    # the SEPA Mandate preload declined below. The function was deleted with the
    # registration -- it had none left anywhere, and leaving a body that still
    # names two non-DocTypes would invite exactly the "just fix the key" revival
    # this block argues against.
    #
    # native_expense_helpers.update_employee_approver. The daily scheduled
    # refresh_all_expense_approvers (hooks/scheduler.py) already recomputes
    # Employee.expense_approver for every volunteer with an employee_id, through
    # this same function. A Volunteer on_update is the wrong trigger regardless:
    # the value derives from Chapter Board Member / Chapter Member / Team Member
    # rows and Verenigingen Settings, none of which touch the Volunteer doc.
    # Nothing writes Volunteer.employee_id through the ORM either: the ACR pipeline
    # uses frappe.db.set_value (account_creation_manager.py:341), which dispatches no
    # document event at all -- that is true of set_value generally, not of the
    # update_modified=False flag, which only suppresses the timestamp. So this
    # handler would have run on saves that cannot change the approver and missed
    # every change that can.
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
        # Payment Reconciliation allocates a previously unallocated payment by setting
        # ignore_validate_update_after_submit and calling .save() on the submitted entry
        # (reconcile_against_document, erpnext/accounts/utils.py:554), so the only event
        # it dispatches is this one -- and at on_submit time the payment named no
        # invoice, so the drain queued there had nothing to correct (#649).
        "on_update_after_submit": [
            "verenigingen.utils.background_jobs.queue_member_payment_history_update_handler",
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
        #
        # The credit note handler is registered alongside the event route rather than
        # inside it: the route refreshes `event_data["invoice"]`, which for a credit
        # note is the credit note, while the outstanding that moved belongs to
        # `return_against` (#649). It returns immediately for anything that is not a
        # return booked against another invoice.
        "on_submit": [
            "verenigingen.events.invoice_events.emit_invoice_submitted",
            "verenigingen.utils.background_jobs.queue_credit_note_payment_history_update_handler",
            "verenigingen.utils.cache_invalidation.on_document_submit",
        ],
        "on_update_after_submit": [
            "verenigingen.events.invoice_events.emit_invoice_updated_after_submit",
            "verenigingen.utils.cache_invalidation.on_document_update",
        ],
        # Cancelling the credit note gives the original invoice its outstanding back,
        # which is the same defect in the other direction.
        "on_cancel": [
            "verenigingen.events.invoice_events.emit_invoice_cancelled",
            "verenigingen.utils.background_jobs.queue_credit_note_payment_history_update_handler",
            "verenigingen.utils.cache_invalidation.on_document_cancel",
        ],
        "on_trash": [
            "verenigingen.services.billing.sales_invoice_hooks.on_trash",
        ],
    },
    "Journal Entry": {
        "validate": "verenigingen.utils.account_group_validation_hooks.validate_journal_entry",
        "on_submit": [
            "verenigingen.services.member.donor.donor_auto_creation.process_payment_for_donor_creation",
            "verenigingen.utils.background_jobs.queue_journal_entry_payment_history_update_handler",
        ],
        # A Journal Entry against a member's receivable moves the invoice's
        # outstanding_amount in both directions -- submit restores it, cancel
        # takes it away again -- and neither reaches the Sales Invoice
        # on_update_after_submit route (#645).
        "on_cancel": [
            "verenigingen.utils.background_jobs.queue_journal_entry_payment_history_update_handler",
        ],
        # The same reconciliation path for a Journal Entry payment. NOT an exact twin of
        # the Payment Entry case: reconcile_against_document passes do_not_save=True for
        # a Payment Entry and saves once itself (utils.py:554), but lets
        # update_reference_in_journal_entry save (utils.py:728) and then saves AGAIN --
        # so a JE reconciliation dispatches this event N+1 times for N rows. Redundant,
        # not wrong: the drain is idempotent. It is not deduplicated away because
        # deduplicate=True is inert under enqueue_after_commit=True (#648).
        "on_update_after_submit": [
            "verenigingen.utils.background_jobs.queue_journal_entry_payment_history_update_handler",
        ],
    },
    "Bank Transaction": {
        "on_submit": "verenigingen.services.member.donor.donor_auto_creation.process_payment_for_donor_creation",
    },
    # The producer none of the registrations above can see: UnreconcilePayment.on_submit
    # calls update_voucher_outstanding directly, once per allocation row, and unlinks the
    # reference with raw query-builder updates -- so it posts no GL row and saves neither
    # the Payment Entry nor the Journal Entry it is undoing. Undoing an allocation puts a
    # member invoice's outstanding back, and nothing refreshed the history row (#649).
    "Unreconcile Payment": {
        "on_submit": [
            "verenigingen.utils.background_jobs.queue_unreconcile_payment_history_update_handler",
        ],
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
        #
        # DELIBERATELY NOT RESTORED: performance_event_handlers.on_sepa_mandate_change.
        # It sat under the dead `after_save` key, so it has never run. It is a
        # speculative preload — it warms a mandate cache for a read that may never
        # come — and it reaches that cache through OptimizedSEPAQueries.
        # get_active_mandates_for_members(), which is a security-decorated API.
        # Measured cost of putting it on the save path (test_site_1, 2026-07-29):
        #   cache_invalidation.on_document_update      1 query
        #   on_sepa_mandate_change                     5 queries, one of which is
        #                                              INSERT INTO `tabAPI Audit Log`
        # So every mandate save would write an audit row and consume rate-limit
        # budget for an internal call that is not an API request at all — a bulk
        # mandate import would trip the limiter and start failing. Reviving a dead
        # cache-warm is not worth that; if the preload is wanted, call the undecorated
        # query layer directly.
        "on_update": [
            "verenigingen.verenigingen_payments.doctype.sepa_mandate.sepa_mandate_audit_hooks.log_mandate_status_change",
            "verenigingen.utils.cache_invalidation.on_document_update",
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
