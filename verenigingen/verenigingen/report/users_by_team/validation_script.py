import frappe


def validate_report_dependencies():
    """
    Utility script to validate all dependencies for the Users by Team report.
    Run this to diagnose issues with the report's dependencies.
    """
    print("Validating report dependencies...")

    # Check doctypes exist
    doctypes = ["Team", "Team Member Role", "Team Role"]
    missing_doctypes = []

    for doctype in doctypes:
        if not frappe.db.exists("DocType", doctype):
            missing_doctypes.append(doctype)

    if missing_doctypes:
        print(f"WARNING: The following doctypes are missing: {', '.join(missing_doctypes)}")
    else:
        print("✓ All required doctypes exist")

    # Check fields in Team doctype
    team_fields = ["name", "team_lead"]
    missing_team_fields = []

    if "Team" not in missing_doctypes:
        meta = frappe.get_meta("Team")
        for field in team_fields:
            if not meta.has_field(field):
                missing_team_fields.append(field)

        if missing_team_fields:
            print(
                f"WARNING: The following fields are missing from Team doctype: {', '.join(missing_team_fields)}"
            )
        else:
            print("✓ All required Team fields exist")

    # Check fields in Team Member Role doctype
    tmr_fields = ["user", "team_role", "from_date", "to_date", "is_active", "parent", "parenttype"]
    missing_tmr_fields = []

    if "Team Member Role" not in missing_doctypes:
        meta = frappe.get_meta("Team Member Role")
        for field in tmr_fields:
            if not meta.has_field(field):
                missing_tmr_fields.append(field)

        if missing_tmr_fields:
            print(
                f"WARNING: The following fields are missing from Team Member Role doctype: {', '.join(missing_tmr_fields)}"
            )
        else:
            print("✓ All required Team Member Role fields exist")

    # Check fields in Team Role doctype
    tr_fields = ["name", "permissions_level"]
    missing_tr_fields = []

    if "Team Role" not in missing_doctypes:
        meta = frappe.get_meta("Team Role")
        for field in tr_fields:
            if not meta.has_field(field):
                missing_tr_fields.append(field)

        if missing_tr_fields:
            print(
                f"WARNING: The following fields are missing from Team Role doctype: {', '.join(missing_tr_fields)}"
            )
        else:
            print("✓ All required Team Role fields exist")

    # Check if Team Member Role is a child table of Team
    if "Team" not in missing_doctypes and "Team Member Role" not in missing_doctypes:
        team_meta = frappe.get_meta("Team")
        has_child_table = False

        for table_field in team_meta.get_table_fields():
            if table_field.options == "Team Member Role":
                has_child_table = True
                print("✓ Team Member Role is properly linked as a child table to Team")
                break

        if not has_child_table:
            print("WARNING: Team Member Role is not linked as a child table to Team doctype")

    print("Validation complete")


# To run this validation, execute:
# bench execute verenigingen.verenigingen.report.users_by_team.validation_script.validate_report_dependencies
