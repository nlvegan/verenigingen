"""
Bank Transaction Summary Reporting

Provides on-demand summary of Bank Transaction creation during eBoekhouden imports.
Can be called manually or scheduled to check import health.
"""

import frappe
from frappe.utils import now_datetime


def generate_bank_transaction_summary():
    """
    Generate comprehensive Bank Transaction creation summary.

    Analyzes all Payment Entries from eBoekhouden and reports on
    Bank Transaction creation success/failure rates for Types 3-6.

    Returns:
        dict: Summary statistics
    """
    # Query Payment Entries with/without Bank Transactions
    summary = {
        "timestamp": now_datetime(),
        "type_3_4": _analyze_type_3_4(),
        "type_5_6": _analyze_type_5_6(),
    }

    # Calculate overall statistics
    total_processed = summary["type_3_4"]["total"] + summary["type_5_6"]["total"]
    total_with_bt = summary["type_3_4"]["with_bank_tx"] + summary["type_5_6"]["with_bank_tx"]
    total_without_bt = summary["type_3_4"]["without_bank_tx"] + summary["type_5_6"]["without_bank_tx"]

    summary["overall"] = {
        "total_processed": total_processed,
        "with_bank_tx": total_with_bt,
        "without_bank_tx": total_without_bt,
        "success_rate": (total_with_bt / total_processed * 100) if total_processed > 0 else 0,
    }

    return summary


def _analyze_type_3_4():
    """Analyze Type 3/4 (Customer/Supplier Payments)"""
    results = frappe.db.sql(
        """
        SELECT
            COUNT(DISTINCT pe.name) as total,
            COUNT(DISTINCT CASE WHEN btp.name IS NOT NULL THEN pe.name END) as with_bank_tx,
            COUNT(DISTINCT CASE WHEN btp.name IS NULL THEN pe.name END) as without_bank_tx
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabBank Transaction Payments` btp ON btp.payment_entry = pe.name
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.eboekhouden_mutation_type IN ('3', '4')
    """,
        as_dict=True,
    )[0]

    return {
        "total": results.total,
        "with_bank_tx": results.with_bank_tx,
        "without_bank_tx": results.without_bank_tx,
        "success_rate": (results.with_bank_tx / results.total * 100) if results.total > 0 else 0,
    }


def _analyze_type_5_6():
    """Analyze Type 5/6 (Money Transfers)"""
    results = frappe.db.sql(
        """
        SELECT
            COUNT(DISTINCT pe.name) as total,
            COUNT(DISTINCT CASE WHEN btp.name IS NOT NULL THEN pe.name END) as with_bank_tx,
            COUNT(DISTINCT CASE WHEN btp.name IS NULL THEN pe.name END) as without_bank_tx
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabBank Transaction Payments` btp ON btp.payment_entry = pe.name
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND (pe.eboekhouden_mutation_type = '' OR pe.eboekhouden_mutation_type IS NULL)
    """,
        as_dict=True,
    )[0]

    return {
        "total": results.total,
        "with_bank_tx": results.with_bank_tx,
        "without_bank_tx": results.without_bank_tx,
        "success_rate": (results.with_bank_tx / results.total * 100) if results.total > 0 else 0,
    }


def log_bank_transaction_summary():
    """
    Generate and log Bank Transaction summary to Error Log.

    Can be called manually via:
        bench --site [site] execute verenigingen.e_boekhouden.utils.bank_transaction_summary.log_bank_transaction_summary
    """
    summary = generate_bank_transaction_summary()

    report_lines = [
        "=" * 80,
        "BANK TRANSACTION CREATION SUMMARY",
        "=" * 80,
        "",
        f"Analysis Time: {summary['timestamp']}",
        "",
        "OVERALL STATISTICS:",
        f"  Total Payment Entries: {summary['overall']['total_processed']:,}",
        f"  With Bank Transactions: {summary['overall']['with_bank_tx']:,} ({summary['overall']['success_rate']:.1f}%)",
        f"  WITHOUT Bank Transactions: {summary['overall']['without_bank_tx']:,}",
        "",
        "TYPE 3/4 (Customer/Supplier Payments):",
        f"  Total: {summary['type_3_4']['total']:,}",
        f"  With Bank TX: {summary['type_3_4']['with_bank_tx']:,} ({summary['type_3_4']['success_rate']:.1f}%)",
        f"  Without Bank TX: {summary['type_3_4']['without_bank_tx']:,}",
        "",
        "TYPE 5/6 (Money Transfers):",
        f"  Total: {summary['type_5_6']['total']:,}",
        f"  With Bank TX: {summary['type_5_6']['with_bank_tx']:,} ({summary['type_5_6']['success_rate']:.1f}%)",
        f"  Without Bank TX: {summary['type_5_6']['without_bank_tx']:,}",
        "",
    ]

    # Add recommendations based on results
    if summary["overall"]["without_bank_tx"] > 0:
        report_lines.extend(["⚠️ ISSUES DETECTED:", ""])

        if summary["type_3_4"]["without_bank_tx"] > 0:
            report_lines.append(
                f"  • {summary['type_3_4']['without_bank_tx']} Type 3/4 payments missing Bank Transactions"
            )
            report_lines.append(
                "    → Check PaymentEntryHandler._create_bank_transaction_for_payment() for failures"
            )

        if summary["type_5_6"]["without_bank_tx"] > 0:
            report_lines.append(
                f"  • {summary['type_5_6']['without_bank_tx']} Type 5/6 payments missing Bank Transactions"
            )
            report_lines.append(
                "    → Check PaymentProcessor._create_bank_transaction_for_money_transfer() for failures"
            )
    else:
        report_lines.extend(["✓ SUCCESS: All Payment Entries have Bank Transactions!", ""])

    report_lines.append("=" * 80)

    report = "\n".join(report_lines)

    # Log to Error Log
    frappe.log_error(title="Bank Transaction Summary Report", message=report)

    # Print to console
    print(report)

    return summary


@frappe.whitelist()
def get_bank_transaction_summary_api():
    """
    API endpoint to get Bank Transaction summary.

    Accessible via:
        /api/method/verenigingen.e_boekhouden.utils.bank_transaction_summary.get_bank_transaction_summary_api
    """
    return generate_bank_transaction_summary()
