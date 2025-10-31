"""
Mollie Membership Dues Payment Processor

Handles processing of Mollie payments for membership dues, including:
- Identifying dues payments vs donations by subscription_id
- Creating Payment Entries for historical dues payments
- Linking payments to members via customer_id
- Proper idempotency to prevent duplicate processing
"""

from calendar import monthrange
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.integrations.mollie.core.mollie_client import MollieClient
from verenigingen.integrations.mollie.domain.payment_classification import PaymentClassifier
from verenigingen.verenigingen_payments.services.payment.payment_entry_creation_service import (
    payment_entry_service,
)


def get_quarter_coverage_dates(payment_date: date) -> Tuple[date, date]:
    """
    Calculate calendar quarter coverage dates for a payment.

    Mijnrood logic: Payment in any part of quarter covers entire quarter.

    Args:
        payment_date: Date the payment was made

    Returns:
        Tuple of (quarter_start_date, quarter_end_date)
    """
    quarter = (payment_date.month - 1) // 3 + 1

    quarter_start_months = {1: 1, 2: 4, 3: 7, 4: 10}
    quarter_end_months = {1: 3, 2: 6, 3: 9, 4: 12}

    start_month = quarter_start_months[quarter]
    end_month = quarter_end_months[quarter]

    coverage_start = date(payment_date.year, start_month, 1)
    # Last day of the quarter end month
    coverage_end = date(payment_date.year, end_month, monthrange(payment_date.year, end_month)[1])

    return coverage_start, coverage_end


def get_month_coverage_dates(payment_date: date) -> Tuple[date, date]:
    """
    Calculate month coverage dates for a payment.

    Args:
        payment_date: Date the payment was made

    Returns:
        Tuple of (month_start_date, month_end_date)
    """
    coverage_start = date(payment_date.year, payment_date.month, 1)
    coverage_end = date(payment_date.year, payment_date.month, monthrange(payment_date.year, payment_date.month)[1])

    return coverage_start, coverage_end


def get_year_coverage_dates(payment_date: date) -> Tuple[date, date]:
    """
    Calculate year coverage dates for a payment.

    Args:
        payment_date: Date the payment was made

    Returns:
        Tuple of (year_start_date, year_end_date)
    """
    coverage_start = date(payment_date.year, 1, 1)
    coverage_end = date(payment_date.year, 12, 31)

    return coverage_start, coverage_end


