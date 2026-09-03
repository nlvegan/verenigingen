"""Campaign donation API.

The Donation Campaign public page (`/campaign/<name>`, `templates/pages/campaign.html`)
posts its donation form to `verenigingen.api.donation_api.process_campaign_donation`.
That module never existed (#430) -- the page resolved fine but the donate button did
nothing. This delegates to `PublicDonationService.submit()`, the same orchestration
`/donate` uses (`templates/pages/donate.py:submit_donation`), mapping the campaign
form's field names onto what the service expects.

The campaign form has no payment-method selector (unlike `/donate`), so this defaults
to Mollie -- the site's only self-service online gateway -- when the caller does not
supply one; a guest can still override it, same as /donate.

Field mapping (campaign form name -> service field name):
  donation_campaign -> campaign_reference (PublicDonationService's Campaign branch)
  donation_message   -> donation_notes     (service field; the form's own name would
                                             otherwise be silently dropped)

`create_periodic_agreement` is accepted but not yet acted on: the campaign form
offers it (gated on `anbi_enabled`), but wiring a public donation to a Periodic
Donation Agreement is a separate, currently-unpublished web form
(`verenigingen/verenigingen/web_form/periodic_donation_agreement_form`) -- out of
scope for #430, which is about calls that don't resolve rather than an incomplete
downstream feature. Left as a known follow-up rather than silently dropping the
checkbox from the form.
"""

import frappe

from verenigingen.services.donation.public_donation_service import get_public_donation_service
from verenigingen.utils.security.api_security_framework import OperationType, public_api


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def process_campaign_donation(**kwargs):
    """Process a donation submitted from a Donation Campaign public page."""
    form_data = frappe._dict(kwargs)
    if form_data.get("donation_campaign") and not form_data.get("campaign_reference"):
        form_data["campaign_reference"] = form_data["donation_campaign"]
    if form_data.get("donation_message") and not form_data.get("donation_notes"):
        form_data["donation_notes"] = form_data["donation_message"]
    form_data.setdefault("payment_method", "Mollie")
    return get_public_donation_service().submit(form_data)
