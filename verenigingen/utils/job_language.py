"""before_job hook: keep a background job from recursing when its user no longer exists (#1970)."""

import frappe


def mark_language_resolved_for_vanished_user(**_):
    """Stop Frappe's lazy job-language lookup from recursing for a deleted job user.

    Frappe's ``_()`` calls ``set_user_lang(job.user)`` on first use and sets ``job.lang_resolved``
    only afterwards. For a user that no longer exists that lookup raises ``DoesNotExistError``,
    whose message is built with ``_()`` again, so every translation in the job recurses until
    ``RecursionError`` (handler messages, the audit logger, Frappe's own ``log_error``).
    Marking the language resolved keeps the site default. ``frappe.db.exists`` is used because it
    builds no translated message; the existing-user case is left to Frappe untouched.
    """
    job = getattr(frappe.local, "job", None)
    user = job and job.user
    if user and user != "Administrator" and not frappe.db.exists("User", user):
        job.lang_resolved = True
