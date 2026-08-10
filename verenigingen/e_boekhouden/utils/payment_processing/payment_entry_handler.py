"""
Enhanced payment entry handler for E-Boekhouden payment import.

This module handles the creation of Payment Entries from E-Boekhouden mutations,
including proper bank account mapping and multi-invoice reconciliation support.
"""

import json
import re
import threading
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists
from verenigingen.e_boekhouden.utils.security_helper import atomic_migration_operation, validate_and_insert

# Lock for thread-safe monkey patching of Payment Entry during floating point fix
_floating_point_fix_lock = threading.Lock()


class PaymentEntryHandler:
    """
    Handles creation of Payment Entries from E-Boekhouden mutations.

    Key capabilities:
    - Parses comma-separated invoice numbers
    - Maps rows to specific invoices
    - Handles both single and multi-invoice payments
    - Intelligent bank account determination from ledger mappings
    - Comprehensive error handling and logging
    """

    def __init__(self, company: str, cost_center: str = None):
        self.company = company
        self.cost_center = cost_center or frappe.db.get_value("Company", company, "cost_center")
        self.debug_log = []
        self._ledger_cache = {}  # Cache for ledger mappings

        # Bank Transaction creation tracking
        self._bank_tx_stats = {
            "total_processed": 0,
            "bank_tx_created": 0,
            "bank_tx_failed": 0,
            "bank_tx_skipped_zero_amount": 0,
            "bank_tx_already_existed": 0,
            "failures": [],  # List of {mutation_nr, reason, payment_entry}
        }

    def process_payment_mutation(self, mutation: Dict) -> Optional[str]:
        """
        Process a payment mutation (types 3 & 4) and create Payment Entry.

        Args:
            mutation: E-Boekhouden mutation data

        Returns:
            Payment Entry name if successful, None otherwise
        """
        mutation_id = mutation.get("id")
        self._log(f"Processing payment mutation {mutation_id}")

        # Log only essential mutation data for debugging
        if frappe.conf.developer_mode:
            self._log(
                f"DEBUG - Mutation {mutation_id} type: {mutation.get('type')}, amount: {mutation.get('amount')}"
            )

        # Check for duplicates before starting atomic operation
        existing_payment = frappe.db.get_value(
            "Payment Entry",
            {"eboekhouden_mutation_nr": str(mutation_id)},
            ["name", "payment_type", "party", "paid_amount"],
        )

        if existing_payment:
            self._log(f"Payment Entry already exists for mutation {mutation_id}: {existing_payment[0]}")
            self._log(
                f"Existing details: {existing_payment[1]} to {existing_payment[2]} for {existing_payment[3]}"
            )
            return existing_payment[0]  # Return early without entering atomic operation

        # Use atomic operation only for new payment entries with retry logic for lock timeouts
        max_retries = 3
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                with atomic_migration_operation("payment_processing"):
                    return self._process_payment_mutation_internal(mutation)
            except Exception as e:
                error_str = str(e)

                # Check if this is a database lock timeout that we should retry
                is_lock_timeout = "Lock wait timeout exceeded" in error_str or "1205" in error_str
                is_deadlock = "Deadlock found" in error_str or "1213" in error_str
                should_retry = (is_lock_timeout or is_deadlock) and attempt < max_retries - 1

                if should_retry:
                    import time

                    wait_time = retry_delay * (attempt + 1)  # Exponential backoff
                    self._log(
                        f"Database lock detected for mutation {mutation_id}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue

                # Final attempt failed or non-retryable error
                self._log(f"ERROR processing mutation {mutation_id}: {error_str}")
                frappe.log_error(
                    f"Payment mutation processing failed: {error_str}\\nMutation: {json.dumps(mutation, indent=2)}\\n\\nTraceback:\\n{frappe.get_traceback()}",
                    "E-Boekhouden Payment Import",
                )
                return None

        # Should never reach here, but return None as safety
        return None

    def _process_payment_mutation_internal(self, mutation: Dict) -> Optional[str]:
        """
        Internal payment processing method that runs within atomic transaction.

        Args:
            mutation: E-Boekhouden mutation data

        Returns:
            Payment Entry name if successful, None otherwise
        """
        try:
            mutation_id = mutation.get("id")

            # Validate mutation type
            mutation_type = mutation.get("type")
            if mutation_type not in [3, 4]:
                self._log(f"ERROR: Invalid mutation type {mutation_type} for payment processing")
                return None

            # Parse invoice numbers
            invoice_numbers = self._parse_invoice_numbers(mutation.get("invoiceNumber"))
            self._log(f"Found {len(invoice_numbers)} invoice(s): {invoice_numbers}")
            self._current_invoice_numbers = invoice_numbers  # Store for account lookup

            # Extract additional invoice references from rows/regels
            if frappe.conf.developer_mode and (mutation.get("rows") or mutation.get("Regels")):
                self._log(
                    f"Checking {len(mutation.get('rows', []))} rows and {len(mutation.get('Regels', []))} regels for invoice references"
                )

            # Determine payment type, party type, and refund status
            raw_amount = flt(mutation.get("amount", 0))
            payment_type, party_type, is_refund = self._determine_payment_type(
                mutation, raw_amount, mutation_type
            )
            initial_payment_type = payment_type

            # Get or create party
            party = self._get_or_create_party(
                mutation.get("relationId"), party_type, mutation.get("description", "")
            )

            if not party:
                self._log(f"ERROR: Could not determine party for mutation {mutation_id}")
                return None

            # Determine bank account from ledger
            bank_account = self._determine_bank_account(
                mutation.get("ledgerId"), payment_type, mutation.get("description")
            )

            if not bank_account:
                self._log(f"ERROR: Could not determine bank account for mutation {mutation_id}")
                return None

            # Keep GL Account for Payment Entry creation (Payment Entry needs GL accounts)
            gl_account = bank_account

            # Convert GL Account to Bank Account name for Bank Transaction creation if needed
            bank_account_name = self._convert_to_bank_account_name(bank_account)
            self._log(f"GL Account: {gl_account}, Bank Account: {bank_account_name}")

            # Create payment entry
            pe = self._create_payment_entry(
                mutation=mutation,
                payment_type=payment_type,
                party_type=party_type,
                party=party,
                bank_account=gl_account,
            )

            # Allocate to invoices and insert payment entry
            self._allocate_and_insert_payment(pe, invoice_numbers, mutation, party_type)

            # Create Bank Transaction and link to Payment Entry
            bank_transaction_name, existing_bt = self._create_and_link_bank_transaction(
                mutation, pe, bank_account_name
            )

            # Submit with floating point precision fix and fiscal year validation
            self._submit_with_floating_point_fix(pe, bank_transaction_name)

            # Track success
            self._track_bank_transaction_stats(mutation, pe.name, bank_transaction_name, existing_bt)

            return pe.name

        except Exception as e:
            # Track failure before re-raising
            pe_name = getattr(pe, "name", None) if "pe" in locals() else None
            self._track_bank_transaction_stats(mutation, pe_name, None, False, error=e)
            raise

    def _track_bank_transaction_stats(
        self,
        mutation: Dict,
        pe_name: Optional[str],
        bt_name: Optional[str],
        existing_bt: bool,
        error: Optional[Exception] = None,
    ) -> None:
        """Update _bank_tx_stats for success or failure."""
        self._bank_tx_stats["total_processed"] += 1

        if error:
            self._bank_tx_stats["bank_tx_failed"] += 1
            self._bank_tx_stats["failures"].append(
                {
                    "mutation_nr": mutation.get("id"),
                    "payment_entry": pe_name or "Not created",
                    "reason": str(error)[:200],
                }
            )
            return

        if bt_name:
            if existing_bt:
                self._bank_tx_stats["bank_tx_already_existed"] += 1
            else:
                self._bank_tx_stats["bank_tx_created"] += 1

    def _allocate_and_insert_payment(
        self, pe, invoice_numbers: List[str], mutation: Dict, party_type: str
    ) -> None:
        """Allocate PE to invoices and insert. Falls back to unallocated on 'fully paid' errors.

        Combines invoice numbers from header and row-level references, performs
        allocation, then inserts. If ERPNext rejects allocation because invoices
        are already fully paid, clears allocations and inserts as unallocated.
        """
        # Combine invoice numbers from header and any found in rows.
        # Dedupe while PRESERVING order: the 1:1 allocation strategy in
        # _allocate_one_to_one zips payment rows (in e-Boekhouden order) against
        # this invoice list, so the invoice order must stay aligned with the
        # header invoiceNumber order. list(set(...)) would randomize it (hash
        # order), mis-allocating multi-invoice payments whose per-invoice amounts
        # differ. dict.fromkeys preserves first-seen order and removes duplicates.
        row_invoice_refs = self._extract_invoice_references_from_rows(mutation)
        all_invoice_refs = list(dict.fromkeys(invoice_numbers + row_invoice_refs))

        if all_invoice_refs:
            self._log(f"All invoice references to link: {all_invoice_refs}")
            if mutation.get("rows"):
                self._allocate_to_invoices(pe, all_invoice_refs, mutation["rows"], party_type)
            else:
                # Single invoice or no rows - simple allocation
                self._simple_invoice_allocation(pe, all_invoice_refs, party_type)
        else:
            self._log("WARNING: No invoice references found in payment mutation")

        # Insert with proper permissions
        # For E-Boekhouden Type 3/4 payments, bypass ERPNext's "fully paid" validation
        # since E-Boekhouden is the authoritative source for payment-invoice relationships
        try:
            validate_and_insert(pe)
            self._log(f"Created Payment Entry {pe.name}")
        except Exception as e:
            # Detect the over-allocation by STATE, not by error message. ERPNext wraps
            # both messages in _(), so the English substring test this used to perform
            # silently stopped working under a non-English site language - and the
            # fallback below is the only thing that keeps the payment from being lost.
            from verenigingen.verenigingen_payments.utils.payment_allocation import (
                any_reference_cannot_absorb,
            )

            if isinstance(e, frappe.ValidationError) and any_reference_cannot_absorb(pe):
                self._log(f"Allocation error: {str(e)} - creating unallocated payment entry as fallback")
                # Clear allocations and create unallocated payment
                pe.references = []
                pe.unallocated_amount = pe.paid_amount or pe.received_amount
                pe.remarks = (
                    pe.remarks or ""
                ) + f"\n[Auto-allocation failed for invoice(s): {', '.join(all_invoice_refs)}]"

                # Save without allocations
                pe.flags.ignore_validate = True
                pe.insert()
                self._log(f"Created unallocated Payment Entry {pe.name} (will need manual reconciliation)")
            else:
                raise

    def _submit_with_floating_point_fix(self, pe, bank_transaction_name: Optional[str]) -> None:
        """Ensure fiscal year, apply floating-point workaround, and submit PE.

        ERPNext can produce floating point precision errors when summing allocated
        amounts during submit(). This method detects the issue and temporarily patches
        PaymentEntry to skip recalculation, preserving the correctly-rounded values
        from insert.

        Thread-safety: Uses _floating_point_fix_lock to serialize monkey-patching.
        """
        # Ensure fiscal year exists before submission
        try:
            debug_info = []
            ensure_fiscal_year_exists(pe.posting_date, self.company, debug_info)
            for msg in debug_info:
                self._log(msg)
        except Exception as fy_error:
            self._log(f"WARNING: Could not ensure fiscal year: {str(fy_error)}")
            # Continue anyway - the submit() will give a clearer error message

        # Submit Payment Entry (commits both PE and BT together in atomic transaction)
        self._log(f"Submitting Payment Entry {pe.name} (will commit both PE and BT atomically)...")

        pe.reload()  # Get fresh values after insert

        # Debug: Log all amounts before submit
        self._log(f"DEBUG PRE-SUBMIT: paid_amount={pe.paid_amount}, received_amount={pe.received_amount}")
        self._log(
            f"DEBUG PRE-SUBMIT: base_paid_amount={pe.base_paid_amount}, base_received_amount={pe.base_received_amount}"
        )
        self._log(
            f"DEBUG PRE-SUBMIT: total_allocated_amount={pe.total_allocated_amount}, base_total_allocated_amount={pe.base_total_allocated_amount}"
        )
        self._log(
            f"DEBUG PRE-SUBMIT: unallocated_amount={pe.unallocated_amount}, repr={repr(pe.unallocated_amount)}"
        )
        self._log(
            f"DEBUG PRE-SUBMIT: source_exchange_rate={pe.source_exchange_rate}, target_exchange_rate={pe.target_exchange_rate}"
        )
        for ref in pe.references:
            self._log(
                f"DEBUG REF: {ref.reference_doctype} {ref.reference_name} allocated={ref.allocated_amount} repr={repr(ref.allocated_amount)}"
            )

        # Detect potential floating point mismatch between raw sum and paid_amount
        raw_sum = sum(ref.allocated_amount for ref in pe.references)
        paid_amount = pe.paid_amount or pe.received_amount
        floating_point_diff = abs(raw_sum - paid_amount)
        needs_floating_point_fix = floating_point_diff > 0 and floating_point_diff < 0.01

        self._log(
            f"DEBUG: raw_sum={raw_sum}, paid_amount={paid_amount}, diff={floating_point_diff}, needs_fix={needs_floating_point_fix}"
        )

        # Use lock for thread-safe monkey patching during submit
        # This prevents race conditions when multiple mutations are imported concurrently
        with _floating_point_fix_lock:
            if needs_floating_point_fix:
                self._log("Applying floating point precision fix for submit")
                from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry

                # Save original methods
                original_set_total_allocated = PaymentEntry.set_total_allocated_amount
                original_set_unallocated = PaymentEntry.set_unallocated_amount

                def patched_set_total_allocated(self):
                    if hasattr(self, "_skip_amount_recalc") and self._skip_amount_recalc:
                        return
                    return original_set_total_allocated(self)

                def patched_set_unallocated(self):
                    if hasattr(self, "_skip_amount_recalc") and self._skip_amount_recalc:
                        return
                    return original_set_unallocated(self)

                PaymentEntry.set_total_allocated_amount = patched_set_total_allocated
                PaymentEntry.set_unallocated_amount = patched_set_unallocated
                pe._skip_amount_recalc = True

            try:
                pe.submit()
            finally:
                # Restore original methods if we patched them
                if needs_floating_point_fix:
                    PaymentEntry.set_total_allocated_amount = original_set_total_allocated
                    PaymentEntry.set_unallocated_amount = original_set_unallocated
        self._log(
            f"✓ ATOMIC TRANSACTION COMPLETE: Payment Entry {pe.name} submitted "
            f"{f'with linked Bank Transaction {bank_transaction_name}' if bank_transaction_name else 'without Bank Transaction'}"
        )

    def _create_and_link_bank_transaction(
        self, mutation: Dict, pe, bank_account_name: str
    ) -> Tuple[Optional[str], bool]:
        """Create Bank Transaction and link to Payment Entry.

        Checks for existing Bank Transaction (idempotency for re-imports),
        creates one if needed, and links it to the Payment Entry.

        Returns:
            Tuple of (bank_transaction_name, was_existing). bank_transaction_name
            is None if creation failed.
        """
        mutation_id = mutation.get("id")

        # Check if Bank Transaction already exists (idempotency for re-imports)
        existing_bt = frappe.db.get_value(
            "Bank Transaction", {"reference_number": f"EB-{mutation_id}"}, "name"
        )

        if existing_bt:
            self._log(
                f"Bank Transaction {existing_bt} already exists for mutation {mutation_id}, skipping creation"
            )
            return existing_bt, True

        # Check if this is a gateway adjustment (for audit trail logging)
        is_gateway_adjustment = bool(mutation.get("_original_amount"))
        if is_gateway_adjustment:
            self._log(
                f"Gateway adjustment: Creating Bank Transaction with adjusted amount "
                f"€{pe.paid_amount or pe.received_amount} (original: €{mutation.get('_original_amount')})"
            )

        self._log(
            f"ATOMIC TRANSACTION START: Creating Bank Transaction for Payment Entry {pe.name} "
            f"(Mutation #{mutation_id}, Amount: {pe.paid_amount or pe.received_amount})"
        )

        bank_transaction_name = self._create_bank_transaction_for_payment(mutation, pe, bank_account_name)

        if bank_transaction_name:
            self._log(f"✓ Bank Transaction created: {bank_transaction_name}")

            # Link the bank transaction to payment entry immediately (only if it's not already linked)
            # Check if already linked to avoid "Cannot edit cancelled document" error
            already_linked = frappe.db.exists(
                "Bank Transaction Payments", {"parent": bank_transaction_name, "payment_entry": pe.name}
            )

            if not already_linked:
                self._log(f"Linking Bank Transaction {bank_transaction_name} to Payment Entry {pe.name}...")
                self._link_bank_transaction_to_payment(bank_transaction_name, pe.name)
                self._log("✓ Bank Transaction linked successfully")
            else:
                self._log(
                    f"Bank Transaction {bank_transaction_name} already linked to Payment Entry {pe.name}"
                )
        else:
            self._log("WARNING: Failed to create Bank Transaction - proceeding with Payment Entry only")

        return bank_transaction_name, False

    def _determine_payment_type(
        self, mutation: Dict, raw_amount: float, mutation_type: int
    ) -> Tuple[str, str, bool]:
        """Determine payment_type, party_type, and is_refund from mutation data.

        Examines the mutation type, amount sign, and gateway adjustment status
        to determine the correct ERPNext payment direction.

        Returns:
            Tuple of (payment_type, party_type, is_refund)
        """
        mutation_id = mutation.get("id")

        # Base payment type from mutation type
        base_payment_type = "Receive" if mutation_type == 3 else "Pay"

        # Check if this is a gateway payment with adjusted amount
        # Gateway payments shouldn't have payment type reversed
        is_gateway_adjustment = bool(mutation.get("_original_amount"))

        # Determine if this is a refund based on mutation type and amount sign
        # Type 3 (Customer Payment): normally positive (money IN), negative = refund TO customer
        # Type 4 (Supplier Payment) in E-Boekhouden convention:
        #   - raw_amount > 0 (positive) = NORMAL payment OUT to supplier (keep as 'Pay')
        #   - raw_amount = 0 with positive rows = NORMAL payment (keep as 'Pay')
        #   - raw_amount < 0 (negative) = REFUND from supplier, money IN (reverse to 'Receive')
        #
        # NOTE: E-Boekhouden stores Type 4 with POSITIVE amounts (money leaving bank)
        # This matches bank statement convention, opposite of ERPNext internal convention
        is_refund = False

        if mutation_type == 3 and raw_amount < 0:
            is_refund = True  # Refund TO customer (money OUT)
        elif mutation_type == 4 and not is_gateway_adjustment:
            # For Type 4: Only NEGATIVE raw_amount indicates refund from supplier
            # Positive or zero = normal supplier payment
            if raw_amount < 0:
                # Negative Type 4 = refund FROM supplier (deposit return, money IN)
                is_refund = True

        # Reverse payment type for refunds
        if is_refund:
            payment_type = "Pay" if base_payment_type == "Receive" else "Receive"
            self._log(
                f"Refund detected (Type {mutation_type}, amount={raw_amount}) - reversing payment type from {base_payment_type} to {payment_type}"
            )
        else:
            payment_type = base_payment_type
            if is_gateway_adjustment:
                self._log(
                    f"Gateway payment detected - keeping payment type as {payment_type} (amount: {raw_amount})"
                )

        party_type = "Customer" if mutation_type == 3 else "Supplier"

        # Validate payment direction consistency
        # For gateway adjustments, validate against adjusted amount to ensure correctness
        if is_gateway_adjustment:
            # Gateway adjustments should result in Type 4 with negative amount (payment OUT)
            if mutation_type == 4 and raw_amount >= 0:
                self._log(
                    f"⚠️ WARNING: Gateway adjustment resulted in non-negative Type 4 amount ({raw_amount}). "
                    f"Expected negative for supplier payment."
                )
                frappe.log_error(
                    title=f"Invalid Gateway Adjustment - Mutation {mutation_id}",
                    message=f"Gateway adjustment for Type 4 resulted in non-negative amount: {raw_amount}\n"
                    f"Original amount: {mutation.get('_original_amount')}\n"
                    f"Adjustment reason: {mutation.get('_adjustment_reason')}\n"
                    f"This indicates a logic error in amount adjustment.",
                )
        else:
            # Normal validation for non-gateway mutations
            self._validate_payment_direction(mutation_type, raw_amount, payment_type, party_type)

        return payment_type, party_type, is_refund

    def _parse_invoice_numbers(self, invoice_str: str) -> List[str]:
        """Parse comma-separated invoice numbers."""
        if not invoice_str:
            return []

        # Split by comma and clean up
        invoices = [inv.strip() for inv in str(invoice_str).split(",")]
        return [inv for inv in invoices if inv]

    def _extract_invoice_references_from_rows(self, mutation: Dict) -> List[str]:
        """Extract any invoice references from mutation rows/regels with validation."""
        references = []

        try:
            # Check rows (REST API format)
            rows = mutation.get("rows", [])
            if rows and isinstance(rows, list):
                for row in rows[:10]:  # Limit to first 10 rows for performance
                    if not isinstance(row, dict):
                        continue
                    # Check various possible fields that might contain invoice references
                    for field in ["invoiceId", "invoiceMutationId", "factuurNummer", "invoiceNumber"]:
                        value = row.get(field)
                        if value and str(value).strip():
                            ref = str(value).strip()[:50]  # Limit length
                            if ref not in references and self._is_valid_invoice_reference(ref):
                                references.append(ref)
                                if frappe.conf.developer_mode:
                                    self._log(f"Found invoice reference in row field '{field}': {ref}")

            # Check Regels (SOAP API format)
            regels = mutation.get("Regels", [])
            if regels and isinstance(regels, list):
                for regel in regels[:10]:  # Limit to first 10 regels
                    if not isinstance(regel, dict):
                        continue
                    for field in ["FactuurNummer", "InvoiceId", "MutatieNummer"]:
                        value = regel.get(field)
                        if value and str(value).strip():
                            ref = str(value).strip()[:50]  # Limit length
                            if ref not in references and self._is_valid_invoice_reference(ref):
                                references.append(ref)
                                if frappe.conf.developer_mode:
                                    self._log(f"Found invoice reference in regel field '{field}': {ref}")

        except Exception as e:
            self._log(f"WARNING: Error extracting invoice references: {str(e)[:100]}")

        return references[:20]  # Limit total references to prevent excessive processing

    def _is_valid_invoice_reference(self, ref: str) -> bool:
        """Validate invoice reference format."""
        if not ref or len(ref) < 2 or len(ref) > 50:
            return False
        # Basic validation - alphanumeric with some allowed characters
        return bool(re.match(r"^[A-Za-z0-9\-_./]+$", ref))

    def _determine_bank_account(
        self, ledger_id: int, payment_type: str, description: str = None
    ) -> Optional[str]:
        """
        Determine the bank account for a payment from its ledger mapping.

        A ledger ID is required. Resolution is driven by the ledger mapping,
        with payment config and description patterns acting only as tiebreakers
        within that lookup. There is no description-only or default fallback:
        a missing ledger ID raises ValidationError rather than risk posting a
        payment against the wrong bank account.
        """
        if not ledger_id:
            raise frappe.ValidationError(
                "No ledger ID provided in mutation. Cannot determine bank account without ledger mapping."
            )

        # Check cache first
        cache_key = f"{ledger_id}:{payment_type}"
        if cache_key in self._ledger_cache:
            return self._ledger_cache[cache_key]

        # Use consolidated bank account resolution
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            resolve_bank_account_for_ledger,
        )
        from verenigingen.e_boekhouden.utils.consolidated.ledger_utils import get_ledger_mapping

        debug_info = []
        bank_account = resolve_bank_account_for_ledger(
            ledger_id=str(ledger_id),
            company=self.company,
            payment_type=payment_type,
            description=description,
            debug_info=debug_info,
            auto_create_mapping=True,
        )

        # Log debug info from consolidated function
        for info in debug_info:
            self._log(info)

        if bank_account:
            self._log(f"Mapped ledger {ledger_id} to bank account: {bank_account}")
            self._ledger_cache[cache_key] = bank_account
            return bank_account

        # Handler-specific fallback: try configurable account mapper pattern matching
        if description:
            bank_account = self._get_account_from_pattern(description, payment_type)
            if bank_account:
                self._log(f"Found bank account via configurable pattern matching: {bank_account}")
                self._ledger_cache[cache_key] = bank_account
                return bank_account

        # No fallback - fail hard with clear error message
        # Surface debug info from final mapping lookup for operational visibility
        ledger_debug = []
        ledger_code, _ = get_ledger_mapping(
            str(ledger_id), self.company, debug_info=ledger_debug, auto_create=False
        )
        for msg in ledger_debug:
            self._log(msg)

        # Include last few debug lines in exception for faster triage
        error_msg = (
            f"No Bank/Cash account found for E-Boekhouden ledger {ledger_id} (code: {ledger_code}). "
            f"Please link the ledger mapping to a Bank or Cash account before importing."
        )
        if ledger_debug:
            debug_snippet = "\n".join(ledger_debug[-3:])
            error_msg += f"\n\nDebug info:\n{debug_snippet}"
        raise frappe.ValidationError(error_msg)

    def _get_account_from_pattern(self, description: str, payment_type: str) -> Optional[str]:
        """Match bank account based on description patterns using configurable mapping."""
        from verenigingen.e_boekhouden.utils.configurable_account_mapper import get_account_mapper

        mapper = get_account_mapper(self.company)

        # Map description patterns to account purposes (no hardcoded numbers)
        pattern_to_purpose = {
            "triodos": "triodos",
            "paypal": "paypal",
            "asn": "asn",
            "kas": "cash",
            "cash": "cash",
        }

        description_lower = description.lower()
        for pattern, purpose in pattern_to_purpose.items():
            if pattern in description_lower:
                account = mapper.get_account_by_purpose(purpose)
                if account:
                    return account

        return None

    def _convert_to_bank_account_name(self, account: str) -> str:
        """
        Convert GL Account to Bank Account name for Bank Transaction creation.

        Delegates to consolidated bank_account_utils while preserving handler logging.

        Args:
            account: Could be either a Bank Account name or GL Account name

        Returns:
            Bank Account name (guaranteed to be Bank Account DocType)

        Raises:
            frappe.ValidationError if no Bank Account found for the GL Account
        """
        from verenigingen.e_boekhouden.utils.consolidated.bank_account_utils import (
            convert_gl_account_to_bank_account_or_raise,
        )

        debug_info = []
        bank_account = convert_gl_account_to_bank_account_or_raise(
            gl_account=account,
            company=self.company,
            debug_info=debug_info,
        )

        # Log debug info from consolidated function
        for info in debug_info:
            self._log(info)

        return bank_account

    def _get_or_create_party(self, relation_id: str, party_type: str, description: str) -> Optional[str]:
        """Get existing party or create new one using canonical party resolver."""
        if not relation_id:
            return None

        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        if party_type == "Customer":
            return resolver.resolve_customer(relation_id, self.debug_log)
        else:
            return resolver.resolve_supplier(relation_id, self.debug_log)

    def _create_payment_entry(
        self, mutation: Dict, payment_type: str, party_type: str, party: str, bank_account: str
    ) -> frappe._dict:
        """Create the payment entry document."""
        pe = frappe.new_doc("Payment Entry")
        pe.company = self.company
        pe.cost_center = self.cost_center
        pe.posting_date = getdate(mutation.get("date"))
        pe.payment_type = payment_type

        # Always calculate amount from rows (rows are source of truth)
        top_level_amount = abs(flt(mutation.get("amount", 0), 2))
        self._log(f"Top-level amount from mutation: {top_level_amount}")

        if mutation.get("rows"):
            row_amounts = [abs(flt(row.get("amount", 0), 2)) for row in mutation.get("rows", [])]
            # Round sum to avoid floating point precision errors (e.g., 504.28 + 117.92 = 622.1999999999999)
            amount = flt(sum(row_amounts), 2)
            self._log(f"Row amounts: {row_amounts}")
            self._log(f"Calculated amount {amount} from {len(mutation.get('rows', []))} rows")

            # Validate top-level amount matches rows (if non-zero)
            if top_level_amount > 0 and abs(top_level_amount - amount) > 0.01:
                self._log(
                    f"WARNING: Top-level amount ({top_level_amount}) doesn't match row total ({amount})"
                )
        else:
            # Fallback to top-level amount only if no rows exist
            amount = top_level_amount
            self._log(f"No rows found, using top-level amount: {amount}")

        # Check for zero-amount payments
        if amount == 0:
            self._log("Zero amount payment detected")
            # Let ERPNext handle the validation - if it requires non-zero amounts, it will fail properly

        # CRITICAL: For same-currency transactions, we must let ERPNext calculate amounts
        # to avoid duplicate GL entries. Set paid_amount, then call set_amounts()
        pe.paid_amount = amount

        # Set party details first (needed before set_amounts)
        if party:
            pe.party_type = party_type
            pe.party = party

        # Set accounts based on payment type
        # Determine party account with invoice-first priority
        party_account = self._get_party_account_with_invoice_priority(mutation, party_type, party)

        if payment_type == "Receive":
            pe.paid_to = bank_account  # Money goes to our bank
            pe.paid_from = party_account  # Money comes from receivable account
        else:
            pe.paid_from = bank_account  # Money comes from our bank
            pe.paid_to = party_account  # Money goes to payable account

        # Set reference details
        invoice_number = mutation.get("invoiceNumber")
        pe.reference_no = invoice_number if invoice_number else f"EB-{mutation.get('id')}"
        pe.reference_date = pe.posting_date

        # Store E-Boekhouden references
        if hasattr(pe, "eboekhouden_mutation_nr"):
            pe.eboekhouden_mutation_nr = str(mutation.get("id"))
        if hasattr(pe, "eboekhouden_mutation_type"):
            pe.eboekhouden_mutation_type = str(mutation.get("type"))

        # Enhanced naming and remarks
        from verenigingen.e_boekhouden.utils.eboekhouden_payment_naming import (
            enhance_payment_entry_fields,
            get_payment_entry_title,
        )

        pe.title = get_payment_entry_title(mutation, party, payment_type)
        enhance_payment_entry_fields(pe, mutation)

        # Add detailed remarks
        pe.remarks = self._generate_remarks(mutation, bank_account, party)

        # CRITICAL: Manually set received_amount = paid_amount for same-currency transactions
        # We CANNOT call set_amounts() here because validate() will call it again (causing doubling)
        # But we MUST set received_amount to satisfy mandatory field validation
        pe.received_amount = pe.paid_amount
        self._log(f"Set amounts: paid_amount={pe.paid_amount}, received_amount={pe.received_amount}")

        return pe

    def _allocate_to_invoices(
        self, payment_entry: frappe._dict, invoice_numbers: List[str], rows: List[Dict], party_type: str
    ):
        """
        Allocate payment to multiple invoices based on row data with validation.

        Strategy:
        1. If row count matches invoice count - 1:1 mapping
        2. Otherwise, use FIFO allocation
        """
        invoice_doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"

        # Get invoice details
        invoices = self._find_invoices(invoice_numbers, invoice_doctype, payment_entry.party)

        if not invoices:
            self._log("WARNING: No matching invoices found for allocation")
            return

        # For Type 3/4 payments, don't filter by outstanding_amount since E-Boekhouden
        # has already determined the payment-invoice relationship
        # ERPNext outstanding_amount may be incorrect during batch import due to race conditions

        if not invoices:
            self._log("WARNING: No matching invoices found for allocation")
            return

        # Log invoice status for debugging and check for debit notes
        has_negative_outstanding = False
        for inv in invoices:
            outstanding = flt(inv.get("outstanding_amount", 0))
            grand_total = flt(inv.get("grand_total", 0))
            self._log(f"Found invoice {inv['name']}: grand_total={grand_total}, outstanding={outstanding}")

            # Check if any invoice has negative outstanding (debit note)
            if outstanding < 0:
                has_negative_outstanding = True
                self._log(f"⚠️ Debit note detected: {inv['name']} has negative outstanding ({outstanding})")

        # CRITICAL: Adjust payment type if dealing with SUPPLIER debit notes (negative outstanding)
        # For SUPPLIER debit notes: supplier owes us money, so reverse Pay→Receive
        # For CUSTOMER credit notes: we owe customer, keep as Pay (don't reverse)
        if (
            has_negative_outstanding
            and payment_entry.payment_type == "Pay"
            and payment_entry.party_type == "Supplier"
        ):
            self._log(
                "Supplier debit note detected - reversing payment type from 'Pay' to 'Receive' (supplier owes us)"
            )
            payment_entry.payment_type = "Receive"
            # Swap paid_from and paid_to accounts
            paid_from, paid_to = payment_entry.paid_from, payment_entry.paid_to
            payment_entry.paid_from = paid_to
            payment_entry.paid_to = paid_from
            self._log(
                f"Swapped accounts: paid_from={payment_entry.paid_from}, paid_to={payment_entry.paid_to}"
            )
        elif has_negative_outstanding and payment_entry.party_type == "Customer":
            self._log(
                "Customer credit note detected with negative outstanding - keeping payment_type='Pay' (we owe customer)"
            )

        # Validate payment amount vs invoice amounts (informational only)
        total_payment = payment_entry.paid_amount or payment_entry.received_amount
        total_grand = sum(inv.get("grand_total", 0) for inv in invoices)

        if total_payment > total_grand * 1.1:  # Allow 10% tolerance
            self._log(
                f"INFO: Payment amount ({total_payment}) exceeds total invoice amount ({total_grand}) - possible overpayment"
            )

        # Prepare row amounts (absolute values)
        row_amounts = [abs(flt(row.get("amount", 0))) for row in rows]

        # Log allocation strategy
        self._log(f"Allocating {len(row_amounts)} row(s) to {len(invoices)} invoice(s)")

        # Allocate based on strategy
        if len(invoices) == len(rows) and len(invoices) > 1:
            # 1:1 mapping
            self._log("Using 1:1 row-to-invoice mapping")
            self._allocate_one_to_one(payment_entry, invoices, row_amounts)
        else:
            # FIFO allocation
            self._log("Using FIFO allocation strategy")
            self._allocate_fifo(payment_entry, invoices, row_amounts)

    def _allocate_one_to_one(
        self, payment_entry: frappe._dict, invoices: List[Dict], row_amounts: List[float]
    ):
        """Allocate with 1:1 mapping between rows and invoices.

        For Type 3/4 payments, trust E-Boekhouden amounts completely since
        ERPNext outstanding_amount may be incorrect during batch processing.

        The last allocation is adjusted to ensure sum exactly equals paid_amount,
        avoiding floating point precision errors that cause ERPNext GL Entry failures.
        """
        paid_amount = payment_entry.paid_amount or payment_entry.received_amount
        allocated_so_far = 0.0

        # If paid_amount is not set (e.g., in tests), fall back to using row amounts directly
        use_floating_point_fix = paid_amount is not None

        for i, (invoice, amount) in enumerate(zip(invoices, row_amounts)):
            # For Type 3/4 payments, use E-Boekhouden amount directly
            invoice_total = invoice["grand_total"]
            is_debit_note = invoice_total < 0

            # Adjust last allocation to ensure sum equals paid_amount exactly
            # This prevents floating point errors like 504.28 + 117.92 = 622.1999999999999
            is_last = i == len(invoices) - 1
            if use_floating_point_fix and is_last:
                # Last allocation = remaining amount to match paid_amount exactly
                allocation = flt(paid_amount - allocated_so_far, 2)
                if is_debit_note:
                    allocation = -abs(allocation)
            else:
                allocation = -amount if is_debit_note else amount
                allocated_so_far += abs(allocation)

            # For E-Boekhouden Type 3/4 payments, bypass outstanding amount validation
            # For debit notes: set outstanding_amount to 0 (ERPNext convention)
            # For normal invoices: set to grand_total to allow any allocation
            outstanding_for_ref = 0 if is_debit_note else invoice["grand_total"]

            payment_entry.append(
                "references",
                {
                    "reference_doctype": invoice["doctype"],
                    "reference_name": invoice["name"],
                    "total_amount": invoice["grand_total"],
                    "outstanding_amount": outstanding_for_ref,
                    "allocated_amount": allocation,
                },
            )

            self._log(
                f"Allocated {allocation} to {invoice['name']} (1:1 mapping, E-Boekhouden authoritative)"
            )

    def _allocate_fifo(self, payment_entry: frappe._dict, invoices: List[Dict], row_amounts: List[float]):
        """Allocate using FIFO strategy.

        For Type 3/4 payments, trust E-Boekhouden amounts and relationships.
        Don't limit by outstanding_amount due to potential race conditions.

        The last allocation is adjusted to ensure sum exactly equals paid_amount,
        avoiding floating point precision errors that cause ERPNext GL Entry failures.
        """
        paid_amount = payment_entry.paid_amount or payment_entry.received_amount
        total_to_allocate = flt(sum(row_amounts), 2) if row_amounts else (paid_amount or 0)

        # If paid_amount is not set (e.g., in tests), fall back to using calculated amounts directly
        use_floating_point_fix = paid_amount is not None

        # First pass: calculate what we'll allocate to each invoice
        allocations = []
        remaining = total_to_allocate

        for invoice in invoices:
            if remaining <= 0:
                break

            invoice_total = invoice["grand_total"]
            is_debit_note = invoice_total < 0
            max_invoice_amount = abs(invoice_total)
            allocation_amount = min(remaining, max_invoice_amount)

            allocations.append(
                {
                    "invoice": invoice,
                    "amount": allocation_amount,
                    "is_debit_note": is_debit_note,
                }
            )
            remaining -= allocation_amount

        # Second pass: adjust last allocation to ensure sum equals paid_amount exactly
        allocated_so_far = 0.0
        for i, alloc in enumerate(allocations):
            invoice = alloc["invoice"]
            is_debit_note = alloc["is_debit_note"]

            is_last = i == len(allocations) - 1
            if use_floating_point_fix and is_last:
                # Last allocation = remaining amount to match paid_amount exactly
                allocation = flt(paid_amount - allocated_so_far, 2)
                if is_debit_note:
                    allocation = -abs(allocation)
            else:
                allocation = -alloc["amount"] if is_debit_note else alloc["amount"]
                allocated_so_far += abs(allocation)

            # For E-Boekhouden Type 3/4 payments, bypass outstanding amount validation
            outstanding_for_ref = 0 if is_debit_note else invoice["grand_total"]

            payment_entry.append(
                "references",
                {
                    "reference_doctype": invoice["doctype"],
                    "reference_name": invoice["name"],
                    "total_amount": invoice["grand_total"],
                    "outstanding_amount": outstanding_for_ref,
                    "allocated_amount": allocation,
                },
            )

            self._log(f"Allocated {allocation} to {invoice['name']} (FIFO, E-Boekhouden authoritative)")

        if remaining > 0.01:  # Allow tiny floating point residual
            self._log(f"WARNING: {remaining} remains unallocated")

    def _simple_invoice_allocation(
        self, payment_entry: frappe._dict, invoice_numbers: List[str], party_type: str
    ):
        """Simple allocation for payments without row details.

        For Type 3/4 payments, trust E-Boekhouden linkage regardless of
        ERPNext outstanding_amount which may be incorrect during batch processing.
        """
        invoice_doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
        invoices = self._find_invoices(invoice_numbers, invoice_doctype, payment_entry.party)

        if invoices:
            # For Type 3/4 payments, don't filter by outstanding_amount
            # E-Boekhouden has already determined the payment-invoice relationship
            for inv in invoices:
                outstanding = flt(inv.get("outstanding_amount", 0))
                grand_total = flt(inv.get("grand_total", 0))
                self._log(
                    f"Allocating to invoice {inv['name']}: grand_total={grand_total}, outstanding={outstanding}"
                )

            # Use FIFO allocation with total payment amount
            self._allocate_fifo(payment_entry, invoices, [])

    def _find_invoices(self, invoice_numbers: List[str], doctype: str, party: str) -> List[Dict]:
        """Find invoices matching the given numbers."""
        invoices = []
        party_field = "customer" if doctype == "Sales Invoice" else "supplier"

        for invoice_num in invoice_numbers:
            # Try multiple matching strategies
            matches = self._find_invoice_by_number(invoice_num, doctype, party_field, party)
            invoices.extend(matches)

        # Remove duplicates and sort by date for FIFO
        seen = set()
        unique_invoices = []
        for inv in invoices:
            if inv["name"] not in seen:
                seen.add(inv["name"])
                unique_invoices.append(inv)

        unique_invoices.sort(key=lambda x: x.get("posting_date", ""))

        return unique_invoices

    def _find_invoice_by_number(
        self, invoice_num: str, doctype: str, party_field: str, party: str
    ) -> List[Dict]:
        """Find invoice using multiple strategies with validation.

        For Type 3/4 payments, ignores outstanding_amount filters since E-Boekhouden
        has already determined the payment-invoice relationship.
        """
        if not invoice_num or not party:
            return []

        try:
            # Validate inputs
            invoice_num = str(invoice_num).strip()[:50]  # Limit length
            if not invoice_num:
                return []

            # Strategy 1: Check if invoice_num is actually a mutation ID (all digits)
            if invoice_num.isdigit() and frappe.db.has_column(doctype, "eboekhouden_mutation_nr"):
                # For Type 3/4 payments, don't filter by outstanding_amount - E-Boekhouden is source of truth
                invoices = frappe.get_all(
                    doctype,
                    filters={
                        party_field: party,
                        "eboekhouden_mutation_nr": invoice_num,
                        "docstatus": 1,
                    },
                    fields=[
                        "name",
                        "grand_total",
                        "outstanding_amount",
                        "posting_date",
                        "eboekhouden_invoice_number",
                    ],
                    limit=5,  # Limit results
                )

                if invoices:
                    for inv in invoices:
                        inv["doctype"] = doctype
                    self._log(
                        f"Found invoice {invoices[0]['name']} via eboekhouden_mutation_nr: {invoice_num}"
                    )
                    return invoices

            # Strategy 2: E-Boekhouden invoice number field
            if frappe.db.has_column(doctype, "eboekhouden_invoice_number"):
                # For Type 3/4 payments, find all matching invoices regardless of outstanding_amount
                invoices = frappe.get_all(
                    doctype,
                    filters={
                        party_field: party,
                        "eboekhouden_invoice_number": invoice_num,
                        "docstatus": 1,
                    },
                    fields=["name", "grand_total", "outstanding_amount", "posting_date"],
                )

                if invoices:
                    for inv in invoices:
                        inv["doctype"] = doctype
                        outstanding = flt(inv.get("outstanding_amount", 0))
                        self._log(
                            f"Found invoice {inv['name']} via eboekhouden_invoice_number (outstanding: {outstanding})"
                        )
                    return invoices

            # Strategy 3: Exact name match
            # For Type 3/4 payments, don't filter by outstanding_amount
            invoices = frappe.get_all(
                doctype,
                filters={
                    party_field: party,
                    "name": invoice_num,
                    "docstatus": 1,
                },
                fields=["name", "grand_total", "outstanding_amount", "posting_date"],
            )

            if invoices:
                for inv in invoices:
                    inv["doctype"] = doctype
                self._log(f"Found invoice {invoices[0]['name']} via exact name match")
                return invoices

            # Strategy 4: Partial match (last resort)
            # For Type 3/4 payments, don't filter by outstanding_amount
            invoices = frappe.get_all(
                doctype,
                filters={
                    party_field: party,
                    "name": ["like", f"%{invoice_num}%"],
                    "docstatus": 1,
                },
                fields=["name", "grand_total", "outstanding_amount", "posting_date"],
                limit=1,
            )

            if invoices:
                for inv in invoices:
                    inv["doctype"] = doctype
                self._log(f"Found invoice {invoices[0]['name']} via partial match")
                return invoices

            self._log(f"No invoice found for number: {invoice_num}")
            return []

        except Exception as e:
            self._log(f"ERROR: Failed to find invoice for number {invoice_num}: {str(e)[:100]}")
            return []

    def _generate_remarks(self, mutation: Dict, bank_account: str, party: str) -> str:
        """Generate detailed remarks for audit trail."""
        remarks = []

        remarks.append(f"E-Boekhouden Import - Mutation {mutation.get('id')}")
        remarks.append(f"Type: {'Customer Payment' if mutation.get('type') == 3 else 'Supplier Payment'}")
        remarks.append(f"Bank Account: {bank_account}")

        if party:
            remarks.append(f"Party: {party} (Relation ID: {mutation.get('relationId')})")

        if mutation.get("invoiceNumber"):
            remarks.append(f"Invoice(s): {mutation.get('invoiceNumber')}")

        if mutation.get("description"):
            remarks.append(f"Description: {mutation.get('description')}")

        if mutation.get("rows"):
            remarks.append(f"Row count: {len(mutation.get('rows'))}")

        remarks.append(f"Original Ledger ID: {mutation.get('ledgerId')}")

        return "\n".join(remarks)

    def _get_party_account_with_invoice_priority(self, mutation: Dict, party_type: str, party: str) -> str:
        """
        Get party account with invoice-first priority to avoid account mismatches.

        Priority order:
        1. Invoice-specific accounts (if invoices found - most reliable)
        2. API row ledger data (ONLY for invoice mutations types 1 & 2)
        3. Party default accounts (fallback for payment mutations types 3 & 4)
        """
        # PRIORITY 1: Use existing invoice accounts if we have matching invoices
        invoice_account = self._get_account_from_matched_invoices(party_type, party)
        if invoice_account:
            self._log(f"Using matched invoice account: {invoice_account}")
            return invoice_account

        # PRIORITY 2: For invoice mutations (types 1 & 2), use API row ledger data
        # For payment mutations (types 3 & 4), skip API row data as it contains
        # control accounts (Crediteuren/Debiteuren) which are not valid for Payment Entries
        mutation_type = mutation.get("type")
        if mutation_type in [1, 2]:
            # Invoice mutations - row ledgers contain correct party accounts
            return self._get_party_account_from_api_rows(mutation, party_type, party)
        else:
            # Payment mutations (types 3 & 4) - skip API row data, use party/invoice defaults
            self._log(
                f"Payment mutation (type {mutation_type}) - skipping API row ledger, "
                f"using party/invoice account fallback"
            )
            return self._get_party_account_from_api_rows(mutation, party_type, party, skip_api_rows=True)

    def _get_account_from_matched_invoices(self, party_type: str, party: str) -> Optional[str]:
        """
        Get receivable/payable account from matched invoices to ensure consistency.
        """
        if not hasattr(self, "_current_invoice_numbers") or not self._current_invoice_numbers:
            return None

        # Check what account the matched invoices are using
        for invoice_num in self._current_invoice_numbers:
            if party_type == "Customer":
                account = frappe.db.get_value(
                    "Sales Invoice",
                    {"customer": party, "eboekhouden_invoice_number": invoice_num, "docstatus": 1},
                    "debit_to",
                )
                if account:
                    self._log(f"Found receivable account from invoice {invoice_num}: {account}")
                    # Ensure the account is configured as Receivable type
                    from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                        ensure_account_type_is_correct,
                    )

                    debug_info = []
                    ensure_account_type_is_correct(account, "Receivable", debug_info, auto_fix=True)
                    for msg in debug_info:
                        self._log(msg)
                    return account
            else:  # Supplier
                account = frappe.db.get_value(
                    "Purchase Invoice",
                    {"supplier": party, "eboekhouden_invoice_number": invoice_num, "docstatus": 1},
                    "credit_to",
                )
                if account:
                    self._log(f"Found payable account from invoice {invoice_num}: {account}")
                    # Ensure the account is configured as Payable type
                    from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                        ensure_account_type_is_correct,
                    )

                    debug_info = []
                    ensure_account_type_is_correct(account, "Payable", debug_info, auto_fix=True)
                    for msg in debug_info:
                        self._log(msg)
                    return account
        return None

    def _get_party_account_from_api_rows(
        self, mutation: Dict, party_type: str, party: str, skip_api_rows: bool = False
    ) -> str:
        """
        Get party account using API row ledger data with intelligent fallbacks.

        Priority order:
        1. API row ledger data (only for invoice mutations, skipped for payment mutations)
        2. Party default accounts (fallback)

        Args:
            mutation: E-Boekhouden mutation data
            party_type: "Customer" or "Supplier"
            party: Party name
            skip_api_rows: If True, skip API row ledger lookup (for payment mutations)
        """
        # PRIORITY 1: Get receivable/payable account from API row ledger data
        # Skip for payment mutations (types 3 & 4) as they contain control accounts
        rows = mutation.get("rows", [])

        if not skip_api_rows and rows and len(rows) > 0:
            row_ledger_id = rows[0].get("ledgerId")
            if row_ledger_id:
                mapping_result = frappe.db.get_value(
                    "E-Boekhouden Ledger Mapping", {"ledger_id": row_ledger_id}, "erpnext_account"
                )
                if mapping_result:
                    self._log(f"Using API row ledger {row_ledger_id} -> {mapping_result}")
                    # Ensure the account is configured correctly
                    from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                        ensure_account_type_is_correct,
                    )

                    expected_type = "Receivable" if party_type == "Customer" else "Payable"
                    debug_info = []
                    ensure_account_type_is_correct(mapping_result, expected_type, debug_info, auto_fix=True)
                    for msg in debug_info:
                        self._log(msg)
                    return mapping_result
                else:
                    self._log(f"WARNING: No mapping found for API row ledger {row_ledger_id}")
        elif skip_api_rows:
            self._log("Skipping API row ledger lookup (payment mutation)")

        # PRIORITY 2: Fall back to existing invoice/party logic only if API data unavailable
        self._log("FALLBACK: API row ledger data not available, using invoice/party lookup")
        fallback_account = self._get_party_account_fallback(party, party_type)

        if not fallback_account:
            # PRIORITY 3: Use company defaults as last resort
            if party_type == "Customer":
                fallback_account = frappe.db.get_value("Company", self.company, "default_receivable_account")
                self._log(f"Using company default receivable account: {fallback_account}")
            else:
                fallback_account = frappe.db.get_value("Company", self.company, "default_payable_account")
                self._log(f"Using company default payable account: {fallback_account}")

        if not fallback_account:
            # Should never happen in a properly configured system
            raise frappe.ValidationError(f"No {party_type.lower()} account found for party {party}")

        # Ensure the fallback account is configured correctly
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
            ensure_account_type_is_correct,
        )

        expected_type = "Receivable" if party_type == "Customer" else "Payable"
        debug_info = []
        ensure_account_type_is_correct(fallback_account, expected_type, debug_info, auto_fix=True)
        for msg in debug_info:
            self._log(msg)

        return fallback_account

    def _get_party_account_fallback(self, party: str, party_type: str) -> str:
        """Get the correct party account, checking invoices first for specific accounts."""
        # First check if there are invoices that specify a particular account
        # This is E-Boekhouden-specific: invoices imported may have specific accounts
        invoice_numbers = self._current_invoice_numbers if hasattr(self, "_current_invoice_numbers") else []

        if invoice_numbers and party_type == "Customer":
            # Check if any Sales Invoice has a specific debtors account
            for invoice_num in invoice_numbers:
                debtors_account = frappe.db.get_value(
                    "Sales Invoice",
                    {"customer": party, "eboekhouden_invoice_number": invoice_num, "docstatus": 1},
                    "debit_to",
                )
                if debtors_account:
                    self._log(f"Using debtors account from invoice: {debtors_account}")
                    return debtors_account
        elif invoice_numbers and party_type == "Supplier":
            # Check if any Purchase Invoice has a specific creditors account
            for invoice_num in invoice_numbers:
                creditors_account = frappe.db.get_value(
                    "Purchase Invoice",
                    {"supplier": party, "eboekhouden_invoice_number": invoice_num, "docstatus": 1},
                    "credit_to",
                )
                if creditors_account:
                    self._log(f"Using creditors account from invoice: {creditors_account}")
                    return creditors_account

        # Fall back to consolidated party account resolution
        from verenigingen.e_boekhouden.utils.consolidated.party_utils import get_party_account

        debug_info = []
        account = get_party_account(party, party_type, self.company, debug_info)

        for msg in debug_info:
            self._log(msg)

        return account

    def _log(self, message: str):
        """Add to debug log."""
        timestamp = nowdate()
        self.debug_log.append(f"{timestamp} {message}")
        frappe.logger().info(f"PaymentHandler: {message}")

    def _validate_payment_direction(
        self, mutation_type: int, amount: float, payment_type: str, party_type: str
    ):
        """Validate that payment direction is correct based on mutation type and amount."""
        # Expected payment types for positive amounts (normal case)
        expected_for_positive = {
            3: "Receive",  # Customer Payment - money comes in
            4: "Pay",  # Supplier Payment - money goes out
        }

        # For negative amounts, payment direction should be reversed
        expected_payment_type = expected_for_positive.get(mutation_type)
        if not expected_payment_type:
            # Not a payment mutation type we validate
            return

        if amount < 0:
            # Negative amount = refund, so reverse the expected direction
            expected_payment_type = "Pay" if expected_payment_type == "Receive" else "Receive"

        if payment_type != expected_payment_type:
            error_msg = (
                f"Payment direction validation failed: "
                f"Mutation type {mutation_type} with amount {amount} should have payment_type '{expected_payment_type}', "
                f"but got '{payment_type}'"
            )
            self._log(f"ERROR: {error_msg}")
            frappe.throw(error_msg, title="Payment Direction Error")

        # Validate party type consistency
        expected_party_type = "Customer" if mutation_type == 3 else "Supplier"
        if party_type != expected_party_type:
            error_msg = (
                f"Party type validation failed: "
                f"Mutation type {mutation_type} should have party_type '{expected_party_type}', "
                f"but got '{party_type}'"
            )
            self._log(f"ERROR: {error_msg}")
            frappe.throw(error_msg, title="Party Type Error")

        self._log(
            f"Payment direction validation passed: type={mutation_type}, amount={amount}, payment_type={payment_type}, party_type={party_type}"
        )

    def _create_bank_transaction_for_payment(
        self, mutation: Dict, payment_entry: frappe._dict, bank_account_name: str
    ) -> Optional[str]:
        """
        Create Bank Transaction for payment mutation with rich description preservation.

        This creates the missing Bank Transaction record that ERPNext expects for proper
        bank reconciliation. The eBoekhouden API only provides mutation data, not the
        underlying bank transactions, so we synthesize them here.

        Args:
            mutation: E-Boekhouden mutation data
            payment_entry: Created Payment Entry document (draft state, not yet submitted)
            bank_account_name: Bank Account DocType name for Bank Transaction creation

        Returns:
            Bank Transaction name if created, None on failure
        """
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        try:
            creator = get_bank_transaction_creator()

            # Get amount from Payment Entry (already calculated correctly from rows or mutation amount)
            amount = payment_entry.paid_amount or payment_entry.received_amount

            # Validate non-zero amount
            if not amount or amount < 0.01:
                self._log(f"Skipping Bank Transaction creation for zero/near-zero amount: {amount}")
                self._bank_tx_stats["bank_tx_skipped_zero_amount"] += 1
                return None

            # Determine sign from Payment Entry payment_type
            # For "Receive" (Type 3), amount is positive (deposit)
            # For "Pay" (Type 4), amount is negative (withdrawal)
            # The sign will be handled by BankTransactionCreator based on payment_type
            bank_transaction_amount = amount if payment_entry.payment_type == "Receive" else -amount

            # Use raw bank description (SEPA data) - this is what the user sees on bank statements
            # Keep it clean without import metadata
            bt_description = mutation.get("description", "")

            # CRITICAL: Always use EB-{mutation_id} as reference for uniqueness
            # Previously tried to extract from description (last token), but this caused
            # collisions when common words like "vertraging" appeared at end of descriptions
            # Example collision: mutation 7949 description ending with "vertraging" matched
            # an existing 2020 Bank Transaction with reference "vertraging", causing
            # "over-allocated" errors when trying to add a second payment entry
            mutation_id = mutation.get("id")
            bt_reference = f"EB-{mutation_id}"  # Guaranteed unique per mutation

            # Create Bank Transaction using service
            transaction_data = {
                "date": payment_entry.posting_date,
                "amount": bank_transaction_amount,  # Signed amount based on payment_type
                "currency": "EUR",  # E-Boekhouden is always EUR
                "description": bt_description,  # Raw SEPA description
                "reference_number": bt_reference,  # Transaction reference for matching
                "party_type": payment_entry.party_type if payment_entry.party else None,
                "party": payment_entry.party if payment_entry.party else None,
            }

            # Link to Member if the Customer is linked to a Member
            if payment_entry.party_type == "Customer" and payment_entry.party:
                from verenigingen.utils.financial_utils import get_member_for_customer

                member_name = get_member_for_customer(payment_entry.party)
                if member_name:
                    transaction_data["custom_member"] = member_name

            bank_transaction_name = creator.create_from_dict(
                transaction_data=transaction_data,
                bank_account=bank_account_name,
                company=self.company,
                source_type="E-Boekhouden Import",
            )

            return bank_transaction_name

        except Exception as e:
            self._log(f"ERROR creating Bank Transaction: {str(e)}")
            frappe.log_error(
                f"Failed to create Bank Transaction for mutation {mutation.get('id')}: {str(e)}",
                "E-Boekhouden Bank Transaction Creation",
            )
            return None

    # Status constants
    BANK_TRANSACTION_STATUS_RECONCILED = "Reconciled"

    def _link_bank_transaction_to_payment(self, bank_transaction_name: str, payment_entry_name: str):
        """
        Link Bank Transaction to Payment Entry for proper reconciliation.

        Uses secure_document_operation() to ensure proper permission validation.

        Args:
            bank_transaction_name: Bank Transaction name
            payment_entry_name: Payment Entry name (draft state)

        Raises:
            frappe.DoesNotExistError: If documents don't exist
            frappe.ValidationError: If linking fails
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        try:
            # Validate Payment Entry exists
            if not frappe.db.exists("Payment Entry", payment_entry_name):
                raise frappe.DoesNotExistError(f"Payment Entry {payment_entry_name} not found")

            # Validate Bank Transaction exists
            if not frappe.db.exists("Bank Transaction", bank_transaction_name):
                raise frappe.DoesNotExistError(f"Bank Transaction {bank_transaction_name} not found")

            # Get documents
            bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
            pe = frappe.get_doc("Payment Entry", payment_entry_name)

            # Add to Bank Transaction Payments child table
            bt.append(
                "payment_entries",
                {
                    "payment_document": "Payment Entry",
                    "payment_entry": payment_entry_name,
                    "allocated_amount": pe.paid_amount or pe.received_amount,
                },
            )

            # Update Bank Transaction status and amounts
            bt.status = self.BANK_TRANSACTION_STATUS_RECONCILED
            bt.allocated_amount = pe.paid_amount or pe.received_amount
            bt.unallocated_amount = 0.0

            # Use secure update operation
            update_result = secure_document_operation(
                operation="update",
                doc=bt,
                justification=f"Linking Bank Transaction to Payment Entry {payment_entry_name} from eBoekhouden import",
                required_permissions=["Bank Transaction:write"],
                allow_system_user=True,  # Allow system context for automated processing
            )

            if not update_result.success:
                # Provide specific error messages based on failure type
                if update_result.errors:
                    error_details = update_result.errors

                    # Check for permission-related errors
                    if any("permission" in str(err).lower() for err in error_details):
                        raise frappe.PermissionError(
                            f"Permission denied while linking Bank Transaction {bank_transaction_name} "
                            f"to Payment Entry {payment_entry_name}. User lacks required permissions: "
                            f"{', '.join(str(e) for e in error_details)}"
                        )

                    # Check for validation errors
                    elif any(
                        "validation" in str(err).lower() or "invalid" in str(err).lower()
                        for err in error_details
                    ):
                        raise frappe.ValidationError(
                            f"Validation failed while linking Bank Transaction {bank_transaction_name} "
                            f"to Payment Entry {payment_entry_name}. Details: {', '.join(str(e) for e in error_details)}"
                        )

                    # Generic error with details
                    else:
                        raise frappe.ValidationError(
                            f"Failed to link Bank Transaction {bank_transaction_name} "
                            f"to Payment Entry {payment_entry_name}. Errors: {', '.join(str(e) for e in error_details)}"
                        )
                else:
                    # No error details provided - this is unusual
                    raise frappe.ValidationError(
                        f"Failed to link Bank Transaction {bank_transaction_name} "
                        f"to Payment Entry {payment_entry_name} with no error details. "
                        f"This may indicate a framework issue - check logs for details."
                    )

            self._log(
                f"Linked Bank Transaction {bank_transaction_name} to Payment Entry {payment_entry_name}"
            )

        except (frappe.DoesNotExistError, frappe.ValidationError, frappe.PermissionError):
            # Re-raise known errors without modification
            raise

        except Exception as e:
            self._log(f"ERROR: Failed to link Bank Transaction to Payment Entry: {str(e)}")
            frappe.log_error(
                f"Bank Transaction linking failed: {str(e)}",
                "E-Boekhouden Bank Transaction Linking",
            )
            # Re-raise to fail atomic transaction if linking fails
            raise frappe.ValidationError(
                f"Failed to link Bank Transaction {bank_transaction_name} to Payment Entry {payment_entry_name}: {str(e)}"
            )

    def get_debug_log(self) -> List[str]:
        """Get the debug log for inspection."""
        return self.debug_log

    def log_bank_transaction_summary(self):
        """
        Log Bank Transaction creation summary to Error Log.

        Should be called at the end of migration batch to provide visibility
        into Bank Transaction creation success/failure rates.
        """
        stats = self._bank_tx_stats

        summary_lines = [
            "=" * 80,
            "BANK TRANSACTION CREATION SUMMARY (Type 3/4 Payments)",
            "=" * 80,
            "",
            f"Total Payment Entries Processed: {stats['total_processed']}",
            f"  ✓ Bank Transactions Created: {stats['bank_tx_created']}",
            f"  ⟳ Bank Transactions Already Existed: {stats['bank_tx_already_existed']}",
            f"  ⊘ Skipped (Zero Amount): {stats['bank_tx_skipped_zero_amount']}",
            f"  ✗ Failed: {stats['bank_tx_failed']}",
            "",
        ]

        # Calculate success rate
        if stats["total_processed"] > 0:
            success_count = stats["bank_tx_created"] + stats["bank_tx_already_existed"]
            success_rate = (success_count / stats["total_processed"]) * 100
            summary_lines.append(f"Success Rate: {success_rate:.1f}%")
            summary_lines.append("")

        # Log failures if any
        if stats["failures"]:
            summary_lines.append("FAILURES:")
            summary_lines.append("-" * 80)
            for i, failure in enumerate(stats["failures"][:20], 1):  # Show first 20
                summary_lines.append(f"{i}. Mutation {failure['mutation_nr']} → {failure['payment_entry']}")
                summary_lines.append(f"   Reason: {failure['reason']}")

            if len(stats["failures"]) > 20:
                summary_lines.append(f"... and {len(stats['failures']) - 20} more failures")

        summary_lines.append("=" * 80)

        summary = "\n".join(summary_lines)

        # Log to Error Log for persistence
        frappe.log_error(title="Bank Transaction Summary - Type 3/4 Payments", message=summary)

        # Also print to console
        print(summary)

        return summary
