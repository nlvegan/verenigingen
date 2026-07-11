# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentPlanPayment(Document):
    """A single online-payment attempt for one payment-plan installment.

    Acts as the reference document handed to the payment gateway: it exposes the
    installment `amount`/`currency` the gateway reads and the `payment_id` it
    writes back, so the shared gateway is reused unchanged. The Mollie webhook
    finalizes the installment (via PaymentPlan.process_payment) and flips this
    record to Paid.
    """

    pass
