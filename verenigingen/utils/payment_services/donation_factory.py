"""
Donation Factory

Creates donation records, payment entries, and payment history from Mollie payment data.
Handles both single and recurring donations with proper ERPNext integration.
"""

import json
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from verenigingen.utils.secure_operations import secure_document_operation

if TYPE_CHECKING:
    from frappe.model.document import Document


class DonationFactory:
    """
    Factory for creating donation-related records from Mollie payment data.

    Handles:
    - Donation record creation and submission
    - Customer record creation/retrieval for Payment Entry
    - Payment Entry creation linking to donation
    - Payment History child table updates
    - Recurring donation setup (mandate_id, subscription_id storage)
    """

    def __init__(self):
        """Initialize factory with field validation."""
        self._validate_required_fields()

    def _validate_required_fields(self):
        """Validate that required DocType fields exist."""
        # Validate Donation DocType fields
        donation_meta = frappe.get_meta("Donation")
        required_donation_fields = ["payment_id", "payment_status", "bank_reference", "donation_purpose_type"]
        missing_donation_fields = [f for f in required_donation_fields if not donation_meta.has_field(f)]

        if missing_donation_fields:
            frappe.throw(f"Missing required Donation fields: {missing_donation_fields}")

        # Validate Member DocType payment_history child table exists
        member_meta = frappe.get_meta("Member")
        if not member_meta.has_field("payment_history"):
            frappe.log_error("Member DocType missing payment_history child table", "Field Validation Warning")

        # Validate Donor custom fields (log warnings if missing)
        donor_meta = frappe.get_meta("Donor")
        mollie_fields = ["mollie_customer_id", "mollie_mandate_id", "mollie_subscription_id"]
        missing_donor_fields = [f for f in mollie_fields if not donor_meta.has_field(f)]

        if missing_donor_fields:
            frappe.log_error(
                f"Missing optional Donor Mollie fields: {missing_donor_fields}. These should be added as custom fields.",
                "Field Validation Warning",
            )

        # Validate Payment Entry custom field (log warning if missing)
        payment_entry_meta = frappe.get_meta("Payment Entry")
        if not payment_entry_meta.has_field("mollie_transaction_id"):
            frappe.log_error(
                "Payment Entry DocType missing mollie_transaction_id custom field. This should be added for better transaction tracking.",
                "Custom Field Validation Warning",
            )

    def create_single_donation_from_payment(
        self, payment_details: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a single donation from completed Mollie payment.

        Args:
            payment_details: Complete payment data from Mollie API
            metadata: Parsed metadata from payment description

        Returns:
            Dict with creation status and created record IDs
        """
        try:
            # Create new donation from scratch using metadata
            donor_name = self._get_or_create_donor(metadata, payment_details)
            if not donor_name:
                return {"status": "error", "message": "Failed to create or find donor"}

            donation_doc = frappe.new_doc("Donation")

            # Basic donation fields from metadata
            donation_doc.donor = donor_name
            donation_doc.donation_date = getdate()
            donation_doc.amount = flt(metadata.get("amount"))
            donation_doc.mode_of_payment = "Mollie"

            # Payment information
            donation_doc.paid = 1
            donation_doc.payment_id = payment_details.get("id")
            donation_doc.payment_status = "Completed"
            donation_doc.bank_reference = payment_details.get("id")

            # Mollie integration fields
            donation_doc.mollie_customer_id = payment_details.get("customerId")
            donation_doc.mollie_mandate_id = payment_details.get("mandateId")

            # Purpose and categorization from metadata
            donation_doc.donation_purpose_type = metadata.get("donation_purpose_type", "General")
            donation_doc.donation_category = metadata.get("donation_category", "General Fund")
            donation_doc.status = "One-time"  # Single donation

            # Chapter reference if provided
            if metadata.get("chapter_reference"):
                donation_doc.chapter_reference = metadata.get("chapter_reference")

            # Campaign reference if provided
            if metadata.get("campaign"):
                donation_doc.campaign = metadata.get("campaign")

            # Add payment record to Donation Payment child table
            payment_row = donation_doc.append("payments")
            payment_row.payment_date = getdate()
            payment_row.amount = flt(metadata.get("amount"))
            payment_row.payment_method = "Mollie"
            payment_row.payment_id = payment_details.get("id")
            payment_row.payment_status = "Paid"
            payment_row.mollie_payment_id = payment_details.get("id")
            payment_row.mollie_customer_id = payment_details.get("customerId")
            payment_row.mollie_mandate_id = payment_details.get("mandateId")

            # Save donation (non-submittable)
            donation_doc.insert()

            frappe.db.commit()

            # Create Customer record for Payment Entry (ERPNext requirement)
            customer_result = self._get_or_create_customer(metadata, payment_details)
            if customer_result["status"] != "success":
                return customer_result

            customer_name = customer_result["customer_name"]

            # Create Payment Entry
            payment_entry_result = self._create_payment_entry(donation_doc, payment_details, customer_name)
            if payment_entry_result["status"] != "success":
                return payment_entry_result

            payment_entry_id = payment_entry_result["payment_entry_id"]

            # Add to Payment History if donor has Member record
            self._add_to_payment_history(donation_doc, payment_details, payment_entry_id)

            return {
                "status": "success",
                "donation_id": donation_doc.name,
                "payment_entry_id": payment_entry_id,
                "customer_name": customer_name,
                "amount": flt(donation_doc.amount),
                "type": "single_donation",
            }

        except Exception as e:
            error_msg = f"Error creating single donation from payment: {str(e)}"
            frappe.log_error(
                f"{error_msg}\nPayment: {payment_details}\nMetadata: {metadata}",
                "Single Donation Creation Error",
            )
            return {"status": "error", "message": "Failed to create single donation"}

    def _get_or_create_donor(
        self, metadata: Dict[str, Any], payment_details: Dict[str, Any]
    ) -> Optional[str]:
        """
        Get or create Donor record from metadata.

        Args:
            metadata: Parsed metadata from payment description
            payment_details: Complete payment data from Mollie

        Returns:
            Donor name or None if failed
        """
        try:
            donor_email = metadata.get("donor_email")
            donor_name = metadata.get("donor_name", "")

            if not donor_email:
                frappe.log_error("No donor email in metadata", "Donor Creation Error")
                return None

            # Check if donor already exists
            existing_donor = frappe.db.get_value("Donor", {"donor_email": donor_email})
            if existing_donor:
                return existing_donor

            # Create new donor
            donor_doc = frappe.new_doc("Donor")
            donor_doc.donor_email = donor_email

            # Parse donor name
            name_parts = donor_name.strip().split(" ", 1)
            donor_doc.first_name = name_parts[0] if name_parts else "Anonymous"
            donor_doc.last_name = name_parts[1] if len(name_parts) > 1 else ""

            # Additional fields from metadata if available
            if metadata.get("donor_phone"):
                donor_doc.phone = metadata.get("donor_phone")
            if metadata.get("donor_address"):
                donor_doc.address = metadata.get("donor_address")

            # Set donor type
            donor_doc.donor_type = "Individual"  # Default for online donations

            # Mollie fields if available
            if payment_details.get("customerId"):
                donor_doc.mollie_customer_id = payment_details.get("customerId")

            donor_doc.insert()
            frappe.db.commit()

            return donor_doc.name

        except Exception as e:
            frappe.log_error(f"Error creating donor: {str(e)}\nMetadata: {metadata}", "Donor Creation Error")
            return None

    def create_recurring_first_donation_from_payment(
        self, payment_details: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create first donation in recurring series and store mandate_id.

        This is called after the first payment which establishes the mandate.
        Mollie will later create a subscription and send more webhooks.
        """
        try:
            # Create single donation first
            single_result = self.create_single_donation_from_payment(payment_details, metadata)
            if single_result["status"] != "success":
                return single_result

            # Store mandate_id from payment for future subscription creation
            mandate_id = payment_details.get("mandateId")
            if mandate_id:
                # Update donor with mandate information (safe field access)
                donor_doc = frappe.get_doc("Donor", metadata.get("donor_id"))
                if hasattr(donor_doc, "mollie_mandate_id"):
                    donor_doc.mollie_mandate_id = mandate_id
                    donor_doc.save(ignore_permissions=True)
                else:
                    frappe.log_error(
                        "Donor DocType missing mollie_mandate_id field - mandate ID not stored",
                        "Custom Field Missing",
                    )

                # Create or update recurring donation settings
                self._setup_recurring_donation_tracking(donor_doc, metadata, mandate_id)

            result = single_result.copy()
            result.update(
                {
                    "type": "recurring_first_donation",
                    "mandate_id": mandate_id,
                    "message": "First recurring donation created, mandate established",
                }
            )

            return result

        except Exception as e:
            error_msg = f"Error creating first recurring donation: {str(e)}"
            frappe.log_error(
                f"{error_msg}\nPayment: {payment_details}\nMetadata: {metadata}",
                "Recurring First Donation Error",
            )
            return {"status": "error", "message": "Failed to create first recurring donation"}

    def create_recurring_donation_from_payment(
        self, payment_details: Dict[str, Any], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create subsequent donation in recurring series from subscription payment.

        This is called for payments from an established Mollie subscription.
        """
        try:
            # For recurring payments, we need to create a new donation record
            # (not update an existing draft like single payments)

            donor_doc = frappe.get_doc("Donor", metadata.get("donor_id"))
            donation_doc = self._create_new_donation_from_metadata(donor_doc, metadata, is_recurring=True)

            # Update with payment information
            donation_doc.paid = 1
            donation_doc.payment_id = payment_details.get("id")
            donation_doc.payment_status = "Completed"
            donation_doc.bank_reference = payment_details.get("id")

            # Submit immediately since this is from successful payment
            result = secure_document_operation(
                operation="submit",
                doc=donation_doc,
                justification=f"Submit recurring donation from Mollie subscription payment {payment_details.get('id')} - webhook processing",
                required_permissions=[],
                allow_system_user=True,
            )

            if not result.success:
                error_msg = f"Failed to submit recurring donation: {'; '.join(result.errors)}"
                frappe.log_error(error_msg, "Recurring Donation Submission Error")
                return {"status": "error", "message": "Failed to submit recurring donation"}

            # Create Customer and Payment Entry
            customer_result = self._get_or_create_customer(metadata, payment_details)
            if customer_result["status"] != "success":
                return customer_result

            payment_entry_result = self._create_payment_entry(
                donation_doc, payment_details, customer_result["customer_name"]
            )
            if payment_entry_result["status"] != "success":
                return payment_entry_result

            # Add to Payment History
            self._add_to_payment_history(
                donation_doc, payment_details, payment_entry_result["payment_entry_id"]
            )

            # Update subscription tracking (safe field access)
            subscription_id = payment_details.get("subscriptionId")
            if subscription_id:
                if hasattr(donor_doc, "mollie_subscription_id"):
                    donor_doc.mollie_subscription_id = subscription_id
                    donor_doc.save(ignore_permissions=True)
                else:
                    frappe.log_error(
                        "Donor DocType missing mollie_subscription_id field - subscription ID not stored",
                        "Custom Field Missing",
                    )

            return {
                "status": "success",
                "donation_id": donation_doc.name,
                "payment_entry_id": payment_entry_result["payment_entry_id"],
                "customer_name": customer_result["customer_name"],
                "amount": flt(donation_doc.amount),
                "type": "recurring_donation",
                "subscription_id": subscription_id,
            }

        except Exception as e:
            error_msg = f"Error creating recurring donation: {str(e)}"
            frappe.log_error(
                f"{error_msg}\nPayment: {payment_details}\nMetadata: {metadata}",
                "Recurring Donation Creation Error",
            )
            return {"status": "error", "message": "Failed to create recurring donation"}

    def _get_or_create_customer(
        self, metadata: Dict[str, Any], payment_details: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Get existing Customer or create new one for Payment Entry.
        Uses API payment data when available for richer customer information.
        """
        try:
            donor_email = metadata.get("donor_email")
            donor_name = metadata.get("donor_name")

            # Check if Customer already exists
            existing_customer = frappe.db.get_value("Customer", {"email_id": donor_email})
            if existing_customer:
                return {"status": "success", "customer_name": existing_customer}

            # Create new Customer using API data when available
            customer_doc = frappe.new_doc("Customer")
            customer_data = {
                "customer_name": donor_name,
                "customer_type": "Individual",
                "customer_group": "Individual",
                "territory": "Netherlands",
                "email_id": donor_email,
            }

            # Enrich with payment API data if available
            if payment_details:
                # Extract additional info from Mollie payment details
                billing_address = payment_details.get("billingAddress", {})
                if billing_address:
                    if billing_address.get("country"):
                        # Update territory based on actual country
                        country_territory = self._get_territory_for_country(billing_address.get("country"))
                        if country_territory:
                            customer_data["territory"] = country_territory

                # Add any other relevant fields from payment details
                if payment_details.get("locale"):
                    customer_data["language"] = payment_details["locale"][:2]  # e.g., "nl_NL" -> "nl"

            customer_doc.update(customer_data)

            result = secure_document_operation(
                operation="insert",
                doc=customer_doc,
                justification=f"Create customer record for donor {donor_name} ({donor_email}) - payment processing requirement",
                required_permissions=[],
                allow_system_user=True,
            )

            if result.success:
                return {"status": "success", "customer_name": customer_doc.name}
            else:
                error_msg = f"Failed to create customer: {'; '.join(result.errors)}"
                frappe.log_error(error_msg, "Customer Creation Error")
                return {"status": "error", "message": "Failed to create customer record"}

        except Exception as e:
            frappe.log_error(f"Error creating customer: {str(e)}", "Customer Creation Error")
            return {"status": "error", "message": "Failed to create customer"}

    def _create_payment_entry(
        self, donation_doc: "Document", payment_details: Dict[str, Any], customer_name: str
    ) -> Dict[str, Any]:
        """Create Payment Entry for the donation with idempotency protection."""
        try:
            transaction_id = payment_details.get("id")

            # Idempotency check - see if Payment Entry already exists for this transaction
            existing_payment_entry = frappe.db.get_value("Payment Entry", {"reference_no": transaction_id})
            if existing_payment_entry:
                frappe.logger().info(
                    f"Payment Entry already exists for transaction {transaction_id}: {existing_payment_entry}"
                )
                return {"status": "success", "payment_entry_id": existing_payment_entry}

            from verenigingen.utils.settings_utils import get_verenigingen_settings

            settings = get_verenigingen_settings()
            mollie_settings = frappe.get_single("Mollie Settings")

            # Get required accounts - fail fast if not properly configured
            company_name = settings.donation_company
            receivable_account = getattr(settings, "default_receivable_account", None)
            mollie_clearing_account = getattr(mollie_settings, "mollie_clearing_account", None)

            # Fail fast - no fallbacks to catch configuration issues early
            if not receivable_account:
                return {
                    "status": "error",
                    "message": "default_receivable_account not configured in Verenigingen Settings",
                }

            if not mollie_clearing_account:
                return {
                    "status": "error",
                    "message": "mollie_clearing_account not configured in Mollie Settings",
                }

            # Generate descriptive naming using donor name + donation series
            donor_doc = frappe.get_doc("Donor", donation_doc.donor)
            donor_name_clean = donor_doc.donor_name.replace(" ", "-")[:20]  # Clean and truncate
            donation_series = donation_doc.naming_series.replace(".", "").replace("-", "")[:10]

            payment_entry = frappe.new_doc("Payment Entry")
            payment_entry.update(
                {
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer_name,
                    "paid_amount": flt(donation_doc.amount),
                    "received_amount": flt(donation_doc.amount),
                    "paid_from": receivable_account,
                    "paid_to": mollie_clearing_account,
                    "reference_no": transaction_id,
                    "reference_date": getdate(),
                    "posting_date": getdate(),
                    "company": company_name,
                    "remarks": f"Mollie payment for donation {donation_doc.name}",
                    "title": f"{donor_name_clean}-{donation_series}-Pay",  # Custom naming pattern
                }
            )

            # Add Mollie transaction ID to custom field (safe field access)
            if hasattr(payment_entry, "mollie_transaction_id"):
                payment_entry.mollie_transaction_id = transaction_id

            result = secure_document_operation(
                operation="insert",
                doc=payment_entry,
                justification=f"Create payment entry for Mollie payment {payment_details.get('id')} - financial transaction recording",
                required_permissions=[],
                allow_system_user=True,
            )

            if result.success:
                # Submit the payment entry
                submit_result = secure_document_operation(
                    operation="submit",
                    doc=payment_entry,
                    justification=f"Submit payment entry for Mollie payment {payment_details.get('id')} - financial transaction recording",
                    required_permissions=[],
                    allow_system_user=True,
                )

                if submit_result.success:
                    return {"status": "success", "payment_entry_id": payment_entry.name}
                else:
                    error_msg = f"Failed to submit payment entry: {'; '.join(submit_result.errors)}"
                    frappe.log_error(error_msg, "Payment Entry Submission Error")
                    return {"status": "error", "message": "Failed to submit payment entry"}
            else:
                error_msg = f"Failed to create payment entry: {'; '.join(result.errors)}"
                frappe.log_error(error_msg, "Payment Entry Creation Error")
                return {"status": "error", "message": "Failed to create payment entry"}

        except Exception as e:
            frappe.log_error(f"Error creating payment entry: {str(e)}", "Payment Entry Creation Error")
            return {"status": "error", "message": "Failed to create payment entry"}

    def _add_to_payment_history(
        self, donation_doc: "Document", payment_details: Dict[str, Any], payment_entry_id: str
    ) -> None:
        """Add entry to Member's payment history child table with idempotency protection."""
        try:
            transaction_id = payment_details.get("id")

            # Check if donor is linked to a Member
            donor_doc = frappe.get_doc("Donor", donation_doc.donor)

            # Look for Member with matching email
            member_name = frappe.db.get_value("Member", {"email": donor_doc.donor_email})
            if not member_name:
                # No Member record, skip payment history
                return

            member_doc = frappe.get_doc("Member", member_name)

            # Idempotency check - see if this transaction is already in payment history
            for existing_row in member_doc.get("payment_history", []):
                if existing_row.reference == transaction_id:
                    frappe.logger().info(
                        f"Payment history already exists for transaction {transaction_id} on member {member_name}"
                    )
                    return

            # Add to payment_history child table
            payment_history_row = member_doc.append("payment_history")
            payment_history_row.update(
                {
                    "date": getdate(),
                    "amount": flt(donation_doc.amount),
                    "payment_method": "Mollie",
                    "reference": transaction_id,
                    "payment_entry": payment_entry_id,
                    "donation": donation_doc.name,
                    "status": "Completed",
                    "notes": f"Donation payment via Mollie",
                }
            )

            result = secure_document_operation(
                operation="save",
                doc=member_doc,
                justification=f"Add payment history entry for donation {donation_doc.name} - payment tracking",
                required_permissions=[],
                allow_system_user=True,
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to update payment history: {'; '.join(result.errors)}",
                    "Payment History Update Error",
                )

        except Exception as e:
            frappe.log_error(f"Error adding payment history: {str(e)}", "Payment History Error")
            # Don't fail the entire process if payment history update fails

    def _create_new_donation_from_metadata(
        self, donor_doc: "Document", metadata: Dict[str, Any], is_recurring: bool = False
    ) -> "Document":
        """Create new donation document from metadata (for recurring payments)."""
        from verenigingen.utils.settings_utils import get_verenigingen_settings

        settings = get_verenigingen_settings()

        donation_doc = frappe.new_doc("Donation")
        donation_doc.update(
            {
                "company": settings.donation_company,
                "donor": donor_doc.name,
                "donation_date": getdate(),
                "amount": flt(metadata.get("amount")),
                "mode_of_payment": "Mollie",
                "status": "Recurring" if is_recurring else "One-time",
                "donation_purpose_type": metadata.get("purpose_type", "General"),
                "donation_notes": metadata.get("donation_notes", ""),
            }
        )

        # Set purpose-specific fields
        purpose_type = metadata.get("purpose_type")
        if purpose_type == "Campaign" and metadata.get("campaign"):
            donation_doc.campaign = metadata["campaign"]
        elif purpose_type == "Chapter" and metadata.get("chapter_reference"):
            donation_doc.chapter_reference = metadata["chapter_reference"]
        elif purpose_type == "Specific Goal" and metadata.get("specific_goal_description"):
            donation_doc.specific_goal_description = metadata["specific_goal_description"]

        # Insert as draft first
        result = secure_document_operation(
            operation="insert",
            doc=donation_doc,
            justification=f"Create recurring donation from Mollie payment - webhook processing",
            required_permissions=[],
            allow_system_user=True,
        )

        if not result.success:
            raise Exception(f"Failed to create donation: {'; '.join(result.errors)}")

        return donation_doc

    def _setup_recurring_donation_tracking(
        self, donor_doc: "Document", metadata: Dict[str, Any], mandate_id: str
    ) -> None:
        """Set up tracking for recurring donations after first payment."""
        try:
            # This could create a separate tracking document or update donor fields
            # Depending on your business requirements

            # For now, just ensure donor has the mandate_id
            if not hasattr(donor_doc, "mollie_mandate_id") or not donor_doc.mollie_mandate_id:
                donor_doc.mollie_mandate_id = mandate_id
                donor_doc.save(ignore_permissions=True)

            # You might want to create a "Recurring Donation Agreement" document here
            # or update other tracking fields based on your business logic

        except Exception as e:
            frappe.log_error(
                f"Error setting up recurring donation tracking: {str(e)}", "Recurring Donation Setup Error"
            )

    def _get_territory_for_country(self, country_code: str) -> Optional[str]:
        """Get Territory name for a country code."""
        try:
            # Map common country codes to territories
            territory_mapping = {
                "NL": "Netherlands",
                "BE": "Belgium",
                "DE": "Germany",
                "FR": "France",
                "GB": "United Kingdom",
                "US": "United States",
            }

            territory_name = territory_mapping.get(country_code.upper())
            if territory_name and frappe.db.exists("Territory", territory_name):
                return territory_name

            # Fallback to checking if country code exists as territory
            if frappe.db.exists("Territory", country_code.upper()):
                return country_code.upper()

            return None

        except Exception:
            return None
