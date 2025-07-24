"""
Data Quality Utilities - Conservative Refactor

These methods were moved exactly as-is from EBoekhoudenMigration class
to improve code organization. No logic changes made.
"""

import frappe


def check_data_quality_impl(migration_doc):
    """Check data quality of imported records - moved from migration class"""
    quality_report = {
        "timestamp": frappe.utils.now(),
        "company": migration_doc.company,
        "issues": [],
        "statistics": {},
        "recommendations": [],
    }

    # Check unmapped GL accounts
    _check_unmapped_accounts(migration_doc, quality_report)

    # Check missing party mappings
    _check_missing_parties(migration_doc, quality_report)

    # Check transactions without categorization
    _check_uncategorized_transactions(migration_doc, quality_report)

    # Check invoices missing tax information
    _check_missing_tax_info(migration_doc, quality_report)

    # Check payment reconciliation status
    _check_unreconciled_payments(migration_doc, quality_report)

    # Generate recommendations
    _generate_quality_recommendations(migration_doc, quality_report)

    return quality_report


def _check_unmapped_accounts(migration_doc, report):
    """Check for GL accounts used in transactions but not mapped - moved from migration class"""
    unmapped = frappe.db.sql(
        """
        SELECT DISTINCT
            jea.account,
            COUNT(*) as usage_count,
            SUM(jea.debit_in_account_currency) as total_debit,
            SUM(jea.credit_in_account_currency) as total_credit
        FROM `tabJournal Entry Account` jea
        JOIN `tabJournal Entry` je ON je.name = jea.parent
        WHERE je.company = %s
        AND je.eboekhouden_mutation_nr IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM `tabE-Boekhouden Ledger Mapping` elm
            WHERE elm.erpnext_account = jea.account
        )
        GROUP BY jea.account
        ORDER BY usage_count DESC
    """,
        migration_doc.company,
        as_dict=True,
    )

    if unmapped:
        report["issues"].append(
            {
                "type": "unmapped_accounts",
                "severity": "medium",
                "count": len(unmapped),
                "details": unmapped[:10],  # Top 10
            }
        )

    report["statistics"]["unmapped_accounts"] = len(unmapped)
    return unmapped


def _check_missing_parties(migration_doc, report):
    """Check for transactions with provisional parties - moved from migration class"""
    missing_customers = frappe.db.count(
        "Customer", {"customer_name": ["like", "Provisional Customer%"], "disabled": 0}
    )

    missing_suppliers = frappe.db.count(
        "Supplier", {"supplier_name": ["like", "Provisional Supplier%"], "disabled": 0}
    )

    total_missing = missing_customers + missing_suppliers

    if total_missing > 0:
        report["issues"].append(
            {
                "type": "provisional_parties",
                "severity": "high",
                "count": total_missing,
                "details": {"customers": missing_customers, "suppliers": missing_suppliers},
            }
        )

    report["statistics"]["provisional_parties"] = total_missing
    return total_missing


def _check_uncategorized_transactions(migration_doc, report):
    """Check for transactions without proper categorization - moved from migration class"""
    # Check invoices with generic items
    generic_items = frappe.db.sql(
        """
        SELECT
            COUNT(DISTINCT parent) as invoice_count,
            COUNT(*) as line_count
        FROM (
            SELECT sii.parent, sii.item_code
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.company = %s
            AND si.eboekhouden_invoice_number IS NOT NULL
            AND sii.item_code IN ('Service Item', 'Generic Service', 'Generic Product')

            UNION ALL

            SELECT pii.parent, pii.item_code
            FROM `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pi.company = %s
            AND pi.eboekhouden_invoice_number IS NOT NULL
            AND pii.item_code IN ('Service Item', 'Generic Service', 'Generic Product')
        ) as generic_usage
    """,
        (migration_doc.company, migration_doc.company),
        as_dict=True,
    )

    if generic_items and len(generic_items) > 0 and generic_items[0].get("invoice_count", 0) > 0:
        generic_item = generic_items[0]
        report["issues"].append(
            {
                "type": "generic_items",
                "severity": "low",
                "count": generic_item.get("invoice_count", 0),
                "details": {
                    "invoices_affected": generic_item.get("invoice_count", 0),
                    "line_items": generic_item.get("line_count", 0),
                },
            }
        )

    report["statistics"]["uncategorized_transactions"] = (
        generic_items[0].get("invoice_count", 0) if generic_items else 0
    )
    return generic_items


