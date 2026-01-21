"""
Check if the failing mutations were imported successfully in the past
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def check_existing_journal_entries() -> OperationResult[Dict[str, Any]]:
    """Check if these mutation IDs already exist in Journal Entry documents"""
    try:
        failing_mutations = [1256, 4549, 5570, 5577, 6338]

        results = []
        for mutation_id in failing_mutations:
            # Check Journal Entries
            je_entries = frappe.get_all(
                "Journal Entry",
                filters={"eboekhouden_mutation_nr": str(mutation_id)},
                fields=["name", "posting_date", "total_debit", "total_credit", "user_remark", "docstatus"],
                limit=5,
            )

            # Check Purchase Invoices
            pi_entries = frappe.get_all(
                "Purchase Invoice",
                filters={"eboekhouden_mutation_nr": str(mutation_id)},
                fields=["name", "posting_date", "grand_total", "supplier", "docstatus"],
                limit=5,
            )

            # Check Sales Invoices
            si_entries = frappe.get_all(
                "Sales Invoice",
                filters={"eboekhouden_mutation_nr": str(mutation_id)},
                fields=["name", "posting_date", "grand_total", "customer", "docstatus"],
                limit=5,
            )

            # Check Payment Entries
            pe_entries = frappe.get_all(
                "Payment Entry",
                filters={"eboekhouden_mutation_nr": str(mutation_id)},
                fields=["name", "posting_date", "paid_amount", "party", "docstatus"],
                limit=5,
            )

            results.append(
                {
                    "mutation_id": mutation_id,
                    "journal_entries": je_entries,
                    "purchase_invoices": pi_entries,
                    "sales_invoices": si_entries,
                    "payment_entries": pe_entries,
                    "total_documents": len(je_entries) + len(pi_entries) + len(si_entries) + len(pe_entries),
                    "was_imported_before": len(je_entries)
                    + len(pi_entries)
                    + len(si_entries)
                    + len(pe_entries)
                    > 0,
                }
            )

        data = {
            "mutation_check_results": results,
            "summary": f"Checked {len(failing_mutations)} failing mutations for existing imports",
        }

        return OperationResult.ok(
            data,
            message=_("Successfully checked {0} mutations for existing imports").format(
                len(failing_mutations)
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Failed to check existing journal entries"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Failed to check existing journal entries: {0}").format(str(e))
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_journal_entry_details() -> OperationResult[Dict[str, Any]]:
    """Get detailed information about existing journal entries for these mutations"""
    try:
        failing_mutations = [1256, 4549, 5570, 5577, 6338]

        results = []
        for mutation_id in failing_mutations:
            # Get journal entry details if they exist
            je_list = frappe.get_all(
                "Journal Entry",
                filters={"eboekhouden_mutation_nr": str(mutation_id)},
                fields=["name"],
                limit=1,
            )

            if je_list:
                je_name = je_list[0].name
                je_doc = frappe.get_doc("Journal Entry", je_name)

                # Get account details from journal entry accounts
                accounts_info = []
                for account in je_doc.accounts:
                    account_type = frappe.db.get_value("Account", account.account, "account_type")
                    accounts_info.append(
                        {
                            "account": account.account,
                            "account_type": account_type,
                            "debit": account.debit,
                            "credit": account.credit,
                            "cost_center": account.cost_center,
                        }
                    )

                results.append(
                    {
                        "mutation_id": mutation_id,
                        "journal_entry": je_name,
                        "posting_date": je_doc.posting_date,
                        "total_debit": je_doc.total_debit,
                        "total_credit": je_doc.total_credit,
                        "user_remark": je_doc.user_remark,
                        "accounts": accounts_info,
                        "has_stock_account": any(acc["account_type"] == "Stock" for acc in accounts_info),
                    }
                )
            else:
                results.append(
                    {
                        "mutation_id": mutation_id,
                        "journal_entry": None,
                        "message": "No journal entry found for this mutation",
                    }
                )

        data = {
            "journal_entry_details": results,
            "analysis": "Shows if these mutations were previously imported and how the accounts were handled",
        }

        return OperationResult.ok(
            data,
            message=_("Successfully retrieved journal entry details for {0} mutations").format(
                len(failing_mutations)
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Failed to get journal entry details"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Failed to get journal entry details: {0}").format(str(e))
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def check_mutation_import_history() -> OperationResult[Dict[str, Any]]:
    """Check when these mutations might have been imported and what changed"""
    try:
        failing_mutations = [1256, 4549, 5570, 5577, 6338]

        # Check different document types that might have these mutation IDs
        document_types = ["Journal Entry", "Sales Invoice", "Purchase Invoice", "Payment Entry"]

        all_results = {}
        for doc_type in document_types:
            docs_with_mutations = frappe.get_all(
                doc_type,
                filters={"eboekhouden_mutation_nr": ["in", [str(m) for m in failing_mutations]]},
                fields=["name", "creation", "modified", "eboekhouden_mutation_nr", "docstatus"],
                order_by="creation desc",
            )

            if docs_with_mutations:
                all_results[doc_type] = docs_with_mutations

        found_count = sum(len(docs) for docs in all_results.values())

        data = {
            "import_history": all_results,
            "found_documents": found_count,
            "explanation": "Shows if these mutations were imported before and in what document types",
        }

        return OperationResult.ok(
            data,
            message=_("Found {0} documents matching {1} mutations").format(
                found_count, len(failing_mutations)
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Failed to check mutation import history"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Failed to check mutation import history: {0}").format(str(e))
        )
