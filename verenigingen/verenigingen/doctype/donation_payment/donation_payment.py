# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class DonationPayment(Document):
    """Child table (istable: 1) of Donation.payments.

    #596: this class used to define validate() (amount > 0; Mollie payments
    require mollie_payment_id). Frappe never runs it -- there is no
    d.run_method("validate") for children anywhere in insert()/save().

    `amount > 0` was NOT ported: reviving it as written would be a regression.
    Production deliberately appends NEGATIVE amounts here for refunds/reversals
    (mollie/services/webhook_wrapper_service_unified.py, e.g.
    `"amount": -float(...)`) -- so that rule is stale relative to current usage,
    not a gap to close.

    The Mollie-requires-mollie_payment_id check now runs from
    Donation.validate_payment_rows() (donation.py), iterating self.payments from
    the parent, where Frappe actually calls validate().
    """
