"""
Data Quality Checker for E-Boekhouden Migration

This module handles all data quality checks and validation
for imported E-Boekhouden data.
"""

import frappe
from frappe.utils import now


class DataQualityChecker:
    """Handles data quality checks for E-Boekhouden migration"""

    def __init__(self, migration_doc):
        self.migration_doc = migration_doc
        self.company = migration_doc.company

    def check_data_quality(self):
        """Check data quality of imported records"""
        quality_report = {
            "timestamp": now(),
            "company": self.company,
            "issues": [],
            "statistics": {},
            "recommendations": [],
        }

        # Run all quality checks
        self._check_unmapped_accounts(quality_report)
        self._check_missing_parties(quality_report)
        self._check_uncategorized_transactions(quality_report)
        self._check_missing_tax_info(quality_report)
        self._check_unreconciled_payments(quality_report)
        self._generate_quality_recommendations(quality_report)

        return quality_report

    def _check_unmapped_accounts(self, report):
        """Check for GL entries with unmapped or temporary accounts"""
        try:
            # Check for accounts containing "Temporary" or similar patterns
            temp_accounts = frappe.db.sql(
                """
                SELECT DISTINCT account, COUNT(*) as count
                FROM `tabGL Entry`
                WHERE company = %s
                AND (account LIKE '%Temporary%'
                     OR account LIKE '%Unmapped%'
                     OR account LIKE '%TEMP%')
                GROUP BY account
                ORDER BY count DESC
                LIMIT 10
            """,
                (self.company,),
                as_dict=True,
            )

            if temp_accounts:
                total_entries = sum(acc.count for acc in temp_accounts)
                report["issues"].append(
                    {
                        "type": "Unmapped GL Accounts",
                        "description": f"Found {len(temp_accounts)} accounts with temporary/unmapped names",
                        "count": total_entries,
                        "examples": [f"{acc.account} ({acc.count} entries)" for acc in temp_accounts[:3]],
                    }
                )

            report["statistics"]["unmapped_accounts"] = len(temp_accounts)

        except Exception as e:
            frappe.log_error(f"Error checking unmapped accounts: {str(e)}")

    def _check_missing_parties(self, report):
        """Check for transactions with provisional or missing party assignments"""
        try:
            # Check for provisional customers/suppliers
            provisional_customers = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabCustomer`
                WHERE customer_name LIKE '%Provisional%'
                OR customer_name LIKE '%TEMP%'
                OR customer_name LIKE '%Unknown%'
            """,
                as_dict=True,
            )[0]

            provisional_suppliers = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabSupplier`
                WHERE supplier_name LIKE '%Provisional%'
                OR supplier_name LIKE '%TEMP%'
                OR supplier_name LIKE '%Unknown%'
            """,
                as_dict=True,
            )[0]

            total_provisional = provisional_customers.count + provisional_suppliers.count

            if total_provisional > 0:
                report["issues"].append(
                    {
                        "type": "Provisional Parties",
                        "description": f"Found {total_provisional} customers/suppliers with provisional names",
                        "count": total_provisional,
                        "examples": [
                            f"{provisional_customers.count} provisional customers",
                            f"{provisional_suppliers.count} provisional suppliers",
                        ],
                    }
                )

            report["statistics"]["provisional_parties"] = total_provisional

        except Exception as e:
            frappe.log_error(f"Error checking missing parties: {str(e)}")

    def _check_uncategorized_transactions(self, report):
        """Check for transactions without proper categorization"""
        try:
            # Check for journal entries without clear categorization
            uncategorized_je = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabJournal Entry`
                WHERE company = %s
                AND (user_remark IS NULL
                     OR user_remark = ''
                     OR user_remark LIKE '%Import%'
                     OR user_remark LIKE '%E-Boekhouden%')
                AND voucher_type = 'Journal Entry'
            """,
                (self.company,),
                as_dict=True,
            )[0]

            if uncategorized_je.count > 0:
                report["issues"].append(
                    {
                        "type": "Uncategorized Transactions",
                        "description": f"Found {uncategorized_je.count} journal entries without clear business purpose",
                        "count": uncategorized_je.count,
                        "examples": ["Journal entries with generic import descriptions"],
                    }
                )

            report["statistics"]["uncategorized_transactions"] = uncategorized_je.count

        except Exception as e:
            frappe.log_error(f"Error checking uncategorized transactions: {str(e)}")

    def _check_missing_tax_info(self, report):
        """Check for invoices missing tax information"""
        try:
            # Check for sales invoices without tax templates
            missing_tax_sales = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabSales Invoice`
                WHERE company = %s
                AND (taxes_and_charges IS NULL OR taxes_and_charges = '')
                AND grand_total != base_net_total
            """,
                (self.company,),
                as_dict=True,
            )[0]

            # Check for purchase invoices without tax templates
            missing_tax_purchase = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabPurchase Invoice`
                WHERE company = %s
                AND (taxes_and_charges IS NULL OR taxes_and_charges = '')
                AND grand_total != base_net_total
            """,
                (self.company,),
                as_dict=True,
            )[0]

            total_missing_tax = missing_tax_sales.count + missing_tax_purchase.count

            if total_missing_tax > 0:
                report["issues"].append(
                    {
                        "type": "Missing Tax Information",
                        "description": f"Found {total_missing_tax} invoices with tax amounts but no tax templates",
                        "count": total_missing_tax,
                        "examples": [
                            f"{missing_tax_sales.count} sales invoices",
                            f"{missing_tax_purchase.count} purchase invoices",
                        ],
                    }
                )

            report["statistics"]["missing_tax_info"] = total_missing_tax

        except Exception as e:
            frappe.log_error(f"Error checking missing tax info: {str(e)}")

    def _check_unreconciled_payments(self, report):
        """Check for payment entries not properly reconciled"""
        try:
            # Check for payment entries without references
            unreconciled_payments = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabPayment Entry` pe
                LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
                WHERE pe.company = %s
                AND pe.party_type IS NOT NULL
                AND pe.party IS NOT NULL
                AND per.name IS NULL
                AND pe.docstatus = 1
            """,
                (self.company,),
                as_dict=True,
            )[0]

            if unreconciled_payments.count > 0:
                report["issues"].append(
                    {
                        "type": "Unreconciled Payments",
                        "description": f"Found {unreconciled_payments.count} payments not linked to invoices",
                        "count": unreconciled_payments.count,
                        "examples": ["Payment entries without invoice references"],
                    }
                )

            report["statistics"]["unreconciled_payments"] = unreconciled_payments.count

        except Exception as e:
            frappe.log_error(f"Error checking unreconciled payments: {str(e)}")

    def _generate_quality_recommendations(self, report):
        """Generate recommendations based on found issues"""
        recommendations = []

        if report["statistics"].get("unmapped_accounts", 0) > 0:
            recommendations.append("Review and map temporary GL accounts to proper chart of accounts")

        if report["statistics"].get("provisional_parties", 0) > 0:
            recommendations.append("Update provisional customer/supplier names with actual business details")

        if report["statistics"].get("uncategorized_transactions", 0) > 0:
            recommendations.append("Add meaningful descriptions to journal entries for better audit trail")

        if report["statistics"].get("missing_tax_info", 0) > 0:
            recommendations.append("Configure tax templates for invoices with tax amounts")

        if report["statistics"].get("unreconciled_payments", 0) > 0:
            recommendations.append("Reconcile payment entries with their corresponding invoices")

        if not report["issues"]:
            recommendations.append("Data quality looks good! Consider periodic quality checks.")

        report["recommendations"] = recommendations


@frappe.whitelist()
def check_migration_data_quality(migration_name):
    """Check data quality for a migration"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        checker = DataQualityChecker(migration)
        quality_report = checker.check_data_quality()

        # Store the quality report in the migration document
        import json

        migration.db_set("data_quality_report", json.dumps(quality_report))

        return {"success": True, "report": quality_report}
    except Exception as e:
        frappe.log_error(f"Data quality check failed: {str(e)}")
        return {"success": False, "error": str(e)}
