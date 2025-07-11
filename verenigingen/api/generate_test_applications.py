"""
Generate test membership applications for onboarding
"""

import random

import frappe


@frappe.whitelist()
def generate_test_members():
    """
    Generate test membership applications from sample data
    This helps new users understand the application review process
    """

    # Sample data - only active members who would realistically apply
    test_members = [
        {
            "first_name": "Jan",
            "preposition": "van den",
            "last_name": "Berg",
            "street": "Dorpsstraat",
            "house_number": "12",
            "postal_code": "1234 AB",
            "city": "Utrecht",
            "country": "Nederland",
            "phone": "030-1234567",
            "mobile": "06-12345678",
            "email": "jan.vandenberg@email.nl",
            "birth_date": "1985-05-01",
            "gender": "Male",
            "iban": "NL91ABNA0417164300",
            "payment_method": "SEPA Direct Debit",
        },
        {
            "first_name": "Sophie",
            "preposition": "",
            "last_name": "Jansen",
            "street": "Kerkplein",
            "house_number": "3",
            "postal_code": "2345 BC",
            "city": "Amsterdam",
            "country": "Nederland",
            "phone": "020-2345678",
            "mobile": "06-23456789",
            "email": "sophie.jansen@email.nl",
            "birth_date": "1992-08-15",
            "gender": "Female",
            "iban": "NL91ABNA0417164301",
            "payment_method": "Bank Transfer",
        },
        {
            "first_name": "Pieter",
            "preposition": "de",
            "last_name": "Vries",
            "street": "Molenweg",
            "house_number": "45A",
            "postal_code": "3456 CD",
            "city": "Rotterdam",
            "country": "Nederland",
            "phone": "010-3456789",
            "mobile": "06-34567890",
            "email": "pieter.devries@email.nl",
            "birth_date": "1978-11-20",
            "gender": "Male",
            "iban": "NL91ABNA0417164302",
            "payment_method": "SEPA Direct Debit",
        },
        {
            "first_name": "Anna",
            "preposition": "van der",
            "last_name": "Meer",
            "street": "Binnenweg",
            "house_number": "1C",
            "postal_code": "6789 FG",
            "city": "Groningen",
            "country": "Nederland",
            "phone": "050-6789012",
            "mobile": "06-67890123",
            "email": "anna.vandermeer@email.nl",
            "birth_date": "1988-09-25",
            "gender": "Female",
            "iban": "NL91ABNA0417164305",
            "payment_method": "SEPA Direct Debit",
        },
        {
            "first_name": "Tim",
            "preposition": "",
            "last_name": "Smit",
            "street": "Buitenweg",
            "house_number": "33",
            "postal_code": "7890 GH",
            "city": "Tilburg",
            "country": "Nederland",
            "phone": "013-7890123",
            "mobile": "06-78901234",
            "email": "tim.smit@email.nl",
            "birth_date": "2001-02-08",
            "gender": "Male",
            "iban": "NL91ABNA0417164306",
            "payment_method": "Bank Transfer",
        },
        {
            "first_name": "Eva",
            "preposition": "",
            "last_name": "Mulder",
            "street": "Heuvel",
            "house_number": "5",
            "postal_code": "8901 HI",
            "city": "Almere",
            "country": "Nederland",
            "phone": "036-8901234",
            "mobile": "06-89012345",
            "email": "eva.mulder@email.nl",
            "birth_date": "1999-06-18",
            "gender": "Female",
            "iban": "NL91ABNA0417164307",
            "payment_method": "SEPA Direct Debit",
        },
        {
            "first_name": "Noa",
            "preposition": "",
            "last_name": "Brouwer",
            "street": "Veldweg",
            "house_number": "9",
            "postal_code": "1012 JK",
            "city": "Nijmegen",
            "country": "Nederland",
            "phone": "024-0123456",
            "mobile": "06-01234567",
            "email": "noa.brouwer@email.nl",
            "birth_date": "2003-04-22",
            "gender": "Female",
            "iban": "NL91ABNA0417164309",
            "payment_method": "SEPA Direct Debit",
        },
    ]

    created_applications = []
    errors = []

    # Motivations for joining
    motivations = [
        "Ik wil graag actief bijdragen aan de doelstellingen van de vereniging en deel uitmaken van deze gemeenschap.",
        "Via een vriend(in) hoorde ik over jullie vereniging en de activiteiten spreken mij zeer aan.",
        "Ik ben geïnteresseerd in de missie van de vereniging en wil graag mijn steentje bijdragen.",
        "De waarden van de vereniging sluiten perfect aan bij mijn persoonlijke overtuigingen.",
        "Ik heb jullie evenement bijgewoond en was onder de indruk van de organisatie en sfeer.",
        "Als student wil ik graag meer leren over dit onderwerp en actief meedoen.",
        "Ik zoek een gemeenschap van gelijkgestemden en jullie vereniging lijkt perfect.",
    ]

    # Check if we already have test applications
    existing_test_apps = frappe.get_all(
        "Membership Application", filters={"email": ["like", "%@email.nl"]}, fields=["name", "email"]
    )

    existing_emails = [app.email for app in existing_test_apps]

    for member in test_members:
        try:
            # Skip if already exists
            if member["email"] in existing_emails:
                continue

            # Create membership application
            app = frappe.new_doc("Membership Application")

            # Personal information
            app.first_name = member["first_name"]
            app.preposition = member["preposition"]
            app.last_name = member["last_name"]

            # Construct full name
            name_parts = [member["first_name"]]
            if member["preposition"]:
                name_parts.append(member["preposition"])
            name_parts.append(member["last_name"])
            app.full_name = " ".join(name_parts)

            # Contact information
            app.email = member["email"]
            app.phone = member["mobile"]  # Use mobile as primary phone

            # Address information
            app.street_address = f"{member['street']} {member['house_number']}"
            app.postal_code = member["postal_code"]
            app.city = member["city"]
            app.country = member["country"]

            # Date of birth
            app.date_of_birth = member["birth_date"]

            # Gender mapping
            gender_map = {"Male": "Man", "Female": "Vrouw"}
            app.gender = gender_map.get(member["gender"], "Anders")

            # Payment information
            app.iban = member["iban"]
            payment_map = {
                "SEPA Direct Debit": "SEPA Automatische Incasso",
                "Bank Transfer": "Bank Overschrijving",
            }
            app.payment_method = payment_map.get(member["payment_method"], "Bank Overschrijving")

            # Application details
            app.motivation = random.choice(motivations)
            app.agree_to_terms = 1
            app.agree_to_privacy_policy = 1

            # Status
            app.status = "Pending"
            app.workflow_state = "Pending"

            # Determine chapter based on city
            chapter_mapping = {
                "Amsterdam": "Amsterdam",
                "Rotterdam": "Rotterdam",
                "Den Haag": "Den Haag",
                "Utrecht": "Utrecht",
                "Groningen": "Groningen",
            }

            # Try to find chapter, otherwise use first available
            chapter = None
            for city_name, chapter_name in chapter_mapping.items():
                if city_name in member["city"]:
                    chapter = frappe.db.get_value("Chapter", {"chapter_name": chapter_name}, "name")
                    if chapter:
                        app.chapter = chapter
                        break

            if not chapter:
                # Get any active chapter
                chapter = frappe.db.get_value("Chapter", {"is_active": 1}, "name")
                if chapter:
                    app.chapter = chapter

            # Save the application
            app.insert(ignore_permissions=True)

            created_applications.append(
                {"name": app.name, "full_name": app.full_name, "email": app.email, "status": app.status}
            )

        except Exception as e:
            errors.append({"member": f"{member['first_name']} {member['last_name']}", "error": str(e)})

    # Create summary
    summary = {
        "created": len(created_applications),
        "skipped": len(existing_emails),
        "errors": len(errors),
        "total_applications": len(created_applications) + len(existing_emails),
    }

    message = f"""
    <h4>Test Applications Generated</h4>
    <ul>
        <li><strong>Created:</strong> {summary['created']} new applications</li>
        <li><strong>Skipped:</strong> {summary['skipped']} (already exist)</li>
        <li><strong>Errors:</strong> {summary['errors']}</li>
        <li><strong>Total Test Applications:</strong> {summary['total_applications']}</li>
    </ul>
    """

    if created_applications:
        message += "<p>You can now review these applications in the Membership Application list.</p>"

    return {
        "success": True,
        "summary": summary,
        "created_applications": created_applications,
        "errors": errors,
        "message": message,
    }


