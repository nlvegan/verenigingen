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

import hashlib

import frappe

# An anonymous caller chooses how many requests it sends and how long its ids are, so what a
# failing webhook writes to the Error Log must be bounded by neither (#1822, #2136).
ERROR_LOG_DEDUPE_SECONDS = 3600
LOGGED_ID_LENGTH = 64
LOGGED_MESSAGE_LENGTH = 4000


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


def first_in_window(key: str, seconds: int = ERROR_LOG_DEDUPE_SECONDS) -> bool:
    """True for the first call with ``key`` in ``seconds``; False for every repeat in the window."""
    if frappe.cache.get_value(key):
        return False
    frappe.cache.set_value(key, 1, expires_in_sec=seconds)
    return True


def short_id(value) -> str:
    """The first 64 characters of a caller-supplied id, for a log line."""
    return str(value)[:LOGGED_ID_LENGTH]


def log_error_once(title: str, message: str, *key_parts) -> bool:
    """One Error Log row per (title, ``key_parts``) per hour, the message cut to 4000 chars.

    ``key_parts`` must be things the caller cannot multiply at will (its IP, an exception
    class), never the id it supplied. Returns whether a row was written. Keywords below
    because this app's positional (title, message) order is routinely swapped.
    """
    fingerprint = "|".join([title, *(str(p) for p in key_parts)])
    key = "webhook_error_log_once:" + hashlib.sha256(fingerprint.encode()).hexdigest()
    if not first_in_window(key):
        return False
    frappe.log_error(title=title[:140], message=message[:LOGGED_MESSAGE_LENGTH])
    return True
