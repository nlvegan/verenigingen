# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MemberSEPAMandateLink(Document):
    def validate(self):
        self.validate_mandate()
        self.check_current_mandate()

    def validate_mandate(self):
        """Ensure the linked SEPA mandate exists and is active"""
        if self.sepa_mandate:
            mandate = frappe.get_doc("SEPA Mandate", self.sepa_mandate)

            # Warn if mandate is not active
            if mandate.status != "Active":
                frappe.msgprint(
                    _("SEPA Mandate {0} is currently {1}").format(mandate.mandate_id, mandate.status),
                    indicator="orange",
                )

    def check_current_mandate(self):
        """Ensure only one current mandate per member"""
        if self.is_current:
            # Get parent document (Member)
            if self.parent and self.parenttype == "Member":
                # Check other mandate links for this member
                for link in self.parent.sepa_mandates:
                    if link.name != self.name and link.is_current:
                        link.is_current = 0
