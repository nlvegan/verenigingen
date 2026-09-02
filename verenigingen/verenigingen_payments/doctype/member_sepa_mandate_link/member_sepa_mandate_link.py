# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MemberSEPAMandateLink(Document):
    """Child table (istable: 1) of Member.sepa_mandates.

    #596: this class used to define validate() -- validate_mandate() (a msgprint
    warning if the linked mandate isn't Active -- cosmetic, blocked nothing) and
    check_current_mandate() (clear a sibling link's is_current when this one is
    set). Frappe never runs it -- there is no d.run_method("validate") for
    children anywhere in insert()/save(); had it ever run, check_current_mandate()
    would have crashed, since self.parent is the parent's NAME (a str), not a
    document -- `self.parent.sepa_mandates` is not a thing a string has. That bug
    dating to "always" is what #584 (a duplicate-Active-mandate defect) traced
    this dead code to in the first place.

    Not moved to the parent: is_current is actively maintained by the real write
    sites instead -- SEPAMandateMemberIntegrationService._sync_mandate_link()
    (verenigingen_payments/services/sepa_mandate_member_integration_service.py)
    sets is_current from the mandate's own Active status on every mandate change,
    and member_utils.py's mandate-selection/replacement flows explicitly clear
    every sibling link's is_current before setting the new one. Combined with
    #584's SEPAMandate.validate_single_active_mandate (only one Active mandate
    per member can exist at all), there is no remaining path this dead code could
    have been the only guard against.
    """
