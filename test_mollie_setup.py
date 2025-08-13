#!/usr/bin/env python3

import frappe


def test_mollie_setup():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    # Check if Mollie Settings DocType exists
    if frappe.db.exists("DocType", "Mollie Settings"):
        print("✅ Mollie Settings DocType exists")

        # Check if test record exists
        if frappe.db.exists("Mollie Settings", "Test"):
            print("✅ Test Mollie Settings record already exists")
            # Get the record
            settings = frappe.get_doc("Mollie Settings", "Test")
            print(f"   Gateway Name: {settings.gateway_name}")
            print(f"   Test Mode: {settings.test_mode}")
            print(f"   Profile ID: {settings.profile_id}")
        else:
            print("📝 Creating test Mollie Settings record...")
            try:
                # Create test record
                doc = frappe.get_doc(
                    {
                        "doctype": "Mollie Settings",
                        "gateway_name": "Test",
                        "profile_id": "pfl_XXXXXXXXXX",  # Placeholder
                        "secret_key": "test_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",  # Placeholder
                        "test_mode": 1,
                    }
                )
                doc.flags.ignore_mandatory = True
                doc.insert(ignore_permissions=True)
                frappe.db.commit()
                print("✅ Created test Mollie Settings record!")
            except Exception as e:
                print(f"❌ Error creating record: {str(e)}")
    else:
        print("❌ Mollie Settings DocType not found!")
        # List available DocTypes with "mollie" in the name
        doctypes = frappe.get_all("DocType", fields=["name"])
        mollie_doctypes = [d.name for d in doctypes if "mollie" in d.name.lower()]
        print(f"Available Mollie DocTypes: {mollie_doctypes}")

    frappe.destroy()


if __name__ == "__main__":
    test_mollie_setup()
