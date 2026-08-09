# verenigingen/hooks/permissions.py
"""Permission query conditions and has_permission handlers.

permission_query_conditions: Functions that return SQL WHERE clauses
to filter document lists based on user permissions.

has_permission: Functions that check if a user has permission to
access a specific document instance.

These work together with DocType permissions to provide row-level security.
"""

# SQL WHERE clause generators for list queries
# Each function receives (user) and returns a SQL condition string or None
permission_query_conditions = {
    "Member": "verenigingen.permissions.get_member_permission_query",
    "Membership": "verenigingen.permissions.get_membership_permission_query",
    "Employee": "verenigingen.permissions.get_employee_permission_query",
    "Chapter": "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_permission_query_conditions",
    "Chapter Member": "verenigingen.permissions.get_chapter_member_permission_query",
    "Team": "verenigingen.verenigingen.doctype.team.team.get_team_permission_query_conditions",
    "Team Member": "verenigingen.permissions.get_team_member_permission_query",
    "Membership Termination Request": "verenigingen.permissions.get_termination_permission_query",
    "Volunteer": "verenigingen.permissions.get_volunteer_permission_query",
    "Address": "verenigingen.permissions.get_address_permission_query",
    "Donor": "verenigingen.permissions.get_donor_permission_query",
    "SEPA Mandate": "verenigingen.permissions.get_sepa_mandate_permission_query",
    "Membership Dues Schedule": "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.get_permission_query_conditions",
    "Project": "verenigingen.utils.project_permissions.get_project_permission_query_conditions",
    "Expense Claim": "verenigingen.permissions.get_expense_claim_permission_query",
    "Event Contact Campaign": "verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.get_permission_query_conditions",
}

# Document-level permission checkers
# Each function receives (doc, user, permission_type) and returns True/False
has_permission = {
    "Member": "verenigingen.permissions.has_member_permission",
    "Employee": "verenigingen.permissions.has_employee_permission",
    "Membership": "verenigingen.permissions.has_membership_permission",
    "Membership Termination Request": "verenigingen.permissions.has_membership_termination_request_permission",
    "Address": "verenigingen.permissions.has_address_permission",
    "Donor": "verenigingen.permissions.has_donor_permission",
    "SEPA Mandate": "verenigingen.permissions.has_sepa_mandate_permission",
    "Donation": "verenigingen.permissions.has_donation_permission",
    "Volunteer": "verenigingen.permissions.has_volunteer_permission",
    "Team": "verenigingen.verenigingen.doctype.team.team.has_team_permission",
    "Chapter": "verenigingen.verenigingen.doctype.chapter.chapter.has_chapter_permission",
    "Membership Dues Schedule": "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule.has_permission",
    "Project": "verenigingen.utils.project_permissions.has_project_permission_via_team",
    "Expense Claim": "verenigingen.permissions.has_expense_claim_permission",
    "Event Contact Campaign": "verenigingen.verenigingen.doctype.event_contact_campaign.event_contact_campaign.has_permission",
}
