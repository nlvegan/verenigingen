"""
Enhanced payment entry handler for E-Boekhouden payment import.

This module handles the creation of Payment Entries from E-Boekhouden mutations,
including proper bank account mapping and multi-invoice reconciliation support.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from verenigingen.e_boekhouden.utils.security_helper import atomic_migration_operation, validate_and_insert


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

        # Use atomic operation only for new payment entries
        try:
            with atomic_migration_operation("payment_processing"):
                return self._process_payment_mutation_internal(mutation)
        except Exception as e:
            self._log(f"ERROR processing mutation {mutation_id}: {str(e)}")
            frappe.log_error(
                f"Payment mutation processing failed: {str(e)}\\nMutation: {json.dumps(mutation, indent=2)}",
                "E-Boekhouden Payment Import",
            )
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

            # Determine payment type and party based on mutation type AND amount sign
            # For negative amounts, payment direction is reversed (refunds)
            raw_amount = flt(mutation.get("amount", 0))
            is_refund = raw_amount < 0

            # Base payment type from mutation type
            base_payment_type = "Receive" if mutation_type == 3 else "Pay"

            # Reverse payment type for refunds (negative amounts)
            if is_refund:
                payment_type = "Pay" if base_payment_type == "Receive" else "Receive"
                self._log(
                    f"Negative amount detected ({raw_amount}) - reversing payment type from {base_payment_type} to {payment_type}"
                )
            else:
                payment_type = base_payment_type

            party_type = "Customer" if mutation_type == 3 else "Supplier"

            # Validate payment direction consistency
            self._validate_payment_direction(mutation_type, raw_amount, payment_type, party_type)

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

            # Create payment entry
            pe = self._create_payment_entry(
                mutation=mutation,
                payment_type=payment_type,
                party_type=party_type,
                party=party,
                bank_account=bank_account,
            )

            # Handle invoice allocations
            # Combine invoice numbers from header and any found in rows
            row_invoice_refs = self._extract_invoice_references_from_rows(mutation)
            all_invoice_refs = list(set(invoice_numbers + row_invoice_refs))  # Remove duplicates

            if all_invoice_refs:
                self._log(f"All invoice references to link: {all_invoice_refs}")
                if mutation.get("rows"):
                    self._allocate_to_invoices(pe, all_invoice_refs, mutation["rows"], party_type)
                else:
                    # Single invoice or no rows - simple allocation
                    self._simple_invoice_allocation(pe, all_invoice_refs, party_type)
            else:
                self._log("WARNING: No invoice references found in payment mutation")

            # Save and submit with proper permissions
            # For E-Boekhouden Type 3/4 payments, bypass ERPNext's "fully paid" validation
            # since E-Boekhouden is the authoritative source for payment-invoice relationships
            try:
                validate_and_insert(pe)
                self._log(f"Created Payment Entry {pe.name}")
            except Exception as e:
                if "has already been fully paid" in str(
                    e
                ) or "cannot be greater than outstanding amount" in str(e):
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
                    self._log(
                        f"Created unallocated Payment Entry {pe.name} (will need manual reconciliation)"
                    )
                else:
                    raise

            # CRITICAL: Create Bank Transaction BEFORE submitting Payment Entry
            # This ensures both operations happen within the same atomic transaction
            # Check if Bank Transaction already exists (idempotency for re-imports)
            existing_bt = frappe.db.get_value(
                "Bank Transaction", {"reference_number": f"EB-{mutation_id}"}, "name"
            )

            if existing_bt:
                self._log(
                    f"Bank Transaction {existing_bt} already exists for mutation {mutation_id}, skipping creation"
                )
                bank_transaction_name = existing_bt
            else:
                self._log(
                    f"ATOMIC TRANSACTION START: Creating Bank Transaction for Payment Entry {pe.name} "
                    f"(Mutation #{mutation_id}, Amount: {pe.paid_amount or pe.received_amount})"
                )

                bank_transaction_name = self._create_bank_transaction_for_payment(mutation, pe, bank_account)
            if bank_transaction_name:
                if not existing_bt:
                    self._log(f"✓ Bank Transaction created: {bank_transaction_name}")

                # Link the bank transaction to payment entry immediately (only if it's not already linked)
                # Check if already linked to avoid "Cannot edit cancelled document" error
                already_linked = frappe.db.exists(
                    "Bank Transaction Payments", {"parent": bank_transaction_name, "payment_entry": pe.name}
                )

                if not already_linked:
                    self._log(
                        f"Linking Bank Transaction {bank_transaction_name} to Payment Entry {pe.name}..."
                    )
                    self._link_bank_transaction_to_payment(bank_transaction_name, pe.name)
                    self._log("✓ Bank Transaction linked successfully")
                else:
                    self._log(
                        f"Bank Transaction {bank_transaction_name} already linked to Payment Entry {pe.name}"
                    )
            else:
                self._log("WARNING: Failed to create Bank Transaction - proceeding with Payment Entry only")

            # Submit Payment Entry (commits both PE and BT together in atomic transaction)
            self._log(f"Submitting Payment Entry {pe.name} (will commit both PE and BT atomically)...")
            pe.submit()
            self._log(
                f"✓ ATOMIC TRANSACTION COMPLETE: Payment Entry {pe.name} submitted "
                f"{f'with linked Bank Transaction {bank_transaction_name}' if bank_transaction_name else 'without Bank Transaction'}"
            )

            return pe.name

        except Exception:
            # Re-raise to let atomic_migration_operation handle rollback
            raise

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
        Determine bank account from ledger mapping.

        Priority:
        1. Direct ledger mapping to bank/cash account
        2. Payment configuration based on ledger code
        3. Pattern matching from description
        4. Intelligent defaults
        """
        if not ledger_id:
            self._log("WARNING: No ledger ID provided, using defaults")
            return self._get_default_bank_account(payment_type)

        # Check cache first
        cache_key = f"{ledger_id}:{payment_type}"
        if cache_key in self._ledger_cache:
            return self._ledger_cache[cache_key]

        # Try direct mapping
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": ledger_id},
            ["erpnext_account", "ledger_code", "ledger_name"],
            as_dict=True,
        )

        if mapping and mapping.get("erpnext_account"):
            # Verify it's a bank/cash account
            account_type = frappe.db.get_value("Account", mapping["erpnext_account"], "account_type")

            if account_type in ["Bank", "Cash"]:
                self._log(
                    f"Mapped ledger {ledger_id} ({mapping.get('ledger_name')}) to {mapping['erpnext_account']}"
                )
                self._ledger_cache[cache_key] = mapping["erpnext_account"]
                return mapping["erpnext_account"]
            else:
                self._log(f"WARNING: Ledger {ledger_id} maps to {account_type} account, not Bank/Cash")

        # Try payment configuration based on ledger code
        if mapping and mapping.get("ledger_code"):
            from verenigingen.e_boekhouden.utils.eboekhouden_migration_config import get_payment_account_info

            account_info = get_payment_account_info(mapping["ledger_code"], self.company)
            if account_info and account_info.get("erpnext_account"):
                self._log(f"Found bank account via payment config: {account_info['erpnext_account']}")
                self._ledger_cache[cache_key] = account_info["erpnext_account"]
                return account_info["erpnext_account"]

        # Try pattern matching on description
        if description:
            bank_account = self._get_account_from_pattern(description, payment_type)
            if bank_account:
                self._log(f"Found bank account via pattern matching: {bank_account}")
                self._ledger_cache[cache_key] = bank_account
                return bank_account

        # Fallback to defaults
        default_account = self._get_default_bank_account(payment_type)
        self._log(f"Using default bank account: {default_account}")
        self._ledger_cache[cache_key] = default_account
        return default_account

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

    def _get_default_bank_account(self, payment_type: str) -> str:
        """Get intelligent default account based on payment type using configurable mapping."""
        from verenigingen.e_boekhouden.utils.configurable_account_mapper import get_account_mapper

        mapper = get_account_mapper(self.company)

        if payment_type == "Receive":
            # Customer payments typically go to main bank account
            main_bank = mapper.get_account_by_purpose("main_bank")
            if main_bank:
                return main_bank

        # Fallback to any active bank account
        bank_account = frappe.db.get_value(
            "Account", {"account_type": "Bank", "company": self.company, "is_group": 0, "disabled": 0}, "name"
        )

        if bank_account:
            return bank_account

        # Last resort - cash account lookup or error
        cash_account = mapper.get_account_by_purpose("cash")
        if cash_account:
            return cash_account

        # If no cash account exists, this is a configuration error
        frappe.throw(
            f"No suitable payment account found for company {self.company}. "
            "Please ensure bank accounts and cash account are properly configured.",
            title="Payment Account Configuration Error",
        )

    def _get_or_create_party(self, relation_id: str, party_type: str, description: str) -> Optional[str]:
        """Get existing party or create new one."""
        if not relation_id:
            return None

        # Try to use existing system first, fall back to simple handler if it fails
        try:
            if party_type == "Customer":
                from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                    _get_or_create_customer,
                )

                return _get_or_create_customer(relation_id, self.debug_log)
            else:
                from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                    _get_or_create_supplier,
                )

                return _get_or_create_supplier(relation_id, description, self.debug_log)
        except Exception as e:
            self._log(f"Error with standard party creation: {str(e)}, using simple handler")

            # Fall back to simple handler
            from verenigingen.e_boekhouden.utils.simple_party_handler import (
                get_or_create_customer_simple,
                get_or_create_supplier_simple,
            )

            if party_type == "Customer":
                return get_or_create_customer_simple(relation_id, self.debug_log)
            else:
                return get_or_create_supplier_simple(relation_id, description, self.debug_log)

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
            amount = sum(row_amounts)
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

        if payment_type == "Receive":
            pe.received_amount = amount
            pe.paid_amount = amount
        else:
            pe.paid_amount = amount
            pe.received_amount = amount

        # Set party details
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

        # Log invoice status for debugging
        for inv in invoices:
            outstanding = flt(inv.get("outstanding_amount", 0))
            grand_total = flt(inv.get("grand_total", 0))
            self._log(f"Found invoice {inv['name']}: grand_total={grand_total}, outstanding={outstanding}")

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
        """
        for invoice, amount in zip(invoices, row_amounts):
            # For Type 3/4 payments, use E-Boekhouden amount directly
            # Don't limit by outstanding_amount due to race conditions
            allocation = amount

            # For E-Boekhouden Type 3/4 payments, bypass outstanding amount validation
            # since E-Boekhouden is the authoritative source for payment-invoice relationships
            payment_entry.append(
                "references",
                {
                    "reference_doctype": invoice["doctype"],
                    "reference_name": invoice["name"],
                    "total_amount": invoice["grand_total"],
                    "outstanding_amount": invoice[
                        "grand_total"
                    ],  # Set to grand_total to allow any allocation
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
        """
        total_to_allocate = (
            sum(row_amounts) if row_amounts else payment_entry.paid_amount or payment_entry.received_amount
        )

        for invoice in invoices:
            if total_to_allocate <= 0:
                break

            # For Type 3/4 payments, allocate what E-Boekhouden specifies
            # Use grand_total as maximum to prevent extreme overpayments
            max_allocation = min(total_to_allocate, invoice["grand_total"])
            allocation = max_allocation

            # For E-Boekhouden Type 3/4 payments, bypass outstanding amount validation
            # since E-Boekhouden is the authoritative source for payment-invoice relationships
            payment_entry.append(
                "references",
                {
                    "reference_doctype": invoice["doctype"],
                    "reference_name": invoice["name"],
                    "total_amount": invoice["grand_total"],
                    "outstanding_amount": invoice[
                        "grand_total"
                    ],  # Set to grand_total to allow any allocation
                    "allocated_amount": allocation,
                },
            )

            total_to_allocate -= allocation
            self._log(f"Allocated {allocation} to {invoice['name']} (FIFO, E-Boekhouden authoritative)")

        if total_to_allocate > 0:
            self._log(f"WARNING: {total_to_allocate} remains unallocated")

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
        2. API row ledger data (if no invoices)
        3. Party default accounts (last resort)
        """
        # PRIORITY 1: Use existing invoice accounts if we have matching invoices
        invoice_account = self._get_account_from_matched_invoices(party_type, party)
        if invoice_account:
            self._log(f"Using matched invoice account: {invoice_account}")
            return invoice_account

        # PRIORITY 2: Fall back to API row ledger data
        return self._get_party_account_from_api_rows(mutation, party_type, party)

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
                    return account
            else:  # Supplier
                account = frappe.db.get_value(
                    "Purchase Invoice",
                    {"supplier": party, "eboekhouden_invoice_number": invoice_num, "docstatus": 1},
                    "credit_to",
                )
                if account:
                    self._log(f"Found payable account from invoice {invoice_num}: {account}")
                    return account
        return None

    def _get_party_account_from_api_rows(self, mutation: Dict, party_type: str, party: str) -> str:
        """
        Get party account using API row ledger data with intelligent fallbacks.

        Priority order:
        1. API row ledger data
        2. Party default accounts (fallback)
        """
        # PRIORITY 1: Get receivable/payable account from API row ledger data
        rows = mutation.get("rows", [])

        if rows and len(rows) > 0:
            row_ledger_id = rows[0].get("ledgerId")
            if row_ledger_id:
                mapping_result = frappe.db.get_value(
                    "E-Boekhouden Ledger Mapping", {"ledger_id": row_ledger_id}, "erpnext_account"
                )
                if mapping_result:
                    self._log(f"Using API row ledger {row_ledger_id} -> {mapping_result}")
                    return mapping_result
                else:
                    self._log(f"WARNING: No mapping found for API row ledger {row_ledger_id}")

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

        return fallback_account

    def _get_party_account_fallback(self, party: str, party_type: str) -> str:
        """Get the correct party account, checking invoices first for specific accounts."""
        # First check if there are invoices that specify a particular account
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

        # Fall back to party's default account
        if party_type == "Customer":
            # Get default receivable account from customer's accounts child table
            accounts = frappe.db.sql(
                """
                SELECT pa.account
                FROM `tabParty Account` pa
                WHERE pa.parent = %s AND pa.parenttype = 'Customer' AND pa.company = %s
                LIMIT 1
            """,
                (party, self.company),
                as_dict=True,
            )
            if accounts:
                return accounts[0].account
        else:
            # Get default payable account from supplier's accounts child table
            accounts = frappe.db.sql(
                """
                SELECT pa.account
                FROM `tabParty Account` pa
                WHERE pa.parent = %s AND pa.parenttype = 'Supplier' AND pa.company = %s
                LIMIT 1
            """,
                (party, self.company),
                as_dict=True,
            )
            if accounts:
                return accounts[0].account

        # Final fallback to default receivable/payable account
        account_type = "Receivable" if party_type == "Customer" else "Payable"
        return frappe.db.get_value("Account", {"account_type": account_type, "company": self.company}, "name")

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
        self, mutation: Dict, payment_entry: frappe._dict, bank_account: str
    ) -> Optional[str]:
        """
        Create Bank Transaction for payment mutation with rich description preservation.

        This creates the missing Bank Transaction record that ERPNext expects for proper
        bank reconciliation. The eBoekhouden API only provides mutation data, not the
        underlying bank transactions, so we synthesize them here.

        Args:
            mutation: E-Boekhouden mutation data
            payment_entry: Created Payment Entry document (draft state, not yet submitted)
            bank_account: Bank account used in Payment Entry

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
                return None

            # Determine sign from Payment Entry payment_type
            # For "Receive" (Type 3), amount is positive (deposit)
            # For "Pay" (Type 4), amount is negative (withdrawal)
            # The sign will be handled by BankTransactionCreator based on payment_type
            bank_transaction_amount = amount if payment_entry.payment_type == "Receive" else -amount

            # Use raw bank description (SEPA data) - this is what the user sees on bank statements
            # Keep it clean without import metadata
            bt_description = mutation.get("description", "")

            # Extract reference number from end of description
            # Common patterns: "Bestelling 50019 tr_ABC123" or "Invoice 12345" or just "50019"
            # We take the last meaningful token as the reference
            mutation_id = mutation.get("id")
            bt_reference = f"EB-{mutation_id}"  # Fallback

            if bt_description:
                # Split by whitespace and get last 3 tokens (common reference location)
                tokens = bt_description.strip().split()
                if tokens:
                    # Take last token as reference (e.g., "tr_WDyL7bgZmU" or "50019")
                    # Filter out very short tokens (like "A" or single digits)
                    candidate = tokens[-1]
                    if len(candidate) >= 3 and not candidate.startswith("("):
                        bt_reference = candidate
                    elif len(tokens) >= 2:
                        # Try second-to-last if last token is too short
                        candidate = tokens[-2]
                        if len(candidate) >= 3:
                            bt_reference = candidate

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

            bank_transaction_name = creator.create_from_dict(
                transaction_data=transaction_data,
                bank_account=bank_account,
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
