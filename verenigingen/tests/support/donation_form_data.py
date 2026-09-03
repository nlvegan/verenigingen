"""Shared builder for minimal, valid public-donation-form payloads.

Both test_guest_donation_flow.py (templates/pages/donate.py's submit_donation,
via the donor/public-donation services) and test_donation_web_form.py
(web_form/donation_form/donation_form.py's process_donation_form) need the
same minimal valid donation-form dict. The two entry points differ only in
which key they read the payment method from ("payment_method" vs
"mode_of_payment") and in what donor-name prefix is useful for telling their
Error Log / DB rows apart while debugging. Consolidated here after the
duplicate-helper ratchet flagged _make_form_data as a new two-file clone
family (#755 review).
"""

from frappe.utils import now_datetime


def make_donation_form_data(*, label, payment_key, payment_method="Bank Transfer", **overrides):
    """Build a minimal valid donation-form payload.

    Args:
        label: Donor-name/email prefix, e.g. "Guest Donor" or "Web Form Donor".
        payment_key: Which key the target function expects the payment method
            under -- "payment_method" (templates/pages/donate.py) or
            "mode_of_payment" (web_form/donation_form/donation_form.py).
        payment_method: Payment method value.
        **overrides: Any additional/overriding keys, applied last -- may also
            override payment_method by passing payment_key's own name.
    """
    ts = now_datetime().strftime("%H%M%S%f")
    slug = label.lower().replace(" ", ".")
    data = {
        "donor_name": f"{label} {ts}",
        "donor_email": f"{slug}.{ts}@example.com",
        "donor_type": "Individual",
        "amount": "25.00",
        payment_key: payment_method,
        "donation_purpose_type": "General",
    }
    data.update(overrides)
    return data
