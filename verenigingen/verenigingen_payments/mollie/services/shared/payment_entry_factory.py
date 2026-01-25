"""
Payment Entry Factory

Centralized factory for creating Payment Entries for all Mollie payment types.
Part of the shared services layer used by all event handlers.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

from .cost_center_resolver import CostCenterResolver

if TYPE_CHECKING:
    from frappe import Document

    from ..payment_context_resolver import PaymentContext


# Field length limits for Payment Entry
PAYMENT_ENTRY_TITLE_MAX_LENGTH = 140
PAYMENT_ENTRY_REMARKS_MAX_LENGTH = 500


class MollieDataValidationError(Exception):
    """Raised when mollie_data is missing required fields or has invalid values."""

    pass


class PaymentEntryFactory:
    """
    Generic factory for creating Payment Entries for any payment type.

    This factory creates Payment Entries based on payment context without
    hardcoding specific payment type logic.
    """

    def __init__(self):
        self.logger = frappe.logger()
        self.cost_center_resolver = CostCenterResolver()

    def create_payment_entry(
        self,
        context: "PaymentContext",
        mollie_data: Dict[str, Any],
        customer: str = None,
        title: str = None,
    ) -> Optional["Document"]:
        """
        Create a generic Payment Entry for any payment type.

        Args:
            context: Payment context information
            mollie_data: Extracted Mollie payment data (must contain 'amount' and 'payment_id')
            customer: Customer for the payment entry (if None, will be resolved)
            title: Custom title for the payment entry (if None, will be generated)

        Returns:
            Payment Entry document or None if creation fails

        Note:
            Callers should perform idempotency checks before calling this method.
            This factory includes a defense-in-depth duplicate check but relies
            on callers for primary idempotency management.
        """
        pe = None  # Track PE for cleanup on submit failure

        try:
            # Validate mollie_data shape and extract required fields
            payment_id, amount = self._validate_and_extract_mollie_data(mollie_data)

            # Defense-in-depth: Check for duplicate Payment Entry by reference_no
            if self._payment_entry_exists(payment_id):
                self.logger.warning(
                    f"Payment Entry already exists for payment_id {payment_id} - "
                    "returning None (idempotent)"
                )
                return None

            # Resolve customer if not provided
            if not customer:
                customer = self._resolve_customer_for_context(context)
                if not customer:
                    self.logger.error(f"Could not resolve customer for context: {context}")
                    return None

            # Get company and accounts
            company = self._get_company()
            accounts = self._get_accounts(company, context.payment_type)

            if not accounts["receivable_account"] or not accounts["bank_account"]:
                self.logger.error(f"Missing required accounts for company {company}")
                return None

            # Validate Mode of Payment exists
            if not DocumentExistenceValidator.check_document_exists("Mode of Payment", "Mollie"):
                self.logger.error("Mollie Mode of Payment not configured")
                return None

            # Generate title if not provided (with sanitization)
            if not title:
                title = self._generate_payment_title(context, mollie_data, customer)
            title = self._sanitize_title(title)

            # Get appropriate cost center using shared resolver
            cost_center = self.cost_center_resolver.resolve_for_context(context, company)

            # Determine reference_date: prefer Mollie's paid_at, fallback to today
            reference_date = self._get_reference_date(mollie_data)

            # Generate and sanitize remarks
            remarks = self._sanitize_remarks(self._generate_remarks(context, mollie_data))

            # Create Payment Entry with Decimal amount
            pe = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer,
                    "paid_amount": amount,
                    "received_amount": amount,
                    "reference_no": payment_id,
                    "reference_date": reference_date,
                    "company": company,
                    "paid_from": accounts["receivable_account"],
                    "paid_to": accounts["bank_account"],
                    "cost_center": cost_center,
                    "title": title,
                    "remarks": remarks,
                }
            )

            # Insert and submit with proper error handling
            pe.insert()

            try:
                pe.submit()
            except Exception as submit_error:
                # Submit failed - clean up the inserted but unsubmitted PE
                self.logger.error(
                    f"Payment Entry {pe.name} insert succeeded but submit failed: {submit_error}. "
                    "Deleting orphaned document."
                )
                try:
                    frappe.delete_doc("Payment Entry", pe.name, force=True)
                    self.logger.info(f"Cleaned up orphaned Payment Entry {pe.name}")
                except Exception as cleanup_error:
                    self.logger.error(f"Failed to clean up orphaned Payment Entry {pe.name}: {cleanup_error}")
                    frappe.log_error(
                        f"Orphaned Payment Entry cleanup failed\n"
                        f"PE: {pe.name}\n"
                        f"Original error: {submit_error}\n"
                        f"Cleanup error: {cleanup_error}",
                        "Payment Entry Factory - Orphaned Document",
                    )
                raise submit_error

            self.logger.info(f"Created Payment Entry: {pe.name} for {context.payment_type}")
            return pe

        except MollieDataValidationError as e:
            self.logger.error(f"Invalid mollie_data for {context}: {e}")
            frappe.log_error(
                f"Payment Entry creation failed - invalid input data\n"
                f"Context: {context}\n"
                f"Error: {str(e)}",
                "Payment Entry Factory - Validation Error",
            )
            return None
        except Exception as e:
            self.logger.error(f"Failed to create Payment Entry for {context}: {e}")
            frappe.log_error(
                f"Payment Entry creation failed for {context}: {str(e)}", "Payment Entry Factory"
            )
            return None

    def _validate_and_extract_mollie_data(self, mollie_data: Dict[str, Any]) -> tuple:
        """
        Validate mollie_data shape and extract required fields.

        Args:
            mollie_data: Dictionary containing Mollie payment data

        Returns:
            Tuple of (payment_id: str, amount: Decimal)

        Raises:
            MollieDataValidationError: If required fields are missing or invalid
        """
        if not isinstance(mollie_data, dict):
            raise MollieDataValidationError(
                f"mollie_data must be a dictionary, got {type(mollie_data).__name__}"
            )

        # Validate payment_id
        payment_id = mollie_data.get("payment_id")
        if not payment_id:
            raise MollieDataValidationError("mollie_data missing required field: 'payment_id'")
        if not isinstance(payment_id, str):
            raise MollieDataValidationError(f"payment_id must be a string, got {type(payment_id).__name__}")

        # Validate and convert amount to Decimal
        raw_amount = mollie_data.get("amount")
        if raw_amount is None:
            raise MollieDataValidationError("mollie_data missing required field: 'amount'")

        try:
            # Convert to Decimal via string to avoid float precision issues
            amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception as e:
            raise MollieDataValidationError(f"Invalid amount value '{raw_amount}': {e}")

        if amount <= 0:
            raise MollieDataValidationError(f"Amount must be positive, got {amount}")

        return payment_id, amount

    def _payment_entry_exists(self, payment_id: str) -> bool:
        """
        Check if a Payment Entry already exists with this reference_no.

        Args:
            payment_id: The Mollie payment ID to check

        Returns:
            True if a Payment Entry exists with this reference_no
        """
        return bool(frappe.db.exists("Payment Entry", {"reference_no": payment_id, "docstatus": ["!=", 2]}))

    def _get_reference_date(self, mollie_data: Dict[str, Any]) -> "frappe.utils.datetime.date":
        """
        Get the reference date for the Payment Entry.

        Prefers Mollie's paid_at timestamp if available, otherwise uses today.

        Args:
            mollie_data: Dictionary containing Mollie payment data

        Returns:
            Date object for the Payment Entry reference_date
        """
        paid_at = mollie_data.get("paid_at")
        if paid_at:
            try:
                from dateutil import parser

                return parser.parse(paid_at).date()
            except Exception as e:
                self.logger.warning(f"Could not parse paid_at '{paid_at}': {e}. Using today's date.")

        return frappe.utils.getdate()

    def _sanitize_title(self, title: str) -> str:
        """
        Sanitize and truncate title to field length limit.

        Args:
            title: Raw title string

        Returns:
            Sanitized and truncated title
        """
        if not title:
            return "Payment"

        # Remove control characters and excessive whitespace
        title = " ".join(title.split())

        # Truncate to max length with ellipsis if needed
        if len(title) > PAYMENT_ENTRY_TITLE_MAX_LENGTH:
            return title[: PAYMENT_ENTRY_TITLE_MAX_LENGTH - 3] + "..."

        return title

    def _sanitize_remarks(self, remarks: str) -> str:
        """
        Sanitize and truncate remarks to field length limit.

        Args:
            remarks: Raw remarks string

        Returns:
            Sanitized and truncated remarks
        """
        if not remarks:
            return ""

        # Remove control characters and excessive whitespace
        remarks = " ".join(remarks.split())

        # Truncate to max length with ellipsis if needed
        if len(remarks) > PAYMENT_ENTRY_REMARKS_MAX_LENGTH:
            return remarks[: PAYMENT_ENTRY_REMARKS_MAX_LENGTH - 3] + "..."

        return remarks

    def _resolve_customer_for_context(self, context: "PaymentContext") -> Optional[str]:
        """Resolve customer based on payment context"""
        try:
            if context.payment_type == "donation":
                # Get customer from donation -> donor
                donation = frappe.get_doc("Donation", context.target_name)
                if hasattr(donation, "donor") and donation.donor:
                    donor = frappe.get_doc("Donor", donation.donor)
                    if hasattr(donor, "customer") and donor.customer:
                        return donor.customer
                    else:
                        # Create customer for donor if missing
                        return self._create_customer_for_donor(donor)

            elif context.payment_type == "membership":
                # Get customer from member
                member = frappe.get_doc("Member", context.target_name)
                if hasattr(member, "customer") and member.customer:
                    return member.customer
                else:
                    # Create customer for member if missing
                    return self._create_customer_for_member(member)

            return None

        except Exception as e:
            self.logger.error(f"Error resolving customer for context {context}: {e}")
            return None

    def _get_company(self) -> str:
        """
        Get the company for payment entries using centralized configuration service.

        Uses MollieConfigurationService for consistent company resolution with
        proper priority chain (Verenigingen Settings -> Global Defaults -> User defaults).
        """
        return get_mollie_config().get_default_company()

    def _get_accounts(self, company: str, payment_type: str) -> Dict[str, str]:
        """Get appropriate accounts based on payment type with fallback logging"""
        accounts = {"receivable_account": None, "bank_account": None}

        try:
            settings = frappe.get_single("Verenigingen Settings")

            # Get receivable account
            if payment_type == "donation":
                if settings.donation_receivable_account:
                    accounts["receivable_account"] = settings.donation_receivable_account
                else:
                    accounts["receivable_account"] = frappe.get_value(
                        "Company", company, "default_receivable_account"
                    )
                    if accounts["receivable_account"]:
                        self.logger.warning(
                            f"Using company default receivable account for donations "
                            f"(donation_receivable_account not configured in Verenigingen Settings)"
                        )
            else:
                # For memberships and other types, use default receivable account
                accounts["receivable_account"] = frappe.get_value(
                    "Company", company, "default_receivable_account"
                )

            # Get Mollie bank account - prefer settings, fallback to named account, then default
            if settings.mollie_bank_account:
                accounts["bank_account"] = settings.mollie_bank_account
            else:
                # First fallback: Look for account named "Mollie"
                accounts["bank_account"] = frappe.get_value(
                    "Account", {"company": company, "account_name": "Mollie"}, "name"
                )
                if accounts["bank_account"]:
                    self.logger.warning(
                        f"Using 'Mollie' named account as fallback "
                        f"(mollie_bank_account not configured in Verenigingen Settings)"
                    )
                else:
                    # Second fallback: Company default bank account
                    accounts["bank_account"] = frappe.get_value("Company", company, "default_bank_account")
                    if accounts["bank_account"]:
                        self.logger.warning(
                            f"Using company default bank account as fallback for Mollie payments "
                            f"(neither mollie_bank_account nor 'Mollie' account configured). "
                            f"This may cause accounting entries in unexpected accounts."
                        )

        except Exception as e:
            self.logger.error(f"Error getting accounts for company {company}: {e}")

        return accounts

    def _generate_payment_title(
        self, context: "PaymentContext", mollie_data: Dict[str, Any], customer: str
    ) -> str:
        """Generate appropriate title for the payment entry"""
        try:
            # Get customer name
            customer_doc = frappe.get_doc("Customer", customer)
            display_name = customer_doc.customer_name or "Unknown Customer"

            # Extract record reference from Mollie data
            record_reference = self._extract_record_reference(mollie_data, context)

            return f"{display_name} - {record_reference}"

        except Exception as e:
            self.logger.warning(f"Could not generate payment title: {e}")
            return f"Payment - {context.target_name}"

    def _extract_record_reference(self, mollie_data: Dict[str, Any], context: "PaymentContext") -> str:
        """Extract record reference for payment title"""
        # Try metadata first
        metadata = mollie_data.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("record_id"):
            return str(metadata["record_id"])[:50]  # Limit length

        # Try description JSON
        description = mollie_data.get("description")
        if description:
            try:
                import json

                desc_data = json.loads(description)
                if isinstance(desc_data, dict) and desc_data.get("record_id"):
                    return str(desc_data["record_id"])[:50]  # Limit length
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback to context target name
        return str(context.target_name)[:50]

    def _generate_remarks(self, context: "PaymentContext", mollie_data: Dict[str, Any]) -> str:
        """Generate remarks for the payment entry"""
        method = mollie_data.get("method", "Unknown method")
        payment_type = context.payment_type.title()

        return f"{payment_type} payment for {context.target_name} via Mollie ({method})"

    def _create_customer_for_donor(self, donor_doc) -> Optional[str]:
        """Create Customer for Donor (reusing existing logic)"""
        try:
            from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
                _create_customer_for_donor,
            )

            return _create_customer_for_donor(donor_doc)
        except Exception as e:
            self.logger.error(f"Failed to create customer for donor {donor_doc.name}: {e}")
            return None

    def _create_customer_for_member(self, member_doc) -> Optional[str]:
        """
        Create Customer for Member with race condition protection.

        Uses a processing lock to prevent duplicate customer creation when
        multiple workers process the same member concurrently.
        """
        member_name = member_doc.name
        lock_key = f"member_customer_creation:{member_name}"

        try:
            # Try to acquire a processing lock to prevent race conditions
            from verenigingen.api.sepa_duplicate_prevention import (
                acquire_processing_lock,
                release_processing_lock,
            )

            if not acquire_processing_lock("member_customer", member_name, timeout=30):
                # Another worker is creating the customer - wait and check if it exists
                self.logger.info(f"Another worker is creating customer for member {member_name}, waiting...")
                import time

                time.sleep(1)

                # Check if customer was created by the other worker
                member_doc.reload()
                if member_doc.customer:
                    self.logger.info(f"Customer {member_doc.customer} was created by another worker")
                    return member_doc.customer

                # Still no customer - try again with longer wait
                time.sleep(2)
                member_doc.reload()
                if member_doc.customer:
                    return member_doc.customer

                self.logger.warning(
                    f"Could not acquire lock and no customer created for member {member_name}"
                )
                return None

            try:
                # Double-check after acquiring lock (another worker may have just finished)
                member_doc.reload()
                if member_doc.customer:
                    self.logger.info(
                        f"Customer {member_doc.customer} already exists for member {member_name} "
                        "(created by concurrent worker)"
                    )
                    return member_doc.customer

                # Also check if a Customer already exists with this member linked
                existing_customer = frappe.db.get_value("Customer", {"custom_member": member_name}, "name")
                if existing_customer:
                    # Link it back to the member
                    member_doc.customer = existing_customer
                    member_doc.flags.ignore_permissions = True
                    member_doc.save()
                    self.logger.info(
                        f"Found existing customer {existing_customer} for member {member_name}, linked it"
                    )
                    return existing_customer

                # Get company
                company = self._get_company()

                # Customer group and territory setup
                customer_group = "Individual"
                territory = "Netherlands"

                # Validate customer group exists
                if not frappe.db.exists("Customer Group", customer_group):
                    fallback_group = frappe.get_value("Customer Group", {"is_group": 0}, "name")
                    customer_group = fallback_group or "All Customer Groups"

                # Validate territory exists
                if not frappe.db.exists("Territory", territory):
                    fallback_territory = frappe.get_value("Territory", {"is_group": 0}, "name")
                    territory = fallback_territory or "All Territories"

                # Create customer
                customer_doc = frappe.get_doc(
                    {
                        "doctype": "Customer",
                        "customer_name": member_doc.full_name or f"Member {member_doc.name}",
                        "customer_type": "Individual",
                        "customer_group": customer_group,
                        "territory": territory,
                        "company": company,
                        "custom_member": member_doc.name,
                        "email_id": getattr(member_doc, "email", None),
                    }
                )

                customer_doc.flags.ignore_permissions = True
                customer_doc.insert()

                # Link customer back to member
                member_doc.customer = customer_doc.name
                member_doc.flags.ignore_permissions = True
                member_doc.save()

                self.logger.info(f"Created customer {customer_doc.name} for member {member_doc.name}")
                return customer_doc.name

            finally:
                release_processing_lock("member_customer", member_name)

        except ImportError:
            # Fallback if sepa_duplicate_prevention not available
            self.logger.warning("sepa_duplicate_prevention not available, creating customer without lock")
            return self._create_customer_for_member_without_lock(member_doc)
        except Exception as e:
            self.logger.error(f"Failed to create customer for member {member_doc.name}: {e}")
            return None

    def _create_customer_for_member_without_lock(self, member_doc) -> Optional[str]:
        """
        Fallback customer creation without locking.

        Used when sepa_duplicate_prevention module is not available.
        """
        try:
            # Check if customer already exists
            existing_customer = frappe.db.get_value("Customer", {"custom_member": member_doc.name}, "name")
            if existing_customer:
                member_doc.customer = existing_customer
                member_doc.flags.ignore_permissions = True
                member_doc.save()
                return existing_customer

            # Get company
            company = self._get_company()

            # Customer group and territory setup
            customer_group = "Individual"
            territory = "Netherlands"

            if not frappe.db.exists("Customer Group", customer_group):
                fallback_group = frappe.get_value("Customer Group", {"is_group": 0}, "name")
                customer_group = fallback_group or "All Customer Groups"

            if not frappe.db.exists("Territory", territory):
                fallback_territory = frappe.get_value("Territory", {"is_group": 0}, "name")
                territory = fallback_territory or "All Territories"

            customer_doc = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": member_doc.full_name or f"Member {member_doc.name}",
                    "customer_type": "Individual",
                    "customer_group": customer_group,
                    "territory": territory,
                    "company": company,
                    "custom_member": member_doc.name,
                    "email_id": getattr(member_doc, "email", None),
                }
            )

            customer_doc.flags.ignore_permissions = True
            customer_doc.insert()

            member_doc.customer = customer_doc.name
            member_doc.flags.ignore_permissions = True
            member_doc.save()

            self.logger.info(f"Created customer {customer_doc.name} for member {member_doc.name}")
            return customer_doc.name

        except Exception as e:
            self.logger.error(f"Failed to create customer for member {member_doc.name}: {e}")
            return None
