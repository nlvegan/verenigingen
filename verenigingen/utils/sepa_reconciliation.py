import re
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.utils import flt


class SEPAReconciliationManager:
    """Manages automatic reconciliation of SEPA payments with bank transactions"""

    def __init__(self):
        self.settings = frappe.get_single("Verenigingen Settings")
        self.match_threshold = 0.85  # 85% similarity required for auto-match

    @frappe.whitelist()
    def reconcile_bank_transactions(self, bank_account=None, from_date=None, to_date=None):
        """Reconcile imported bank transactions with SEPA batches"""

        # Get unreconciled bank transactions
        filters = {"status": "Pending", "reference_type": ["is", "not set"]}

        if bank_account:
            filters["bank_account"] = bank_account

        if from_date:
            filters["date"] = [">=", from_date]

        if to_date:
            filters["date"] = ["<=", to_date]

        transactions = frappe.get_all(
            "Bank Transaction",
            filters=filters,
            fields=[
                "name",
                "date",
                "credit",
                "debit",
                "description",
                "bank_account",
                "reference_number",
                "party_iban",
            ],
        )

        matched_count = 0
        for transaction in transactions:
            if self.match_transaction(transaction):
                matched_count += 1

        return {
            "total_transactions": len(transactions),
            "matched": matched_count,
            "unmatched": len(transactions) - matched_count,
        }

    def match_transaction(self, transaction):
        """Try to match a bank transaction with SEPA payments"""

        # Try different matching strategies
        matches = []

        # Strategy 1: Match by SEPA batch reference
        if transaction.get("reference_number"):
            batch_match = self.match_by_batch_reference(transaction)
            if batch_match:
                matches.append(batch_match)

        # Strategy 2: Match by amount and IBAN
        if transaction.get("party_iban"):
            amount_match = self.match_by_amount_and_iban(transaction)
            if amount_match:
                matches.append(amount_match)

        # Strategy 3: Match by description patterns
        desc_match = self.match_by_description(transaction)
        if desc_match:
            matches.append(desc_match)

        # Select best match
        if matches:
            best_match = max(matches, key=lambda x: x["confidence"])
            if best_match["confidence"] >= self.match_threshold:
                return self.create_reconciliation(transaction, best_match)

        return False

    def match_by_batch_reference(self, transaction):
        """Match transaction by SEPA batch reference"""

        # Look for batch reference in transaction description
        batch_pattern = r"BATCH-([A-Z0-9-]+)"
        match = re.search(batch_pattern, transaction.get("description", ""))

        if match:
            batch_ref = match.group(1)

            # Find matching batch
            batch = frappe.db.exists("Direct Debit Batch", {"name": ["like", f"%{batch_ref}%"]})

            if batch:
                batch_doc = frappe.get_doc("Direct Debit Batch", batch)

                # Verify amount matches
                if flt(transaction["credit"]) == flt(batch_doc.total_amount):
                    return {
                        "type": "batch",
                        "reference": batch,
                        "confidence": 1.0,
                        "match_reason": "Exact batch reference match",
                    }

        return None

    def match_by_amount_and_iban(self, transaction):
        """Match transaction by amount and IBAN"""

        amount = flt(transaction.get("credit", 0))
        iban = transaction.get("party_iban", "").replace(" ", "").upper()

        if not amount or not iban:
            return None

        # Find invoices with matching amount and IBAN
        matching_invoices = frappe.db.sql(
            """
            SELECT
                ddi.parent as batch,
                ddi.invoice,
                ddi.amount,
                ddi.iban,
                ddi.member_name
            FROM `tabDirect Debit Invoice` ddi
            JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
            WHERE
                ddi.amount = %s
                AND REPLACE(UPPER(ddi.iban), ' ', '') = %s
                AND ddb.status IN ('Submitted', 'Processed')
                AND ddb.batch_date BETWEEN DATE_SUB(%s, INTERVAL 7 DAY) AND DATE_ADD(%s, INTERVAL 7 DAY)
        """,
            (amount, iban, transaction["date"], transaction["date"]),
            as_dict=True,
        )

        if matching_invoices:
            # If single match, high confidence
            if len(matching_invoices) == 1:
                return {
                    "type": "invoice",
                    "reference": matching_invoices[0]["invoice"],
                    "batch": matching_invoices[0]["batch"],
                    "confidence": 0.95,
                    "match_reason": f'Amount and IBAN match for {matching_invoices[0]["member_name"]}',
                }
            else:
                # Multiple matches, need more context
                return {
                    "type": "multiple",
                    "matches": matching_invoices,
                    "confidence": 0.7,
                    "match_reason": f"Multiple invoices match amount {amount}",
                }

        return None

    def match_by_description(self, transaction):
        """Match transaction by description patterns"""

        description = transaction.get("description", "").upper()

        # Common patterns in SEPA descriptions
        patterns = [
            (r"INVOICE\s+([A-Z0-9-]+)", "invoice"),
            (r"MEMBERSHIP\s+([A-Z0-9-]+)", "membership"),
            (r"MEMBER\s+ID\s*:?\s*([A-Z0-9-]+)", "member"),
            (r"MANDATE\s*:?\s*([A-Z0-9-]+)", "mandate"),
        ]

        for pattern, match_type in patterns:
            match = re.search(pattern, description)
            if match:
                reference = match.group(1)

                if match_type == "invoice":
                    if frappe.db.exists("Sales Invoice", reference):
                        return {
                            "type": "invoice",
                            "reference": reference,
                            "confidence": 0.9,
                            "match_reason": "Invoice number found in description",
                        }

                elif match_type == "membership":
                    if frappe.db.exists("Membership", reference):
                        # Get related invoice
                        invoice = frappe.db.get_value(
                            "Sales Invoice",
                            {"membership": reference, "status": ["in", ["Unpaid", "Overdue"]]},
                            "name",
                        )
                        if invoice:
                            return {
                                "type": "invoice",
                                "reference": invoice,
                                "confidence": 0.85,
                                "match_reason": f"Membership {reference} found in description",
                            }

                elif match_type == "member":
                    # Find unpaid invoices for member
                    member_invoices = self.get_member_unpaid_invoices(reference, transaction["credit"])
                    if member_invoices:
                        return {
                            "type": "member",
                            "reference": member_invoices[0],
                            "confidence": 0.8,
                            "match_reason": f"Member ID {reference} found in description",
                        }

        # Fuzzy matching on member names
        return self.fuzzy_match_member_name(description, transaction["credit"])

    def fuzzy_match_member_name(self, description, amount):
        """Try to match based on member name in description"""

        # Get members with unpaid invoices of matching amount
        members_with_invoices = frappe.db.sql(
            """
            SELECT DISTINCT
                m.name as member_id,
                m.full_name,
                si.name as invoice
            FROM `tabMember` m
            JOIN `tabMembership` ms ON ms.member = m.name
            JOIN `tabSales Invoice` si ON si.membership = ms.name
            WHERE
                si.outstanding_amount = %s
                AND si.status IN ('Unpaid', 'Overdue')
        """,
            (amount,),
            as_dict=True,
        )

        best_match = None
        best_score = 0

        for member in members_with_invoices:
            # Calculate similarity between member name and description
            score = SequenceMatcher(None, member["full_name"].upper(), description).ratio()

            if score > best_score and score > 0.6:  # At least 60% match
                best_score = score
                best_match = member

        if best_match:
            return {
                "type": "invoice",
                "reference": best_match["invoice"],
                "confidence": best_score * 0.9,  # Reduce confidence for fuzzy matches
                "match_reason": f'Name match: {best_match["full_name"]} (score: {best_score:.2f})',
            }

        return None

    def get_member_unpaid_invoices(self, member_id, amount):
        """Get unpaid invoices for a member with matching amount"""

        return frappe.db.sql_list(
            """
            SELECT si.name
            FROM `tabSales Invoice` si
            JOIN `tabMembership` ms ON si.membership = ms.name
            WHERE
                ms.member = %s
                AND si.outstanding_amount = %s
                AND si.status IN ('Unpaid', 'Overdue')
            ORDER BY si.due_date DESC
        """,
            (member_id, amount),
        )

    def create_reconciliation(self, transaction, match):
        """Create reconciliation entry for matched transaction"""

        try:
            bank_trans = frappe.get_doc("Bank Transaction", transaction["name"])

            if match["type"] in ["invoice", "batch"]:
                # Create payment entry
                payment_entry = self.create_payment_entry_from_transaction(
                    bank_trans, match["reference"], match.get("batch")
                )

                # Update bank transaction
                bank_trans.status = "Reconciled"
                bank_trans.reference_type = "Payment Entry"
                bank_trans.reference_name = payment_entry.name
                bank_trans.add_comment(
                    "Comment",
                    f'Auto-reconciled: {match["match_reason"]} (Confidence: {match["confidence"]:.0%})',
                )
                bank_trans.save()

                return True

            elif match["type"] == "multiple":
                # Flag for manual review
                bank_trans.add_comment(
                    "Comment",
                    f'Multiple matches found: {len(match["matches"])} invoices with amount {transaction["credit"]}',
                )
                return False

        except Exception as e:
            frappe.log_error(f"Reconciliation error: {str(e)}", "SEPA Reconciliation")
            return False

    def create_payment_entry_from_transaction(self, bank_trans, invoice_name, batch_name=None):
        """Create payment entry from bank transaction"""

        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Get the invoice
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Create payment entry
        payment_entry = get_payment_entry(dt="Sales Invoice", dn=invoice.name, party_amount=bank_trans.credit)

        # Set payment details
        payment_entry.posting_date = bank_trans.date
        payment_entry.reference_no = bank_trans.reference_number or batch_name
        payment_entry.reference_date = bank_trans.date
        payment_entry.mode_of_payment = "SEPA Direct Debit"

        # Link to bank transaction
        payment_entry.bank_transaction = bank_trans.name

        # Save and submit
        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()

        # Update membership payment status
        if invoice.membership:
            membership = frappe.get_doc("Membership", invoice.membership)
            membership.payment_status = "Paid"
            membership.payment_date = bank_trans.date
            membership.flags.ignore_validate_update_after_submit = True
            membership.save()

        return payment_entry


