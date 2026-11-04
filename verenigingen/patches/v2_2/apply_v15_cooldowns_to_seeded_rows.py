"""Move seeded-default cooldowns to the v15 values the registry now carries (#2012).

#1998/#2016 seeded every registry key's row with the default 60 minutes. Maintainer ruling on #2012:
the registry takes the per-key cooldowns the v15 patches hard-coded (transactional keys mostly 0,
reminder keys longer), and a row that still holds the seeded 60 follows. Any other value is an
admin's own choice and is left alone.

Accepted by the ruling: a row an admin deliberately set to 60 cannot be told from the seeded
default, so it is moved too. Keys whose ruled value is itself 60 need no entry.

The values are frozen here, NOT read from the registry, so a later registry edit does not
retroactively rewrite rows at 60 when this patch has already run (or runs late on another site).
The keys are those where a v15 patch value differs from 60. The five #1999 dunning/subscription
keys are in it (v15 and #1999 agree), for sites seeded at 60 before #2013 gave them a value. The
#1999 reminder keys (``payment_reminder_friendly`` / ``_urgent``) are deliberately absent.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"
SEEDED_DEFAULT = 60
RULED_COOLDOWNS = {
    "anbi_consent_request": 43200,
    "dues_amendment_approved": 0,
    "dues_amendment_rejected": 0,
    "dues_schedule_manual_creation": 0,
    "expense_approved": 0,
    "expense_rejected": 0,
    "member_application_approved": 0,
    "member_application_rejected": 0,
    "membership_renewal_reminder": 1440,
    "payment_history_critical_error": 0,
    "payment_plan_approved": 0,
    "payment_plan_request": 0,
    "periodic_donation_cancellation": 0,
    "periodic_donation_confirmation": 0,
    "payment_failure_final": 0,
    "payment_failure_first": 1440,
    "payment_failure_second": 1440,
    "periodic_donation_expiry": 1440,
    "ponto_payment_link_request": 0,
    "sepa_batch_error": 0,
    "sepa_batch_warning": 30,
    "subscription_cancelled": 0,
    "subscription_suspended": 0,
    "system_stuck_schedules": 240,
    "termination_overdue": 1440,
}


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    # A direct UPDATE on the child rows: a Single's save would rewrite every row's `modified`.
    for key, minutes in RULED_COOLDOWNS.items():
        frappe.db.sql(
            """
            UPDATE `tabEmail Notification Type`
            SET cooldown_minutes = %s
            WHERE parent = %s AND parenttype = %s AND notification_key = %s AND cooldown_minutes = %s
            """,
            (minutes, DOCTYPE, DOCTYPE, key, SEEDED_DEFAULT),
        )
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)