@frappe.whitelist()
def cleanup_test_applications():
    """
    Remove test applications (those with @email.nl addresses)
    """
    test_applications = frappe.get_all(
        "Membership Application", filters={"email": ["like", "%@email.nl"]}, fields=["name"]
    )

    deleted_count = 0
    for app in test_applications:
        try:
            # Check if application has been processed into a member
            member_exists = frappe.db.exists(
                "Member", {"email": frappe.db.get_value("Membership Application", app.name, "email")}
            )

            if not member_exists:
                frappe.delete_doc("Membership Application", app.name, ignore_permissions=True)
                deleted_count += 1
        except Exception as e:
            frappe.log_error(f"Failed to delete test application {app.name}: {str(e)}")

    return {
        "success": True,
        "deleted": deleted_count,
        "message": f"Deleted {deleted_count} test applications",
    }


@frappe.whitelist()
def get_test_applications_status():
    """
    Get status of test applications
    """
    test_applications = frappe.get_all(
        "Membership Application",
        filters={"email": ["like", "%@email.nl"]},
        fields=["name", "full_name", "email", "status", "workflow_state", "creation"],
    )

    # Group by status
    status_summary = {}
    for app in test_applications:
        status = app.workflow_state or app.status
        if status not in status_summary:
            status_summary[status] = 0
        status_summary[status] += 1

    return {"total": len(test_applications), "by_status": status_summary, "applications": test_applications}
