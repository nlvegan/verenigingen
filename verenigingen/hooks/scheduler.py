# verenigingen/hooks/scheduler.py
"""Scheduled task configuration.

Tasks are organized by frequency. Each task should:
- Be idempotent (safe to run multiple times)
- Handle its own error recovery
- Log meaningful progress information
- Not block for extended periods

Frequencies:
- daily: Runs once per day (typically early morning)
- hourly: Runs every hour
- weekly: Runs once per week
- monthly: Runs once per month
- cron: Custom cron expressions for specific timing
"""

scheduler_events = {
    # =========================================================================
    # DAILY TASKS
    # =========================================================================
    "daily": [
        # Member financial history refresh
        "verenigingen.verenigingen.doctype.member.scheduler.refresh_all_member_financial_histories",
        # Email system integration
        "verenigingen.email.email_group_sync.scheduled_email_group_sync",
        "verenigingen.email.automated_campaigns.process_scheduled_campaigns",
        # Core membership system
        "verenigingen.verenigingen.doctype.membership.scheduler.process_expired_memberships",
        "verenigingen.verenigingen.doctype.membership.scheduler.send_renewal_reminders",
        "verenigingen.verenigingen.doctype.membership.scheduler.notify_about_orphaned_records",
        "verenigingen.api.membership_application_review.send_overdue_notifications",
        # Dues schedule system
        "verenigingen.utils.dues_schedule_auto_creator.auto_create_missing_dues_schedules_scheduled",
        "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.generate_dues_invoices",
        "verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules",
        # Analytics and goals
        "verenigingen.verenigingen.doctype.membership_goal.membership_goal.update_all_goals",
        # Termination system maintenance
        "verenigingen.utils.termination_utils.process_overdue_termination_requests",
        "verenigingen.utils.termination_utils.audit_termination_compliance",
        # SEPA mandate management
        "verenigingen.verenigingen.doctype.member.mixins.sepa_mixin.check_sepa_mandate_discrepancies",
        "verenigingen.verenigingen_payments.api.sepa_mandate_management.periodic_sepa_mandate_child_table_sync",
        # Contact request automation
        "verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation.process_contact_request_automation",
        # E-Boekhouden integration
        "verenigingen.e_boekhouden.utils.eboekhouden_api.update_dashboard_data_periodically",
        # Payment processing
        "verenigingen.utils.payment_retry.execute_payment_retry",
        "verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation.reconcile_bank_transactions",
        "verenigingen.verenigingen_payments.utils.sepa_notifications.check_and_send_expiry_notifications",
        # Expense management
        "verenigingen.utils.native_expense_helpers.refresh_all_expense_approvers",
        "verenigingen.utils.department_approver_sync.sync_all_department_approvers",
        "verenigingen.utils.expense_history_batch_processor.process_pending_expense_history_updates",
        # SEPA Direct Debit
        "verenigingen.verenigingen_payments.api.dd_batch_scheduler.daily_batch_optimization",
        "verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor.create_monthly_dues_collection_batch",
        # Analytics
        "verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot.create_scheduled_snapshots",
        # Payment plans
        "verenigingen.verenigingen_payments.doctype.payment_plan.payment_plan.process_overdue_installments",
        # Security and monitoring
        "verenigingen.utils.security.audit_logging.cleanup_old_audit_logs",
        "verenigingen.utils.alert_manager.run_daily_checks",
        "verenigingen.utils.auth_monitoring.alert_if_auth_issues",
        # Performance monitoring
        "verenigingen.utils.bulk_performance_monitor.run_performance_monitoring",
        "verenigingen.utils.bulk_queue_config.monitor_bulk_queue_health",
        # Address optimization
        "verenigingen.tasks.address_optimization.update_all_member_address_fingerprints",
    ],
    # =========================================================================
    # HOURLY TASKS
    # =========================================================================
    "hourly": [
        # Security notifications
        "verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule.send_security_policy_change_digest",
        # Analytics alerts
        "verenigingen.verenigingen.doctype.analytics_alert_rule.analytics_alert_rule.check_all_active_alerts",
        # Monitoring
        "verenigingen.utils.alert_manager.run_hourly_checks",
        # Payment history validation
        "verenigingen.utils.payment_history_validator.validate_payment_history_integrity",
        # Bulk operations
        "verenigingen.utils.bulk_retry_processor.process_retry_queues",
        # Amendment processing (moved from daily for faster same-day processing)
        "verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.process_pending_amendments",
        # SEPA pain.002 ingestion - scans inbox for bank status reports, updates batch status
        "verenigingen.services.payment.pain002_ingestion_service.run_pain002_ingestion",
    ],
    # =========================================================================
    # WEEKLY TASKS
    # =========================================================================
    "weekly": [
        # Termination reports
        "verenigingen.utils.termination_utils.generate_weekly_termination_report",
        # Security health check
        "verenigingen.utils.security.audit_logging.weekly_security_health_check",
        # Address maintenance
        "verenigingen.tasks.address_optimization.refresh_member_address_displays",
        # Expense history validation
        "verenigingen.utils.expense_history_batch_processor.validate_expense_history_integrity",
        # Session cleanup
        "verenigingen.utils.session_cleanup_enhanced.scheduled_session_cleanup",
    ],
    # =========================================================================
    # MONTHLY TASKS
    # =========================================================================
    "monthly": [
        # Address data cleanup
        "verenigingen.tasks.address_optimization.cleanup_orphaned_address_data",
        # Expense history cleanup
        "verenigingen.utils.expense_history_batch_processor.cleanup_orphaned_expense_history",
    ],
}

# =========================================================================
# CRON JOBS - High frequency tasks
# =========================================================================
cron = {
    # Financial history batch processing - every 10 seconds
    "*/10 * * * * *": [
        "verenigingen.utils.financial_history_batch_processor.schedule_financial_history_processing"
    ],
}
