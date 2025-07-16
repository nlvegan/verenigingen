"""
Test E-Boekhouden API Connection
"""

import frappe


@frappe.whitelist()
def test_eboekhouden_connection():
    """Test E-Boekhouden API connection"""
    try:
        # Get E-Boekhouden settings
        settings = frappe.get_single("E-Boekhouden Settings")

        if not settings:
            return {"success": False, "error": "E-Boekhouden Settings not found"}

        # Test SOAP API connection first
        try:
            from verenigingen.utils.eboekhouden.eboekhouden_soap_api import EBoekhoudenSOAPAPI

            soap_api = EBoekhoudenSOAPAPI(settings)
            test_result = soap_api.test_connection()

            if test_result.get("success"):
                message = "✅ SOAP API: Connection successful"
            else:
                message = f"❌ SOAP API: {test_result.get('error', 'Connection failed')}"

        except Exception as e:
            message = f"❌ SOAP API: Error - {str(e)}"

        # Test REST API connection if configured
        rest_message = ""
        api_token = settings.get_password("api_token") or settings.get_password("rest_api_token")

        if api_token:
            try:
                from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

                rest_api = EBoekhoudenAPI(settings)
                session_token = rest_api.get_session_token()

                if session_token:
                    rest_message = "✅ REST API: Connection successful"
                else:
                    rest_message = "❌ REST API: Failed to get session token"

            except Exception as e:
                rest_message = f"❌ REST API: Error - {str(e)}"
        else:
            rest_message = "⚠️ REST API: Not configured (no API token)"

        # Combine results
        full_message = f"{message}<br>{rest_message}"

        # Overall success if at least one API works
        overall_success = "✅" in message or "✅" in rest_message

        return {
            "success": overall_success,
            "message": full_message,
            "soap_working": "✅" in message,
            "rest_working": "✅" in rest_message,
            "rest_configured": bool(api_token),
        }

    except Exception as e:
        frappe.log_error(f"Error testing E-Boekhouden connection: {str(e)}")
        return {"success": False, "error": f"Connection test failed: {str(e)}"}
