import frappe


@frappe.whitelist()
def save_soap_credentials():
    """Save SOAP credentials to E-Boekhouden Settings"""

    # Get the settings doctype
    doctype = frappe.get_doc("DocType", "E-Boekhouden Settings")

    # Check if fields exist in the doctype definition
    field_names = [f.fieldname for f in doctype.fields]

    # Add fields to the DocType if they don't exist
    if "username" not in field_names:
        doctype.append(
            "fields",
            {"fieldname": "username", "fieldtype": "Data", "label": "Username", "insert_after": "api_token"},
        )
        doctype.save()

    if "security_code_1" not in field_names:
        doctype.append(
            "fields",
            {
                "fieldname": "security_code_1",
                "fieldtype": "Password",
                "label": "Security Code 1",
                "insert_after": "username",
            },
        )
        doctype.save()

    # Now get the settings and update
    settings = frappe.get_single("E-Boekhouden Settings")

    # Save the credentials
    settings.username = "NVV_penningmeester"
    settings.security_code_1 = "7e3169c820d849518853df7e30c4ba3f"
    settings.api_token = "BB51E315-A9B2-4D37-8E8E-96EF2E2554A7"  # This is security code 2
    settings.save()

    return {"success": True, "message": "SOAP credentials saved"}


if __name__ == "__main__":
    print(save_soap_credentials())
