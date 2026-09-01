# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MemberIBANHistory(Document):
    """Child table (istable: 1) of Member.iban_history.

    #596: this class used to define validate(), which Frappe never calls on a
    child DocType -- there is no d.run_method("validate") for children anywhere
    in insert()/save(). The rules it stated (to_date/is_active consistency,
    changed_by default, BIC auto-derivation) are now enforced from
    Member.validate_iban_history_rows() (verenigingen/verenigingen/doctype/member/
    mixins/payment_mixin.py), which iterates this child table from the PARENT,
    where Frappe actually calls validate(). IBAN format/checksum validation is
    not repeated there either -- see that method's docstring.
    """
