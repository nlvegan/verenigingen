"""
Check if the failing mutations were imported successfully in the past
"""

import frappe


@frappe.whitelist()
def check_existing_journal_entries():
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

        return {
            "success": True,
            "mutation_check_results": results,
            "summary": f"Checked {len(failing_mutations)} failing mutations for existing imports",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def get_journal_entry_details():
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

        return {
            "success": True,
            "journal_entry_details": results,
            "analysis": "Shows if these mutations were previously imported and how the accounts were handled",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_mutation_import_history():
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

        return {
            "success": True,
            "import_history": all_results,
            "found_documents": sum(len(docs) for docs in all_results.values()),
            "explanation": "Shows if these mutations were imported before and in what document types",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
