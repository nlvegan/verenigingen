"""
Generate test members for onboarding
"""

from datetime import datetime, timedelta

import frappe


@frappe.whitelist()
def generate_test_members():
    """
    Generate test members from sample data
    This helps new users understand the member management system
    """

    # Sample data - realistic Dutch member data
    test_members = [
        {
            "first_name": "Jan",
            "preposition": "van den",
            "last_name": "Berg",
            "email": "jan.vandenberg@testvereniging.nl",
            "phone": "06-12345678",
            "street_address": "Dorpsstraat 12",
            "postal_code": "1234 AB",
            "city": "Utrecht",
            "country": "Nederland",
            "date_of_birth": "1985-05-01",
            "gender": "Man",
            "member_since": "2010-01-01",
            "membership_type": "Regulier lid",
        },
        {
            "first_name": "Sophie",
            "preposition": "",
            "last_name": "Jansen",
            "email": "sophie.jansen@testvereniging.nl",
            "phone": "06-23456789",
            "street_address": "Kerkplein 3",
            "postal_code": "2345 BC",
            "city": "Amsterdam",
            "country": "Nederland",
            "date_of_birth": "1992-08-15",
            "gender": "Vrouw",
            "member_since": "2011-02-03",
            "membership_type": "Regulier lid",
        },
        {
            "first_name": "Pieter",
            "preposition": "de",
            "last_name": "Vries",
            "email": "pieter.devries@testvereniging.nl",
            "phone": "06-34567890",
            "street_address": "Molenweg 45A",
            "postal_code": "3456 CD",
            "city": "Rotterdam",
            "country": "Nederland",
            "date_of_birth": "1978-11-20",
            "gender": "Man",
            "member_since": "2012-04-05",
            "membership_type": "Studentlid",
        },
        {
            "first_name": "Anna",
            "preposition": "van der",
            "last_name": "Meer",
            "email": "anna.vandermeer@testvereniging.nl",
            "phone": "06-67890123",
            "street_address": "Binnenweg 1C",
            "postal_code": "6789 FG",
            "city": "Groningen",
            "country": "Nederland",
            "date_of_birth": "1988-09-25",
            "gender": "Vrouw",
            "member_since": "2015-10-11",
            "membership_type": "Regulier lid",
        },
        {
            "first_name": "Tim",
            "preposition": "",
            "last_name": "Smit",
            "email": "tim.smit@testvereniging.nl",
            "phone": "06-78901234",
            "street_address": "Buitenweg 33",
            "postal_code": "7890 GH",
            "city": "Tilburg",
            "country": "Nederland",
            "date_of_birth": "2001-02-08",
            "gender": "Man",
            "member_since": "2016-12-13",
            "membership_type": "Studentlid",
        },
        {
            "first_name": "Eva",
            "preposition": "",
            "last_name": "Mulder",
            "email": "eva.mulder@testvereniging.nl",
            "phone": "06-89012345",
            "street_address": "Heuvel 5",
            "postal_code": "8901 HI",
            "city": "Almere",
            "country": "Nederland",
            "date_of_birth": "1999-06-18",
            "gender": "Vrouw",
            "member_since": "2018-01-15",
            "membership_type": "Regulier lid",
        },
        {
            "first_name": "Noa",
            "preposition": "",
            "last_name": "Brouwer",
            "email": "noa.brouwer@testvereniging.nl",
            "phone": "06-01234567",
            "street_address": "Veldweg 9",
            "postal_code": "1012 JK",
            "city": "Nijmegen",
            "country": "Nederland",
            "date_of_birth": "2003-04-22",
            "gender": "Vrouw",
            "member_since": "2020-05-20",
            "membership_type": "Studentlid",
        },
    ]

    created_members = []
    errors = []

    # Check if we already have test members
    existing_test_members = frappe.get_all(
        "Member", filters={"email": ["like", "%@testvereniging.nl"]}, fields=["name", "email"]
    )

    existing_emails = [member.email for member in existing_test_members]

    # Get organization
    organization = frappe.db.get_single_value("Verenigingen Settings", "organization")
    if not organization:
        # Try to get any organization
        organizations = frappe.get_all("Organization", limit=1)
        if organizations:
            organization = organizations[0].name
        else:
            return {"success": False, "error": "No organization found. Please create an organization first."}

    for member_data in test_members:
        try:
            # Skip if already exists
            if member_data["email"] in existing_emails:
                continue

            # Create member
            member = frappe.new_doc("Member")

            # Personal information
            member.first_name = member_data["first_name"]
            member.preposition = member_data["preposition"]
            member.last_name = member_data["last_name"]

            # Construct full name
            name_parts = [member_data["first_name"]]
            if member_data["preposition"]:
                name_parts.append(member_data["preposition"])
            name_parts.append(member_data["last_name"])
            member.full_name = " ".join(name_parts)

            # Contact information
            member.email = member_data["email"]
            member.phone = member_data["phone"]

            # Address information
            member.street_address = member_data["street_address"]
            member.postal_code = member_data["postal_code"]
            member.city = member_data["city"]
            member.country = member_data["country"]

            # Personal details
            member.date_of_birth = member_data["date_of_birth"]
            member.gender = member_data["gender"]

            # Membership details
            member.member_since = member_data["member_since"]
            member.membership_type = member_data["membership_type"]
            member.organization = organization

            # Set status
            member.membership_status = "Active"

            # Determine chapter based on city
            chapter_mapping = {
                "Amsterdam": "Amsterdam",
                "Rotterdam": "Rotterdam",
                "Den Haag": "Den Haag",
                "Utrecht": "Utrecht",
                "Groningen": "Groningen",
                "Nijmegen": "Nijmegen",
            }

            # Try to find chapter
            for city_name, chapter_name in chapter_mapping.items():
                if city_name in member_data["city"]:
                    chapter = frappe.db.get_value("Chapter", {"region": chapter_name}, "name")
                    if chapter:
                        member.primary_chapter = chapter
                        break

            # Save the member
            member.insert(ignore_permissions=True)

            # Create membership record
            membership = frappe.new_doc("Membership")
            membership.member = member.name
            membership.membership_type = member_data["membership_type"]
            membership.from_date = member_data["member_since"]

            # Calculate to_date (1 year from member_since)
            from_date = datetime.strptime(member_data["member_since"], "%Y-%m-%d")
            to_date = from_date + timedelta(days=365)
            membership.to_date = to_date.strftime("%Y-%m-%d")

            membership.insert(ignore_permissions=True)

            created_members.append(
                {
                    "name": member.name,
                    "full_name": member.full_name,
                    "email": member.email,
                    "chapter": member.primary_chapter,
                }
            )

        except Exception as e:
            errors.append(
                {"member": f"{member_data['first_name']} {member_data['last_name']}", "error": str(e)}
            )

    # Create summary
    summary = {
        "created": len(created_members),
        "skipped": len(existing_emails),
        "errors": len(errors),
        "total_test_members": len(created_members) + len(existing_emails),
    }

    message = f"""
    <h4>Test Members Generated</h4>
    <ul>
        <li><strong>Created:</strong> {summary['created']} new members</li>
        <li><strong>Skipped:</strong> {summary['skipped']} (already exist)</li>
        <li><strong>Errors:</strong> {summary['errors']}</li>
        <li><strong>Total Test Members:</strong> {summary['total_test_members']}</li>
    </ul>
    """

    if created_members:
        message += "<p>You can now view these members in the Member list and explore the member management features.</p>"

    return {
        "success": True,
        "summary": summary,
        "created_members": created_members,
        "errors": errors,
        "message": message,
    }


