"""
Debug Payment Entry creation in detail
"""

import frappe


def debug_payment_entry_creation():
    """
    Debug Payment Entry creation step by step
    """
    try:
        print("=== DEBUGGING PAYMENT ENTRY CREATION ===")

        donation_name = "Assoc-Dnt-2025-00752"
        payment_id = "tr_ubPbvN2sJEEzqabCPA7EJ"

        # Set user context
        frappe.set_user("webhook.user@veganisme.org")

        donation = frappe.get_doc("Donation", donation_name)

        # Check settings
        print("--- Checking Settings ---")
        try:
            settings = frappe.get_single("Verenigingen Settings")
            print(f"Settings exist: Yes")
            company = settings.donation_company or frappe.defaults.get_global_default("company")
            print(f"Company: {company}")

            donation_account = getattr(settings, "donation_receivable_account", None)
            print(f"Donation receivable account: {donation_account}")

            if not donation_account:
                donation_account = frappe.get_value("Company", company, "default_receivable_account")
                print(f"Fallback receivable account: {donation_account}")

        except Exception as e:
            print(f"Settings error: {e}")
            return False

        # Check bank account
        print("--- Checking Bank Account ---")
        bank_account = frappe.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
        print(f"Mollie bank account: {bank_account}")

        if not bank_account:
            bank_account = frappe.get_value("Company", company, "default_bank_account")
            print(f"Fallback bank account: {bank_account}")

        # Check Mode of Payment
        print("--- Checking Mode of Payment ---")
        mop_exists = frappe.db.exists("Mode of Payment", "Mollie")
        print(f"Mollie Mode of Payment exists: {mop_exists}")

        # Check donor
        print("--- Checking Donor ---")
        donor = frappe.get_doc("Donor", donation.donor)
        print(f"Donor name: {donor.donor_name}")

        # Identify what's missing
        missing_items = []
        if not company:
            missing_items.append("Company")
        if not donation_account:
            missing_items.append("Donation receivable account")
        if not bank_account:
            missing_items.append("Bank account")
        if not mop_exists:
            missing_items.append("Mollie Mode of Payment")

        if missing_items:
            print(f"\n❌ MISSING REQUIREMENTS: {', '.join(missing_items)}")
            return False
        else:
            print("\n✅ All requirements found")

            # Try creating PE manually with all the data
            print("--- Creating Payment Entry ---")

            # Generate naming series
            donor_name_clean = frappe.scrub(donor.donor_name)
            donation_number = donation.name.split("-")[-1]
            custom_naming_series = f"PE-{donor_name_clean}-{donation_number}-"

            print(f"Naming series: {custom_naming_series}")
            print(f"Party: {donation.donor}")
            print(f"Amount: {donation.amount}")
            print(f"Paid from: {donation_account}")
            print(f"Paid to: {bank_account}")

            try:
                pe = frappe.get_doc(
                    {
                        "doctype": "Payment Entry",
                        "naming_series": custom_naming_series,
                        "payment_type": "Receive",
                        "party_type": "Customer",
                        "party": donation.donor,
                        "paid_amount": donation.amount,
                        "received_amount": donation.amount,
                        "reference_no": payment_id,
                        "reference_date": frappe.utils.getdate(),
                        "company": company,
                        "paid_from": donation_account,
                        "paid_to": bank_account,
                        "mode_of_payment": "Mollie",
                        "remarks": f"Donation payment {donation.name} via Mollie (ideal) - {donor.donor_name}",
                    }
                )

                print(f"Payment Entry created in memory")

                # Try to insert
                pe.insert()
                print(f"Payment Entry inserted: {pe.name}")

                # Try to submit
                pe.submit()
                print(f"✅ Payment Entry submitted: {pe.name}")

                return True

            except Exception as pe_error:
                print(f"❌ Payment Entry creation error: {pe_error}")
                import traceback

                traceback.print_exc()
                return False

    except Exception as e:
        print(f"❌ Debug error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    debug_payment_entry_creation()
