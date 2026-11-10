"""
Short guest return route for Ponto Payment Link redirects (/ponto-return).

Ponto rejects a payment-request redirectUri longer than 255 characters, and the
/api/method/... path of payment_link_callback with two 64-hex tokens did not fit. This page
serves the same callback logic on a short path; the old /api/method endpoint stays for links
whose URL is already stored at Ponto.
"""

import frappe
from frappe.utils import get_url

from verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback import payment_link_callback


def get_context(context):
    context.no_cache = 1
    if frappe.request.method == "GET":
        # Whitelisting is only consulted at dispatch, so calling it here keeps its rate limit
        # (Critical Operation Rule) and every guard; it answers through frappe.local.response.
        payment_link_callback()
        location = (frappe.local.response or {}).get("location")
    else:
        # The /api endpoint is GET-only; do not let a POST (always committed) reach the logic.
        location = None
    frappe.local.flags.redirect_location = location or get_url("/app/home")
    # 302, not Redirect's default 301: this answer differs per request and must not be cached.
    raise frappe.Redirect(302)
