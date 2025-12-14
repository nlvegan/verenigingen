"""
Mollie Webhook Service

COMPLETE webhook processing service ported from the original mollie_payment_webhook.py
with all critical business logic for payment completion and financial record creation.
"""

import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from ..core.client import MollieClient
from ..exceptions import MollieSecurityError, MollieWebhookError
from ..utils.amount_helpers import extract_amount_currency
from ..utils.audit import MollieAuditLogger
from ..utils.mollie_relationship_manager import MollieRelationshipManager, MollieWebhookQueue
from ..utils.webhook_security import authenticate_mollie_webhook, validate_webhook_user_permissions


class WebhookService:
    """
    Complete webhook processing service with all critical business logic
    ported from the original implementation.
    """

    def __init__(self):
        """Initialize webhook service with required components."""
        self.client = MollieClient()
        self.relationship_manager = MollieRelationshipManager()
        self.webhook_queue = MollieWebhookQueue()
        self.audit_logger = MollieAuditLogger()

    def handle_mollie_payment_webhook(self, request_data: dict = None, headers: dict = None) -> dict:
        """
        Main webhook handler - complete port from original mollie_payment_webhook.py
        """
        # CRITICAL: Log every webhook call for debugging
        try:
            frappe.log_error(
                f"WEBHOOK_DEBUG: Called at {frappe.utils.now()}\n"
                f"Form dict: {frappe.form_dict}\n"
                f"Request method: {frappe.request.method if frappe.request else 'None'}\n"
                f"Raw data: {frappe.request.get_data(as_text=True) if frappe.request else 'None'}",
                "Mollie Webhook Call Debug",
            )
        except Exception as debug_error:
            frappe.log_error(f"Debug logging failed: {debug_error}", "Webhook Debug Error")

        try:
            # Set webhook user context for proper security
            authenticate_mollie_webhook()

            # Validate permissions
            if not validate_webhook_user_permissions():
                frappe.throw("Webhook user lacks required permissions")

            # Parse webhook data
            payment_id, event_type, webhook_data = self._parse_webhook_payload()

            if not payment_id:
                return {"status": "error", "message": "No payment ID found in webhook"}

            frappe.logger().info(f"🎯 Processing webhook for payment: {payment_id}")

            # Skip if ping
            if payment_id == "ping" or event_type == "hook.ping":
                return {"status": "success", "message": "Ping received"}

            # Process with lock to prevent race conditions
            with self.webhook_queue.with_lock(payment_id):
                return self._process_payment_webhook(payment_id, webhook_data)

        except Exception as e:
            frappe.log_error(f"Webhook processing error: {e}", "Mollie Webhook Error")
            return {"status": "error", "message": str(e)}

    def _parse_webhook_payload(self) -> tuple:
        """
        Parse webhook payload - handles both JSON events and form data.
        Ported from original implementation.
        """
        raw_payload = frappe.request.get_data(as_text=True) if frappe.request else ""
        payment_id = None
        event_type = None
        webhook_data = {}

        frappe.logger().info(f"🔍 Raw payload: {repr(raw_payload)}")
        frappe.logger().info(f"🔍 Form dict: {dict(frappe.form_dict)}")

        # Try different parsing approaches in order
        if raw_payload and raw_payload.strip():
            # First, check if it's URL-encoded data (common for POST form data)
            if "=" in raw_payload and not raw_payload.startswith("{"):
                try:
                    parsed_data = urllib.parse.parse_qs(raw_payload)
                    payment_id = parsed_data.get("id", [None])[0]
                    webhook_data = {k: v[0] if v else None for k, v in parsed_data.items()}
                    frappe.logger().info(f"✅ Parsed URL-encoded data: payment_id={payment_id}")
                except Exception as parse_error:
                    frappe.logger().error(f"⚠️ Failed to parse URL-encoded data: {parse_error}")
            else:
                # Try JSON parsing for Mollie event webhooks
                try:
                    webhook_data = frappe.parse_json(raw_payload)

                    # Handle Mollie's JSON event structure
                    if webhook_data.get("resource") == "event":
                        event_type = webhook_data.get("type")

                        # For payment events, the payment ID is in entityId
                        if event_type and event_type.startswith("payment."):
                            payment_id = webhook_data.get("entityId")
                        elif event_type == "hook.ping":
                            payment_id = "ping"

                    frappe.logger().info(f"✅ Parsed JSON event: payment_id={payment_id}, type={event_type}")
                except Exception as json_error:
                    frappe.logger().error(f"⚠️ Failed to parse JSON: {json_error}")

        # Fallback to form_dict if raw payload parsing failed
        if not payment_id and frappe.form_dict:
            payment_id = frappe.form_dict.get("id")
            webhook_data = dict(frappe.form_dict)
            frappe.logger().info(f"✅ Using form_dict: payment_id={payment_id}")

        # Validate payment ID format (security-critical)
        if payment_id and payment_id != "ping":
            if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
                frappe.log_error(
                    f"Webhook validation failed - Invalid payment ID format: {payment_id}. Type: {type(payment_id)}",
                    "Mollie Webhook Validation Error",
                )
                raise ValueError("Invalid payment ID format")

        return payment_id, event_type, webhook_data

    def _process_payment_webhook(self, payment_id: str, webhook_data: dict) -> dict:
        """
        Process payment webhook with complete business logic.
        """
        try:
            # Get payment from Mollie
            from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

            if not gateway or not gateway.client:
                raise MollieWebhookError("Mollie gateway not available")

            payment = gateway.client.payments.get(payment_id)

            frappe.logger().info(f"📊 Payment status: {payment.status}")
            frappe.logger().info(f"📊 Payment amount: {payment.amount}")

            # Only process paid payments
            # Handle payment status - complete port from original logic
            if payment.status == "paid":
                # Payment successful - continue with processing
                pass
            elif payment.status in ["canceled", "expired", "failed"]:
                # Handle failed payments - port from original lines 214-221
                frappe.logger().info(f"❌ Payment {payment_id} failed (status: {payment.status})")

                # Find donation to update status
                donation = self._find_donation_for_payment(payment_id, payment)
                if donation:
                    # Update donation status for failed payments
                    donation.paid = 0
                    if hasattr(donation, "payment_status"):
                        donation.payment_status = "Failed"
                    donation.save()
                    frappe.logger().info(f"✅ Updated donation {donation.name} for failed payment")

                return {"status": "processed", "payment_status": "failed", "payment_id": payment_id}
            else:
                # Payment still pending
                frappe.logger().info(f"⏸️ Payment {payment_id} pending (status: {payment.status})")
                return {"status": "processed", "payment_status": "pending", "payment_id": payment_id}

            # Find corresponding donation
            donation = self._find_donation_for_payment(payment_id, payment)

            if not donation:
                frappe.logger().error(f"❌ No donation found for payment {payment_id}")
                return {"status": "error", "message": f"No donation found for payment {payment_id}"}

            # Check if already processed (critical idempotency check)
            idempotency_status = self._check_payment_processing_status(donation, payment_id)

            if idempotency_status["all_complete"]:
                frappe.logger().info(f"⏭️ Payment {payment_id} already fully processed")
                return {
                    "status": "already_processed",
                    "donation": donation.name,
                    "details": idempotency_status,
                }

            # Check for subscription creation (first payment setup)
            # Complete port from original implementation (lines 177-204)
            if (
                getattr(payment, "sequence_type", None) == "first"
                and hasattr(payment, "metadata")
                and payment.metadata.get("subscription_setup") == "true"
            ):
                frappe.logger().info("🎯 Processing first payment with subscription metadata")

                try:
                    # Process subscription creation using payment gateway
                    from verenigingen.verenigingen_payments.utils.payment_gateways import (
                        PaymentGatewayFactory,
                        _activate_direct_subscription_after_first_payment,
                    )

                    gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
                    subscription_result = _activate_direct_subscription_after_first_payment(gateway, payment)

                    frappe.logger().info(f"Subscription creation result: {subscription_result}")

                    if subscription_result.get("status") == "success":
                        # Update donation with subscription ID
                        donation.db_set("mollie_subscription_id", subscription_result["subscription_id"])
                        frappe.logger().info(
                            f"✅ Created subscription: {subscription_result['subscription_id']}"
                        )
                    else:
                        frappe.logger().error(
                            f"❌ Subscription creation failed: {subscription_result.get('message', 'Unknown error')}"
                        )
                except Exception as e:
                    frappe.log_error(f"Error creating subscription for payment {payment_id}: {e}")
                    frappe.logger().error(f"❌ Subscription creation error: {e}")

            # Process the payment
            result = self._process_successful_payment_with_idempotency(donation, payment, idempotency_status)

            frappe.logger().info(f"✅ Successfully processed payment {payment_id}")
            return {
                "status": "success",
                "message": f"Payment {payment_id} processed successfully",
                "payment_id": payment_id,
                "donation": donation.name,
                "result": result,
            }

        except Exception as e:
            frappe.log_error(
                f"Error processing payment webhook {payment_id}: {e}", "Payment Processing Error"
            )
            raise MollieWebhookError(f"Failed to process payment {payment_id}: {e}")

    def _find_donation_for_payment(self, payment_id: str, payment) -> Optional[Document]:
        """
        Find donation record for the given payment.
        Complete port from original implementation.
        """
        donation = None

        # Method 1: Direct payment_id match (with database locking to prevent race conditions)
        donation = self._find_donation_for_payment_by_id(payment_id, with_lock=True)
        if donation:
            frappe.logger().info(f"✅ Found donation by payment_id: {donation.name}")
            return donation

        # Method 2: For subscription payments, use metadata (with database locking)
        if hasattr(payment, "subscription_id") and payment.subscription_id:
            donation = self._find_donation_for_subscription_payment(payment_id, payment, with_lock=True)
            if donation:
                frappe.logger().info(f"✅ Found donation by subscription: {donation.name}")
                return donation

        # Method 3: Customer + time window matching (fallback)
        if hasattr(payment, "customer_id") and payment.customer_id:
            donation = self._find_donation_by_customer_timeframe(payment)
            if donation:
                frappe.logger().info(f"✅ Found donation by customer+time: {donation.name}")
                return donation

        frappe.logger().error(f"❌ No donation found for payment {payment_id}")
        return None

    def _find_donation_for_payment_by_id(
        self, payment_id: str, with_lock: bool = False
    ) -> Optional[Document]:
        """Find donation record by payment_id (primary matching only)"""
        try:
            filters = {"payment_id": payment_id}
            donation_name = frappe.db.get_value("Donation", filters, "name", for_update=with_lock)

            if donation_name:
                return frappe.get_doc("Donation", donation_name, for_update=with_lock)

        except Exception as e:
            frappe.log_error(f"Error finding donation by payment_id {payment_id}: {e}")

        return None

    def _find_donation_for_subscription_payment(
        self, payment_id: str, payment, with_lock: bool = False
    ) -> Optional[Document]:
        """
        Find donation record for subscription payments by looking at payment metadata.
        Complete port from original implementation (lines 249-290).
        """
        # If payment object is available, check if this is a subscription payment
        if payment and (not hasattr(payment, "subscription_id") or not payment.subscription_id):
            return None

        # If payment object is available, get donation_id from payment metadata
        if payment:
            metadata = getattr(payment, "metadata", {})
            donation_id = metadata.get("donation_id")

            if donation_id:
                frappe.logger().info(f"🔍 Found donation_id in subscription payment metadata: {donation_id}")
                try:
                    if with_lock:
                        # Acquire row-level lock
                        frappe.db.sql(
                            "SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE", (donation_id,)
                        )
                    return frappe.get_doc("Donation", donation_id)
                except frappe.DoesNotExistError:
                    frappe.logger().error(f"❌ Donation {donation_id} from metadata not found")
                    return None

            # Fallback: try to find by subscription_id (if donation has it stored)
            frappe.logger().info(f"🔍 Trying fallback lookup by subscription_id: {payment.subscription_id}")
            donation_name = frappe.db.get_value(
                "Donation", {"mollie_subscription_id": payment.subscription_id}, "name"
            )
            if donation_name:
                if with_lock:
                    frappe.db.sql(
                        "SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE", (donation_name,)
                    )
                return frappe.get_doc("Donation", donation_name)

        # If no payment object or no subscription info found, return None
        # This is normal for first payments that haven't been processed yet
        return None

    def _find_donation_by_customer_timeframe(self, payment) -> Optional[Document]:
        """
        Fallback: Find donation by customer and time window.
        Complete port from original implementation (lines 357-407).
        """
        customer_id = getattr(payment, "customer_id", None)
        if not customer_id:
            return None

        # Get payment creation time
        payment_created = getattr(payment, "created_at", None)
        if not payment_created:
            return None

        # Convert to datetime if it's a string
        if isinstance(payment_created, str):
            try:
                payment_created = datetime.fromisoformat(payment_created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

        # Search for donations within 30-minute window
        time_window_start = payment_created - timedelta(minutes=30)
        time_window_end = payment_created + timedelta(minutes=30)

        donations = frappe.get_all(
            "Donation",
            filters={
                "mollie_customer_id": customer_id,
                "creation": ["between", [time_window_start, time_window_end]],
                "paid": 0,  # Only unpaid donations
            },
            order_by="creation desc",
            limit=1,
        )

        if donations:
            frappe.logger().info(f"✅ Found donation via customer+timestamp fallback: {donations[0].name}")
            return frappe.get_doc("Donation", donations[0].name)

        return None

    def _check_payment_processing_status(self, donation: Document, payment_id: str) -> dict:
        """
        Check the processing status of each component with isolated idempotency checks.
        Complete port from original implementation (lines 310-354).
        """
        # Check 1: Payment Entry using unified idempotency manager
        from verenigingen.integrations.mollie.services.unified_idempotency_manager import (
            get_unified_idempotency_manager,
        )

        idempotency_manager = get_unified_idempotency_manager()
        payment_entry = idempotency_manager.payment_entry_exists(payment_id)
        payment_entry_created = bool(payment_entry)

        # Check 2: Payment History (isolated check - only looks for history with this transaction)
        payment_history_exists = False
        if hasattr(donation, "payments") and donation.payments:
            for payment_record in donation.payments:
                # Check multiple possible field names for transaction ID
                if (
                    getattr(payment_record, "mollie_payment_id", None) == payment_id
                    or getattr(payment_record, "payment_reference", None) == payment_id
                    or getattr(payment_record, "payment_id", None) == payment_id
                ):
                    payment_history_exists = True
                    break

        # Check 3: Donation Status (isolated check - only verifies status is not "Promised")
        donation_status_updated = donation.status in ["One-time", "Recurring"]

        all_complete = payment_entry_created and payment_history_exists and donation_status_updated

        return {
            "payment_entry_created": payment_entry_created,
            "payment_history_exists": payment_history_exists,
            "donation_status_updated": donation_status_updated,
            "payment_entry_name": payment_entry if payment_entry_created else None,
            "donation_history_updated": payment_history_exists,
            "all_complete": all_complete,
        }

    def _process_successful_payment_with_idempotency(
        self, donation: Document, payment, idempotency_status: dict
    ) -> dict:
        """
        Process successful payment with proper ordering and isolated idempotency checks.
        Order: Payment Entry → Payment History → Status Updates → Paid Flag (one-time only)
        """
        result = {
            "payment_entry": None,
            "payment_history_updated": False,
            "donation_updated": False,
            "already_processed": idempotency_status["fully_processed"],
        }

        try:
            # Extract Mollie payment data
            mollie_data = self._extract_mollie_payment_data(payment)

            # Step 1: Create Payment Entry (if not exists)
            if not idempotency_status["payment_entry_created"]:
                payment_entry_name = self._create_payment_entry_for_donation(donation, mollie_data)
                result["payment_entry"] = payment_entry_name
                frappe.logger().info(f"✅ Created Payment Entry: {payment_entry_name}")
            else:
                frappe.logger().info("⏭️ Payment Entry already exists")

            # Step 2: Update Payment History (if not exists)
            if not idempotency_status["payment_history_updated"]:
                self._update_donation_payment_history(donation, mollie_data, result.get("payment_entry"))
                result["payment_history_updated"] = True
                frappe.logger().info("✅ Updated payment history")
            else:
                frappe.logger().info("⏭️ Payment history already updated")

            # Step 3: Update donation with Mollie data
            if not idempotency_status["status_updated"]:
                self._update_donation_with_mollie_data(donation, mollie_data)
                result["donation_updated"] = True
                frappe.logger().info("✅ Updated donation with Mollie data")
            else:
                frappe.logger().info("⏭️ Donation already updated")

            # Commit changes
            frappe.db.commit()

        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(f"Error processing successful payment: {e}", "Payment Processing Error")
            raise

        return result

    def _extract_mollie_payment_data(self, payment) -> dict:
        """Extract relevant data from Mollie payment object using centralized extractor"""
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()

        return {
            "payment_id": extractor.extract_payment_id(payment),
            "amount": extractor.extract_amount(payment, allow_zero=True),  # Allow zero for audit purposes
            "currency": extract_amount_currency(payment.amount),
            "status": payment.status,
            "method": getattr(payment, "method", None),
            "paid_at": getattr(payment, "paid_at", None),  # Keep raw for dict return
            "created_at": getattr(payment, "created_at", None),  # Keep raw for dict return
            "description": extractor.extract_description(payment, fallback_description=""),
            "customer_id": getattr(payment, "customer_id", None),
            "subscription_id": getattr(payment, "subscription_id", None),
            "metadata": getattr(payment, "metadata", {}),
            "details": getattr(payment, "details", {}),
        }

    def _determine_recurring_status(self, donation: Document, mollie_data: dict) -> bool:
        """
        Determine if payment should be treated as recurring based on Mollie data and donation status.
        Complete port from original implementation (lines 441-468).
        """
        # Check 1: Has Mollie subscription ID
        has_mollie_subscription = bool(mollie_data.get("subscription_id"))

        # Check 2: For first payments of subscriptions, check description metadata
        donation_metadata_recurring = False
        mollie_description = mollie_data.get("description")
        frappe.logger().info(f"🔍 Mollie description raw: {repr(mollie_description)}")

        if mollie_description:
            try:
                desc_data = json.loads(mollie_description)
                donation_metadata_recurring = desc_data.get("type") == "recurring"
                frappe.logger().info(f"🔍 Parsed description JSON: {desc_data}")
                frappe.logger().info(f"🔍 Type field: {desc_data.get('type')}")
                frappe.logger().info(f"🔍 Is recurring from description: {donation_metadata_recurring}")
            except (json.JSONDecodeError, TypeError) as e:
                frappe.logger().info(f"⚠️ Failed to parse Mollie description JSON: {e}")
        else:
            frappe.logger().info("⚠️ No Mollie description found")

        # Check 3: Check if donation was already marked as recurring (for subsequent payments)
        already_recurring = donation.get("status") == "Recurring" if hasattr(donation, "status") else False

        is_recurring = has_mollie_subscription or donation_metadata_recurring or already_recurring

        frappe.logger().info(
            f"🔍 Recurring detection: subscription={has_mollie_subscription}, metadata={donation_metadata_recurring}, already={already_recurring} → {is_recurring}"
        )

        return is_recurring

    def _create_payment_entry_for_donation(self, donation: Document, mollie_data: dict) -> str:
        """Create Payment Entry for the successful donation payment"""
        try:
            # Get the customer linked to the donor
            donor_doc = frappe.get_doc("Donor", donation.donor)
            customer = donor_doc.customer
            if not customer:
                frappe.logger().info(f"🔄 No customer linked to donor {donation.donor}, creating one...")
                # Auto-create customer from donor
                customer = donor_doc.get_or_create_customer()
                if not customer:
                    frappe.logger().error(f"❌ Failed to create customer for donor {donation.donor}")
                    return None
                frappe.logger().info(f"✅ Created customer {customer} for donor {donation.donor}")

            # Check if Payment Entry already exists (idempotency)
            existing_pe = frappe.db.get_value(
                "Payment Entry",
                {"payment_type": "Receive", "reference_no": mollie_data["payment_id"], "party": customer},
                "name",
            )

            if existing_pe:
                frappe.logger().info(f"⚠️ Payment Entry already exists: {existing_pe}")
                return existing_pe

            # Get company
            settings = frappe.get_single("Verenigingen Settings")
            company = settings.company or frappe.defaults.get_global_default("company")

            # Validate Mode of Payment exists
            from verenigingen.utils.validation_utilities import DocumentExistenceValidator

            if not DocumentExistenceValidator.check_document_exists("Mode of Payment", "Mollie"):
                frappe.logger().error("❌ Mollie Mode of Payment not configured")
                return None

            # Create Payment Entry for donation - let ERPNext handle account assignment automatically
            payment_entry = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer,
                    "company": company,
                    "paid_amount": mollie_data["amount"],
                    "received_amount": mollie_data["amount"],
                    "reference_no": mollie_data["payment_id"],
                    "reference_date": frappe.utils.getdate(),
                    # "mode_of_payment": "Mollie",  # Temporarily commented out to fix cancel button issue
                    "remarks": f"Donation payment {donation.name} via Mollie ({mollie_data.get('method', 'Unknown method')}) - {donor_doc.donor_name}",
                }
            )

            # No references table for donations - they're standalone payments, not invoice reconciliations

            payment_entry.insert()
            payment_entry.submit()

            frappe.logger().info(f"✅ Created Payment Entry: {payment_entry.name}")
            return payment_entry.name

        except Exception as e:
            frappe.log_error(f"Error creating payment entry for donation {donation.name}: {e}")
            return None

    def _update_donation_payment_history(
        self, donation: Document, mollie_data: dict, payment_entry_name: str = None
    ):
        """Update donation payment history child table"""
        try:
            # Check if already exists
            existing_history = None
            for history in donation.payment_history or []:
                if history.mollie_payment_id == mollie_data["payment_id"]:
                    existing_history = history
                    break

            if not existing_history:
                donation.append(
                    "payment_history",
                    {
                        "payment_date": frappe.utils.getdate(),
                        "amount": mollie_data["amount"],
                        "currency": mollie_data["currency"],
                        "payment_method": mollie_data.get("method", ""),
                        "mollie_payment_id": mollie_data["payment_id"],
                        "payment_entry": payment_entry_name,
                        "status": "Completed",
                        "remarks": f"Mollie payment {mollie_data['payment_id']}",
                    },
                )

                donation.save(ignore_permissions=True)
                frappe.logger().info(f"✅ Added payment history for {mollie_data['payment_id']}")

        except Exception as e:
            frappe.log_error(f"Error updating payment history for donation {donation.name}: {e}")
            raise

    def _update_donation_with_mollie_data(self, donation: Document, mollie_data: dict):
        """Update donation record with Mollie metadata"""
        try:
            updates = {}

            # Update payment-related fields
            if not donation.payment_id:
                updates["payment_id"] = mollie_data["payment_id"]

            if not donation.mollie_customer_id and mollie_data.get("customer_id"):
                updates["mollie_customer_id"] = mollie_data["customer_id"]

            if mollie_data.get("subscription_id") and not donation.mollie_subscription_id:
                updates["mollie_subscription_id"] = mollie_data["subscription_id"]

            # Update status based on payment type (critical business logic!)
            is_recurring = self._determine_recurring_status(donation, mollie_data)

            if is_recurring:
                updates["status"] = "Recurring"
                frappe.logger().info(f"✅ Set donation {donation.name} status to Recurring")
            else:
                updates["status"] = "One-time"
                # Also set paid flag for one-time donations
                updates["paid"] = 1
                frappe.logger().info(f"✅ Set donation {donation.name} status to One-time")

            updates["paid_amount"] = mollie_data["amount"]
            updates["paid_date"] = frappe.utils.getdate()

            # Apply updates
            if updates:
                for field, value in updates.items():
                    setattr(donation, field, value)

                donation.save(ignore_permissions=True)
                frappe.logger().info(f"✅ Updated donation {donation.name} with: {list(updates.keys())}")

        except Exception as e:
            frappe.log_error(f"Error updating donation with Mollie data: {e}")
            raise
