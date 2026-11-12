"""
Context for application success page
"""

from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.utils import get_url


def get_context(context):
    """Get context for application success page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Application Submitted Successfully")

    # Get member ID from URL parameter
    member_id = frappe.form_dict.get("id")
    payment_url = _same_site_payment_url(frappe.form_dict.get("payment_url"))

    context.member_id = member_id
    context.payment_url = payment_url

    return context


def _same_site_payment_url(url):
    """Return ``url`` only when it points at this site, else None (#2495).

    The value is guest-supplied and rendered as an href, so ``javascript:``/``data:`` and any
    foreign host would become a link on the association's own domain. Backslashes, whitespace and
    control characters are refused outright because browsers normalise them (``/\\evil.test`` is
    protocol-relative).
    """
    if not url or not isinstance(url, str):
        return None
    if any(ch == "\\" or ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url):
        return None
    try:
        parts = urlsplit(url)
        site_host = urlsplit(get_url()).hostname
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme or parts.netloc:
        if parts.scheme not in ("http", "https") or parts.username or not host or host != site_host:
            return None
    elif not url.startswith("/") or url.startswith("//"):
        return None
    return url
