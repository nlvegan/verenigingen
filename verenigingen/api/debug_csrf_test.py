"""
Debug CSRF Implementation Test
Testing the CSRF validation issues
"""

import frappe
from frappe import _


# Test without security framework first
@frappe.whitelist()
def test_basic_api():
    """Basic API test without security framework"""
    return {"success": True, "message": "Basic API working", "user": frappe.session.user}


# Test with only CSRF protection
@frappe.whitelist()
def test_csrf_only():
    """Test CSRF protection only"""
    from verenigingen.utils.security.csrf_protection import require_csrf_token

    @require_csrf_token
    def protected_function():
        return {"success": True, "message": "CSRF protected API working", "user": frappe.session.user}

    return protected_function()


# Test with security framework
@frappe.whitelist()
def test_security_framework():
    """Test full security framework"""
    from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def protected_function():
        return {"success": True, "message": "Security framework API working", "user": frappe.session.user}

    return protected_function()


@frappe.whitelist()
def test_csrf_token_check():
    """Check if CSRF token is available in request"""
    from verenigingen.utils.security.csrf_protection import CSRFProtection

    # Check if token is in request
    token = CSRFProtection.get_token_from_request()

    request_info = {
        "method": getattr(frappe.request, "method", "unknown"),
        "headers": dict(frappe.request.headers) if frappe.request else {},
        "form_data": dict(frappe.form_dict),
        "csrf_token_found": bool(token),
        "csrf_token_value": token[:10] + "..." if token else None,
    }

    return {"success": True, "request_info": request_info, "user": frappe.session.user}


@frappe.whitelist()
def debug_suspension_api_call():
    """Debug the suspension API call specifically"""
    try:
        # Import the actual function to test it directly
        from verenigingen.utils.termination_integration import get_member_suspension_status

        # Test with a non-existent member to avoid actual data issues
        test_member = "TEST_MEMBER_123"

        result = get_member_suspension_status(test_member)

        return {"success": True, "message": "Direct function call worked", "result": result}

    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
