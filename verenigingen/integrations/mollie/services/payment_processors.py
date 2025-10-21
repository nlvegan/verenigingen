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
    donation status updates, and payment history management.
    """

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

            # Track what we actually process
            processed_components = []
            payment_entry = None

            # 1. Create Payment Entry only if it doesn't exist
            if not idempotency_status.get("payment_entry_created"):
                self.logger.info(f"Creating Payment Entry for {mollie_data['payment_id']}")
                payment_entry = self.payment_factory.create_payment_entry(
                    context=context, mollie_data=mollie_data
                )
                if not payment_entry:
                    raise Exception("Failed to create Payment Entry")
                processed_components.append("payment_entry")
            else:
                self.logger.info(f"Payment Entry already exists for {mollie_data['payment_id']}")
                # Get existing payment entry for return data
                payment_entry_name = frappe.db.get_value(
                    "Payment Entry", {"reference_no": mollie_data["payment_id"]}, "name"
                )
                if payment_entry_name:
                    payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)

            # 2. Update donation status only if not already set
            if not idempotency_status.get("payment_recorded"):
                self.logger.info(f"Updating donation status for {context.target_name}")
                donation.paid = 1
                donation.received_amount = float(mollie_data["amount"])
                donation.payment_id = mollie_data["payment_id"]
                donation.payment_date = frappe.utils.getdate()

                # Set payment_status if field exists
                if hasattr(donation, "payment_status"):
                    donation.payment_status = "Completed"

                # Update subscription ID if present and not already set
                if mollie_data.get("subscription_id") and not getattr(
                    donation, "mollie_subscription_id", None
                ):
                    donation.mollie_subscription_id = mollie_data["subscription_id"]
                    self.logger.info(
                        f"✅ Updated donation {donation.name} with subscription ID: {mollie_data['subscription_id']}"
                    )

                # Update customer ID if present and not already set
                if mollie_data.get("customer_id") and not getattr(donation, "mollie_customer_id", None):
                    donation.mollie_customer_id = mollie_data["customer_id"]
                    self.logger.info(
                        f"✅ Updated donation {donation.name} with customer ID: {mollie_data['customer_id']}"
                    )

                # Determine if recurring and set appropriate status
                if not idempotency_status.get("donation_status_updated"):
                    is_recurring = self._determine_recurring_status(donation, mollie_data)
                    if is_recurring:
                        donation.status = "Recurring"
                        self.logger.info(f"✅ Set donation {donation.name} status to Recurring")
                    else:
                        donation.status = "One-time"
                        self.logger.info(f"✅ Set donation {donation.name} status to One-time")

                processed_components.append("donation_status")
            else:
                self.logger.info(f"Donation status already updated for {context.target_name}")

            # 3. Add payment history only if not already exists
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
                    "payment_status": "Paid",
                    "mollie_payment_id": mollie_data["payment_id"],
                    "remarks": f"Mollie payment {mollie_data['payment_id']}",
                }

                # Add currency if available
                if mollie_data.get("currency"):
                    payment_history["currency"] = mollie_data["currency"]

                # Add payment_entry link if we created one
                if payment_entry and hasattr(payment_entry, "name"):
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
                    "payment_status": "Cancelled",
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
        # Check if Payment Entry exists (any docstatus - draft or submitted)
        payment_entry_exists = bool(
            frappe.db.get_value("Payment Entry", {"reference_no": payment_id}, "name")
        )

        # Check donation status
        donation = frappe.get_doc("Donation", context.target_name)
        payment_recorded = (
            getattr(donation, "paid", 0) == 1 and getattr(donation, "payment_id", None) == payment_id
        )

        # Check donation status is properly set (One-time or Recurring)
        donation_status_updated = getattr(donation, "status", None) in ["One-time", "Recurring"]

        # Check payment history
        history_exists = False
        if hasattr(donation, "payments") and donation.payments:
            for payment_record in donation.payments:
                if getattr(payment_record, "mollie_payment_id", None) == payment_id:
                    history_exists = True
                    break

        all_complete = (
            payment_entry_exists and payment_recorded and history_exists and donation_status_updated
        )

        return {
            "payment_entry_created": payment_entry_exists,
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
        if hasattr(donation, "status") and donation.get("status") == "Recurring":
            self.logger.info("🔍 Donation already marked as recurring - preserving status")
            return True

        # Default to one-time if no indicators found
        self.logger.info("🔍 No subscription indicators found - marking as one-time")
        return False


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
                    "payment_status": "Paid",
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
                    "payment_status": "Cancelled",
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
        # For membership payments, check if Payment Entry exists and member history is updated
        payment_entry_exists = bool(
            frappe.db.get_value("Payment Entry", {"reference_no": payment_id, "docstatus": 1}, "name")
        )

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
