# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MembershipDuesScheduleReturn(Document):
    """One counted SEPA return of a Membership Dues Schedule (exact-match dedupe key, #3347)."""
