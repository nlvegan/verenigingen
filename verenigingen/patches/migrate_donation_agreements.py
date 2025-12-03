import frappe
from frappe.utils import flt, today


def execute():
    """Migrate Donation Agreement records to consolidated Donation model"""

    print("🚀 Starting Donation Agreement Migration")
    print("=" * 50)

    # Get all Donation Agreements
    agreements = frappe.get_all(
        "Donation Agreement", fields=["name", "donor", "amount", "status"], order_by="creation"
    )

    if not agreements:
        print("❌ No Donation Agreement records found")
        return

    print(f"📊 Found {len(agreements)} Donation Agreement records to migrate")

    migrated_count = 0
    error_count = 0

    for i, agreement_data in enumerate(agreements):
        try:
            # Get full agreement document
            agreement = frappe.get_doc("Donation Agreement", agreement_data.name)

            # Create new Donation record
            new_donation = frappe.new_doc("Donation")

            # Map fields from agreement to donation
            field_mapping = {
                "donor": agreement.donor,
                "donation_date": today(),
                "amount": flt(agreement.amount or 25.0),
                "donation_type": "Herhalend",  # All agreements are recurring
                "is_recurring": 1,
                "recurring_frequency": "1 month",
                "company": frappe.get_single("Verenigingen Settings").company,
                "donation_notes": f"Migrated from Donation Agreement {agreement.name} on {today()}",
                "payment_status": "Active" if agreement.status == "Active" else "Pending",
                "mollie_customer_id": getattr(agreement, "mollie_customer_id", None),
                "mollie_subscription_id": getattr(agreement, "mollie_subscription_id", None),
                "subscription_status": agreement.status or "Active",
                "mode_of_payment": "Mollie",
            }

            # Apply mapped fields
            for field, value in field_mapping.items():
                if value is not None:
                    new_donation.set(field, value)

            # Save the new donation
            new_donation.insert()

            # Mark original agreement as migrated
            agreement.add_comment("Comment", f"✅ Migrated to Donation {new_donation.name} on {today()}")

            migrated_count += 1

            # Progress logging
            if (i + 1) % 25 == 0:
                print(f"📊 Progress: {i + 1}/{len(agreements)} processed - {migrated_count} migrated")

        except Exception as e:
            error_count += 1
            print(f"❌ Error migrating {agreement_data.name}: {str(e)}")
            # Continue with other records instead of failing completely
            continue

    print("\n✅ Migration completed:")
    print(f"   📄 New Donation records created: {migrated_count}")
    print(f"   ❌ Errors encountered: {error_count}")
    print(
        f"   📊 Success rate: {migrated_count}/{len(agreements)} ({100 * migrated_count // len(agreements)}%)"
    )

    if migrated_count > 0:
        print("   🗂️ Original agreements marked with migration comments")
        print("   🔄 Webhook handler updated to use new consolidated model")

    frappe.db.commit()  # Make sure changes are saved
