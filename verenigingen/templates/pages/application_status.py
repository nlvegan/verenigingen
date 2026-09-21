"""
Context for application status page
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name, get_member_chapters
from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token

# Namespaces the HMAC return token minted at application-submission time
# (submit_application, verenigingen/api/membership_application.py) for the
# "Check Application Status" link (#1051). Distinct from every other page's
# purpose string so a token minted here cannot be replayed against a
# different guest-return check that happens to share the same identifier.
APPLICATION_STATUS_TOKEN_PURPOSE = "application_status"


def get_context(context):
    """Get context for application status page"""

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Application Status")

    # Get member from URL parameter or logged in user
    member_id = frappe.form_dict.get("id")

    if member_id:
        # A guest-reachable GET carrying a caller-supplied member id, with no
        # session to check ownership against. Member.autoname is
        # format:Assoc-Member-{YYYY}-{MM}-{####} -- sequential and enumerable
        # -- so the id alone proves nothing (#1051). Ownership is proven
        # either by the HMAC return token minted for this member at
        # application-submission time (same shape as donate.py #1018 and
        # payment_success.py/ponto_pay.py #1053/#1055), or by the caller
        # being logged in AS that same member already (same shape as
        # payment_retry.py #1052) -- e.g. a member who bookmarked their own
        # status link. Anything else -- Guest with no/wrong token, or a
        # logged-in member requesting a DIFFERENT member's id -- is refused
        # exactly like an unknown id, checked before any Member table access
        # so an unknown id and a wrong token cost and look identical.
        token = frappe.form_dict.get("token")
        token_proves_ownership = verify_guest_return_token(APPLICATION_STATUS_TOKEN_PURPOSE, member_id, token)
        session_proves_ownership = (
            frappe.session.user != "Guest" and get_current_user_member_name() == member_id
        )
        if not (token_proves_ownership or session_proves_ownership):
            member_id = None
    elif frappe.session.user != "Guest":
        # No id supplied: fall back to the caller's own logged-in session, as
        # before -- unrelated to the token check above, since this identity
        # is already bound to the session rather than caller-supplied.
        member_id = get_current_user_member_name()

    if member_id:
        member = frappe.get_doc("Member", member_id)
        context.member = member
        context.member_chapters = get_member_chapters(member_id)
    else:
        context.member = None
        context.member_chapters = []

    return context