@frappe.whitelist()
def cleanup_test_members():
    """
    Remove test members (those with @testvereniging.nl email addresses)
    """
    test_members = frappe.get_all(
        "Member", filters={"email": ["like", "%@testvereniging.nl"]}, fields=["name"]
    )

    deleted_count = 0
    for member in test_members:
        try:
            # Delete associated records first
            # Delete memberships
            memberships = frappe.get_all("Membership", filters={"member": member.name})
            for membership in memberships:
                frappe.delete_doc("Membership", membership.name, ignore_permissions=True)

            # Delete the member
            frappe.delete_doc("Member", member.name, ignore_permissions=True)
            deleted_count += 1
        except Exception as e:
            frappe.log_error(f"Failed to delete test member {member.name}: {str(e)}")

    return {
        "success": True,
        "deleted": deleted_count,
        "message": f"Deleted {deleted_count} test members and their associated records",
    }


@frappe.whitelist()
def get_test_members_status():
    """
    Get status of test members
    """
    test_members = frappe.get_all(
        "Member",
        filters={"email": ["like", "%@testvereniging.nl"]},
        fields=["name", "full_name", "email", "membership_status", "current_chapter_display", "member_since"],
    )

    # Group by status
    status_summary = {}
    for member in test_members:
        status = member.membership_status or "Unknown"
        if status not in status_summary:
            status_summary[status] = 0
        status_summary[status] += 1

    # Group by chapter
    chapter_summary = {}
    for member in test_members:
        chapter = member.primary_chapter or "No Chapter"
        if chapter not in chapter_summary:
            chapter_summary[chapter] = 0
        chapter_summary[chapter] += 1

    return {
        "total": len(test_members),
        "by_status": status_summary,
        "by_chapter": chapter_summary,
        "members": test_members,
    }
