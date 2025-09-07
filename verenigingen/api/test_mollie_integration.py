#!/usr/bin/env python3

import json

import frappe
from frappe import _


@frappe.whitelist()
def run_mollie_integration_test():
    """Test MolliePaymentService integration via API"""

    print("🎯 Testing MolliePaymentService integration...")
    results = []

    try:
        from verenigingen.utils.payment_services.mollie_payment_service import MolliePaymentService

        results.append("✅ Successfully imported MolliePaymentService")

        # Initialize service
        service = MolliePaymentService()
        results.append("✅ MolliePaymentService initialized successfully")

        # Get a test donor
        donors = frappe.get_all("Donor", limit=1)
        if not donors:
            results.append("⚠️ No donors found - creating test donor")
            from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

            factory = EnhancedTestDataFactory()
            donor_doc = factory.create_test_donor(
                donor_name="Test Mollie Donor", donor_email="test.mollie@example.com"
            )
            donor_name = donor_doc.name
        else:
            donor_name = donors[0]["name"]

        results.append(f"📋 Using donor: {donor_name}")

        # Create test donation doc (not inserted)
        donation_doc = frappe.new_doc("Donation")
        donation_doc.update({"donor": donor_name, "amount": 25.00, "donation_purpose_type": "General"})

        # Test form data
        form_data = {"donor_name": "Test Donor", "donor_email": "test@example.com", "amount": 25.00}

        # Test metadata creation
        results.append("📊 Testing payment metadata creation...")
        metadata = service._build_payment_metadata(donation_doc, form_data, is_recurring=False)
        results.append(f"✅ Metadata created with {len(metadata)} fields")
        results.append(f'   Type: {metadata.get("type")}')
        results.append(f'   Amount: {metadata.get("amount")}')
        results.append(f'   Donor: {metadata.get("donor_name")}')

        # Test single payment creation (will likely fail without API key but shows integration)
        results.append("🎯 Testing single payment creation...")
        result = service.create_single_payment(donation_doc, form_data)
        results.append(f'Payment result status: {result.get("status")}')

        if result.get("status") == "error":
            results.append(f'⚠️ Expected error (likely no API key): {result.get("message", "Unknown error")}')
        elif result.get("status") == "redirect_required":
            results.append("✅ Payment creation successful - would redirect to Mollie")
            results.append(f'   Payment URL: {result.get("payment_url", "N/A")}')
            results.append(f'   Payment ID: {result.get("payment_id", "N/A")}')

        # Test recurring payment setup
        results.append("🔄 Testing recurring payment creation...")
        form_data_recurring = form_data.copy()
        form_data_recurring["subscription_interval"] = "1 month"

        recurring_result = service.create_recurring_first_payment(donation_doc, form_data_recurring)
        results.append(f'Recurring payment result status: {recurring_result.get("status")}')

        if recurring_result.get("status") == "error":
            results.append(f'⚠️ Expected error: {recurring_result.get("message", "Unknown error")}')

        return {"success": True, "results": results, "test_completed": True}

    except Exception as e:
        import traceback

        error_trace = traceback.format_exc()
        results.append(f"❌ Error: {e}")
        results.append(f"Traceback: {error_trace}")

        return {"success": False, "results": results, "error": str(e), "traceback": error_trace}
