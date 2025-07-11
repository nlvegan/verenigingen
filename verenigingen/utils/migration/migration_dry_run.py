"""
Dry-run mode for eBoekhouden migration

Provides simulation capabilities to test migrations without
actually creating or modifying any data.
"""

import copy
import json
from datetime import datetime

import frappe
from frappe.utils import cint, flt


class DryRunSimulator:
    """Simulates migration operations without database changes"""

    def __init__(self):
        self.simulated_records = {}
        self.simulation_log = []
        self.validation_errors = []
        self.statistics = {
            "accounts": {"would_create": 0, "would_update": 0, "would_skip": 0},
            "customers": {"would_create": 0, "would_update": 0, "would_skip": 0},
            "suppliers": {"would_create": 0, "would_update": 0, "would_skip": 0},
            "sales_invoices": {"would_create": 0, "would_fail": 0},
            "purchase_invoices": {"would_create": 0, "would_fail": 0},
            "payment_entries": {"would_create": 0, "would_fail": 0},
            "journal_entries": {"would_create": 0, "would_fail": 0},
        }
        self.financial_impact = {
            "total_debit": 0,
            "total_credit": 0,
            "accounts_affected": set(),
            "gl_entries_count": 0,
        }

    def simulate_record_creation(self, doctype, data):
        """Simulate creating a record"""
        # Generate simulated name
        simulated_name = "SIM-{doctype}-{len(self.simulated_records.get(doctype, []))}"

        # Validate without saving
        validation_result = self._validate_record(doctype, data)

        if validation_result["valid"]:
            # Store simulated record
            if doctype not in self.simulated_records:
                self.simulated_records[doctype] = []

            simulated_record = {
                "name": simulated_name,
                "data": copy.deepcopy(data),
                "validation": validation_result,
                "would_create_gl": self._would_create_gl_entries(doctype, data),
                "financial_impact": self._calculate_financial_impact(doctype, data),
            }

            self.simulated_records[doctype].append(simulated_record)

            # Update statistics
            self._update_statistics(doctype, "would_create")

            # Log simulation
            self.simulation_log.append(
                {
                    "action": "create",
                    "doctype": doctype,
                    "name": simulated_name,
                    "status": "success",
                    "data_preview": self._get_data_preview(data),
                }
            )

            return {"success": True, "simulated_name": simulated_name, "validation": validation_result}
        else:
            # Record validation failure
            self.validation_errors.append(
                {
                    "doctype": doctype,
                    "data": self._get_data_preview(data),
                    "errors": validation_result["errors"],
                }
            )

            # Update statistics
            self._update_statistics(doctype, "would_fail")

            # Log simulation
            self.simulation_log.append(
                {
                    "action": "create",
                    "doctype": doctype,
                    "status": "failed",
                    "errors": validation_result["errors"],
                }
            )

            return {"success": False, "errors": validation_result["errors"]}

    def simulate_record_update(self, doctype, name, updates):
        """Simulate updating a record"""
        # Check if record exists
        existing = frappe.db.exists(doctype, name)

        if existing:
            # Get current data
            current_doc = frappe.get_doc(doctype, name)

            # Create updated version (without saving)
            updated_data = current_doc.as_dict()
            updated_data.update(updates)

            # Validate changes
            validation_result = self._validate_record(doctype, updated_data)

            if validation_result["valid"]:
                # Log simulation
                self.simulation_log.append(
                    {
                        "action": "update",
                        "doctype": doctype,
                        "name": name,
                        "status": "success",
                        "changes": updates,
                    }
                )

                # Update statistics
                self._update_statistics(doctype, "would_update")

                return {"success": True, "validation": validation_result}
            else:
                return {"success": False, "errors": validation_result["errors"]}
        else:
            return {"success": False, "errors": ["Record does not exist"]}

    def _validate_record(self, doctype, data):
        """Validate record data without saving"""
        validation_result = {"valid": True, "errors": [], "warnings": []}

        try:
            # Create document instance for validation
            doc = frappe.new_doc(doctype)
            doc.update(data)

            # Run document validation
            doc.flags.ignore_permissions = True
            doc.flags.ignore_mandatory = False
            doc.flags.ignore_validate = False

            # Mock save to trigger validation
            doc._validate()

            # Check specific validations based on doctype
            if doctype == "Sales Invoice":
                validation_result.update(self._validate_sales_invoice(doc))
            elif doctype == "Purchase Invoice":
                validation_result.update(self._validate_purchase_invoice(doc))
            elif doctype == "Payment Entry":
                validation_result.update(self._validate_payment_entry(doc))
            elif doctype == "Account":
                validation_result.update(self._validate_account(doc))

        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(str(e))

        return validation_result

    def _validate_sales_invoice(self, doc):
        """Specific validation for sales invoice"""
        result = {"valid": True, "errors": [], "warnings": []}

        # Check customer exists
        if not self._record_exists_or_simulated("Customer", doc.customer):
            result["valid"] = False
            result["errors"].append("Customer {doc.customer} does not exist")

        # Check items
        if not doc.items:
            result["valid"] = False
            result["errors"].append("No items in invoice")

        # Check accounts
        for item in doc.items:
            if hasattr(item, "income_account") and item.income_account:
                if not self._record_exists_or_simulated("Account", item.income_account):
                    result["warnings"].append("Income account {item.income_account} may not exist")

        # Check total
        if doc.grand_total <= 0:
            result["warnings"].append("Invoice total is zero or negative")

        return result

    def _validate_purchase_invoice(self, doc):
        """Specific validation for purchase invoice"""
        result = {"valid": True, "errors": [], "warnings": []}

        # Check supplier exists
        if not self._record_exists_or_simulated("Supplier", doc.supplier):
            result["valid"] = False
            result["errors"].append("Supplier {doc.supplier} does not exist")

        # Check items
        if not doc.items:
            result["valid"] = False
            result["errors"].append("No items in invoice")

        return result

    def _validate_payment_entry(self, doc):
        """Specific validation for payment entry"""
        result = {"valid": True, "errors": [], "warnings": []}

        # Check party exists
        if doc.party_type == "Customer":
            if not self._record_exists_or_simulated("Customer", doc.party):
                result["valid"] = False
                result["errors"].append("Customer {doc.party} does not exist")
        elif doc.party_type == "Supplier":
            if not self._record_exists_or_simulated("Supplier", doc.party):
                result["valid"] = False
                result["errors"].append("Supplier {doc.party} does not exist")

        # Check accounts
        if doc.payment_type == "Receive":
            if doc.paid_to and not self._record_exists_or_simulated("Account", doc.paid_to):
                result["warnings"].append("Account {doc.paid_to} may not exist")
        else:
            if doc.paid_from and not self._record_exists_or_simulated("Account", doc.paid_from):
                result["warnings"].append("Account {doc.paid_from} may not exist")

        return result

    def _validate_account(self, doc):
        """Specific validation for account"""
        result = {"valid": True, "errors": [], "warnings": []}

        # Check parent account
        if doc.parent_account:
            if not self._record_exists_or_simulated("Account", doc.parent_account):
                result["warnings"].append("Parent account {doc.parent_account} may not exist")

        # Check account number uniqueness
        if doc.account_number:
            existing = frappe.db.exists(
                "Account", {"account_number": doc.account_number, "company": doc.company}
            )
            if existing:
                result["valid"] = False
                result["errors"].append("Account number {doc.account_number} already exists")

        return result

    def _record_exists_or_simulated(self, doctype, name):
        """Check if record exists in database or simulation"""
        # Check database
        if frappe.db.exists(doctype, name):
            return True

        # Check simulated records
        if doctype in self.simulated_records:
            for record in self.simulated_records[doctype]:
                if record["name"] == name or record["data"].get("name") == name:
                    return True
                # Check by key fields
                if doctype == "Customer" and record["data"].get("customer_name") == name:
                    return True
                if doctype == "Supplier" and record["data"].get("supplier_name") == name:
                    return True

        return False

    def _would_create_gl_entries(self, doctype, data):
        """Check if this document would create GL entries"""
        gl_doctypes = ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"]
        return doctype in gl_doctypes

    def _calculate_financial_impact(self, doctype, data):
        """Calculate financial impact of the record"""
        impact = {"debit": 0, "credit": 0, "accounts": []}

        if doctype == "Sales Invoice":
            impact["debit"] = flt(data.get("grand_total", 0))
            impact["credit"] = flt(data.get("grand_total", 0))
            impact["accounts"] = [data.get("debit_to"), "Sales Account"]

        elif doctype == "Purchase Invoice":
            impact["debit"] = flt(data.get("grand_total", 0))
            impact["credit"] = flt(data.get("grand_total", 0))
            impact["accounts"] = ["Expense Account", data.get("credit_to")]

        elif doctype == "Payment Entry":
            amount = flt(data.get("paid_amount", 0))
            impact["debit"] = amount
            impact["credit"] = amount
            impact["accounts"] = [data.get("paid_from"), data.get("paid_to")]

        elif doctype == "Journal Entry":
            for account in data.get("accounts", []):
                impact["debit"] += flt(account.get("debit_in_account_currency", 0))
                impact["credit"] += flt(account.get("credit_in_account_currency", 0))
                impact["accounts"].append(account.get("account"))

        # Update totals
        self.financial_impact["total_debit"] += impact["debit"]
        self.financial_impact["total_credit"] += impact["credit"]
        self.financial_impact["accounts_affected"].update([a for a in impact["accounts"] if a])

        if impact["debit"] > 0 or impact["credit"] > 0:
            self.financial_impact["gl_entries_count"] += 1

        return impact

    def _update_statistics(self, doctype, action):
        """Update simulation statistics"""
        stat_key = self._get_stat_key(doctype)
        if stat_key and action in self.statistics[stat_key]:
            self.statistics[stat_key][action] += 1

    def _get_stat_key(self, doctype):
        """Get statistics key for doctype"""
        mapping = {
            "Account": "accounts",
            "Customer": "customers",
            "Supplier": "suppliers",
            "Sales Invoice": "sales_invoices",
            "Purchase Invoice": "purchase_invoices",
            "Payment Entry": "payment_entries",
            "Journal Entry": "journal_entries",
        }
        return mapping.get(doctype)

    def _get_data_preview(self, data):
        """Get a preview of data for logging"""
        preview = {}
        preview_fields = [
            "name",
            "customer",
            "supplier",
            "party",
            "posting_date",
            "grand_total",
            "paid_amount",
            "account_name",
            "account_number",
        ]

        for field in preview_fields:
            if field in data:
                preview[field] = data[field]

        return preview

    def generate_dry_run_report(self):
        """Generate comprehensive dry-run report"""
        report = {
            "summary": {
                "total_records_analyzed": sum(sum(stat.values()) for stat in self.statistics.values()),
                "would_succeed": sum(
                    stat.get("would_create", 0) + stat.get("would_update", 0)
                    for stat in self.statistics.values()
                ),
                "would_fail": sum(stat.get("would_fail", 0) for stat in self.statistics.values()),
                "validation_errors": len(self.validation_errors),
            },
            "statistics": self.statistics,
            "financial_impact": {
                "total_debit": self.financial_impact["total_debit"],
                "total_credit": self.financial_impact["total_credit"],
                "balance": self.financial_impact["total_debit"] - self.financial_impact["total_credit"],
                "accounts_affected": len(self.financial_impact["accounts_affected"]),
                "gl_entries_count": self.financial_impact["gl_entries_count"],
            },
            "validation_errors": self.validation_errors[:50],  # First 50 errors
            "warnings": self._extract_warnings(),
            "recommendations": self._generate_recommendations(),
        }

        return report

    def _extract_warnings(self):
        """Extract warnings from simulation log"""
        warnings = []

        for record_type, records in self.simulated_records.items():
            for record in records:
                if record["validation"].get("warnings"):
                    warnings.extend(
                        [
                            {"doctype": record_type, "record": record["name"], "warning": warning}
                            for warning in record["validation"]["warnings"]
                        ]
                    )

        return warnings[:50]  # First 50 warnings

    def _generate_recommendations(self):
        """Generate recommendations based on dry-run results"""
        recommendations = []

        # Check for high failure rate
        total_would_fail = sum(stat.get("would_fail", 0) for stat in self.statistics.values())
        total_would_succeed = sum(
            stat.get("would_create", 0) + stat.get("would_update", 0) for stat in self.statistics.values()
        )

        if total_would_fail > 0:
            failure_rate = (
                (total_would_fail / (total_would_fail + total_would_succeed) * 100)
                if total_would_succeed > 0
                else 100
            )

            if failure_rate > 10:
                recommendations.append(
                    {
                        "type": "high_failure_rate",
                        "severity": "high",
                        "message": "High failure rate detected: {failure_rate:.1f}% of records would fail",
                        "action": "Review validation errors before proceeding",
                    }
                )

        # Check for missing master data
        if self.statistics["customers"]["would_fail"] > 0:
            recommendations.append(
                {
                    "type": "missing_customers",
                    "severity": "medium",
                    "message": "Some customer records are missing",
                    "action": "Import customers before invoices",
                }
            )

        if self.statistics["suppliers"]["would_fail"] > 0:
            recommendations.append(
                {
                    "type": "missing_suppliers",
                    "severity": "medium",
                    "message": "Some supplier records are missing",
                    "action": "Import suppliers before invoices",
                }
            )

        # Check financial balance
        balance = abs(self.financial_impact["total_debit"] - self.financial_impact["total_credit"])
        if balance > 0.01:  # Allow small rounding differences
            recommendations.append(
                {
                    "type": "unbalanced_entries",
                    "severity": "high",
                    "message": "GL entries would be unbalanced by {balance}",
                    "action": "Review journal entries for correctness",
                }
            )

        # Check for no data
        if sum(sum(stat.values()) for stat in self.statistics.values()) == 0:
            recommendations.append(
                {
                    "type": "no_data",
                    "severity": "info",
                    "message": "No data was processed in dry-run",
                    "action": "Verify data source and filters",
                }
            )

        return recommendations


@frappe.whitelist()
def run_migration_dry_run(migration_name, sample_size=None):
    """Run a dry-run simulation of the migration"""
    from .eboekhouden_soap_migration import fetch_eboekhouden_data

    # migration_doc = frappe.get_doc("E Boekhouden Migration", migration_name)
    simulator = DryRunSimulator()

    # Fetch data (limited sample for dry-run)
    data = fetch_eboekhouden_data(
        migration_doc.company,
        migration_doc.from_date,
        migration_doc.to_date,
        migration_doc.get("username"),
        migration_doc.get("security_code_1"),
        migration_doc.get("security_code_2"),
    )

    # Limit to sample size if specified
    if sample_size:
        for key in data:
            if isinstance(data[key], list) and len(data[key]) > sample_size:
                data[key] = data[key][:sample_size]

    # Simulate processing each type of data
    # ... (simulate processing similar to actual migration)

    # Generate and return report
    report = simulator.generate_dry_run_report()

    # Save report to file
    report_path = frappe.get_site_path(
        "private",
        "files",
        "migration_dry_runs",
        "dry_run_{migration_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )

    import os

    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return {"success": True, "report": report, "report_path": report_path}
