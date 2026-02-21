"""
Sales Invoice overrides.

The monkey-patch of erpnext.accounts.party.validate_due_date was removed 2026-02-21.
Root cause: invoice_generator.py was setting due_date = today() + 30 days, but for
retroactive billing (coverage_start in the past), this could produce due_date < posting_date.
Fix: due_date is now set to coverage_start + 45 days in invoice_generator.py.

The empty doc_event stubs below are still registered in hooks/doc_events.py.
They are harmless no-ops kept to avoid removing hook entries mid-release.
"""


def custom_validate(doc, method):
    """Sales Invoice validate hook — no-op placeholder."""


def after_validate(doc, method):
    """Sales Invoice after_validate hook — no-op placeholder."""
