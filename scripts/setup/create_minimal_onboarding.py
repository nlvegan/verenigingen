import frappe


def create_minimal_onboarding():
    """Create a minimal onboarding document"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Check if already exists
    if frappe.db.exists("Module Onboarding", "Verenigingen"):
        print("Deleting existing onboarding...")
        frappe.db.sql("DELETE FROM `tabModule Onboarding` WHERE name='Verenigingen'")
        frappe.db.commit()

    # Create minimal onboarding without steps first
    doc_data = {
        "doctype": "Module Onboarding",
        "name": "Verenigingen",
        "title": "Let's set up your Association Management.",
        "subtitle": "Members, Volunteers, Chapters, and more.",
        "success_message": "The Verenigingen Module is all set up!",
        "module": "Verenigingen",
        "category": "Modules",
        "is_complete": 0,
    }

    doc = frappe.get_doc(doc_data)
    doc.flags.ignore_links = True  # Skip link validation
    doc.insert()
    frappe.db.commit()

    print("Minimal onboarding created successfully")
    return doc.name


if __name__ == "__main__":
    create_minimal_onboarding()