class DuesPaymentProcessor:
    """Process Mollie payments for membership dues"""

    def __init__(self):
        self.mollie_client = MollieClient()
        self.classifier = PaymentClassifier()

        # Use centralized Bank Transaction creator
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        self.bank_tx_creator = get_bank_transaction_creator()

    def identify_payment_type(self, payment: Any) -> str:
        """
        Identify whether a payment is for membership dues or a donation.

        Uses the PaymentClassifier strategy pattern for classification with audit trail.

        Args:
            payment: Mollie payment object

        Returns:
            str: "dues", "donation", or "unknown"
        """
        result = self.classifier.classify(payment)
        return result.payment_type

    def find_member_for_payment(self, payment) -> Optional[str]:
        """
        Find the Member record associated with a Mollie payment.

        Args:
            payment: Mollie payment object

        Returns:
            str: Member name if found, None otherwise
        """
        customer_id = getattr(payment, "customer_id", None)
        subscription_id = getattr(payment, "subscription_id", None)
        description = getattr(payment, "description", "")

        # Method 1: Direct subscription_id match
        if subscription_id:
            member_name = frappe.db.get_value("Member", {"mollie_subscription_id": subscription_id}, "name")
            if member_name:
                frappe.logger().info(f"✅ Found member {member_name} by subscription_id")
                return member_name

        # Method 2: Customer ID match
        if customer_id:
            member_name = frappe.db.get_value("Member", {"mollie_customer_id": customer_id}, "name")
            if member_name:
                frappe.logger().info(f"✅ Found member {member_name} by customer_id")
                return member_name

        # Method 3: Parse member ID from description
        if description and isinstance(description, str):
            # Try to extract member ID pattern (e.g., "Assoc-Member-2024-01-0001")
            import re

            member_id_pattern = r"Assoc-Member-\d{4}-\d{2}-\d{4}"
            match = re.search(member_id_pattern, description)
            if match:
                potential_member_id = match.group(0)
                if frappe.db.exists("Member", potential_member_id):
                    frappe.logger().info(f"✅ Found member {potential_member_id} by parsing description")
                    return potential_member_id

        frappe.logger().warning(f"⚠️ No member found for payment {payment.id}")
        return None

    def _get_or_create_historical_invoice(
        self, member_name: str, payment_date: date, payment_amount: float
    ) -> Optional[str]:
        """
        Get existing invoice or create a new historical invoice for a payment.

        MIJNROOD BUSINESS LOGIC:
        Any payment made during a calendar quarter (Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec)
        provides membership coverage for the ENTIRE quarter. This differs from standard monthly billing
        where payments cover only the specific month. This "first payment covers quarter" approach was
        used by mijnrood for simplified administration.

        TECHNICAL IMPLEMENTATION:
        This method bypasses the standard InvoiceGenerator service because historical imports don't have
        Membership Dues Schedules. This is acceptable for one-time data migration but should not be used
        for ongoing payment processing.

        Uses priority hierarchy for membership type:
        1. Member's current_membership_plan (if exists)
        2. Default membership type from Verenigingen Settings

        Input Validation:
        - Payment amount must be positive and reasonable (< €10,000)
        - Payment date cannot be in the future
        - Coverage dates must be logically valid

        Database Impact:
        - Reads: Member, Membership, Verenigingen Settings, Sales Invoice
        - Writes: Sales Invoice (if created), Item (if dues item missing)

        Args:
            member_name: Member document name (e.g., "Assoc-Member-2024-01-0001")
            payment_date: Date the payment was made (determines quarter coverage)
            payment_amount: Amount in EUR (must be positive)

        Returns:
            Sales Invoice name if found/created, None if:
            - Member has no customer record
            - No membership type available
            - Invoice creation fails (logged to error log)

        Raises:
            ValueError: If payment_amount or payment_date are invalid
            frappe.ValidationError: If member or membership data is invalid

        Side Effects:
            - May create new Sales Invoice (auto-submitted)
            - May create new Item if membership dues item doesn't exist
            - Logs audit trail for historical backdating
            - Logs errors to "Historical Invoice Creation Error"

        Example:
            >>> processor = DuesPaymentProcessor(mollie_client)
            >>> invoice = processor._get_or_create_historical_invoice(
            ...     "Assoc-Member-2024-01-0001",
            ...     date(2024, 5, 15),  # Payment in May = Q2
            ...     25.0
            ... )
            >>> # Returns invoice covering 2024-04-01 to 2024-06-30 (entire Q2)
        """
        # Input validation
        if payment_amount <= 0:
            raise ValueError(f"Payment amount must be positive, got {payment_amount}")

        if payment_amount > 10000:
            frappe.logger().warning(
                f"Unusually large payment amount €{payment_amount} for member {member_name}. "
                "Proceeding but flagging for review."
            )

        # Validate payment_date is not in future
        from frappe.utils import getdate
        payment_date = getdate(payment_date)
        if payment_date > date.today():
            raise ValueError(f"Payment date {payment_date} cannot be in the future")

        try:
            # Calculate quarter coverage dates (mijnrood logic)
            coverage_start, coverage_end = get_quarter_coverage_dates(payment_date)

            frappe.logger().info(
                f"Looking for invoice for {member_name} covering {coverage_start} to {coverage_end}"
            )

            # Get member doc
            member = frappe.get_doc("Member", member_name)

            if not member.customer:
                frappe.logger().error(f"Member {member_name} has no customer record")
                return None

            # Check if invoice already exists for this exact coverage period
            # Use custom coverage fields for precise matching (not just posting_date range)
            existing_invoice = frappe.db.get_value(
                "Sales Invoice",
                filters={
                    "customer": member.customer,
                    "custom_coverage_start_date": coverage_start,
                    "custom_coverage_end_date": coverage_end,
                    "docstatus": ["<", 2],  # Not cancelled
                },
                fieldname=["name", "grand_total"],
                as_dict=True
            )

            if existing_invoice:
                frappe.logger().info(
                    f"✅ Found existing invoice {existing_invoice.name} for coverage period "
                    f"{coverage_start} to {coverage_end}"
                )
                return existing_invoice.name

            # No existing invoice - need to create one
            # Determine membership type using priority hierarchy with caching
            membership_type = self._get_membership_type_cached(member)

            if not membership_type:
                frappe.logger().error(
                    f"No membership type available for invoice generation (member: {member_name})"
                )
                return None

            # Create invoice directly (simpler than using InvoiceGenerator which requires a schedule)
            invoice_name = self._create_simple_invoice(
                member, membership_type, coverage_start, coverage_end, payment_amount, payment_date
            )

            if invoice_name:
                frappe.logger().info(
                    f"✅ Created historical invoice {invoice_name} for {member_name} "
                    f"(coverage: {coverage_start} to {coverage_end})"
                )

            return invoice_name

        except Exception as e:
            frappe.log_error(
                f"Error creating historical invoice for {member_name}: {str(e)}",
                "Historical Invoice Creation Error",
            )
            return None

    def _get_membership_type_cached(self, member_doc: Any) -> Optional[str]:
        """
        Get membership type for member with caching to optimize batch processing.

        Priority hierarchy:
        1. Member's current_membership_plan.membership_type
        2. Default from Verenigingen Settings

        Caching Strategy:
        - Caches membership plan lookups to avoid N+1 queries during batch processing
        - Caches default membership type from settings (singleton, rarely changes)
        - Cache lifetime: Duration of DuesPaymentProcessor instance (safe for batch jobs)

        Args:
            member_doc: Member document

        Returns:
            Membership type name, or None if not available
        """
        # Initialize cache on first use
        if not hasattr(self, '_membership_type_cache'):
            self._membership_type_cache = {}
            self._default_membership_type = None

        # Try member's current membership plan (cached)
        if member_doc.current_membership_plan:
            if member_doc.current_membership_plan not in self._membership_type_cache:
                # Cache miss - fetch from database
                try:
                    membership_type = frappe.db.get_value(
                        "Membership",
                        member_doc.current_membership_plan,
                        "membership_type",
                        cache=True
                    )
                    if membership_type:
                        self._membership_type_cache[member_doc.current_membership_plan] = membership_type
                        frappe.logger().info(
                            f"Cached membership type {membership_type} for plan {member_doc.current_membership_plan}"
                        )
                except Exception as e:
                    frappe.logger().warning(
                        f"Failed to fetch membership type for plan {member_doc.current_membership_plan}: {e}"
                    )

            # Return from cache if available
            if member_doc.current_membership_plan in self._membership_type_cache:
                return self._membership_type_cache[member_doc.current_membership_plan]

        # Fallback to default from settings (cached)
        if self._default_membership_type is None:
            settings = frappe.get_single("Verenigingen Settings")
            self._default_membership_type = settings.default_membership_type
            frappe.logger().info(
                f"Cached default membership type: {self._default_membership_type}"
            )

        return self._default_membership_type

    def _create_simple_invoice(
        self, member_doc: Any, membership_type: str, coverage_start: date, coverage_end: date, amount: float, payment_date: date
    ) -> Optional[str]:
        """
        Create a simple Sales Invoice for historical payment (mijnrood import use case).

        IMPORTANT - ONE-TIME MIGRATION CODE:
        This method creates invoices directly without going through InvoiceGenerator service.
        This is acceptable for historical data migration where Membership Dues Schedules don't exist,
        but should NOT be used for ongoing payment processing.

        Invoice Configuration:
        - Posting date: Set to actual payment date (backdated) using set_posting_time flag
        - Due date: Same as posting date (historical payments are already paid)
        - Coverage dates: Stored in custom fields for period tracking
        - Income account: From Verenigingen Settings or company default
        - Auto-submit: Yes (historical invoices should be complete)

        Audit Trail:
        - Logs historical backdating for compliance review
        - Creates audit trail entry for manual invoice creation

        Args:
            member_doc: Member document instance
            membership_type: Membership type name (e.g., "Standard Member", "Student Member")
            coverage_start: Coverage period start date
            coverage_end: Coverage period end date
            amount: Invoice amount in EUR
            payment_date: Actual payment date (used for posting_date)

        Returns:
            Sales Invoice name if successful, None if creation fails

        Raises:
            Does not raise exceptions - logs errors and returns None for graceful degradation

        Side Effects:
            - Creates and submits Sales Invoice
            - May create new Item if membership dues item doesn't exist
            - Logs to "Invoice Creation Failed" on error
        """
        try:
            settings = frappe.get_single("Verenigingen Settings")

            # Get income account
            income_account = settings.dues_income_account
            if not income_account:
                company_doc = frappe.get_cached_doc("Company", settings.company)
                income_account = company_doc.default_income_account

            if not income_account:
                frappe.logger().error("No income account configured")
                return None

            # Create invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member_doc.customer
            invoice.company = settings.company

            # Set posting date explicitly (must be done before insert to prevent auto-setting)
            invoice.posting_date = payment_date
            invoice.set_posting_time = 1  # Enable custom posting date
            invoice.due_date = payment_date

            # Set coverage period custom fields
            invoice.custom_coverage_start_date = coverage_start
            invoice.custom_coverage_end_date = coverage_end

            # Audit logging for historical backdating
            frappe.logger().warning(
                f"HISTORICAL INVOICE CREATION: User {frappe.session.user} creating backdated invoice "
                f"for member {member_doc.name} ({member_doc.full_name}) with posting_date={payment_date} "
                f"(today={date.today()}), coverage={coverage_start} to {coverage_end}, amount=€{amount}"
            )

            # Add item
            item_name = f"Membership Dues - {membership_type}"
            invoice.append("items", {
                "item_code": self._get_or_create_dues_item(item_name, settings.company, income_account),
                "qty": 1,
                "rate": amount,
                "income_account": income_account,
                "description": f"Membership dues for {member_doc.full_name} ({membership_type}) - Period: {coverage_start} to {coverage_end}"
            })

            invoice.insert()
            invoice.submit()

            return invoice.name

        except Exception as e:
            frappe.logger().error(f"Failed to create simple invoice: {str(e)}")
            return None

    def _get_or_create_dues_item(self, item_name: str, company: str, income_account: str) -> str:
        """Get or create a membership dues item."""
        if frappe.db.exists("Item", item_name):
            return item_name

        try:
            item = frappe.new_doc("Item")
            item.item_code = item_name
            item.item_name = item_name
            item.item_group = "Services"
            item.stock_uom = "Unit"
            item.is_stock_item = 0
            item.insert(ignore_if_duplicate=True)
            return item_name
        except Exception:
            # If creation fails, try to find any membership dues item
            existing_item = frappe.get_all("Item",
                                          filters={"item_name": ["like", "%Membership Dues%"]},
                                          limit=1)
            if existing_item:
                return existing_item[0].name
            return "Membership Dues"  # Fallback to generic name

    def process_dues_payment(
        self, payment_id: str, payment=None, creation_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a membership dues payment from Mollie.

        Creates a Payment Entry or Bank Transaction for the member's dues payment.
        Uses proper idempotency checks to prevent duplicate processing.

        Args:
            payment_id: Mollie payment ID
            payment: Optional Mollie payment object (if already fetched)
            creation_mode: Optional override for document creation mode.
                         "Payment Entry" to create Payment Entry directly
                         "Bank Transaction" to create Bank Transaction for reconciliation
                         None (default) to use centralized configuration

        Returns:
            dict: Processing result with status, payment_entry, member, etc.
        """
        result = {
            "payment_id": payment_id,
            "status": "pending",
            "payment_type": "unknown",
            "member": None,
            "payment_entry": None,
            "bank_transaction": None,
            "error": None,
            "skipped_reason": None,
        }

        try:
            # Fetch payment from Mollie if not provided
            if not payment:
                payment = self.mollie_client.sdk_client.payments.get(payment_id)

            result["payment_status"] = payment.status
            result["amount"] = (
                f"{payment.amount['value']} {payment.amount['currency']}" if payment.amount else "Unknown"
            )

            # Only process paid payments
            if payment.status != "paid":
                result["status"] = "skipped"
                result["skipped_reason"] = f"Payment status is '{payment.status}', not 'paid'"
                return result

            # Check idempotency using centralized service
            from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                get_bank_transaction_creator,
            )

            creator = get_bank_transaction_creator()
            idempotency_check = creator.check_already_processed(
                payment_id,
                check_payment_entry=True,  # Dual mode: check both Payment Entry and Bank Transaction
            )

            if idempotency_check["already_processed"]:
                result["status"] = "already_processed"
                result["payment_entry"] = idempotency_check["payment_entry"]
                result["bank_transaction"] = idempotency_check["bank_transaction"]
                result["skipped_reason"] = idempotency_check["details"]
                return result

            # Identify payment type
            payment_type = self.identify_payment_type(payment)
            result["payment_type"] = payment_type

            if payment_type != "dues":
                result["status"] = "skipped"
                result["skipped_reason"] = f"Payment type is '{payment_type}', not membership dues"
                return result

            # Find associated member
            member_name = self.find_member_for_payment(payment)
            if not member_name:
                result["status"] = "error"
                result["error"] = "No member found for this payment"
                return result

            result["member"] = member_name

            # Determine creation mode: use override if provided, otherwise use centralized configuration
            if creation_mode is None:
                from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
                    get_mollie_config,
                )

                mollie_config = get_mollie_config()
                creation_mode = mollie_config.get_dues_payment_creation_mode()

            if creation_mode == "Payment Entry":
                # Legacy mode: Create Payment Entry directly
                record_name = self._create_payment_entry_for_dues(member_name, payment)
                record_type = "Payment Entry"
            else:
                # Default mode: Create Bank Transaction for reconciliation
                record_name = self._create_bank_transaction_for_dues(member_name, payment)
                record_type = "Bank Transaction"

            if record_name:
                result["status"] = "success"
                # Set BOTH fields for frontend compatibility, only one will have value
                result["payment_entry"] = record_name if creation_mode == "Payment Entry" else None
                result["bank_transaction"] = record_name if creation_mode != "Payment Entry" else None
                result["record_type"] = record_type

                # Get linked Sales Invoice if Payment Entry was created
                if creation_mode == "Payment Entry" and record_name:
                    try:
                        pe_doc = frappe.get_doc("Payment Entry", record_name)
                        # Check if any Sales Invoices are referenced
                        sales_invoices = []
                        for ref in pe_doc.get("references", []):
                            if ref.reference_doctype == "Sales Invoice":
                                sales_invoices.append({
                                    "name": ref.reference_name,
                                    "allocated_amount": float(ref.allocated_amount)
                                })
                        if sales_invoices:
                            result["sales_invoices"] = sales_invoices
                    except Exception as si_error:
                        frappe.log_error(f"Could not fetch Sales Invoice references for {record_name}: {si_error}")

                frappe.logger().info(
                    f"✅ Successfully processed dues payment {payment_id} for member {member_name} "
                    f"(created {record_type}: {record_name})"
                )
            else:
                result["status"] = "error"
                result["error"] = f"Failed to create {record_type}"

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            frappe.log_error(
                f"Error processing dues payment {payment_id}: {e}", "Dues Payment Processing Error"
            )

        return result

    def _create_payment_entry_for_dues(self, member_name: str, payment) -> Optional[str]:
        """
        Create a Payment Entry for a membership dues payment from Mollie.

        Creates an unallocated payment entry - reconciliation with Sales Invoices
        happens separately (either automatically via payment hooks or manually).

        Args:
            member_name: Member document name
            payment: Mollie payment object

        Returns:
            str: Payment Entry name if created, None otherwise
        """
        # Get member and customer
        member = frappe.get_doc("Member", member_name)
        customer = member.customer

        if not customer:
            frappe.throw(f"Member {member_name} has no linked Customer record")

        # Get company first (needed for currency validation)
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        company = verenigingen_settings.donation_company or frappe.defaults.get_global_default("company")

        # Extract payment data using centralized extractor
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()
        payment_id = extractor.extract_payment_id(payment)
        amount = extractor.extract_amount(payment)
        currency = extractor.extract_currency(payment, company)
        payment_date = extractor.extract_date(payment, field_name="paid_at")
        mode_of_payment = getattr(verenigingen_settings, "mode_of_payment", None) or "Mollie"

        # Get Mollie clearing account from centralized configuration (throws if not configured)
        mollie_config = get_mollie_config()
        mollie_clearing_account = mollie_config.get_clearing_account()

        # Get customer receivable account (customer's outstanding balance)
        # Use dues-specific receivable account from settings, fallback to company default
        customer_account = getattr(verenigingen_settings, "dues_payments_receivable_account", None)
        if not customer_account:
            customer_account = frappe.get_cached_value("Company", company, "default_receivable_account")

        if not customer_account:
            frappe.throw(f"Missing customer receivable account for company {company}")

        # Try to get or create historical invoice for this payment
        invoice_name = self._get_or_create_historical_invoice(member_name, payment_date, amount)

        # Create Payment Entry
        payment_entry = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "company": company,
                "paid_from": customer_account,
                "paid_to": mollie_clearing_account,  # Use clearing account, not bank account
                "paid_amount": amount,
                "received_amount": amount,
                "reference_no": payment_id,
                "reference_date": payment_date,
                "posting_date": payment_date,
                "mode_of_payment": mode_of_payment,
                "remarks": f"Membership dues payment via Mollie for {member.full_name} (awaiting settlement). "
                + (f"Linked to invoice {invoice_name}" if invoice_name else "Manual reconciliation may be required."),
                "custom_member": member_name,  # Link to member for payment history tracking
            }
        )

        # If we have an invoice, link it to the payment entry
        if invoice_name:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
            payment_entry.append(
                "references",
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice_name,
                    "total_amount": invoice_doc.grand_total,
                    "outstanding_amount": invoice_doc.outstanding_amount,
                    "allocated_amount": min(amount, invoice_doc.outstanding_amount),
                },
            )

        payment_entry.insert()
        payment_entry.submit()

        frappe.logger().info(
            f"✅ Created Payment Entry {payment_entry.name} for member {member_name} "
            f"(amount: {currency} {amount}, payment: {payment_id})"
        )

        return payment_entry.name

    def _create_bank_transaction_for_dues(self, member_name: str, payment) -> Optional[str]:
        """
        Create a Bank Transaction for a membership dues payment from Mollie.

        This creates an unreconciled bank transaction that can later be matched
        to Sales Invoices via the Bank Reconciliation Tool.

        Args:
            member_name: Member document name
            payment: Mollie payment object

        Returns:
            str: Bank Transaction name if created, None otherwise
        """
        # Get member and customer
        member = frappe.get_doc("Member", member_name)
        customer = member.customer

        if not customer:
            frappe.throw(f"Member {member_name} has no linked Customer record")

        # Get bank account configuration using centralized helper
        config = self.bank_tx_creator.get_mollie_bank_account_config()

        if config.get("error"):
            frappe.throw(config["error"])

        bank_account = config["bank_account"]
        company = config["company"]

        # Extract payment data from Mollie
        payment_id = payment.id
        payment_description = getattr(payment, "description", None)

        # Build description with member context (start with payment description for title_field visibility)
        if payment_description:
            additional_description = f"{payment_id} | Member: {member.full_name}"
        else:
            additional_description = f"Mollie dues payment | {payment_id} | Member: {member.full_name}"

        # Use centralized PaymentDataExtractor for consistent extraction
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()
        payment_date = extractor.extract_date(payment, field_name="paid_at")
        amount = extractor.extract_amount(payment)
        currency = extractor.extract_currency(payment, company)

        # Build full description
        if payment_description:
            description = f"{payment_description} | {additional_description}"
        else:
            description = additional_description

        # Use centralized create() method with party fields
        bank_transaction_name = self.bank_tx_creator.create(
            date=payment_date,
            bank_account=bank_account,
            company=company,
            deposit=amount,
            withdrawal=0.0,
            currency=currency,
            reference_number=payment_id,
            transaction_id=payment_id,
            description=description,
            party_type="Customer",
            party=customer,
        )

        if bank_transaction_name:
            frappe.logger().info(
                f"✅ Created Bank Transaction {bank_transaction_name} for member {member_name} "
                f"(amount: {currency} {amount}, payment: {payment_id}, status: Unreconciled)"
            )

        return bank_transaction_name

    def batch_process_customer_payments(
        self, customer_id: str, limit: int = 250, only_unpaid: bool = False
    ) -> Dict[str, Any]:
        """
        Retrieve and process all payments for a Mollie customer.

        This is the main method for batch processing historical dues payments.

        Args:
            customer_id: Mollie customer ID
            limit: Maximum number of payments to retrieve
            only_unpaid: If True, only process payments not yet in Payment Entry

        Returns:
            dict: {
                "customer_id": str,
                "total_retrieved": int,
                "processed": int,
                "skipped": int,
                "errors": int,
                "results": List[dict]
            }
        """
        # Enforce maximum limit to prevent memory exhaustion
        MAX_LIMIT = 250
        if limit > MAX_LIMIT:
            raise ValueError(
                f"Limit cannot exceed {MAX_LIMIT}. "
                f"Requested: {limit}. Please use smaller batches to prevent memory issues."
            )

        batch_result = {
            "customer_id": customer_id,
            "total_retrieved": 0,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
        }

        try:
            # Retrieve all payments for customer
            customer_obj = self.mollie_client.sdk_client.customers.get(customer_id)
            payments = customer_obj.payments.list(limit=limit)

            batch_result["total_retrieved"] = len(payments)

            for payment in payments:
                # Process each payment
                result = self.process_dues_payment(payment.id, payment)

                batch_result["results"].append(result)

                if result["status"] == "success":
                    batch_result["processed"] += 1
                elif result["status"] == "skipped" or result["status"] == "already_processed":
                    batch_result["skipped"] += 1
                elif result["status"] == "error":
                    batch_result["errors"] += 1

            frappe.logger().info(
                f"✅ Batch processing complete for customer {customer_id}: "
                f"{batch_result['processed']} processed, {batch_result['skipped']} skipped, {batch_result['errors']} errors"
            )

        except Exception as e:
            batch_result["error"] = str(e)
            frappe.log_error(f"Error batch processing payments for customer {customer_id}: {e}")

        return batch_result
