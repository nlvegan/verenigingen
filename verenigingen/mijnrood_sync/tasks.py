"""
MijnRood Sync Scheduled Tasks

Entry points for Frappe scheduler. Each function is idempotent and
handles its own error recovery.
"""

import frappe


def run_mijnrood_sync():
    """Scheduled task entry point for MijnRood polling.

    Checks if sync is enabled before running. Called by the scheduler
    every 15 minutes (configured in hooks/scheduler.py cron dict).

    Concurrency is enforced inside polling_service.run_sync() via a
    cache-based lease, not by the Settings.last_sync_status field —
    that flag would get stranded by crashed runs.
    """
    settings = frappe.get_single("MijnRood Sync Settings")
    if not settings.enabled:
        return

    from verenigingen.mijnrood_sync.services.polling_service import get_polling_service

    service = get_polling_service()
    service.run_sync()
