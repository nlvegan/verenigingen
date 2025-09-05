"""
Subscription Management Utility

Administrative utility for managing Mollie subscriptions outside of the normal
donation flow. Provides functions to create, modify, and troubleshoot subscriptions
for customer support and administrative purposes.

Usage: Call functions via bench console or admin interface
"""
import frappe


@frappe.whitelist()
def create_subscription_for_customer(
    customer_id, amount=25.0, interval="1 month", description="Manual Subscription"
):
    """
    Administrative function to create Mollie subscription for customer

    Args:
        customer_id: Mollie customer ID
        amount: Subscription amount (default 25.0)
        interval: Payment interval (default "1 month")
        description: Subscription description
    """

    # Get Mollie settings and client
    settings = frappe.get_single("Mollie Settings")
    import mollie.api.client

    client = mollie.api.client.Client()
    client.set_api_key(settings.get_active_api_key())

    try:
        # Get the customer
        customer = client.customers.get(customer_id)
        print("👤 Customer: {customer.name} ({customer.email})")

        # Check mandates
        mandates = customer.mandates.list()
        print("🔐 Mandates: {mandates.count}")
        valid_mandates = [m for m in mandates if m.status == "valid"]
        if not valid_mandates:
            print("❌ No valid mandates found")
            return None

        print("✅ Found {len(valid_mandates)} valid mandate(s)")

        # Create subscription using the established mandate
        subscription_data = {
            "amount": {"currency": "EUR", "value": "25.00"},
            "interval": "1 month",
            "description": "Recurring donation - General Donation",
            "webhookUrl": "https://dev.veganisme.net/api/method/verenigingen.utils.payment_gateways.mollie_subscription_webhook",
            "metadata": {
                "donor_id": "DN-25-00050",
                "donation_type": "General Donation",
                "purpose_type": "General",
                "company": "Vegan Netwerk Nederland",
                "subscription_interval": "1 month",
                "donation_amount": "25.0",
                "subscription_source": "manual_creation",
            },
        }

        print("🔄 Creating subscription with data: {subscription_data}")
        subscription = customer.subscriptions.create(subscription_data)

        print("✅ SUCCESS! Subscription created: {subscription.id}")
        print("   Status: {subscription.status}")
        print("   Amount: {subscription.amount.currency} {subscription.amount.value}")
        print("   Interval: {subscription.interval}")
        if hasattr(subscription, "nextPaymentDate") and subscription.nextPaymentDate:
            print("   Next payment: {subscription.nextPaymentDate}")

        return subscription

    except Exception as e:
        print(f"❌ Error creating subscription: {e}")
        import traceback

        traceback.print_exc()
        return None
