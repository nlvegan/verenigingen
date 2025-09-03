#!/usr/bin/env python3
"""
Test script to reproduce Mollie donation subscription issue
"""

import json

import requests


def test_mollie_donation_subscription():
    """Test creating a Mollie subscription via the donation form"""

    # Test data for subscription donation
    donation_data = {
        "donor_name": "Test Subscriber",
        "donor_email": "test.subscriber@example.com",
        "donor_phone": "+31612345678",
        "amount": "25.00",
        "payment_method": "Mollie",
        "donation_status": "Recurring",
        "subscription_interval": "1 month",
        "donation_type": "General",
        "donation_purpose_type": "General",
        "donation_notes": "Test recurring donation subscription",
    }

    # Use local site URL
    base_url = "https://dev.veganisme.net"
    endpoint = "/api/method/verenigingen.templates.pages.donate.submit_donation"

    try:
        print("🚀 Testing Mollie subscription donation creation...")
        print(f"📋 Data: {json.dumps(donation_data, indent=2)}")

        response = requests.post(
            f"{base_url}{endpoint}",
            data=donation_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        print(f"📊 Response status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"✅ Response: {json.dumps(result, indent=2)}")

            if result.get("message"):
                if "success" in result["message"].get("success", False):
                    print("🎉 Subscription donation created successfully!")
                    payment_info = result["message"].get("payment_info", {})
                    if payment_info.get("status") == "subscription_redirect_required":
                        print(f"🔗 Payment URL: {payment_info.get('payment_url')}")
                        print(f"📝 Subscription ID: {payment_info.get('subscription_id')}")
                else:
                    print(f"❌ Donation creation failed: {result['message'].get('message', 'Unknown error')}")
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"Response: {response.text}")

    except Exception as e:
        print(f"💥 Error: {str(e)}")


if __name__ == "__main__":
    test_mollie_donation_subscription()
