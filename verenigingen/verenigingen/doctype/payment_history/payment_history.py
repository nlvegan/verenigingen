# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentHistory(Document):
    """DocType marked `"istable": 1`, but not actually a child table of anything.

    #596: this class used to define validate() (cross-parent payment_id
    uniqueness via a raw SQL scan of the whole tabPayment History table, plus
    required-field checks). Frappe never runs it -- there is no
    d.run_method("validate") for children anywhere in insert()/save(). Not moved
    to a parent: no DocType JSON on this bench declares a Table field with
    `"options": "Payment History"`, and no non-test code references the doctype
    name "Payment History" at all -- it is unreachable via any real save path.
    (Donation's actual payment child table is the similarly-named but distinct
    "Donation Payment" -- see donation_payment.py.) The cross-parent uniqueness
    check this class attempted also could not have been expressed as "iterate
    the child table from the parent" even if this doctype were live: a parent's
    validate() only sees its own children, not siblings under other parents.
    Whether "Payment History" should be removed entirely is a separate,
    out-of-scope question -- this only removes the dead validate().
    """
