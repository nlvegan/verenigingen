# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Migration Data Quality Service

Centralized data quality checking for E-Boekhouden migrations.
Extracted from e_boekhouden_migration.py to reduce controller size.
"""

from typing import Any, Callable, Dict, List, Optional

import frappe


class MigrationDataQualityService:
    """
    Service for checking data quality of imported E-Boekhouden records.

    Handles:
    - Unmapped GL accounts detection
    - Provisional party identification
    - Uncategorized transaction detection
    - Missing tax information checks
    - Unreconciled payment identification
    - Quality recommendations generation
    """

    def __init__(
        self,
        company: str,
        error_callback: Optional[Callable] = None,
    ):
        """
        Initialize the data quality service.

        Args:
            company: Company name to check data quality for
            error_callback: Function to call for error logging
        """
        self.company = company
        self._error_callback = error_callback

    def log_error(self, message: str, record_type: str = None, record_data: dict = None):
        """Log error using callback or frappe.log_error."""
        if self._error_callback:
            self._error_callback(message, record_type, record_data)
        else:
            frappe.log_error(message, f"E-Boekhouden Data Quality {record_type or ''} Error")

    def check_data_quality(self) -> Dict[str, Any]:
        """Check data quality of imported records.

        Returns:
            Dict containing quality report with issues, statistics, and recommendations
        """
        quality_report = {
            "timestamp": frappe.utils.now(),
            "company": self.company,
            "issues": [],
            "statistics": {},
            "recommendations": [],
        }

        # Check unmapped GL accounts
        self._check_unmapped_accounts(quality_report)

        # Check missing party mappings
        self._check_missing_parties(quality_report)

        # Check transactions without categorization
        self._check_uncategorized_transactions(quality_report)

        # Check invoices missing tax information
        self._check_missing_tax_info(quality_report)

        # Check payment reconciliation status
        self._check_unreconciled_payments(quality_report)

        # Generate recommendations
        self._generate_quality_recommendations(quality_report)

        return quality_report

    def _check_unmapped_accounts(self, report: Dict) -> List[Dict]:
        """Check for GL accounts used in transactions but not mapped."""
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
            self.company,
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

    def _check_missing_parties(self, report: Dict) -> int:
        """Check for transactions with provisional parties."""
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

    def _check_uncategorized_transactions(self, report: Dict) -> List[Dict]:
        """Check for transactions without proper categorization."""
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
            (self.company, self.company),
            as_dict=True,
        )

        if generic_items and generic_items[0].get("invoice_count", 0) > 0:
            report["issues"].append(
                {
                    "type": "generic_items",
                    "severity": "low",
                    "count": generic_items[0].get("invoice_count", 0),
                    "details": {
                        "invoices_affected": generic_items[0].get("invoice_count", 0),
                        "line_items": generic_items[0].get("line_count", 0),
                    },
                }
            )

        report["statistics"]["uncategorized_transactions"] = (
            generic_items[0].get("invoice_count", 0) if generic_items else 0
        )
        return generic_items

    def _check_missing_tax_info(self, report: Dict) -> List[Dict]:
        """Check for invoices missing tax information."""
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
            (self.company, self.company),
            as_dict=True,
        )

        total_missing = sum(row.get("count", 0) for row in missing_tax)

        if total_missing > 0:
            report["issues"].append(
                {
                    "type": "missing_tax_info",
                    "severity": "high",
                    "count": total_missing,
                    "details": missing_tax,
                }
            )

        report["statistics"]["missing_tax_info"] = total_missing
        return missing_tax

    def _check_unreconciled_payments(self, report: Dict) -> List[Dict]:
        """Check payment reconciliation status."""
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
            self.company,
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

    def _generate_quality_recommendations(self, report: Dict) -> List[Dict]:
        """Generate recommendations based on quality issues."""
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
        return recommendations
