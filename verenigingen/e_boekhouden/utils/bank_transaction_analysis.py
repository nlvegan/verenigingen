"""
Bank Transaction Creation Analysis

Analyzes why Bank Transactions were not created for eBoekhouden imports
and logs detailed failure reasons to Error Log.
"""

import frappe
from frappe.utils import now_datetime


class BankTransactionAnalysisResult:
    """Container for analysis results"""

    def __init__(self):
        self.total_payment_entries = 0
        self.payment_entries_with_bank_tx = 0
        self.payment_entries_without_bank_tx = 0
        self.total_journal_entries = 0
        self.failure_categories = {}
        self.detailed_failures = []

    def add_failure(self, category, mutation_nr, payment_entry, reason):
        """Add a failure record"""
        if category not in self.failure_categories:
            self.failure_categories[category] = 0
        self.failure_categories[category] += 1

        self.detailed_failures.append(
            {
                "category": category,
                "mutation_nr": mutation_nr,
                "payment_entry": payment_entry,
                "reason": reason,
            }
        )

    def get_summary(self):
        """Get formatted summary"""
        lines = [
            "=" * 80,
            "BANK TRANSACTION CREATION ANALYSIS SUMMARY",
            "=" * 80,
            "",
            f"Analysis Time: {now_datetime()}",
            "",
            "OVERVIEW:",
            f"  Total Payment Entries from eBoekhouden: {self.total_payment_entries:,}",
            f"  Payment Entries WITH Bank Transactions: {self.payment_entries_with_bank_tx:,} ({self._pct(self.payment_entries_with_bank_tx, self.total_payment_entries)}%)",
            f"  Payment Entries WITHOUT Bank Transactions: {self.payment_entries_without_bank_tx:,} ({self._pct(self.payment_entries_without_bank_tx, self.total_payment_entries)}%)",
            f"  Total Journal Entries from eBoekhouden: {self.total_journal_entries:,}",
            "",
            "FAILURE CATEGORIES:",
        ]

        for category, count in sorted(self.failure_categories.items(), key=lambda x: x[1], reverse=True):
            pct = self._pct(count, self.payment_entries_without_bank_tx)
            lines.append(f"  {category}: {count:,} ({pct}%)")

        lines.extend(
            [
                "",
                "=" * 80,
                "",
                "DETAILED BREAKDOWN:",
                "",
            ]
        )

        # Group by category
        by_category = {}
        for failure in self.detailed_failures:
            cat = failure["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(failure)

        for category in sorted(by_category.keys(), key=lambda c: len(by_category[c]), reverse=True):
            failures = by_category[category]
            lines.append(f"\n{category} ({len(failures)} cases):")
            lines.append("-" * 80)

            # Show first 10 examples
            for i, failure in enumerate(failures[:10], 1):
                lines.append(f"  {i}. Mutation {failure['mutation_nr']} → {failure['payment_entry']}")
                lines.append(f"     Reason: {failure['reason']}")

            if len(failures) > 10:
                lines.append(f"  ... and {len(failures) - 10} more")

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)

    @staticmethod
    def _pct(value, total):
        """Calculate percentage"""
        if total == 0:
            return 0
        return round((value / total) * 100, 1)


