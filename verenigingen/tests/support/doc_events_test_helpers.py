"""Shared test helper for asserting on hooks/doc_events.py wiring.

Frappe's own doc_events convention accepts either a bare string or a list for
a single (doctype, event) pair; this normalizes to a list so callers can
uniformly assertIn/assertNotIn without each test re-implementing the
str-vs-list check.
"""


def get_doc_event_handlers(doctype: str, event: str) -> list:
    """Return the doc_events.py handler list for (doctype, event)."""
    from verenigingen.hooks.doc_events import doc_events

    handlers = doc_events.get(doctype, {}).get(event, [])
    if isinstance(handlers, str):
        handlers = [handlers]
    return handlers