@frappe.whitelist()
def process_sepa_return_file(file_content, file_type="pain.002"):
    """Process SEPA return/status file from bank"""

    SEPAReconciliationManager()

    if file_type == "pain.002":
        # Parse pain.002 status report
        return_data = parse_pain002_file(file_content)
    else:
        # Parse other formats (MT940, CAMT, etc.)
        frappe.throw(_("File type {0} not yet supported").format(file_type))

    processed_count = 0

    for return_item in return_data:
        if return_item["status"] == "Rejected":
            # Handle rejection
            handle_payment_rejection(
                return_item["end_to_end_id"], return_item["reason_code"], return_item["reason_text"]
            )
            processed_count += 1

        elif return_item["status"] == "Accepted":
            # Mark as successfully processed
            mark_payment_successful(return_item["end_to_end_id"])
            processed_count += 1

    return {"processed": processed_count, "total": len(return_data)}


def parse_pain002_file(file_content):
    """Parse pain.002 XML file"""
    # Implementation would parse the XML and extract status information
    # This is a placeholder for the actual XML parsing logic


def handle_payment_rejection(end_to_end_id, reason_code, reason_text):
    """Handle rejected SEPA payment"""

    # Extract invoice number from end-to-end ID
    invoice_match = re.search(r"E2E-(.+)", end_to_end_id)
    if not invoice_match:
        return

    invoice_name = invoice_match.group(1)

    # Schedule retry
    from verenigingen.utils.payment_retry import PaymentRetryManager

    retry_manager = PaymentRetryManager()
    retry_manager.schedule_retry(invoice_name, reason_code, reason_text)


