import json
import os

import frappe


def install_onboarding():
    """Install the Module Onboarding from JSON file"""

    # Read the onboarding JSON file
    json_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/module_onboarding/verenigingen/verenigingen.json"

    if not os.path.exists(json_path):
        print(f"JSON file not found at {json_path}")
        return

    with open(json_path, "r") as f:
        data = json.load(f)

    # Check if it already exists
    if frappe.db.exists("Module Onboarding", "Verenigingen"):
        print("Module Onboarding 'Verenigingen' already exists")
        # Delete and recreate
        frappe.delete("Module Onboarding", "Verenigingen")
        frappe.db.commit()

    # Create the document
    data["doctype"] = "Module Onboarding"
    doc = frappe.get_doc(data)
    doc.insert()
    frappe.db.commit()

    print("Module Onboarding 'Verenigingen' created successfully")
    return doc.name


if __name__ == "__main__":
    install_onboarding()
