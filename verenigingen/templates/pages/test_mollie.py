"""
Mollie Payment Testing Page

This module provides isolated testing for Mollie payment integration
to help diagnose payment setup issues without the complexity of the
full donation form workflow.
"""

import traceback

import frappe
from frappe import _


def get_context(context):
    """Basic context for the test page"""
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Mollie Payment Test")
    return context


@frappe.whitelist()
def test_mollie_settings():
    """Test Mollie Settings configuration"""
    try:
        result = {"test": "mollie_settings", "success": False, "details": {}}

        # Test 1: Check if Mollie Settings doctype exists
        try:
            mollie_settings_list = frappe.get_all("Mollie Settings", fields=["name", "gateway_name"])
            result["details"]["settings_found"] = len(mollie_settings_list)
            result["details"]["settings_list"] = mollie_settings_list

            if mollie_settings_list:
                # Get the first settings record
                settings_name = mollie_settings_list[0].name
                settings_doc = frappe.get_doc("Mollie Settings", settings_name)

                result["details"]["settings_doc"] = {
                    "name": settings_doc.name,
                    "gateway_name": settings_doc.gateway_name,
                    "test_mode": getattr(settings_doc, "test_mode", None),
                    "has_secret_key": bool(getattr(settings_doc, "secret_key", None)),
                }

                # Try to get the actual API key
                try:
                    api_key = settings_doc.get_password("secret_key")
                    if api_key:
                        result["details"]["api_key_length"] = len(api_key)
                        result["details"]["api_key_type"] = (
                            "test"
                            if api_key.startswith("test_")
                            else "live"
                            if api_key.startswith("live_")
                            else "unknown"
                        )
                        result["success"] = True
                    else:
                        result["details"]["error"] = "API key is empty"
                except Exception as e:
                    result["details"]["api_key_error"] = str(e)
            else:
                result["details"]["error"] = "No Mollie Settings found"

        except Exception as e:
            result["details"]["doctype_error"] = str(e)
            result["details"]["traceback"] = traceback.format_exc()

        return result

    except Exception as e:
        return {
            "test": "mollie_settings",
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@frappe.whitelist()
def test_mollie_client():
    """Test Mollie client creation"""
    try:
        result = {"test": "mollie_client", "success": False, "details": {}}

        # Test 1: Import mollie-api-python
        try:
            import mollie.api.client

            result["details"]["library_import"] = "success"
        except ImportError as e:
            result["details"]["library_import"] = f"failed: {str(e)}"
            return result

        # Test 2: Create basic client
        try:
            client = mollie.api.client.Client()
            result["details"]["client_creation"] = "success"
        except Exception as e:
            result["details"]["client_creation"] = f"failed: {str(e)}"
            return result

        # Test 3: Test get_mollie_settings function
        try:
            from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import (
                get_mollie_settings,
            )

            settings = get_mollie_settings()
            result["details"]["get_mollie_settings"] = "success"
            result["details"]["settings_name"] = settings.name
        except Exception as e:
            result["details"]["get_mollie_settings"] = f"failed: {str(e)}"
            result["details"]["get_mollie_settings_traceback"] = traceback.format_exc()
            return result

        # Test 4: Test get_mollie_client method
        try:
            mollie_client = settings.get_mollie_client()
            result["details"]["get_mollie_client"] = "success"
            result["details"]["client_type"] = str(type(mollie_client))
            result["success"] = True
        except Exception as e:
            result["details"]["get_mollie_client"] = f"failed: {str(e)}"
            result["details"]["get_mollie_client_traceback"] = traceback.format_exc()

        return result

    except Exception as e:
        return {
            "test": "mollie_client",
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@frappe.whitelist()
def test_payment_creation(**kwargs):
    """Test Mollie payment creation"""
    try:
        result = {"test": "payment_creation", "success": False, "details": {}, "form_data": kwargs}

        # Test 1: Import PaymentGatewayFactory
        try:
            from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

            result["details"]["factory_import"] = "success"
        except Exception as e:
            result["details"]["factory_import"] = f"failed: {str(e)}"
            result["details"]["factory_traceback"] = traceback.format_exc()
            return result

        # Test 2: Get Mollie gateway
        try:
            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
            result["details"]["gateway_creation"] = "success"
            result["details"]["gateway_type"] = str(type(gateway))
        except Exception as e:
            result["details"]["gateway_creation"] = f"failed: {str(e)}"
            result["details"]["gateway_traceback"] = traceback.format_exc()
            return result

        # Test 3: Create a test donation document (in memory only)
        try:
            # Create minimal donation doc for testing
            donation_data = {
                "doctype": "Donation",
                "amount": float(kwargs.get("amount", 25.0)),
                "donor_name": kwargs.get("donor_name", "Test Donor"),
                "donor_email": kwargs.get("donor_email", "test@example.com"),
                "payment_method": "Mollie",
            }

            # Get required company
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "donation_company") and settings.donation_company:
                donation_data["company"] = settings.donation_company
            else:
                # Use first available company
                companies = frappe.get_all("Company", limit=1)
                if companies:
                    donation_data["company"] = companies[0].name
                else:
                    result["details"]["error"] = "No company found for donation"
                    return result

            # Create donation document (don't save to database)
            donation = frappe.new_doc("Donation")
            donation.update(donation_data)

            result["details"]["test_donation"] = "created"

        except Exception as e:
            result["details"]["test_donation"] = f"failed: {str(e)}"
            result["details"]["donation_traceback"] = traceback.format_exc()
            return result

        # Test 4: Try to process payment
        try:
            payment_result = gateway.process_payment(donation, kwargs)
            result["details"]["payment_processing"] = "success"
            result["details"]["payment_result"] = payment_result
            result["success"] = True

        except Exception as e:
            result["details"]["payment_processing"] = f"failed: {str(e)}"
            result["details"]["payment_traceback"] = traceback.format_exc()

        return result

    except Exception as e:
        return {
            "test": "payment_creation",
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@frappe.whitelist()
def test_comprehensive_mollie():
    """Run all Mollie tests in sequence"""
    try:
        results = {"comprehensive_test": True, "tests": []}

        # Test 1: Settings
        settings_result = test_mollie_settings()
        results["tests"].append(settings_result)

        # Test 2: Client
        client_result = test_mollie_client()
        results["tests"].append(client_result)

        # Test 3: Payment creation with sample data
        payment_result = test_payment_creation(
            amount="25.00",
            donor_name="Test Donor",
            donor_email="test@example.com",
            description="Test payment",
        )
        results["tests"].append(payment_result)

        # Summary
        all_success = all(test.get("success", False) for test in results["tests"])
        results["overall_success"] = all_success

        return results

    except Exception as e:
        return {
            "comprehensive_test": True,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
