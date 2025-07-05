"""
Analyze what ledger IDs are actually in the E-Boekhouden mutations
"""

from collections import Counter

import frappe


@frappe.whitelist()
def analyze_mutation_ledgers():
    """Analyze the ledger IDs in actual mutations to understand the mapping issue"""

    try:
        # Since we don't have the cache table, let's check the migration logs
        migration_logs = frappe.db.sql(
            """
            SELECT
                name,
                error_log,
                imported_records,
                failed_records
            FROM `tabE-Boekhouden Migration`
            WHERE migration_status = 'Completed'
            ORDER BY modified DESC
            LIMIT 1
        """,
            as_dict=True,
        )

        # Get error logs that might show what ledger IDs were being processed
        error_logs = frappe.db.sql(
            """
            SELECT
                el.name,
                el.error,
                el.creation
            FROM `tabError Log` el
            WHERE el.error LIKE '%ledger%'
            OR el.error LIKE '%tegenrekening%'
            OR el.error LIKE '%48010%'
            ORDER BY el.creation DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Check if we're getting proper ledger IDs from mutations
        # Look at the purchase invoice descriptions to infer what should have been mapped
        invoice_analysis = frappe.db.sql(
            """
            SELECT
                pi.name,
                pi.bill_no,
                pii.description,
                pii.expense_account,
                pii.rate
            FROM `tabPurchase Invoice` pi
            JOIN `tabPurchase Invoice Item` pii ON pii.parent = pi.name
            WHERE pi.supplier = 'E-Boekhouden Import'
            AND pi.posting_date >= '2025-01-01'
            ORDER BY pi.creation DESC
            LIMIT 30
        """,
            as_dict=True,
        )

        # Count expense account usage
        account_counter = Counter()
        for inv in invoice_analysis:
            account_counter[inv.expense_account] += 1

        # Try to identify patterns in descriptions
        description_patterns = {}
        for inv in invoice_analysis[:10]:
            desc_lower = (inv.description or "").lower()
            if "salaris" in desc_lower or "loon" in desc_lower:
                description_patterns[inv.name] = "Should be salary/wages account"
            elif "bank" in desc_lower:
                description_patterns[inv.name] = "Should be bank charges"
            elif "verzekering" in desc_lower:
                description_patterns[inv.name] = "Should be insurance"
            elif "telefoon" in desc_lower or "internet" in desc_lower:
                description_patterns[inv.name] = "Should be telecom expenses"
            else:
                description_patterns[inv.name] = f"Unknown category: {inv.description[:50]}"

        return {
            "success": True,
            "migration_logs": migration_logs,
            "error_logs": error_logs[:5],
            "invoice_samples": invoice_analysis[:10],
            "account_usage_count": dict(account_counter.most_common()),
            "description_patterns": description_patterns,
            "total_invoices_analyzed": len(invoice_analysis),
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_ledger_extraction():
    """Debug how ledger IDs are being extracted from mutations"""

    try:
        # Check the debug logs for REST import
        debug_logs = frappe.db.sql(
            """
            SELECT
                name,
                error,
                creation
            FROM `tabError Log`
            WHERE error LIKE '%REST Debug%'
            OR error LIKE '%ledger_id%'
            OR error LIKE '%Smart mapping%'
            ORDER BY creation DESC
            LIMIT 5
        """,
            as_dict=True,
        )

        # Look for patterns in the error logs
        pattern_analysis = {"has_ledger_id_mentions": 0, "has_none_ledger": 0, "has_numeric_ledger": 0}

        for log in debug_logs:
            if log.error:
                if "ledger_id" in log.error:
                    pattern_analysis["has_ledger_id_mentions"] += 1
                if "ledger_id: None" in log.error:
                    pattern_analysis["has_none_ledger"] += 1
                if "ledger_id: " in log.error and any(c.isdigit() for c in log.error):
                    pattern_analysis["has_numeric_ledger"] += 1

        return {
            "success": True,
            "debug_logs": debug_logs,
            "pattern_analysis": pattern_analysis,
            "recommendation": "Check if ledger_id is being properly extracted from mutation rows",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
