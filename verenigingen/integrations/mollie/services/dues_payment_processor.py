"""
Mollie Membership Dues Payment Processor

Handles processing of Mollie payments for membership dues, including:
- Identifying dues payments vs donations by subscription_id
- Creating Payment Entries for historical dues payments
- Linking payments to members via customer_id
- Proper idempotency to prevent duplicate processing
"""

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.integrations.mollie.core.client import MollieClient
from verenigingen.integrations.mollie.domain.payment_classification import PaymentClassifier
from verenigingen.utils.bank_utils import get_or_create_unknown_bank
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
    coverage_end = date(
        payment_date.year, payment_date.month, monthrange(payment_date.year, payment_date.month)[1]
    )

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
                frappe.logger().info(f"[Mollie] Found member {member_name} by subscription_id")
                return member_name

        # Method 2: Customer ID match
        if customer_id:
            member_name = frappe.db.get_value("Member", {"mollie_customer_id": customer_id}, "name")
            if member_name:
                frappe.logger().info(f"[Mollie] Found member {member_name} by customer_id")
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
                    frappe.logger().info(
                        f"[Mollie] Found member {potential_member_id} by parsing description"
                    )
                    return potential_member_id

        frappe.logger().warning(f"[Mollie] No member found for payment {payment.id}")
        return None

    def _extract_and_save_consumer_bank_data(self, member_name: str, payment) -> None:
        """
        Extract consumer bank account data from Mollie payment and save to Member/Customer.

        This enables future payment matching by IBAN. Data is extracted from Mollie's
        payment.details for iDEAL, bank transfer, and direct debit payments.

        Args:
            member_name: Member document name
            payment: Mollie payment object with details
        """
        try:
            # Extract payment details
            details = getattr(payment, "details", None)
            if not details:
                return

            # Handle both dict and object-style access
            if hasattr(details, "get"):
                consumer_name = details.get("consumerName")
                consumer_account = details.get("consumerAccount")
            else:
                consumer_name = getattr(details, "consumerName", None) or getattr(
                    details, "consumer_name", None
                )
                consumer_account = getattr(details, "consumerAccount", None) or getattr(
                    details, "consumer_account", None
                )

            if not consumer_account:
                return

            # Validate IBAN format
            from verenigingen.integrations.mollie.utils.validators import validate_iban

            iban_result = validate_iban(consumer_account)
            if not iban_result.get("valid"):
                frappe.logger().debug(
                    f"Consumer account {consumer_account} is not a valid IBAN, skipping bank data save"
                )
                return

            # Clean IBAN
            clean_iban = consumer_account.replace(" ", "").upper()

            # Get Member document
            member = frappe.get_doc("Member", member_name)

            # Save IBAN to Member if not already set
            if not member.iban:
                member.iban = clean_iban
                member.save(ignore_permissions=True)
                frappe.logger().info(
                    f"[Mollie] Saved IBAN {clean_iban} to Member {member_name} from Mollie payment"
                )

            # Create Bank Account link for Customer (enables future MT940 matching)
            if member.customer:
                self._ensure_customer_bank_account(member.customer, clean_iban, consumer_name)

        except Exception as e:
            # Fail loudly - bank data integrity is important for future matching
            frappe.log_error(
                title="Mollie Bank Data Save Failed", message=f"Member: {member_name}, Error: {str(e)}"
            )
            raise

    def _ensure_customer_bank_account(
        self, customer: str, iban: str, account_holder_name: str = None
    ) -> None:
        """
        Ensure a Bank Account record exists linking this IBAN to the Customer.

        Args:
            customer: Customer document name
            iban: IBAN to link
            account_holder_name: Optional account holder name from payment
        """
        try:
            # Check if Bank Account already exists for this IBAN
            existing = frappe.db.exists("Bank Account", {"iban": iban})
            if existing:
                # Check if it's linked to the right customer
                existing_party = frappe.db.get_value(
                    "Bank Account", existing, ["party_type", "party"], as_dict=True
                )
                if existing_party and existing_party.get("party") == customer:
                    return  # Already correctly linked

                # Exists but linked to different party - log and skip
                frappe.logger().debug(
                    f"Bank Account for IBAN {iban} exists but linked to {existing_party}, not updating"
                )
                return

            # Create Bank Account linking IBAN to Customer
            # Use migration context for proper permission handling
            from verenigingen.e_boekhouden.utils.security_helper import migration_context

            with migration_context("party_creation"):
                bank_account = frappe.new_doc("Bank Account")
                bank_account.account_name = f"{customer} - {iban[-4:]}"
                bank_account.bank = get_or_create_unknown_bank()
                bank_account.iban = iban
                bank_account.party_type = "Customer"
                bank_account.party = customer
                bank_account.is_default = 0
                bank_account.insert()

            frappe.logger().info(f"[Mollie] Created Bank Account link: IBAN {iban} -> Customer {customer}")

        except Exception as e:
            # Fail loudly - bank account linking is important for payment matching
            frappe.log_error(
                title="Bank Account Creation Failed",
                message=f"Customer: {customer}, IBAN: {iban}, Error: {str(e)}",
            )
            raise

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

            # Check for overlapping coverage (not just exact match)
            # This prevents creating invoices that would overlap with existing coverage
            from verenigingen.services.billing.coverage_overlap_detector import check_coverage_overlap

            overlap_result = check_coverage_overlap(
                customer=member.customer,
                proposed_start=coverage_start,
                proposed_end=coverage_end,
                exclude_cancelled=True,
            )

            if overlap_result.has_overlap:
                if overlap_result.exact_match:
                    # Exact match - return the existing invoice
                    frappe.logger().info(
                        f"[Mollie] Found existing invoice {overlap_result.exact_match} for coverage period "
                        f"{coverage_start} to {coverage_end}"
                    )
                    return overlap_result.exact_match
                else:
                    # Overlapping but not exact - cannot safely create invoice
                    overlapping_names = [inv["name"] for inv in overlap_result.overlapping_invoices]
                    frappe.logger().warning(
                        f"[Mollie] Coverage overlap detected for member {member_name}: "
                        f"proposed {coverage_start} to {coverage_end} overlaps with "
                        f"existing invoice(s): {', '.join(overlapping_names)}. "
                        f"Skipping invoice creation - manual review required."
                    )
                    return None  # Signal to caller that invoice wasn't created due to overlap

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
                    f"[Mollie] Created historical invoice {invoice_name} for {member_name} "
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
        if not hasattr(self, "_membership_type_cache"):
            self._membership_type_cache = {}
            self._default_membership_type = None

        # Try member's current membership plan (cached)
        if member_doc.current_membership_plan:
            if member_doc.current_membership_plan not in self._membership_type_cache:
                # Cache miss - fetch from database
                try:
                    membership_type = frappe.db.get_value(
                        "Membership", member_doc.current_membership_plan, "membership_type", cache=True
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
            frappe.logger().info(f"Cached default membership type: {self._default_membership_type}")

        return self._default_membership_type

    def _create_simple_invoice(
        self,
        member_doc: Any,
        membership_type: str,
        coverage_start: date,
        coverage_end: date,
        amount: float,
        payment_date: date,
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
        import time

        from verenigingen.services.billing.coverage_overlap_detector import check_coverage_overlap

        # Check for overlapping coverage (not just exact match) - idempotency with proper overlap detection
        overlap_result = check_coverage_overlap(
            customer=member_doc.customer,
            proposed_start=coverage_start,
            proposed_end=coverage_end,
            exclude_cancelled=True,
        )

        if overlap_result.has_overlap:
            if overlap_result.exact_match:
                # Exact match found - check if it has outstanding amount
                exact_invoice = frappe.db.get_value(
                    "Sales Invoice",
                    overlap_result.exact_match,
                    ["name", "outstanding_amount"],
                    as_dict=True,
                )
                if exact_invoice and exact_invoice.outstanding_amount > 0:
                    frappe.logger().info(
                        f"[Mollie] Sales Invoice already exists for coverage {coverage_start} to {coverage_end}: "
                        f"{exact_invoice.name} (outstanding: {exact_invoice.outstanding_amount})"
                    )
                    return exact_invoice.name
                else:
                    # Invoice exists but is already paid - don't create duplicate
                    frappe.logger().warning(
                        f"[Mollie] Invoice {overlap_result.exact_match} exists for coverage "
                        f"{coverage_start} to {coverage_end} but is already paid. "
                        f"Payment Entry will be created unallocated for manual reconciliation."
                    )
                    return None
            else:
                # Overlapping but not exact - cannot safely create invoice
                overlapping_names = [inv["name"] for inv in overlap_result.overlapping_invoices]
                frappe.logger().warning(
                    f"[Mollie] Coverage overlap detected for member {member_doc.name}: "
                    f"proposed {coverage_start} to {coverage_end} overlaps with "
                    f"existing invoice(s): {', '.join(overlapping_names)}. "
                    f"Skipping invoice creation - manual review required."
                )
                return None

        # Deadlock retry configuration
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                settings = frappe.get_single("Verenigingen Settings")

                # Ensure fiscal year exists BEFORE creating invoice (prevents GL entry failures)
                from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

                try:
                    fiscal_year = ensure_fiscal_year_exists(payment_date, settings.company)
                    frappe.logger().info(
                        f"Fiscal year {fiscal_year} confirmed for invoice with posting_date={payment_date}"
                    )
                except Exception as fy_error:
                    frappe.logger().error(
                        f"Cannot create invoice for {member_doc.name}: Missing fiscal year for {payment_date}: {fy_error}"
                    )
                    return None

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
                invoice.append(
                    "items",
                    {
                        "item_code": self._get_or_create_dues_item(
                            item_name, settings.company, income_account
                        ),
                        "qty": 1,
                        "rate": amount,
                        "income_account": income_account,
                        "description": f"Membership dues for {member_doc.full_name} ({membership_type}) - Period: {coverage_start} to {coverage_end}",
                    },
                )

                invoice.insert()
                invoice.submit()

                return invoice.name

            except frappe.QueryDeadlockError as e:
                # Deadlock detected - retry with exponential backoff
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 0.1 * (2 ** (retry_count - 1))  # 0.1s, 0.2s, 0.4s
                    frappe.logger().warning(
                        f"[Mollie] Deadlock creating Sales Invoice for {member_doc.name}, "
                        f"retry {retry_count}/{max_retries} after {wait_time}s"
                    )
                    time.sleep(wait_time)
                    continue  # Retry
                else:
                    # Max retries exceeded
                    frappe.logger().error(
                        f"❌ Failed to create Sales Invoice after {max_retries} retries due to deadlocks: {e}"
                    )
                    frappe.log_error(
                        f"Sales Invoice creation failed after {max_retries} deadlock retries for member {member_doc.name}: {e}",
                        "Sales Invoice Deadlock Error",
                    )
                    return None

            except Exception as e:
                frappe.logger().error(f"Failed to create simple invoice: {str(e)}")
                frappe.log_error(
                    f"Sales Invoice creation failed for member {member_doc.name}: {e}",
                    "Sales Invoice Creation Error",
                )
                return None

        # Should never reach here, but safety fallback
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
            existing_item = frappe.get_all(
                "Item", filters={"item_name": ["like", "%Membership Dues%"]}, limit=1
            )
            if existing_item:
                return existing_item[0].name
            return "Membership Dues"  # Fallback to generic name

    def process_dues_payment(
        self,
        payment_id: str,
        payment=None,
        creation_mode: Optional[str] = None,
        invoice_name: Optional[str] = None,
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
            invoice_name: Optional pre-matched invoice name to allocate PE against

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

            # Detect partial processing scenarios
            has_payment_entry = bool(idempotency_check.get("payment_entry"))
            has_bank_transaction = bool(idempotency_check.get("bank_transaction"))

            # Full processing complete - both exist
            if has_payment_entry and has_bank_transaction:
                result["status"] = "already_processed"
                result["payment_entry"] = idempotency_check["payment_entry"]
                result["bank_transaction"] = idempotency_check["bank_transaction"]
                result["skipped_reason"] = "Both Payment Entry and Bank Transaction already exist"
                return result

            # Only Payment Entry exists (legacy mode) - fully processed
            if has_payment_entry and not has_bank_transaction:
                result["status"] = "already_processed"
                result["payment_entry"] = idempotency_check["payment_entry"]
                result["skipped_reason"] = "Payment Entry already exists (legacy mode)"
                return result

            # Partial processing: Bank Transaction exists but no Payment Entry
            # Continue processing to create Payment Entry, but skip Bank Transaction creation
            partial_processing = has_bank_transaction and not has_payment_entry

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

            # Extract and save consumer bank data from Mollie payment
            # This populates Member.iban and creates Bank Account links for future matching
            self._extract_and_save_consumer_bank_data(member_name, payment)

            # Determine creation mode: use override if provided, otherwise use centralized configuration
            if creation_mode is None:
                from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
                    get_mollie_config,
                )

                mollie_config = get_mollie_config()
                creation_mode = mollie_config.get_dues_payment_creation_mode()

            # Initialize tracking variables
            record_name = None
            bt_name = None

            # Handle partial processing: if Bank Transaction exists, only create Payment Entry
            if partial_processing:
                frappe.logger().info(
                    f"[Mollie] Partial processing for {payment_id}: Bank Transaction {idempotency_check['bank_transaction']} "
                    f"exists but no Payment Entry. Creating Payment Entry only."
                )
                record_name = self._create_payment_entry_for_dues(
                    member_name, payment, invoice_name=invoice_name
                )
                record_type = "Payment Entry"

                if record_name:
                    result["status"] = "success"
                    result["payment_entry"] = record_name
                    result["bank_transaction"] = idempotency_check["bank_transaction"]  # Reference existing
                    result["record_type"] = record_type
                    result["partial_processing"] = True
                    result["message"] = (
                        f"Completed partial processing: Created Payment Entry {record_name} "
                        f"for existing Bank Transaction {idempotency_check['bank_transaction']}"
                    )
            elif creation_mode == "Payment Entry":
                # Legacy mode: Create Payment Entry directly
                record_name = self._create_payment_entry_for_dues(member_name, payment)
                record_type = "Payment Entry"

                if record_name:
                    result["status"] = "success"
                    result["payment_entry"] = record_name
                    result["bank_transaction"] = None
                    result["record_type"] = record_type
            else:
                # Default mode: Create Bank Transaction for reconciliation
                bt_name = self._create_bank_transaction_for_dues(member_name, payment)
                record_type = "Bank Transaction"

                if bt_name:
                    result["status"] = "success"
                    result["bank_transaction"] = bt_name

                    # If invoice_name provided, also create PE and reconcile
                    if invoice_name:
                        pe_name = self._create_payment_entry_for_dues(
                            member_name, payment, invoice_name=invoice_name
                        )
                        if pe_name:
                            result["payment_entry"] = pe_name
                            result["record_type"] = "Bank Transaction + Payment Entry"

                            # Link BT to PE using ERPNext's reconciliation pattern
                            try:
                                bt_doc = frappe.get_doc("Bank Transaction", bt_name)
                                voucher = {
                                    "payment_doctype": "Payment Entry",
                                    "payment_name": pe_name,
                                }
                                bt_doc.add_payment_entries([voucher])
                                bt_doc.validate_duplicate_references()
                                bt_doc.allocate_payment_entries()
                                bt_doc.update_allocated_amount()
                                bt_doc.set_status()
                                bt_doc.save()
                                result["reconciled"] = True
                                frappe.logger().info(f"[Mollie] Reconciled BT {bt_name} with PE {pe_name}")
                            except Exception as e:
                                frappe.logger().warning(
                                    f"Could not reconcile BT {bt_name} with PE {pe_name}: {e}"
                                )
                                result["reconciled"] = False
                        else:
                            result["payment_entry"] = None
                    else:
                        result["payment_entry"] = None
                        result["record_type"] = record_type

            # Check if any record was created
            if record_name or bt_name or result.get("status") == "success":
                # Get linked Sales Invoices - check both Payment Entry references and member's unpaid invoices
                try:
                    sales_invoices = []

                    # If Payment Entry was created, check its references
                    # This includes both direct Payment Entry creation and partial_processing mode
                    if (creation_mode == "Payment Entry" or partial_processing) and record_name:
                        pe_doc = frappe.get_doc("Payment Entry", record_name)
                        for ref in pe_doc.get("references", []):
                            if ref.reference_doctype == "Sales Invoice":
                                sales_invoices.append(
                                    {
                                        "name": ref.reference_name,
                                        "allocated_amount": float(ref.allocated_amount),
                                        "linked": True,
                                    }
                                )

                    # Also show recent unpaid invoices for this member (helpful for Bank Transaction mode)
                    if member_name:
                        unpaid_invoices = frappe.get_all(
                            "Sales Invoice",
                            filters={
                                "member": member_name,
                                "docstatus": 1,
                                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
                            },
                            fields=["name", "posting_date", "grand_total", "outstanding_amount"],
                            order_by="posting_date desc",
                            limit=3,
                        )

                        # Add unpaid invoices that aren't already in the linked list
                        linked_names = {inv["name"] for inv in sales_invoices}
                        for inv in unpaid_invoices:
                            if inv.name not in linked_names:
                                sales_invoices.append(
                                    {
                                        "name": inv.name,
                                        "amount": float(inv.grand_total),
                                        "outstanding": float(inv.outstanding_amount),
                                        "date": str(inv.posting_date),
                                        "linked": False,
                                    }
                                )

                    if sales_invoices:
                        result["sales_invoices"] = sales_invoices

                except Exception as si_error:
                    frappe.log_error(f"Could not fetch Sales Invoice information: {si_error}")

                frappe.logger().info(
                    f"[Mollie] Successfully processed dues payment {payment_id} for member {member_name} "
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

    def _create_payment_entry_for_dues(
        self, member_name: str, payment, invoice_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a Payment Entry for a membership dues payment from Mollie.

        Creates a payment entry, optionally allocated to a specific invoice.
        If invoice_name is provided, uses that invoice directly instead of
        doing a lookup via _get_or_create_historical_invoice.

        Args:
            member_name: Member document name
            payment: Mollie payment object
            invoice_name: Optional specific invoice to allocate to (skips lookup)

        Returns:
            str: Payment Entry name if created, None otherwise
        """
        # Get member and customer
        member = frappe.get_doc("Member", member_name)
        customer = member.customer

        if not customer:
            frappe.throw(f"Member {member_name} has no linked Customer record")

        # Get settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")

        # Extract payment data using centralized extractor
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()
        payment_id = extractor.extract_payment_id(payment)
        amount = extractor.extract_amount(payment)
        payment_date = extractor.extract_date(payment, field_name="paid_at")
        mode_of_payment = getattr(verenigingen_settings, "mode_of_payment", None) or "Mollie"

        # Idempotency check: ensure Payment Entry doesn't already exist for this payment
        from verenigingen.integrations.mollie.services.unified_idempotency_manager import (
            get_unified_idempotency_manager,
        )

        idempotency_manager = get_unified_idempotency_manager()
        existing_pe = idempotency_manager.payment_entry_exists(payment_id)
        if existing_pe:
            frappe.logger().info(
                f"[Mollie] Payment Entry already exists for payment {payment_id}: {existing_pe}"
            )
            return existing_pe

        # Determine company - prioritize invoice's company if available
        # This prevents company/account mismatches
        company = None
        if invoice_name:
            company = frappe.db.get_value("Sales Invoice", invoice_name, "company")
        if not company:
            company = verenigingen_settings.company or frappe.defaults.get_global_default("company")

        # Get currency after company is determined
        currency = extractor.extract_currency(payment, company)

        # Ensure fiscal year exists for the payment date (prevents submission failures)
        from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

        try:
            fiscal_year = ensure_fiscal_year_exists(payment_date, company)
            frappe.logger().info(
                f"Fiscal year {fiscal_year} confirmed for Payment Entry with posting_date={payment_date}"
            )
        except Exception as fy_error:
            frappe.logger().error(
                f"Cannot create Payment Entry for {member_name}: Missing fiscal year for {payment_date}: {fy_error}"
            )
            return None

        # Get Mollie clearing account - must belong to same company
        mollie_config = get_mollie_config()
        mollie_clearing_account = mollie_config.get_clearing_account()

        # Validate clearing account belongs to the same company
        clearing_account_company = frappe.db.get_value("Account", mollie_clearing_account, "company")
        if clearing_account_company and clearing_account_company != company:
            # Try to find a compatible clearing account for this company
            # Look for an account with "Mollie" in name for this company
            compatible_account = frappe.db.get_value(
                "Account", {"company": company, "account_name": ["like", "%Mollie%"], "is_group": 0}, "name"
            )
            if compatible_account:
                frappe.logger().info(
                    f"Using company-specific clearing account {compatible_account} instead of {mollie_clearing_account}"
                )
                mollie_clearing_account = compatible_account
            else:
                # Fall back to company's default bank account
                mollie_clearing_account = frappe.get_cached_value("Company", company, "default_bank_account")
                if not mollie_clearing_account:
                    frappe.throw(
                        f"No compatible Mollie clearing account found for company {company}. "
                        f"Configured account {mollie_config.get_clearing_account()} belongs to {clearing_account_company}."
                    )
                frappe.logger().warning(
                    f"Using company default bank account {mollie_clearing_account} as clearing account fallback"
                )

        # Use provided invoice_name if given, otherwise try to get or create one
        if invoice_name is None:
            invoice_name = self._get_or_create_historical_invoice(member_name, payment_date, amount)

        # If we have a valid invoice, use ERPNext's get_payment_entry for proper account handling
        # This ensures paid_from matches the invoice's debit_to account (critical for validation)
        if invoice_name:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
            if invoice_doc.outstanding_amount > 0:
                # Use ERPNext's standard get_payment_entry which properly handles accounts
                from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

                payment_entry = get_payment_entry(
                    dt="Sales Invoice",
                    dn=invoice_name,
                    party_amount=min(amount, invoice_doc.outstanding_amount),
                    bank_account=mollie_clearing_account,
                )
                # Override/set additional fields for Mollie tracking
                payment_entry.posting_date = payment_date
                payment_entry.reference_no = payment_id
                payment_entry.reference_date = payment_date
                payment_entry.mode_of_payment = mode_of_payment
                payment_entry.paid_to = mollie_clearing_account
                payment_entry.remarks = (
                    f"Membership dues payment via Mollie for {member.full_name} (awaiting settlement). "
                    f"Linked to invoice {invoice_name}"
                )
                payment_entry.custom_member = member_name

                frappe.logger().info(
                    f"Using get_payment_entry for invoice {invoice_name} "
                    f"(outstanding: {invoice_doc.outstanding_amount}, paid_from: {payment_entry.paid_from})"
                )
            else:
                frappe.logger().warning(
                    f"Invoice {invoice_name} has no outstanding amount ({invoice_doc.outstanding_amount}), "
                    f"creating unallocated PE"
                )
                invoice_name = None  # Fall through to unallocated PE creation

        # Fallback: Create unallocated PE if no valid invoice
        if not invoice_name:
            customer_account = getattr(verenigingen_settings, "dues_payments_receivable_account", None)
            if not customer_account:
                customer_account = frappe.get_cached_value("Company", company, "default_receivable_account")
            if not customer_account:
                frappe.throw(f"Missing customer receivable account for company {company}")

            payment_entry = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer,
                    "company": company,
                    "paid_from": customer_account,
                    "paid_to": mollie_clearing_account,
                    "paid_amount": amount,
                    "received_amount": amount,
                    "reference_no": payment_id,
                    "reference_date": payment_date,
                    "posting_date": payment_date,
                    "mode_of_payment": mode_of_payment,
                    "remarks": f"Membership dues payment via Mollie for {member.full_name} (awaiting settlement). "
                    "Manual reconciliation may be required.",
                    "custom_member": member_name,
                }
            )

        payment_entry.insert()
        payment_entry.submit()

        frappe.logger().info(
            f"[Mollie] Created Payment Entry {payment_entry.name} for member {member_name} "
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

        # Use centralized create() method with party fields and member link
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
            custom_member=member_name,
        )

        if bank_transaction_name:
            frappe.logger().info(
                f"[Mollie] Created Bank Transaction {bank_transaction_name} for member {member_name} "
                f"(amount: {currency} {amount}, payment: {payment_id}, status: Unreconciled)"
            )

        return bank_transaction_name

    def batch_process_customer_payments(
        self,
        customer_id: str,
        limit: int = 250,
        only_unpaid: bool = False,
        create_payment_entry: bool = False,
    ) -> Dict[str, Any]:
        """
        Retrieve and process all payments for a Mollie customer.

        This is the main method for batch processing historical dues payments.

        Args:
            customer_id: Mollie customer ID
            limit: Maximum number of payments to retrieve
            only_unpaid: If True, only process payments not yet in Payment Entry
            create_payment_entry: If True, creates both Bank Transaction + Payment Entry (complete audit trail).
                                 If False, creates only Bank Transaction (for manual reconciliation later).

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
                # Process each payment with deadlock retry
                import time

                max_retries = 3
                retry_count = 0
                result = None

                while retry_count < max_retries:
                    try:
                        # Strategy 1: Bank Transaction only (default)
                        result = self.process_dues_payment(
                            payment.id, payment, creation_mode="Bank Transaction"
                        )

                        # Strategy 2: If create_payment_entry requested, also create PE and link them
                        # IMPORTANT: PE creation is INSIDE the retry loop to handle deadlocks
                        if (
                            create_payment_entry
                            and result.get("status") == "success"
                            and result.get("bank_transaction")
                        ):
                            member_name = result.get("member")
                            if member_name:
                                pe_name = self._create_payment_entry_for_dues(member_name, payment)
                                bt_name = result.get("bank_transaction")
                                bt_doc = frappe.get_doc("Bank Transaction", bt_name)
                                bt_doc.append(
                                    "payment_entries",
                                    {
                                        "payment_document": "Payment Entry",
                                        "payment_entry": pe_name,
                                        "allocated_amount": abs(bt_doc.unallocated_amount),
                                    },
                                )
                                bt_doc.save()
                                result["payment_entry"] = pe_name
                                result["pe_creation_mode"] = "linked_to_bank_transaction"

                        break  # Success - exit retry loop

                    except Exception as e:
                        retry_count += 1
                        error_str = str(e)
                        is_deadlock = "1213" in error_str or "Deadlock" in error_str

                        if is_deadlock and retry_count < max_retries:
                            wait_time = 0.1 * (2 ** (retry_count - 1))  # 0.1s, 0.2s, 0.4s
                            frappe.logger().warning(
                                f"Deadlock on {payment.id}, retry {retry_count}/{max_retries} after {wait_time}s"
                            )
                            time.sleep(wait_time)
                            continue
                        else:
                            # Not a deadlock or max retries reached
                            result = {"payment_id": payment.id, "status": "error", "error": error_str}
                            frappe.log_error(f"Error processing {payment.id}: {e}")
                            break

                if result:
                    batch_result["results"].append(result)

                    if result["status"] == "success":
                        batch_result["processed"] += 1
                    elif result["status"] == "skipped" or result["status"] == "already_processed":
                        batch_result["skipped"] += 1
                    elif result["status"] == "error":
                        batch_result["errors"] += 1

            frappe.logger().info(
                f"[Mollie] Batch processing complete for customer {customer_id}: "
                f"{batch_result['processed']} processed, {batch_result['skipped']} skipped, {batch_result['errors']} errors"
            )

        except Exception as e:
            batch_result["error"] = str(e)
            frappe.log_error(f"Error batch processing payments for customer {customer_id}: {e}")

        return batch_result
