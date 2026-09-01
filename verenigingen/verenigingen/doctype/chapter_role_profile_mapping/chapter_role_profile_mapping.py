# Copyright (c) 2025, Vereniging Veganisme and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ChapterRoleProfileMapping(Document):
    """
    Child DocType for configuring role-specific profile assignments within chapter boards.

    This allows chapters to assign different role profiles based on the specific
    board role (e.g., Chapter Treasurer gets different permissions than Secretary).

    #596: this class used to define validate() (role_profile and chapter_role must
    exist). Frappe never runs it -- there is no d.run_method("validate") for
    children anywhere in insert()/save(). Not moved to the parent: both fields are
    `reqd: 1` Link fields, and Frappe's own Document._validate_links() (called from
    both insert() and save(), for parent AND children, before any validate() runs)
    already rejects a Link value that does not exist -- this was always redundant.
    """
