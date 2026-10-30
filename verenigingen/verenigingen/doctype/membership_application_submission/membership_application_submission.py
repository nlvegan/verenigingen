# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
from frappe.model.document import Document


class MembershipApplicationSubmission(Document):
    """An unconfirmed short application. Holds the cleaned payload until the email is confirmed."""
