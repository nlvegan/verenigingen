# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MemberIBANHistory(Document):
    def validate(self):
        # Validate IBAN format
        if self.iban:
            from verenigingen.utils.iban_validator import derive_bic_from_iban, format_iban, validate_iban

            # Validate IBAN
            validation_result = validate_iban(self.iban)
            if not validation_result["valid"]:
                frappe.throw(_(validation_result["message"]))

            # Format IBAN properly
            self.iban = format_iban(self.iban)

            # Auto-derive BIC if not provided
            if not self.bic:
                derived_bic = derive_bic_from_iban(self.iban)
                if derived_bic:
                    self.bic = derived_bic

        # Set changed_by if not set
        if not self.changed_by:
            self.changed_by = frappe.session.user

        # Validate dates
        if self.to_date and self.from_date and self.to_date < self.from_date:
            frappe.throw(_("Valid Until date cannot be before Valid From date"))

        # Check if marked as active but has end date
        if self.is_active and self.to_date:
            frappe.throw(_("Active IBAN records should not have an end date"))
