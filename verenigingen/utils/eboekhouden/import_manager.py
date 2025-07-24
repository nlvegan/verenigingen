# E-Boekhouden Import Manager - Clean import with update capabilities
import json
from datetime import datetime

import frappe
from frappe.utils import add_days, now, today


class EBoekhoudenImportManager:
    """Manages E-Boekhouden imports with clean slate and update capabilities"""

    def __init__(self):
        self.settings = frappe.get_single("E-Boekhouden Settings")
        self.company = self.settings.company
        self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")

    @frappe.whitelist()
    def clean_import_all(self, from_date=None, to_date=None, mutation_types=None):
        """
        Clean import - removes existing imported documents and reimports

        Args:
            from_date: Start date for import
            to_date: End date for import
            mutation_types: List of mutation types to import (1=Sales, 2=Purchase, etc)
        """
        results = {"deleted": 0, "imported": 0, "updated": 0, "failed": 0, "errors": [], "log": []}

        # Step 1: Delete ALL financial data (not just E-Boekhouden imports)
        print("WARNING: This will delete ALL financial data including GLEs and PLEs!")
        results["deleted"] = self._delete_existing_imports(from_date, to_date, mutation_types)
        results["log"].append(
            f"Deleted {results['deleted']} existing documents and all related ledger entries"
        )

        # Step 2: Import fresh data
        import_results = self._import_mutations(from_date, to_date, mutation_types)
        results["imported"] = import_results["imported"]
        results["failed"] = import_results["failed"]
        results["errors"] = import_results["errors"]
        results["log"].extend(import_results["log"])

        return results

    @frappe.whitelist()
    def update_existing_imports(self, from_date=None, to_date=None, force_update=False):
        """
        Update existing imports with latest data from E-Boekhouden

        Args:
            from_date: Start date for update check
            to_date: End date for update check
            force_update: Force update even if no changes detected
        """
        results = {"checked": 0, "updated": 0, "unchanged": 0, "errors": [], "log": []}

        # Get existing imported documents
        existing_docs = self._get_existing_imports(from_date, to_date)
        results["log"].append(f"Found {len(existing_docs)} existing documents to check")

        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        for doc_info in existing_docs:
            results["checked"] += 1

            try:
                # Fetch latest mutation data
                mutation_detail = iterator.fetch_mutation_detail(doc_info["mutation_id"])

                if not mutation_detail:
                    results["log"].append(
                        f"Mutation {doc_info['mutation_id']} no longer exists in E-Boekhouden"
                    )
                    continue

                # Check if update needed
                if self._needs_update(doc_info, mutation_detail) or force_update:
                    # Update the document
                    self._update_document(doc_info, mutation_detail)
                    results["updated"] += 1
                    results["log"].append(f"Updated {doc_info['doctype']} {doc_info['name']}")
                else:
                    results["unchanged"] += 1

            except Exception as e:
                results["errors"].append(f"Error updating {doc_info['name']}: {str(e)}")

        return results

    def _delete_existing_imports(self, from_date=None, to_date=None, mutation_types=None):
        """Delete existing imported documents using the comprehensive nuke utility"""
        # Use the existing battle-tested nuke functionality
        from verenigingen.utils.nuke_financial_data import nuke_all_financial_data

        # Call the nuke function with proper confirmation
        result = nuke_all_financial_data(confirm="YES_DELETE_ALL_FINANCIAL_DATA")

        if result.get("success"):
            total_deleted = sum(result.get("deleted", {}).values())
            return total_deleted
        else:
            frappe.throw(f"Failed to delete existing data: {result.get('error', 'Unknown error')}")
            return 0

    def _import_mutations(self, from_date=None, to_date=None, mutation_types=None):
        """Import mutations with enhanced data"""
        from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import _process_single_mutation

        results = {"imported": 0, "failed": 0, "errors": [], "log": []}

        # Get mutations from E-Boekhouden
        from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        if not mutation_types:
            mutation_types = [1, 2, 3, 4]  # Sales, Purchase, Payments

        for mutation_type in mutation_types:
            try:
                mutations = iterator.fetch_mutations_by_type(
                    mutation_type=mutation_type, date_from=from_date, date_to=to_date
                )

                results["log"].append(f"Found {len(mutations)} mutations of type {mutation_type}")

                for mutation in mutations:
                    try:
                        debug_info = []
                        doc = _process_single_mutation(mutation, self.company, self.cost_center, debug_info)

                        if doc:
                            results["imported"] += 1
                            results["log"].append(f"Imported {doc.doctype} {doc.name}")

                    except Exception as e:
                        results["failed"] += 1
                        results["errors"].append(f"Mutation {mutation.get('id')}: {str(e)}")

            except Exception as e:
                results["errors"].append(f"Error fetching mutations type {mutation_type}: {str(e)}")

        return results

    def _get_existing_imports(self, from_date=None, to_date=None):
        """Get list of existing imported documents"""
        existing_docs = []

        doctypes = [
            ("Sales Invoice", "eboekhouden_mutation_nr"),
            ("Purchase Invoice", "eboekhouden_mutation_nr"),
            ("Payment Entry", "eboekhouden_mutation_nr"),
            ("Journal Entry", "eboekhouden_mutation_nr"),
        ]

        for doctype, field in doctypes:
            filters = {field: ["!=", ""]}

            if from_date:
                filters["posting_date"] = [">=", from_date]
            if to_date:
                filters["posting_date"] = ["<=", to_date]

            docs = frappe.get_all(
                doctype, filters=filters, fields=["name", field, "posting_date", "modified"]
            )

            for doc in docs:
                existing_docs.append(
                    {
                        "doctype": doctype,
                        "name": doc.name,
                        "mutation_id": int(doc[field]),
                        "posting_date": doc.posting_date,
                        "modified": doc.modified,
                    }
                )

        return existing_docs

    def _needs_update(self, doc_info, mutation_detail):
        """Check if document needs updating based on E-Boekhouden data"""
        # Check key fields that might change
        checks = []

        # Check amount
        if "amount" in mutation_detail:
            doc = frappe.get_doc(doc_info["doctype"], doc_info["name"])
            if hasattr(doc, "grand_total"):
                checks.append(abs(float(doc.grand_total) - float(mutation_detail["amount"])) > 0.01)

        # Check description
        if "description" in mutation_detail:
            doc = frappe.get_doc(doc_info["doctype"], doc_info["name"])
            if hasattr(doc, "remarks"):
                checks.append(doc.remarks != mutation_detail["description"])

        # Check line items count
        if "Regels" in mutation_detail:
            doc = frappe.get_doc(doc_info["doctype"], doc_info["name"])
            if hasattr(doc, "items"):
                checks.append(len(doc.items) != len(mutation_detail["Regels"]))

        return any(checks)

    def _update_document(self, doc_info, mutation_detail):
        """Update existing document with new data"""
        doc = frappe.get_doc(doc_info["doctype"], doc_info["name"])

        # Cancel existing document
        if doc.docstatus == 1:
            doc.cancel()

        # Delete and reimport (cleanest approach)
        frappe.delete_doc(doc_info["doctype"], doc_info["name"], force=True)

        # Reimport with new data
        debug_info = []
        from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import _process_single_mutation

        _process_single_mutation(mutation_detail, self.company, self.cost_center, debug_info)

    @frappe.whitelist()
    def get_import_status(self, from_date=None, to_date=None):
        """Get current import status and statistics"""
        status = {
            "total_imported": 0,
            "by_type": {},
            "date_range": {"from": from_date or "All time", "to": to_date or "Current"},
            "last_import": None,
        }

        doctypes = [
            ("Sales Invoice", "Sales Invoices"),
            ("Purchase Invoice", "Purchase Invoices"),
            ("Payment Entry", "Payments"),
            ("Journal Entry", "Journal Entries"),
        ]

        for doctype, label in doctypes:
            count = frappe.db.count(doctype, {"eboekhouden_mutation_nr": ["!=", ""]})
            status["by_type"][label] = count
            status["total_imported"] += count

        # Get last import date
        last_import = frappe.db.sql(
            """
            SELECT MAX(modified) as last_modified
            FROM `tabSales Invoice`
            WHERE eboekhouden_mutation_nr != ''
            UNION
            SELECT MAX(modified) as last_modified
            FROM `tabPurchase Invoice`
            WHERE eboekhouden_mutation_nr != ''
            UNION
            SELECT MAX(modified) as last_modified
            FROM `tabPayment Entry`
            WHERE eboekhouden_mutation_nr != ''
            UNION
            SELECT MAX(modified) as last_modified
            FROM `tabJournal Entry`
            WHERE eboekhouden_mutation_nr != ''
            ORDER BY last_modified DESC
            LIMIT 1
        """,
            as_dict=True,
        )

        if last_import and len(last_import) > 0 and last_import[0].get("last_modified"):
            status["last_import"] = last_import[0]["last_modified"]

        return status


# Convenience functions
@frappe.whitelist()
def clean_import_all(from_date=None, to_date=None):
    """Clean import all E-Boekhouden data"""
    manager = EBoekhoudenImportManager()
    return manager.clean_import_all(from_date, to_date)


@frappe.whitelist()
def update_existing_imports(from_date=None, to_date=None, force_update=False):
    """Update existing E-Boekhouden imports"""
    manager = EBoekhoudenImportManager()
    return manager.update_existing_imports(from_date, to_date, force_update)


@frappe.whitelist()
def get_import_status():
    """Get E-Boekhouden import status"""
    manager = EBoekhoudenImportManager()
    return manager.get_import_status()
