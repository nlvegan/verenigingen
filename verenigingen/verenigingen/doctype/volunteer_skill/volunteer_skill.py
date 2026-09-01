# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VolunteerSkill(Document):
    """Child table (istable: 1) of Volunteer.skills_and_qualifications.

    #596: this class used to define validate() (proficiency_level must parse as
    "N - Label" with N in 1..5). Frappe never runs it -- there is no
    d.run_method("validate") for children anywhere in insert()/save(). Not moved
    to the parent: proficiency_level is a Select field whose options are exactly
    "1 - Beginner", "2 - Basic", "3 - Intermediate", "4 - Advanced", "5 - Expert",
    and Frappe's own Document._validate_selects() (called from _validate() for
    children too, regardless of any custom validate()) already rejects any value
    outside that declared list -- this was always redundant.
    """
