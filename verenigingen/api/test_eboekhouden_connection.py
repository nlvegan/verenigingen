"""
Test E-Boekhouden API Connection (REST API only)
"""

import frappe


@frappe.whitelist()
def test_eboekhouden_connection():
    """Test E-Boekhouden REST API connection"""
    try:
        # Get E-Boekhouden settings
        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings:
            return {"success": False, "error": "E-Boekhouden Settings not found"}

        # Test REST API connection
        api_token = settings.get_password("api_token") or settings.get_password("rest_api_token")

        if not api_token:
            return {
                "success": False,
                "error": "REST API token not configured",
                "message": "⚠️ REST API: Not configured (no API token)",
            }

        try:
            from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

            rest_api = EBoekhoudenAPI(settings)
            session_token = rest_api.get_session_token()

            if session_token:
                message = "✅ REST API: Connection successful"
                success = True
            else:
                message = "❌ REST API: Failed to get session token"
                success = False

        except Exception as e:
            message = f"❌ REST API: Error - {str(e)}"
            success = False

        return {
            "success": success,
            "message": message,
            "rest_working": success,
            "rest_configured": True,
        }

    except Exception as e:
        frappe.log_error(f"Error testing E-Boekhouden connection: {str(e)}")
        return {"success": False, "error": f"Connection test failed: {str(e)}"}
