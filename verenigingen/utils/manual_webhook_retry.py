"""
Manually retry webhook processing for failed payments
"""

import frappe


def retry_webhook_processing(payment_id="tr_kEvfjvo5qm7pN74wj27EJ"):
    """
    Manually retry webhook processing for a payment that failed
    """
    try:
        print(f"=== MANUALLY PROCESSING WEBHOOK FOR {payment_id} ===")

        # Get Mollie client and payment
        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()
        payment = client.payments.get(payment_id)

        print(f"Payment Status: {payment.status}")
        print(f"Sequence Type: {getattr(payment, 'sequence_type', 'N/A')}")
        print(f"Customer ID: {getattr(payment, 'customer_id', 'N/A')}")
        print(f"Is Paid: {payment.is_paid()}")

        # Check metadata
        metadata = getattr(payment, "metadata", {})
        print("Payment Metadata:")
        for key, value in metadata.items():
            print(f"  {key}: {value}")

        if not payment.is_paid():
            print("❌ Payment is not paid - cannot process")
            return False

        # Get the donation
        donation_id = metadata.get("donation_id")
        if not donation_id:
            print("❌ No donation ID in metadata")
            return False

        print(f"\n--- Processing donation {donation_id} ---")

        # Update donation as paid
        donation = frappe.get_doc("Donation", donation_id)
        print(
            f"Current donation status - Paid: {donation.paid}, Payment Status: {getattr(donation, 'payment_status', 'None')}"
        )

        # Mark donation as paid
        donation.db_set("paid", 1)
        donation.db_set("payment_status", "Completed")
        print("✅ Updated donation payment status")

        # Create payment entry if method exists
        if hasattr(donation, "create_payment_entry"):
            try:
                result = donation.create_payment_entry()
                print(f"✅ Created payment entry: {result}")
            except Exception as e:
                print(f"⚠️ Payment entry creation failed: {e}")

        # Process subscription if this is a first payment
        if payment.sequence_type == "first" and metadata.get("subscription_setup") == "true":
            print("\n--- Creating subscription from metadata ---")

            # Import the new subscription function
            from verenigingen.verenigingen_payments.utils.payment_gateways import (
                PaymentGatewayFactory,
                _activate_direct_subscription_after_first_payment,
            )

            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
            result = _activate_direct_subscription_after_first_payment(gateway, payment)

            print(f"Subscription creation result: {result}")

            if result.get("status") == "success":
                subscription_id = result.get("subscription_id")
                print(f"✅ Created subscription: {subscription_id}")

                # Update donation with subscription ID
                donation.db_set("mollie_subscription_id", subscription_id)
                print("✅ Updated donation with subscription ID")
            else:
                print(f"❌ Subscription creation failed: {result.get('message', 'Unknown error')}")

        print("\n=== MANUAL PROCESSING COMPLETE ===")
        return True

    except Exception as e:
        print(f"❌ Error during manual processing: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    retry_webhook_processing()
