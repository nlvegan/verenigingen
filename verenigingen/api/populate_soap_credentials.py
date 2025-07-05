import frappe


@frappe.whitelist()
def populate_soap_credentials():
    """Populate SOAP credentials from hardcoded values for existing installation"""

    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Check if SOAP credentials are already set
        if settings.soap_username:
            return {"success": True, "message": "SOAP credentials already configured"}

        # Set the credentials from the hardcoded values
        settings.soap_username = "NVV_penningmeester"
        settings.soap_security_code1 = "7e3169c820d849518853df7e30c4ba3f"
        settings.soap_security_code2 = "BB51E315-A9B2-4D37-8E8E-96EF2E2554A7"

        settings.save()
        frappe.db.commit()

        return {"success": True, "message": "SOAP credentials populated successfully"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_soap_credentials_status():
    """Check if SOAP credentials are configured"""

    settings = frappe.get_single("E-Boekhouden Settings")

    return {
        "has_username": bool(settings.soap_username),
        "has_code1": bool(
            settings.get_password("soap_security_code1")
            if hasattr(settings, "soap_security_code1")
            else False
        ),
        "has_code2": bool(
            settings.get_password("soap_security_code2")
            if hasattr(settings, "soap_security_code2")
            else False
        ),
        "has_guid": bool(settings.soap_guid if hasattr(settings, "soap_guid") else False),
    }
