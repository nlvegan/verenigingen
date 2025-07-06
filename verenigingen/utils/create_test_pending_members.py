"""
Create test members with Pending status bypassing automatic validation
"""

import frappe


@frappe.whitelist()
def create_test_pending_members():
    """Create test members with Pending status by bypassing validation"""

    try:
        # Define test members
        test_members = [
            {
                "first_name": "Jan",
                "middle_name": "van den",
                "last_name": "Berg",
                "email": "jan.vandenberg@email.nl",
                "contact_number": "06-12345678",
                "birth_date": "1985-05-01",
                "pronouns": "He/him",
            },
            {
                "first_name": "Sophie",
                "middle_name": "",
                "last_name": "Jansen",
                "email": "sophie.jansen@email.nl",
                "contact_number": "06-23456789",
                "birth_date": "1992-08-15",
                "pronouns": "She/her",
            },
            {
                "first_name": "Eva",
                "middle_name": "",
                "last_name": "Mulder",
                "email": "eva.mulder@email.nl",
                "contact_number": "06-89012345",
                "birth_date": "1999-06-18",
                "pronouns": "She/her",
            },
            {
                "first_name": "Noa",
                "middle_name": "",
                "last_name": "Brouwer",
                "email": "noa.brouwer@email.nl",
                "contact_number": "06-01234567",
                "birth_date": "2003-04-22",
                "pronouns": "She/her",
            },
            {
                "first_name": "Lucas",
                "middle_name": "de",
                "last_name": "Vries",
                "email": "lucas.devries@email.nl",
                "contact_number": "06-34567890",
                "birth_date": "1990-11-12",
                "pronouns": "He/him",
            },
            {
                "first_name": "Emma",
                "middle_name": "van",
                "last_name": "Dijk",
                "email": "emma.vandijk@email.nl",
                "contact_number": "06-45678901",
                "birth_date": "1988-03-27",
                "pronouns": "She/her",
            },
            {
                "first_name": "Mohammed",
                "middle_name": "",
                "last_name": "Hassan",
                "email": "mohammed.hassan@email.nl",
                "contact_number": "06-56789012",
                "birth_date": "1995-07-08",
                "pronouns": "He/him",
            },
        ]

        created_members = []
        errors = []

        for member_data in test_members:
            try:
                # Check if member already exists
                existing = frappe.db.exists("Member", {"email": member_data["email"]})
                if existing:
                    continue

                # Create full name
                name_parts = [member_data["first_name"]]
                if member_data.get("middle_name"):
                    name_parts.append(member_data["middle_name"])
                name_parts.append(member_data["last_name"])
                full_name = " ".join(name_parts)

                # Create member document
                member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "first_name": member_data["first_name"],
                        "last_name": member_data["last_name"],
                        "full_name": full_name,
                        "email": member_data.get("email"),
                        "contact_number": member_data.get("contact_number"),
                        "birth_date": member_data.get("birth_date"),
                        "application_date": frappe.utils.nowdate(),
                        "review_notes": "Test member created via onboarding for workflow testing",
                    }
                )

                # Add optional fields if they exist
                if member_data.get("middle_name"):
                    member.middle_name = member_data["middle_name"]
                if member_data.get("pronouns"):
                    member.pronouns = member_data["pronouns"]

                # Insert the member first
                member.insert(ignore_permissions=True)

                # Now directly update the status fields using SQL to bypass validation
                frappe.db.sql(
                    """
                    UPDATE `tabMember`
                    SET status = 'Pending',
                        application_status = 'Pending'
                    WHERE name = %s
                """,
                    member.name,
                )

                frappe.db.commit()

                created_members.append({"name": member.name, "full_name": full_name, "email": member.email})

            except Exception as e:
                errors.append(
                    {"member": f"{member_data['first_name']} {member_data['last_name']}", "error": str(e)}
                )

        return {
            "success": True,
            "message": f"✅ Successfully created {len(created_members)} test members with Pending status!",
            "created": len(created_members),
            "error_count": len(errors),
            "created_members": created_members,
            "errors": errors,
        }

    except Exception as e:
        frappe.log_error(f"Test member generation failed: {str(e)}")
        return {"success": False, "message": f"❌ Error generating test members: {str(e)}"}


@frappe.whitelist()
def force_pending_status():
    """Force all test members to have Pending status"""

    try:
        # Get all test members
        test_members = frappe.db.sql(
            """
            SELECT name
            FROM `tabMember`
            WHERE email LIKE '%@email.nl'
        """,
            as_dict=True,
        )

        updated_count = 0

        for member in test_members:
            # Update status directly via SQL to bypass validation
            frappe.db.sql(
                """
                UPDATE `tabMember`
                SET status = 'Pending',
                    application_status = 'Pending',
                    application_date = CURDATE(),
                    review_notes = 'Test member - forced to Pending status for workflow testing'
                WHERE name = %s
            """,
                member.name,
            )
            updated_count += 1

        frappe.db.commit()

        return {
            "success": True,
            "message": f"✅ Successfully forced {updated_count} test members to Pending status!",
            "updated": updated_count,
        }

    except Exception as e:
        frappe.log_error(f"Force pending status failed: {str(e)}")
        return {"success": False, "message": f"❌ Error forcing pending status: {str(e)}"}
