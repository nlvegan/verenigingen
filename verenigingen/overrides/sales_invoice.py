"""
Sales Invoice overrides.

The monkey-patch of erpnext.accounts.party.validate_due_date was removed 2026-02-21.
Root cause: invoice_generator.py was setting due_date = today() + 30 days, but for
retroactive billing (coverage_start in the past), this could produce due_date < posting_date.
Fix: due_date is now set to coverage_start + 45 days in invoice_generator.py.

custom_validate() is still registered under Sales Invoice `validate` in
hooks/doc_events.py — a harmless no-op kept to avoid removing a hook entry
mid-release.

after_validate() is NOT registered any more: Frappe dispatches no server-side
`after_validate` event, so that registration never fired and was removed. The
function is now unreferenced dead code and can be deleted.
"""


def custom_validate(doc, method):
    """Sales Invoice validate hook — no-op placeholder."""


def after_validate(doc, method):
    """Sales Invoice after_validate hook — no-op placeholder."""
