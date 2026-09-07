"""Shared HMAC return-token helpers for guest-reachable page-render disclosures.

Several `templates/pages/*.py::get_context` controllers resolve a
caller-supplied, guessable/enumerable document identifier and render a
document's details with no session to check ownership against (the guest
has not logged in -- they are returning from a payment provider, or
following a link sent directly to them). #1018/PR #1054 established the
pattern for `donate.py`: mint an HMAC-SHA256 proof, keyed by the site's own
encryption key (no new stored secret, no schema change -- mirrors Frappe
core's own `frappe.utils.verified_command.get_secret()`), embed it only in
the one URL construction site we control, and require it before disclosing
anything. This module generalizes that pattern for the sibling findings in
#1053/#1055 (and any future one) instead of copy-pasting the same two
functions per page.

A `purpose` string scopes each token to the caller's own namespace (e.g.
"ponto_payment_link", "payment_success") so a token minted for one purpose
cannot be replayed against a different check that happens to share the same
raw identifier.

Trade-offs, carried over from #1054's review and unchanged here:
- No expiry. A leaked/forwarded URL grants access to that one document's
  disclosed fields indefinitely. Accepted for the same reason as #1054: the
  gateway/redirect round-trip has no other channel to carry a proof.
- The token travels in a URL, so it reaches browser history, `Referer`
  headers and server access logs.
- Keyed by the site encryption key: rotating that key invalidates every
  outstanding return link.
"""

import hashlib
import hmac


def generate_guest_return_token(purpose: str, identifier: str) -> str:
    """Sign a proof that this browser is the one being sent back for
    `identifier` under `purpose`.

    Uses the site's own encryption key (`frappe.utils.password.get_encryption_key`)
    as the HMAC secret, so no new stored secret or schema change is needed --
    the same choice #1054 made and confirmed mirrors Frappe core's
    `frappe.utils.verified_command.get_secret()`.
    """
    from frappe.utils.password import get_encryption_key

    secret = get_encryption_key().encode("utf-8")
    message = f"{purpose}:{identifier}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_guest_return_token(purpose: str, identifier: str, token: str) -> bool:
    """Constant-time check of a token produced by generate_guest_return_token.

    Fails closed: a missing/empty token is rejected before any comparison.
    """
    if not token:
        return False
    expected = generate_guest_return_token(purpose, identifier)
    return hmac.compare_digest(expected, token)
