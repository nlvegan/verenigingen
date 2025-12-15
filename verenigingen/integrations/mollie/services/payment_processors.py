"""
Payment Processors

Abstract base classes and concrete implementations for processing different types of payments.
This separates donation-specific logic from member-specific logic and provides a clean interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import frappe

from .payment_context_resolver import PaymentContext
from .payment_entry_factory import PaymentEntryFactory


# Donation status constants
class DonationStatus:
    """Donation status values"""

    ONE_TIME = "One-time"
    RECURRING = "Recurring"
    PROMISED = "Promised"


# Payment status constants
class PaymentStatus:
    """Payment status values"""

    PAID = "Paid"
    CANCELLED = "Cancelled"
    FAILED = "Failed"


class PaymentProcessingResult:
    """Container for payment processing results"""

    def __init__(self, success: bool = False, message: str = "", data: Dict[str, Any] = None):
        self.success = success
        self.message = message
        self.data = data or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "message": self.message, "data": self.data}


class AbstractPaymentProcessor(ABC):
    """
    Abstract base class for payment processors.

    Each payment processor handles a specific type of payment (donations, memberships, etc.)
    and provides consistent interface for webhook processing.
    """

    def __init__(self):
        self.logger = frappe.logger()
        self.payment_factory = PaymentEntryFactory()

    @abstractmethod
    def supports_context(self, context: PaymentContext) -> bool:
        """Check if this processor supports the given payment context"""
        pass

    @abstractmethod
    def process_successful_payment(
        self, context: PaymentContext, payment_data: Any, mollie_data: Dict[str, Any]
    ) -> PaymentProcessingResult:
        """Process a successful payment for this payment type"""
        pass

    @abstractmethod
    def process_failed_payment(
        self, context: PaymentContext, payment_data: Any, mollie_data: Dict[str, Any]
    ) -> PaymentProcessingResult:
        """Process a failed payment for this payment type"""
        pass

    @abstractmethod
    def check_idempotency(self, context: PaymentContext, payment_id: str) -> Dict[str, Any]:
        """Check if payment has already been processed"""
        pass

    def extract_mollie_payment_data(self, payment) -> Dict[str, Any]:
        """Extract relevant data from Mollie payment object using centralized extractor"""
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()

        return {
            "payment_id": extractor.extract_payment_id(payment),
            "status": payment.status,
            "amount": extractor.extract_amount(payment, allow_zero=True),  # Handles both dict and object
            "currency": extractor._extract_payment_currency(
                payment
            ),  # Returns None if missing (for dict compatibility)
            "method": getattr(payment, "method", None),
            "customer_id": getattr(payment, "customer_id", None),
            "mandate_id": getattr(payment, "mandate_id", None),
            "subscription_id": getattr(payment, "subscription_id", None),
            "created_at": getattr(payment, "created_at", None),  # Keep raw for dict return
            "paid_at": getattr(payment, "paid_at", None),  # Keep raw for dict return
            "description": extractor.extract_description(payment, fallback_description=None),
            "metadata": getattr(payment, "metadata", {}),
        }


class DonationPaymentProcessor(AbstractPaymentProcessor):
    """
    Payment processor for donation payments.

    Handles all donation-specific logic including Payment Entry creation,
    Bank Transaction creation, donation status updates, and payment history management.
    """

    def __init__(self):
        super().__init__()
        # Import centralized Bank Transaction creator
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        self.bank_tx_creator = get_bank_transaction_creator()

    def supports_context(self, context: PaymentContext) -> bool:
        return context.payment_type == "donation"

    def process_successful_payment(
        self, context: PaymentContext, payment_data: Any, mollie_data: Dict[str, Any]
    ) -> PaymentProcessingResult:
        """Process successful donation payment"""
        try:
            self.logger.info(f"Processing successful donation payment for {context.target_name}")

            # Check idempotency status for all components
            idempotency_status = self.check_idempotency(context, mollie_data["payment_id"])

            # If everything is already complete, return early
            if idempotency_status.get("all_complete"):
                return PaymentProcessingResult(
                    success=True,
                    message="Donation payment already processed",
                    data={"donation_id": context.target_name, "status": "already_processed"},
                )

            # Get donation document
            donation = frappe.get_doc("Donation", context.target_name)

            # Extract and save consumer bank data from Mollie payment (for Customer only)
            # This creates Bank Account links for future MT940 matching
            if donation.donor:
                donor = frappe.get_doc("Donor", donation.donor)
                customer = getattr(donor, "customer", None)
                if customer:
                    self._extract_and_save_consumer_bank_data(customer, payment_data)

            # Track what we actually process
            processed_components = []
            payment_entry = None
            bank_transaction = None

            # 1. Create Bank Transaction FIRST (matches ERPNext standard flow)
            if not idempotency_status.get("bank_transaction_created"):
                self.logger.info(f"Creating Bank Transaction for {mollie_data['payment_id']}")
                bank_transaction_name = self._create_bank_transaction_for_donation(
                    donation=donation, mollie_data=mollie_data
                )
                if bank_transaction_name:
                    bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
                    processed_components.append("bank_transaction")
                else:
                    # Log at ERROR level since Bank Transaction is expected in normal flow
                    self.logger.error(
                        f"❌ AUDIT TRAIL GAP: Failed to create Bank Transaction for {mollie_data['payment_id']} "
                        f"(donation: {donation.name}, donor: {donation.donor}). Payment will be processed but "
                        f"bank reconciliation will require manual intervention."
                    )
                    # Also create error log for monitoring
                    frappe.log_error(
                        f"Bank Transaction creation failed for donation {donation.name}\n"
                        f"Payment ID: {mollie_data['payment_id']}\n"
                        f"Donor: {donation.donor}\n"
                        f"Amount: {mollie_data.get('amount', 'N/A')}\n"
                        f"Requires manual Bank Transaction creation for reconciliation",
                        "Missing Bank Transaction - Donation Payment",
                    )
            else:
                self.logger.info(f"Bank Transaction already exists for {mollie_data['payment_id']}")
                # Get existing bank transaction for return data
                bank_transaction_name = frappe.db.get_value(
                    "Bank Transaction", {"reference_number": mollie_data["payment_id"]}, "name"
                )
                if bank_transaction_name:
                    bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)

            # 2. Create Payment Entry SECOND and link to Bank Transaction
            if not idempotency_status.get("payment_entry_created"):
                self.logger.info(f"Creating Payment Entry for {mollie_data['payment_id']}")
                payment_entry = self.payment_factory.create_payment_entry(
                    context=context, mollie_data=mollie_data
                )
                if not payment_entry:
                    raise Exception("Failed to create Payment Entry")
                processed_components.append("payment_entry")

                # Note: Bank Transaction is already submitted by bank_tx_creator.create()
                # We cannot add child table rows to submitted documents in ERPNext
                # The Bank Transaction exists for audit/reference - the Payment Entry
                # already handles the accounting, so linking in child table is optional
                if bank_transaction:
                    self.logger.info(
                        f"Created Payment Entry {payment_entry.name} and Bank Transaction {bank_transaction.name} "
                        f"for payment {mollie_data['payment_id']}"
                    )
            else:
                self.logger.info(f"Payment Entry already exists for {mollie_data['payment_id']}")
                # Get existing payment entry for return data
                payment_entry_name = frappe.db.get_value(
                    "Payment Entry", {"reference_no": mollie_data["payment_id"]}, "name"
                )
                if payment_entry_name:
                    payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)

            # 3. Update donation status only if not already set
            if not idempotency_status.get("payment_recorded"):
                self.logger.info(f"Updating donation status for {context.target_name}")
                donation.paid = 1
                donation.payment_id = mollie_data["payment_id"]

                # Update subscription ID if present and not already set
                # (mollie_subscription_id is a confirmed DocType field)
                if mollie_data.get("subscription_id") and not donation.mollie_subscription_id:
                    donation.mollie_subscription_id = mollie_data["subscription_id"]
                    self.logger.info(
                        f"✅ Updated donation {donation.name} with subscription ID: {mollie_data['subscription_id']}"
                    )

                # Update customer ID if present and not already set
                # (mollie_customer_id is a confirmed DocType field)
                if mollie_data.get("customer_id") and not donation.mollie_customer_id:
                    donation.mollie_customer_id = mollie_data["customer_id"]
                    self.logger.info(
                        f"✅ Updated donation {donation.name} with customer ID: {mollie_data['customer_id']}"
                    )

                # Determine if recurring and set appropriate status
                if not idempotency_status.get("donation_status_updated"):
                    is_recurring = self._determine_recurring_status(donation, mollie_data)
                    if is_recurring:
                        donation.status = DonationStatus.RECURRING
                        self.logger.info(f"✅ Set donation {donation.name} status to Recurring")
                    else:
                        donation.status = DonationStatus.ONE_TIME
                        self.logger.info(f"✅ Set donation {donation.name} status to One-time")

                processed_components.append("donation_status")
            else:
                self.logger.info(f"Donation status already updated for {context.target_name}")

            # 4. Add payment history only if not already exists
            if not idempotency_status.get("payment_history_exists"):
                self.logger.info(f"Adding payment history for {mollie_data['payment_id']}")

                # Build payment history record with all required fields
                payment_history = {
                    "payment_date": frappe.utils.getdate(),
                    "amount": float(mollie_data["amount"]),
                    "payment_method": mollie_data.get(
                        "method", ""
                    ),  # Use actual method (ideal, creditcard, etc.)
                    "payment_id": mollie_data["payment_id"],
                    "payment_reference": mollie_data["payment_id"],
                    "payment_status": PaymentStatus.PAID,
                    "mollie_payment_id": mollie_data["payment_id"],
                    "remarks": f"Mollie payment {mollie_data['payment_id']}",
                }

                # Add currency if available
                if mollie_data.get("currency"):
                    payment_history["currency"] = mollie_data["currency"]

                # Add payment_entry link if we created one
                if payment_entry and payment_entry.name:
                    payment_history["payment_entry"] = payment_entry.name

                donation.append("payments", payment_history)
                processed_components.append("payment_history")
            else:
                self.logger.info(f"Payment history already exists for {mollie_data['payment_id']}")

            # Save donation if any updates were made
            if "donation_status" in processed_components or "payment_history" in processed_components:
                donation.save()
                self.logger.info(f"Saved donation {donation.name} with updates")

            # Return appropriate message based on what was processed
            if not processed_components:
                message = "All payment components already processed (idempotent)"
            else:
                message = f"Processed missing components: {', '.join(processed_components)}"

            return PaymentProcessingResult(
                success=True,
                message=message,
                data={
                    "donation_id": donation.name,
                    "payment_entry": payment_entry.name if payment_entry else None,
                    "bank_transaction": bank_transaction.name if bank_transaction else None,
                    "amount": mollie_data["amount"],
                    "status": "completed",
                    "processed_components": processed_components,
                },
            )

        except Exception as e:
            self.logger.error(f"Error processing donation payment: {e}")
            return PaymentProcessingResult(
                success=False, message=f"Failed to process donation payment: {str(e)}"
            )

    def process_failed_payment(
        self, context: PaymentContext, payment_data: Any, mollie_data: Dict[str, Any]
    ) -> PaymentProcessingResult:
        """Process failed donation payment"""
        try:
            self.logger.info(f"Processing failed donation payment for {context.target_name}")

            # Get donation document
            donation = frappe.get_doc("Donation", context.target_name)

            # Add failed payment to donation history
            donation.append(
                "payments",
                {
                    "payment_date": frappe.utils.getdate(),
                    "amount": donation.amount,
                    "payment_method": "Mollie",
                    "payment_id": mollie_data["payment_id"],
                    "payment_reference": mollie_data["payment_id"],
                    "payment_status": PaymentStatus.CANCELLED,
                    "mollie_payment_id": mollie_data["payment_id"],
                    "remarks": f"Payment failed: {payment_data.status}",
                },
            )

            donation.save()

            return PaymentProcessingResult(
                success=True,
                message="Failed donation payment recorded",
                data={"donation_id": donation.name, "status": "failed_payment_recorded"},
            )

        except Exception as e:
            self.logger.error(f"Error processing failed donation payment: {e}")
            return PaymentProcessingResult(
                success=False, message=f"Failed to record failed payment: {str(e)}"
            )

    def check_idempotency(self, context: PaymentContext, payment_id: str) -> Dict[str, Any]:
        """Check donation payment processing status"""
        # Use unified idempotency manager for Payment Entry check
        from verenigingen.integrations.mollie.services.unified_idempotency_manager import (
            get_unified_idempotency_manager,
        )

        idempotency_manager = get_unified_idempotency_manager()
        payment_entry_exists = bool(idempotency_manager.payment_entry_exists(payment_id))

        # Check if Bank Transaction exists (any docstatus - draft or submitted)
        bank_transaction_exists = bool(
            frappe.db.get_value("Bank Transaction", {"reference_number": payment_id}, "name")
        )

        # Check donation status
        donation = frappe.get_doc("Donation", context.target_name)
        payment_recorded = (
            getattr(donation, "paid", 0) == 1 and getattr(donation, "payment_id", None) == payment_id
        )

        # Check donation status is properly set BY THIS PAYMENT
        # (i.e., paid flag is set AND status is valid - not just status being valid)
        donation_status_updated = payment_recorded and getattr(donation, "status", None) in [
            DonationStatus.ONE_TIME,
            DonationStatus.RECURRING,
        ]

        # Check payment history
        history_exists = False
        if hasattr(donation, "payments") and donation.payments:
            for payment_record in donation.payments:
                if getattr(payment_record, "mollie_payment_id", None) == payment_id:
                    history_exists = True
                    break

        # Bank Transaction is optional - payment processing can succeed without it
        # This handles cases where Bank Transaction creation fails (e.g., missing donor/customer)
        all_complete = (
            payment_entry_exists and payment_recorded and history_exists and donation_status_updated
        )

        return {
            "payment_entry_created": payment_entry_exists,
            "bank_transaction_created": bank_transaction_exists,
            "payment_recorded": payment_recorded,
            "payment_history_exists": history_exists,
            "donation_status_updated": donation_status_updated,
            "all_complete": all_complete,
        }

    def _determine_recurring_status(self, donation, mollie_data):
        """
        Determine if payment should be treated as recurring with priority ordering
        Priority 1: Explicit metadata override (highest priority)
        Priority 2: Mollie subscription ID (definitive)
        Priority 3: SEPA mandate setup (mandate + customer indicates subscription intent)
        Priority 4: Other metadata indicators
        Priority 5: Legacy JSON description parsing
        Priority 6: Existing donation status
        """
        # Priority 1: Explicit metadata override (highest priority)
        if "metadata" in mollie_data and mollie_data["metadata"]:
            metadata = mollie_data["metadata"]
            subscription_setup = metadata.get("subscription_setup")
            if subscription_setup == "false":
                self.logger.info("🔍 Explicit subscription_setup=false override - marking as one-time")
                return False  # Explicit override
            elif subscription_setup == "true":
                self.logger.info("🔍 Explicit subscription_setup=true override - marking as recurring")
                return True  # Explicit override

        # Priority 2: Mollie subscription ID (definitive)
        if mollie_data.get("subscription_id"):
            self.logger.info("🔍 Mollie subscription_id present - marking as recurring")
            return True

        # Priority 3: SEPA mandate setup (mandate + customer indicates subscription intent)
        if mollie_data.get("mandate_id") and mollie_data.get("customer_id"):
            self.logger.info("🔍 SEPA mandate + customer detected - marking as recurring")
            return True

        # Priority 4: Other metadata indicators
        if "metadata" in mollie_data and mollie_data["metadata"]:
            metadata = mollie_data["metadata"]
            if metadata.get("subscription_interval") or metadata.get("subscription_amount"):
                self.logger.info("🔍 Subscription metadata indicators found - marking as recurring")
                return True

        # Priority 5: Legacy JSON description parsing (backward compatibility)
        mollie_description = mollie_data.get("description")
        if mollie_description:
            try:
                import json

                desc_data = json.loads(mollie_description)
                if desc_data.get("type") == "recurring":
                    self.logger.info("🔍 Legacy JSON description indicates recurring - marking as recurring")
                    return True
            except (json.JSONDecodeError, TypeError):
                pass

        # Priority 6: Existing donation status (for subsequent payments)
        if hasattr(donation, "status") and donation.get("status") == DonationStatus.RECURRING:
            self.logger.info("🔍 Donation already marked as recurring - preserving status")
            return True

        # Default to one-time if no indicators found
        self.logger.info("🔍 No subscription indicators found - marking as one-time")
        return False

    def _extract_and_save_consumer_bank_data(self, customer: str, payment_data: Any) -> None:
        """
        Extract consumer bank account data from Mollie payment and save to Customer.

        For donations, we only create Bank Account links for the Customer (not Member/Donor).
        This enables future payment matching by IBAN in MT940 imports, etc.

        Args:
            customer: Customer document name
            payment_data: Mollie payment object with details
        """
        if not customer:
            return

        try:
            # Extract payment details
            details = getattr(payment_data, "details", None)
            if not details:
                return

            # Handle both dict and object-style access
            if hasattr(details, "get"):
                consumer_account = details.get("consumerAccount")
            else:
                consumer_account = getattr(details, "consumerAccount", None) or getattr(details, "consumer_account", None)

            if not consumer_account:
                return

            # Validate IBAN format
            from verenigingen.integrations.mollie.utils.validators import validate_iban

            iban_result = validate_iban(consumer_account)
            if not iban_result.get("valid"):
                self.logger.debug(
                    f"Consumer account {consumer_account} is not a valid IBAN, skipping bank data save"
                )
                return

            # Clean IBAN
            clean_iban = consumer_account.replace(" ", "").upper()

            # Create Bank Account link for Customer (enables future MT940 matching)
            self._ensure_customer_bank_account(customer, clean_iban)

        except Exception as e:
            # Don't fail payment processing if bank data save fails
            self.logger.warning(
                f"Could not save consumer bank data for customer {customer}: {str(e)}"
            )

    def _ensure_customer_bank_account(self, customer: str, iban: str) -> None:
        """
        Ensure a Bank Account record exists linking this IBAN to the Customer.

        Args:
            customer: Customer document name
            iban: IBAN to link
        """
        try:
            # Check if Bank Account already exists for this IBAN
            existing = frappe.db.exists("Bank Account", {"iban": iban})
            if existing:
                # Check if it's linked to the right customer
                existing_party = frappe.db.get_value("Bank Account", existing, ["party_type", "party"], as_dict=True)
                if existing_party and existing_party.get("party") == customer:
                    return  # Already correctly linked

                # Exists but linked to different party - log and skip
                self.logger.debug(
                    f"Bank Account for IBAN {iban} exists but linked to {existing_party}, not updating"
                )
                return

            # Create Bank Account linking IBAN to Customer
            bank_account = frappe.new_doc("Bank Account")
            bank_account.account_name = f"{customer} - {iban[-4:]}"
            bank_account.bank = "Unknown"
            bank_account.iban = iban
            bank_account.party_type = "Customer"
            bank_account.party = customer
            bank_account.is_default = 0
            bank_account.insert(ignore_permissions=True)

            self.logger.info(
                f"✅ Created Bank Account link from donation: IBAN {iban} -> Customer {customer}"
            )

        except Exception as e:
            self.logger.warning(f"Could not create Bank Account for {customer}: {str(e)}")

    def _create_bank_transaction_for_donation(self, donation, mollie_data: Dict[str, Any]) -> Optional[str]:
        """
        Create Bank Transaction for a donation payment from Mollie.

        Creates a submitted Bank Transaction. The Payment Entry will be linked to it
        after PE creation via the child table.

        Args:
            donation: Donation document
            mollie_data: Extracted Mollie payment data dict

        Returns:
            str: Bank Transaction name if created, None otherwise
        """
        try:
            # Get donor and customer
            if not hasattr(donation, "donor") or not donation.donor:
                self.logger.warning(
                    f"Donation {donation.name} has no linked Donor - skipping Bank Transaction"
                )
                return None

            donor = frappe.get_doc("Donor", donation.donor)
            customer = getattr(donor, "customer", None)

            if not customer:
                self.logger.warning(
                    f"Donor {donor.name} has no linked Customer - skipping Bank Transaction creation"
                )
                return None

            # Get bank account configuration using centralized helper
            config = self.bank_tx_creator.get_mollie_bank_account_config()

            if config.get("error"):
                self.logger.error(f"Mollie configuration error: {config['error']}")
                return None

            bank_account = config["bank_account"]
            company = config["company"]

            # Extract payment data from Mollie
            payment_id = mollie_data["payment_id"]

            # Extract payment data
            amount = mollie_data["amount"]
            currency = mollie_data.get("currency") or "EUR"

            # Extract and convert payment date
            paid_at = mollie_data.get("paid_at")
            if paid_at:
                # Convert ISO string to date object
                from dateutil import parser

                payment_date = parser.parse(paid_at).date()
            else:
                # Fallback to today if paid_at is missing
                payment_date = frappe.utils.getdate()

            # Build description with donation context
            donor_name = donor.donor_name or "Unknown Donor"
            description = f"Donation from {donor_name} | {payment_id}"

            # Use centralized create() method with party fields
            bank_transaction_name = self.bank_tx_creator.create(
                date=payment_date,
                bank_account=bank_account,
                company=company,
                deposit=float(amount),
                withdrawal=0.0,
                currency=currency,
                reference_number=payment_id,
                transaction_id=payment_id,
                description=description,
                party_type="Customer",
                party=customer,
            )

            if bank_transaction_name:
                self.logger.info(
                    f"✅ Created Bank Transaction {bank_transaction_name} for donation {donation.name} "
                    f"(amount: {currency} {amount}, payment: {payment_id}, status: Submitted)"
                )

            return bank_transaction_name

        except Exception as e:
            self.logger.error(f"Failed to create Bank Transaction for donation {donation.name}: {e}")
            frappe.log_error(
                f"Bank Transaction creation failed for donation {donation.name}: {str(e)}",
                "Donation Payment Processing",
            )
            return None


class MembershipPaymentProcessor(AbstractPaymentProcessor):
    """
    Payment processor for membership payments.

    Handles member subscription payments, dues payments, and membership-specific logic.
    """

    def supports_context(self, context: PaymentContext) -> bool:
        return context.payment_type == "membership"

    def process_successful_payment(
        self, context: PaymentContext, payment_data: Any, mollie_data: Dict[str, Any]
    ) -> PaymentProcessingResult:
        """Process successful membership payment"""
        try:
            self.logger.info(f"Processing successful membership payment for {context.target_name}")

            # Check idempotency first
            idempotency_status = self.check_idempotency(context, mollie_data["payment_id"])
            if idempotency_status.get("all_complete"):
                return PaymentProcessingResult(
                    success=True,
                    message="Membership payment already processed",
                    data={"member_id": context.target_name, "status": "already_processed"},
                )

            # Get member document
            member = frappe.get_doc("Member", context.target_name)

            # Create Payment Entry using the factory
            payment_entry = self.payment_factory.create_payment_entry(
                context=context, mollie_data=mollie_data
            )

            if not payment_entry:
                raise Exception("Failed to create Payment Entry")

            # Add payment to member history
            member.append(
                "payment_history",
                {
                    "posting_date": frappe.utils.getdate(),
                    "payment_date": frappe.utils.getdate(),
                    "amount": float(mollie_data["amount"]),
                    "payment_method": "Mollie",
                    "payment_status": PaymentStatus.PAID,
                    "transaction_type": "Membership Payment",
                    "payment_reference": mollie_data["payment_id"],
                    "mollie_payment_id": mollie_data["payment_id"],
                    "notes": f"Mollie payment {mollie_data['payment_id']} via {mollie_data.get('method', 'Unknown method')}",
                },
            )

            member.save()

            # Try to find and link to unpaid Sales Invoice (membership dues)
            invoice_result = self._link_to_membership_invoice(member, mollie_data, payment_entry)

            return PaymentProcessingResult(
                success=True,
                message="Membership payment processed successfully",
                data={
                    "member_id": member.name,
                    "payment_entry": payment_entry.name,
                    "amount": mollie_data["amount"],
                    "invoice_link": invoice_result,
                    "status": "completed",
                },
            )

        except Exception as e:
            self.logger.error(f"Error processing membership payment: {e}")
            return PaymentProcessingResult(
                success=False, message=f"Failed to process membership payment: {str(e)}"
            )

    def process_failed_payment(
        self, context: PaymentContext, payment_data: Any, mollie_data: Dict[str, Any]
    ) -> PaymentProcessingResult:
        """Process failed membership payment"""
        try:
            self.logger.info(f"Processing failed membership payment for {context.target_name}")

            # Get member document
            member = frappe.get_doc("Member", context.target_name)

            # Validate payment amount
            amount = float(mollie_data.get("amount", 0))
            if amount <= 0:
                amount = getattr(payment_data, "amount", {}).get("value", 0)
                if isinstance(amount, str):
                    amount = float(amount)

            # Add failed payment to member history
            member.append(
                "payment_history",
                {
                    "posting_date": frappe.utils.getdate(),
                    "payment_date": frappe.utils.getdate(),
                    "amount": amount,
                    "payment_method": "Mollie",
                    "payment_status": PaymentStatus.CANCELLED,
                    "transaction_type": "Membership Payment",
                    "payment_reference": mollie_data["payment_id"],
                    "mollie_payment_id": mollie_data["payment_id"],
                    "notes": f"Mollie payment {mollie_data['payment_id']} failed: {getattr(payment_data, 'status', 'Unknown')}",
                },
            )

            member.save()

            return PaymentProcessingResult(
                success=True,
                message="Failed membership payment recorded",
                data={"member_id": member.name, "status": "failed_payment_recorded"},
            )

        except Exception as e:
            self.logger.error(f"Error processing failed membership payment: {e}")
            return PaymentProcessingResult(
                success=False, message=f"Failed to record failed membership payment: {str(e)}"
            )

    def check_idempotency(self, context: PaymentContext, payment_id: str) -> Dict[str, Any]:
        """Check membership payment processing status"""
        # Use unified idempotency manager for Payment Entry check
        from verenigingen.integrations.mollie.services.unified_idempotency_manager import (
            get_unified_idempotency_manager,
        )

        idempotency_manager = get_unified_idempotency_manager()
        payment_entry_exists = bool(idempotency_manager.payment_entry_exists(payment_id))

        # Check member payment history
        member = frappe.get_doc("Member", context.target_name)
        history_exists = False
        if hasattr(member, "payment_history") and member.payment_history:
            for payment_record in member.payment_history:
                if (
                    getattr(payment_record, "payment_reference", None) == payment_id
                    or getattr(payment_record, "mollie_payment_id", None) == payment_id
                ):
                    history_exists = True
                    break

        all_complete = payment_entry_exists and history_exists

        return {
            "payment_entry_created": payment_entry_exists,
            "payment_history_exists": history_exists,
            "all_complete": all_complete,
        }

    def _link_to_membership_invoice(self, member, mollie_data, payment_entry):
        """Try to find and link payment to an unpaid membership dues invoice"""
        try:
            # Find unpaid Sales Invoice for this member
            customer = member.customer if hasattr(member, "customer") else None
            if not customer:
                return {"status": "no_customer", "message": "Member has no linked customer"}

            unpaid_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": customer, "outstanding_amount": [">", 0], "status": ["!=", "Cancelled"]},
                fields=["name", "outstanding_amount", "grand_total"],
                order_by="posting_date desc",
                limit=1,
            )

            if unpaid_invoices:
                invoice = unpaid_invoices[0]
                # Link Payment Entry to Sales Invoice through Payment Entry References
                payment_entry.append(
                    "references",
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": invoice.name,
                        "allocated_amount": min(float(mollie_data["amount"]), invoice.outstanding_amount),
                    },
                )
                payment_entry.save()

                return {
                    "status": "linked",
                    "invoice": invoice.name,
                    "allocated_amount": min(float(mollie_data["amount"]), invoice.outstanding_amount),
                }
            else:
                return {"status": "no_unpaid_invoices", "message": "No unpaid invoices found"}

        except Exception as e:
            self.logger.warning(f"Could not link to membership invoice: {e}")
            return {"status": "error", "message": str(e)}


class PaymentProcessorFactory:
    """
    Factory for creating appropriate payment processors based on context
    """

    def __init__(self):
        self.processors = [
            DonationPaymentProcessor(),
            MembershipPaymentProcessor(),
        ]

    def get_processor(self, context: PaymentContext) -> Optional[AbstractPaymentProcessor]:
        """Get the appropriate processor for the given payment context"""
        for processor in self.processors:
            if processor.supports_context(context):
                return processor
        return None

    def register_processor(self, processor: AbstractPaymentProcessor):
        """Register a new payment processor"""
        self.processors.append(processor)