def mark_payment_successful(end_to_end_id):
    """Mark payment as successful"""

    # Extract invoice number from end-to-end ID
    invoice_match = re.search(r"E2E-(.+)", end_to_end_id)
    if not invoice_match:
        return

    invoice_name = invoice_match.group(1)

    # Update invoice status
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.status in ["Unpaid", "Overdue"]:
        # Payment will be created when bank transaction is imported
        invoice.add_comment("Comment", "SEPA payment accepted by bank")


@frappe.whitelist()
def get_reconciliation_summary(from_date=None, to_date=None):
    """Get summary of reconciliation status"""

    filters = {}
    if from_date:
        filters["date"] = [">=", from_date]
    if to_date:
        filters["date"] = ["<=", to_date]

    summary = {
        "total_transactions": frappe.db.count("Bank Transaction", filters),
        "reconciled": frappe.db.count("Bank Transaction", {**filters, "status": "Reconciled"}),
        "pending": frappe.db.count("Bank Transaction", {**filters, "status": "Pending"}),
        "unmatched": frappe.db.count("Bank Transaction", {**filters, "status": "Unmatched"}),
    }

    summary["reconciliation_rate"] = (
        (summary["reconciled"] / summary["total_transactions"] * 100)
        if summary["total_transactions"] > 0
        else 0
    )

    return summary


def reconcile_bank_transactions(bank_account=None, from_date=None, to_date=None):
    """Module-level function for scheduled job to reconcile bank transactions"""
    manager = SEPAReconciliationManager()
    return manager.reconcile_bank_transactions(bank_account, from_date, to_date)
