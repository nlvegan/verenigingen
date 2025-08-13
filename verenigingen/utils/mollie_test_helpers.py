"""
Mollie Integration Test Helpers

Utility functions for testing and debugging Mollie subscription functionality
with the actual test API key that's now configured.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, today


@frappe.whitelist()
def create_test_member_with_subscription(first_name="Test", last_name="Member", email=None):
    """
    Create a test member with full setup for Mollie subscription testing

    Returns:
        dict: Created member and related records
    """
    if not frappe.db.exists("Mollie Settings", "Default"):
        return {"error": "No Mollie Settings found. Please configure Mollie first."}

    try:
        # Create test member
        email = email or f"{first_name.lower()}.{last_name.lower()}@test.example.com"

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "birth_date": "1990-01-01",
                "status": "Active",
            }
        )
        member.insert()

        # Create customer for the member
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"{first_name} {last_name}",
                "customer_type": "Individual",
                "territory": "Netherlands",
            }
        )
        customer.insert()

        # Link customer to member
        member.customer = customer.name
        member.payment_method = "Mollie"
        member.save()

        # Create membership dues schedule
        dues_schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "member": member.name,
                "billing_frequency": "Monthly",
                "dues_rate": 25.00,  # €25/month for testing
                "next_invoice_date": today(),
                "auto_generate": 1,
                "status": "Active",
            }
        )
        dues_schedule.insert()

        return {
            "success": True,
            "member": member.name,
            "customer": customer.name,
            "dues_schedule": dues_schedule.name,
            "message": f"Created test member {member.name} ready for Mollie subscription testing",
        }

    except Exception as e:
        frappe.log_error(f"Error creating test member: {str(e)}", "Mollie Test Helper")
        return {"error": str(e)}


@frappe.whitelist()
def test_mollie_subscription_creation(member_name, amount=25.0, interval="1 month"):
    """
    Test creating a Mollie subscription for a member using real API

    Args:
        member_name (str): Member document name
        amount (float): Subscription amount
        interval (str): Billing interval

    Returns:
        dict: Subscription creation result
    """
    try:
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        member = frappe.get_doc("Member", member_name)
        if not member.customer:
            return {"error": "Member must have a customer record"}

        # Create subscription via Mollie gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        subscription_data = {
            "amount": amount,
            "interval": interval,
            "currency": "EUR",
            "description": f"Test membership dues for {member.first_name} {member.last_name}",
        }

        result = gateway.create_subscription(member, subscription_data)

        if result["status"] == "success":
            frappe.msgprint(
                f"✅ Mollie subscription created successfully!\n\n"
                f"Customer ID: {result['customer_id']}\n"
                f"Subscription ID: {result['subscription_id']}\n"
                f"Status: {result['subscription_status']}\n"
                f"Next payment: {result.get('next_payment_date', 'Not set')}",
                title="Subscription Created",
                indicator="green",
            )
        else:
            frappe.msgprint(
                f"❌ Subscription creation failed:\n{result.get('message', 'Unknown error')}",
                title="Subscription Failed",
                indicator="red",
            )

        return result

    except Exception as e:
        error_msg = f"Error creating subscription: {str(e)}"
        frappe.log_error(error_msg, "Mollie Subscription Test")
        frappe.msgprint(f"❌ {error_msg}", title="Error", indicator="red")
        return {"error": error_msg}


@frappe.whitelist()
def test_mollie_webhook_simulation(member_name, payment_amount=25.0):
    """
    Simulate a Mollie subscription webhook to test payment processing

    Args:
        member_name (str): Member with Mollie subscription
        payment_amount (float): Payment amount to simulate

    Returns:
        dict: Webhook processing result
    """
    try:
        member = frappe.get_doc("Member", member_name)

        if not member.mollie_subscription_id:
            return {"error": "Member does not have a Mollie subscription ID"}

        # First, create an unpaid invoice for testing
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member_name, "status": "Active"}, limit=1
        )

        if dues_schedules:
            schedule = frappe.get_doc("Membership Dues Schedule", dues_schedules[0]["name"])
            invoice_name = schedule.generate_invoice(force=True)
            if invoice_name:
                frappe.msgprint(f"📄 Created test invoice: {invoice_name}", indicator="blue")

        # Simulate webhook payload
        from unittest.mock import MagicMock

        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            PaymentGatewayFactory,
            _process_subscription_payment,
        )

        # Create mock gateway and payment
        gateway = MagicMock()
        mock_client = MagicMock()
        gateway.client = mock_client

        # Mock successful payment
        mock_payment = MagicMock()
        mock_payment.is_paid.return_value = True
        mock_payment.amount = {"value": f"{payment_amount:.2f}", "currency": "EUR"}
        mock_payment.status = "paid"
        mock_client.payments.get.return_value = mock_payment

        # Process simulated payment
        result = _process_subscription_payment(
            gateway,
            member.name,
            member.customer,
            f"tr_test_{frappe.utils.random_string(10)}",
            member.mollie_subscription_id,
        )

        if result["status"] == "success":
            frappe.msgprint(
                f"✅ Webhook simulation successful!\n\n"
                f"Payment Entry: {result['payment_entry']}\n"
                f"Invoice: {result['invoice']}\n"
                f"Amount: €{result['amount']}\n"
                f"Payment ID: {result['payment_id']}",
                title="Payment Processed",
                indicator="green",
            )
        else:
            frappe.msgprint(
                f"⚠️ Webhook simulation result:\n{result.get('reason', 'Unknown issue')}",
                title="Payment Not Processed",
                indicator="orange",
            )

        return result

    except Exception as e:
        error_msg = f"Error simulating webhook: {str(e)}"
        frappe.log_error(error_msg, "Mollie Webhook Simulation")
        frappe.msgprint(f"❌ {error_msg}", title="Error", indicator="red")
        return {"error": error_msg}


@frappe.whitelist()
def get_mollie_subscription_status(member_name):
    """
    Check the current status of a member's Mollie subscription

    Args:
        member_name (str): Member document name

    Returns:
        dict: Subscription status information
    """
    try:
        member = frappe.get_doc("Member", member_name)

        if not (member.mollie_customer_id and member.mollie_subscription_id):
            return {
                "error": "Member does not have Mollie subscription details",
                "customer_id": member.mollie_customer_id,
                "subscription_id": member.mollie_subscription_id,
            }

        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        result = gateway.get_subscription_status(member.mollie_customer_id, member.mollie_subscription_id)

        if result["status"] == "success":
            subscription = result["subscription"]
            frappe.msgprint(
                f"📊 Subscription Status for {member.first_name} {member.last_name}\n\n"
                f"Status: {subscription.get('status', 'Unknown')}\n"
                f"Amount: {subscription.get('amount', 'N/A')}\n"
                f"Interval: {subscription.get('interval', 'N/A')}\n"
                f"Next Payment: {subscription.get('next_payment_date', 'N/A')}\n"
                f"Created: {subscription.get('created_at', 'N/A')}\n"
                f"Cancelled: {subscription.get('canceled_at', 'N/A')}",
                title="Subscription Status",
                indicator="blue",
            )
        else:
            frappe.msgprint(
                f"❌ Failed to get subscription status:\n{result.get('message', 'Unknown error')}",
                title="Status Check Failed",
                indicator="red",
            )

        return result

    except Exception as e:
        error_msg = f"Error checking subscription status: {str(e)}"
        frappe.log_error(error_msg, "Mollie Status Check")
        frappe.msgprint(f"❌ {error_msg}", title="Error", indicator="red")
        return {"error": error_msg}


@frappe.whitelist()
def cancel_mollie_subscription(member_name):
    """
    Cancel a member's Mollie subscription

    Args:
        member_name (str): Member document name

    Returns:
        dict: Cancellation result
    """
    try:
        member = frappe.get_doc("Member", member_name)

        if not (member.mollie_customer_id and member.mollie_subscription_id):
            return {"error": "Member does not have an active Mollie subscription"}

        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        result = gateway.cancel_subscription(member)

        if result["status"] == "success":
            frappe.msgprint(
                f"✅ Subscription cancelled successfully for {member.first_name} {member.last_name}",
                title="Subscription Cancelled",
                indicator="green",
            )
        else:
            frappe.msgprint(
                f"❌ Failed to cancel subscription:\n{result.get('message', 'Unknown error')}",
                title="Cancellation Failed",
                indicator="red",
            )

        return result

    except Exception as e:
        error_msg = f"Error cancelling subscription: {str(e)}"
        frappe.log_error(error_msg, "Mollie Subscription Cancel")
        frappe.msgprint(f"❌ {error_msg}", title="Error", indicator="red")
        return {"error": error_msg}


@frappe.whitelist()
def run_mollie_integration_test_suite():
    """
    Run a complete integration test of Mollie subscription functionality

    Returns:
        dict: Test results
    """
    results = {"tests_run": 0, "tests_passed": 0, "tests_failed": 0, "details": []}

    try:
        # Test 1: Create test member
        results["tests_run"] += 1
        member_result = create_test_member_with_subscription(
            "Integration", "Test", "integration.test@mollie.example.com"
        )

        if member_result.get("success"):
            results["tests_passed"] += 1
            results["details"].append("✅ Test member creation: PASSED")
            member_name = member_result["member"]
        else:
            results["tests_failed"] += 1
            results["details"].append(f"❌ Test member creation: FAILED - {member_result.get('error')}")
            return results

        # Test 2: Create Mollie subscription
        results["tests_run"] += 1
        subscription_result = test_mollie_subscription_creation(member_name, 30.0, "1 month")

        if subscription_result.get("status") == "success":
            results["tests_passed"] += 1
            results["details"].append("✅ Mollie subscription creation: PASSED")
        else:
            results["tests_failed"] += 1
            results["details"].append(
                f"❌ Mollie subscription creation: FAILED - {subscription_result.get('message', subscription_result.get('error'))}"
            )

        # Test 3: Check subscription status
        results["tests_run"] += 1
        status_result = get_mollie_subscription_status(member_name)

        if status_result.get("status") == "success":
            results["tests_passed"] += 1
            results["details"].append("✅ Subscription status check: PASSED")
        else:
            results["tests_failed"] += 1
            results["details"].append(
                f"❌ Subscription status check: FAILED - {status_result.get('message', status_result.get('error'))}"
            )

        # Test 4: Simulate webhook payment processing
        results["tests_run"] += 1
        webhook_result = test_mollie_webhook_simulation(member_name, 30.0)

        if webhook_result.get("status") == "success":
            results["tests_passed"] += 1
            results["details"].append("✅ Webhook payment simulation: PASSED")
        else:
            results["tests_failed"] += 1
            results["details"].append(
                f"❌ Webhook payment simulation: FAILED - {webhook_result.get('reason', webhook_result.get('error'))}"
            )

        # Test 5: Cancel subscription
        results["tests_run"] += 1
        cancel_result = cancel_mollie_subscription(member_name)

        if cancel_result.get("status") == "success":
            results["tests_passed"] += 1
            results["details"].append("✅ Subscription cancellation: PASSED")
        else:
            results["tests_failed"] += 1
            results["details"].append(
                f"❌ Subscription cancellation: FAILED - {cancel_result.get('message', cancel_result.get('error'))}"
            )

        # Generate summary message
        success_rate = (results["tests_passed"] / results["tests_run"]) * 100

        summary = f"""
🧪 **Mollie Integration Test Suite Complete**

**Results:**
- Tests run: {results['tests_run']}
- Passed: {results['tests_passed']}
- Failed: {results['tests_failed']}
- Success rate: {success_rate:.1f}%

**Test Details:**
{chr(10).join(results['details'])}

**Test Member:** {member_name}
"""

        indicator = (
            "green" if results["tests_failed"] == 0 else "orange" if results["tests_passed"] > 0 else "red"
        )
        frappe.msgprint(summary, title="Test Suite Results", indicator=indicator)

        return results

    except Exception as e:
        error_msg = f"Error running test suite: {str(e)}"
        frappe.log_error(error_msg, "Mollie Test Suite")
        results["details"].append(f"❌ Test suite error: {error_msg}")
        frappe.msgprint(f"❌ {error_msg}", title="Test Suite Error", indicator="red")
        return results
