# Copyright (c) 2025, Vereniging Veganisme and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TeamRoleProfileAssignment(Document):
    """
    Child DocType for configuring role-specific profile assignments within teams.

    This allows teams to assign different role profiles based on the specific
    team role (e.g., Team Lead gets different permissions than Team Member).

    #596: this class used to define validate() (role_profile and team_role must
    exist). Frappe never runs it -- there is no d.run_method("validate") for
    children anywhere in insert()/save(). Not moved to the parent: both fields are
    `reqd: 1` Link fields, and Frappe's own Document._validate_links() (called from
    both insert() and save(), for parent AND children, before any validate() runs)
    already rejects a Link value that does not exist -- this was always redundant.
    """