def _check_missing_tax_info(migration_doc, report):
    """Check for invoices missing tax information - moved from migration class"""
    missing_tax = frappe.db.sql(
        """
        SELECT
            'Sales' as invoice_type,
            COUNT(*) as count
        FROM `tabSales Invoice` si
        WHERE si.company = %s
        AND si.eboekhouden_invoice_number IS NOT NULL
        AND si.docstatus = 1
        AND NOT EXISTS (
            SELECT 1 FROM `tabSales Taxes and Charges` stc
            WHERE stc.parent = si.name
        )

        UNION ALL

        SELECT
            'Purchase' as invoice_type,
            COUNT(*) as count
        FROM `tabPurchase Invoice` pi
        WHERE pi.company = %s
        AND pi.eboekhouden_invoice_number IS NOT NULL
        AND pi.docstatus = 1
        AND NOT EXISTS (
            SELECT 1 FROM `tabPurchase Taxes and Charges` ptc
            WHERE ptc.parent = pi.name
        )
    """,
        (migration_doc.company, migration_doc.company),
        as_dict=True,
    )

    total_missing = sum(row.get("count", 0) for row in missing_tax)

    if total_missing > 0:
        report["issues"].append(
            {"type": "missing_tax_info", "severity": "high", "count": total_missing, "details": missing_tax}
        )

    report["statistics"]["missing_tax_info"] = total_missing
    return missing_tax


def _check_unreconciled_payments(migration_doc, report):
    """Check payment reconciliation status - moved from migration class"""
    unreconciled = frappe.db.sql(
        """
        SELECT
            pe.payment_type,
            COUNT(*) as count,
            SUM(CASE WHEN pe.payment_type = 'Receive'
                THEN pe.received_amount
                ELSE pe.paid_amount END) as total_amount
        FROM `tabPayment Entry` pe
        WHERE pe.company = %s
        AND pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        AND pe.unallocated_amount > 0
        GROUP BY pe.payment_type
    """,
        migration_doc.company,
        as_dict=True,
    )

    total_unreconciled = sum(row.get("count", 0) for row in unreconciled)

    if total_unreconciled > 0:
        report["issues"].append(
            {
                "type": "unreconciled_payments",
                "severity": "medium",
                "count": total_unreconciled,
                "details": unreconciled,
            }
        )

    report["statistics"]["unreconciled_payments"] = total_unreconciled
    return unreconciled


def _generate_quality_recommendations(migration_doc, report):
    """Generate recommendations based on quality issues - moved from migration class"""
    recommendations = []

    if report["statistics"].get("unmapped_accounts", 0) > 0:
        recommendations.append(
            {
                "priority": "high",
                "action": "Map GL Accounts",
                "description": f"Map {report['statistics']['unmapped_accounts']} GL accounts to E-Boekhouden ledgers",
                "impact": "Improves reporting accuracy and automation",
            }
        )

    if report["statistics"].get("provisional_parties", 0) > 0:
        recommendations.append(
            {
                "priority": "high",
                "action": "Update Party Information",
                "description": f"Replace {report['statistics']['provisional_parties']} provisional parties with actual customer/supplier data",
                "impact": "Enables proper communication and relationship management",
            }
        )

    if report["statistics"].get("missing_tax_info", 0) > 0:
        recommendations.append(
            {
                "priority": "high",
                "action": "Add Tax Information",
                "description": f"Add tax details to {report['statistics']['missing_tax_info']} invoices",
                "impact": "Ensures tax compliance and accurate financial reporting",
            }
        )

    if report["statistics"].get("unreconciled_payments", 0) > 0:
        recommendations.append(
            {
                "priority": "medium",
                "action": "Reconcile Payments",
                "description": f"Reconcile {report['statistics']['unreconciled_payments']} payments with their invoices",
                "impact": "Improves cash flow visibility and reduces outstanding balances",
            }
        )

    if report["statistics"].get("uncategorized_transactions", 0) > 0:
        recommendations.append(
            {
                "priority": "low",
                "action": "Categorize Items",
                "description": f"Replace generic items in {report['statistics']['uncategorized_transactions']} invoices with specific categories",
                "impact": "Better inventory management and cost analysis",
            }
        )

    report["recommendations"] = recommendations
