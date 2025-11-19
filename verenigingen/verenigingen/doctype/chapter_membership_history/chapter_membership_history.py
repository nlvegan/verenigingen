# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ChapterMembershipHistory(Document):
    """
    Child doctype to track historical chapter memberships for members.

    This tracks both regular membership and board member assignments
    with status changes over time.
    """
