# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class EventContactCampaignMember(Document):
    def before_save(self):
        """Auto-fill contacted_date and contacted_by when contacted is checked."""
        # Get the previous state if this is an existing row
        if self.contacted and not self.contacted_date:
            self.contacted_date = now_datetime()

        if self.contacted and not self.contacted_by:
            self.contacted_by = frappe.session.user

        # Update contact_method if contacted but still set to "Not Contacted"
        if self.contacted and self.contact_method == "Not Contacted":
            self.contact_method = "Other"

        # Clear contact fields if unchecked
        if not self.contacted:
            self.contact_method = "Not Contacted"