def analyze_bank_transaction_creation():
    """
    Analyze why Bank Transactions were not created for Payment Entries.

    Returns:
        BankTransactionAnalysisResult: Analysis results
    """
    result = BankTransactionAnalysisResult()

    # Get totals
    result.total_payment_entries = frappe.db.count(
        "Payment Entry", filters={"eboekhouden_mutation_nr": ["is", "set"]}
    )

    result.total_journal_entries = frappe.db.count(
        "Journal Entry", filters={"eboekhouden_mutation_nr": ["is", "set"]}
    )

    # Get Payment Entries with Bank Transactions
    payment_entries_with_bt = frappe.db.sql(
        """
        SELECT DISTINCT pe.name
        FROM `tabPayment Entry` pe
        INNER JOIN `tabBank Transaction Payments` btp ON btp.payment_entry = pe.name
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
    """,
        as_dict=True,
    )
    result.payment_entries_with_bank_tx = len(payment_entries_with_bt)

    # Get Payment Entries WITHOUT Bank Transactions
    payment_entries_without_bt = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.eboekhouden_mutation_nr,
            pe.eboekhouden_mutation_type,
            pe.payment_type,
            pe.party_type,
            pe.party,
            pe.paid_amount,
            pe.received_amount,
            pe.posting_date
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabBank Transaction Payments` btp ON btp.payment_entry = pe.name
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND btp.name IS NULL
        ORDER BY pe.eboekhouden_mutation_nr
    """,
        as_dict=True,
    )
    result.payment_entries_without_bank_tx = len(payment_entries_without_bt)

    # Analyze each failure
    for pe in payment_entries_without_bt:
        mutation_nr = pe.eboekhouden_mutation_nr
        mutation_type = pe.eboekhouden_mutation_type or ""
        payment_type = pe.payment_type
        party_type = pe.party_type
        party = pe.party

        # Categorize the failure
        category, reason = _categorize_failure(pe, mutation_type, payment_type, party_type, party)

        result.add_failure(category, mutation_nr, pe.name, reason)

    return result


def _categorize_failure(pe, mutation_type, payment_type, party_type, party):
    """
    Categorize why Bank Transaction was not created.

    Returns:
        tuple: (category, reason)
    """
    # Category 1: Type 5/6 mutations (empty mutation_type) that fell back to legacy Journal Entry
    if not mutation_type or mutation_type == "":
        # Check if there's a corresponding Journal Entry
        je_exists = frappe.db.exists("Journal Entry", {"eboekhouden_mutation_nr": pe.eboekhouden_mutation_nr})

        if je_exists:
            return (
                "Type 5/6: Fell back to Journal Entry (no Bank Transaction created)",
                f"Legacy code created Journal Entry instead of Payment Entry with Bank Transaction. "
                f"Likely failed party extraction or account mapping.",
            )
        else:
            return (
                "Type 5/6: Payment Entry created but Bank Transaction creation failed",
                f"Payment Entry created successfully but Bank Transaction creation step failed or was skipped. "
                f"Party: {party_type}/{party}, Payment Type: {payment_type}",
            )

    # Category 2: Type 3/4 with missing Bank Transaction (should NOT happen based on code)
    elif mutation_type in ["3", "4"]:
        # Check if payment has invoice references
        has_invoice_ref = frappe.db.exists("Payment Entry Reference", {"parent": pe.name})

        if not has_invoice_ref:
            return (
                f"Type {mutation_type}: No invoice references",
                f"Payment Entry created but has no invoice references. Bank Transaction may have been skipped.",
            )
        else:
            return (
                f"Type {mutation_type}: Bank Transaction creation failed despite invoice refs",
                f"Payment Entry has invoice references but Bank Transaction was not created. "
                f"This indicates a failure in the Bank Transaction creation step (line ~1185-1263 in payment_entry_handler.py).",
            )

    # Category 3: Unknown mutation type
    else:
        return (
            f"Unknown mutation type: {mutation_type}",
            f"Mutation type '{mutation_type}' is not recognized. Expected 3, 4, 5, or 6.",
        )


def analyze_and_log():
    """
    Run analysis and log results to Error Log.

    This can be called manually via bench console or scheduled.
    """
    try:
        result = analyze_bank_transaction_creation()

        summary = result.get_summary()

        # Log to Error Log for persistence
        frappe.log_error(title="Bank Transaction Analysis - Missing Records", message=summary)

        # Also print to console
        print(summary)

        return result

    except Exception as e:
        error_msg = f"Failed to run Bank Transaction analysis: {str(e)}"
        frappe.log_error(title="Bank Transaction Analysis Failed", message=error_msg)
        print(error_msg)
        raise


def get_missing_bank_transactions_query():
    """
    Get SQL query to identify Payment Entries missing Bank Transactions.

    Useful for manual investigation.

    Returns:
        str: SQL query
    """
    return """
    SELECT
        pe.name as payment_entry,
        pe.eboekhouden_mutation_nr as mutation_nr,
        pe.eboekhouden_mutation_type as mutation_type,
        pe.payment_type,
        pe.party_type,
        pe.party,
        pe.paid_amount,
        pe.received_amount,
        pe.posting_date,
        CASE
            WHEN je.name IS NOT NULL THEN 'Has Journal Entry'
            ELSE 'No Journal Entry'
        END as journal_entry_status,
        CASE
            WHEN per.name IS NOT NULL THEN 'Has Invoice Refs'
            ELSE 'No Invoice Refs'
        END as invoice_ref_status
    FROM `tabPayment Entry` pe
    LEFT JOIN `tabBank Transaction Payments` btp ON btp.payment_entry = pe.name
    LEFT JOIN `tabJournal Entry` je ON je.eboekhouden_mutation_nr = pe.eboekhouden_mutation_nr
    LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
    WHERE pe.eboekhouden_mutation_nr IS NOT NULL
    AND btp.name IS NULL
    ORDER BY pe.eboekhouden_mutation_nr
    """
