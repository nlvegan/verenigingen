#!/usr/bin/env python3

import frappe


def create_onboarding():
    # Check if already exists
    if frappe.db.exists("Module Onboarding", "Verenigingen"):
        print("Onboarding already exists")
        return

    doc = frappe.get_doc(
        {
            "doctype": "Module Onboarding",
            "name": "Verenigingen",
            "title": "Let's set up your Association Management.",
            "subtitle": "Members, Volunteers, Chapters, and more.",
            "success_message": "The Verenigingen Module is all set up!",
            "module": "Verenigingen",
            "category": "Modules",
            "steps": [
                {
                    "step": "Create Member",
                    "title": "Create Member",
                    "description": "Create a member profile to get started with membership management.",
                    "action": "Create Entry",
                    "action_label": "Create your first Member",
                    "reference_document": "Member",
                    "creation_doctype": "Member",
                    "is_mandatory": 1,
                    "validate_action": 1,
                },
                {
                    "step": "Create Membership Type",
                    "title": "Create Membership Type",
                    "description": "Define the different types of memberships your association offers.",
                    "action": "Create Entry",
                    "action_label": "Set up Membership Types",
                    "reference_document": "Membership Type",
                    "creation_doctype": "Membership Type",
                    "is_mandatory": 1,
                    "validate_action": 1,
                },
                {
                    "step": "Create Membership",
                    "title": "Create Membership",
                    "description": "Link members to their membership types and track their status.",
                    "action": "Create Entry",
                    "action_label": "Create your first Membership",
                    "reference_document": "Membership",
                    "creation_doctype": "Membership",
                    "is_mandatory": 1,
                    "validate_action": 1,
                },
                {
                    "step": "Create Chapter",
                    "title": "Create Chapter",
                    "description": "Organize members by geographic regions or local chapters.",
                    "action": "Create Entry",
                    "action_label": "Set up your first Chapter",
                    "reference_document": "Chapter",
                    "creation_doctype": "Chapter",
                    "is_mandatory": 0,
                    "validate_action": 1,
                },
                {
                    "step": "Create Volunteer",
                    "title": "Create Volunteer",
                    "description": "Track volunteers and their activities within your association.",
                    "action": "Create Entry",
                    "action_label": "Register your first Volunteer",
                    "reference_document": "Volunteer",
                    "creation_doctype": "Volunteer",
                    "is_mandatory": 0,
                    "validate_action": 1,
                },
            ],
        }
    )
    doc.insert()
    frappe.db.commit()
    print("Verenigingen onboarding created successfully")


if __name__ == "__main__":
    create_onboarding()
