"""What an anonymous provider webhook is allowed to tell its caller (#1804, #1772).

Pay.nl and Ponto need only the HTTP status: a 2xx stops redelivery, a non-2xx asks for
it. The body used to carry the processing result (transaction, reference document,
payment entry), ``str(e)``, the rate-limit reason and the name of the setting that
refused the request, and ``frappe.throw``/``msgprint`` calls made on the way in sat in
``message_log``, which the framework serialises into ``_server_messages``.

So every return from these handlers goes through :func:`webhook_ack`. It never sets or
changes the HTTP status (a real failure must stay non-2xx so the provider retries), and it
cuts ``message_log`` back to its length on entry.
"""

import frappe


def webhook_ack(messages_before: int) -> dict:
    """The one body an anonymous webhook caller gets: ``ok``, ``error`` or ``rate_limited``.

    ``messages_before`` is ``len(frappe.local.message_log or [])`` taken on entry to the
    handler. The status word is derived from the HTTP status the handler already set.
    """
    if frappe.local.message_log:
        del frappe.local.message_log[messages_before:]
    code = frappe.local.response.get("http_status_code") or 200
    if code == 429:
        return {"status": "rate_limited"}
    return {"status": "error" if code >= 400 else "ok"}


def message_log_length() -> int:
    """Length of ``message_log`` now; pass it to :func:`webhook_ack` later."""
    return len(frappe.local.message_log or [])
