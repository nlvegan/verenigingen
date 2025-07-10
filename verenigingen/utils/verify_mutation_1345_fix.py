#!/usr/bin/env python3
"""
Verify that mutation 1345 was imported correctly with proper account mappings
"""

import frappe


@frappe.whitelist()
def verify_mutation_1345_fix():
    """Verify the mutation 1345 was imported correctly"""
    try:
        # Find the new Journal Entry for mutation 1345
        je_entries = frappe.db.sql(
            """SELECT name, title, posting_date, user_remark, total_debit, total_credit, creation
               FROM `tabJournal Entry`
               WHERE eboekhouden_mutation_nr = %s
               ORDER BY creation DESC""",
            "1345",
            as_dict=True,
        )

        if not je_entries:
            return {"success": False, "error": "No Journal Entry found for mutation 1345"}

        latest_je = je_entries[0]
        je_name = latest_je["name"]

        # Get all accounts for this Journal Entry
        accounts = frappe.db.sql(
            """SELECT account, debit, credit, debit_in_account_currency,
                      credit_in_account_currency, user_remark
               FROM `tabJournal Entry Account`
               WHERE parent = %s
               ORDER BY idx""",
            je_name,
            as_dict=True,
        )

        # Analyze the accounts
        analysis = {
            "journal_entry": latest_je,
            "accounts": accounts,
            "account_analysis": [],
            "balancing_entry": None,
            "issues": [],
        }

        # Check each account
        for account in accounts:
            account_analysis = {
                "account": account["account"],
                "debit": float(account["debit"] or 0),
                "credit": float(account["credit"] or 0),
                "user_remark": account["user_remark"],
                "is_balancing": "Balancing entry" in (account["user_remark"] or ""),
            }

            # Identify the expected account based on ledger mapping
            if "99998 - Eindresultaat" in account["account"]:
                account_analysis["expected"] = "✅ CORRECT - Main ledger (99998)"
                account_analysis["correct"] = True
            elif "05292 - Bestemmingsreserve Melk Je Kan Zonder" in account["account"]:
                account_analysis["expected"] = "✅ CORRECT - Row ledger (13201866)"
                account_analysis["correct"] = True
            elif "05000 - Vrij besteedbaar eigen vermogen" in account["account"]:
                account_analysis["expected"] = "✅ CORRECT - Row ledger (13201865)"
                account_analysis["correct"] = True
            else:
                account_analysis["expected"] = "❓ UNKNOWN - Not expected for mutation 1345"
                account_analysis["correct"] = False

            if account_analysis["is_balancing"]:
                analysis["balancing_entry"] = account_analysis

            analysis["account_analysis"].append(account_analysis)

        # Verify balancing entry uses correct account
        if analysis["balancing_entry"]:
            if "99998 - Eindresultaat" in analysis["balancing_entry"]["account"]:
                analysis["balancing_correct"] = True
                analysis["balancing_status"] = "✅ FIXED - Balancing entry uses main ledger (99998)"
            else:
                analysis["balancing_correct"] = False
                analysis[
                    "balancing_status"
                ] = "❌ WRONG - Balancing entry uses {analysis['balancing_entry']['account']}"
                analysis["issues"].append("Balancing entry still uses wrong account")
        else:
            analysis["balancing_correct"] = False
            analysis["balancing_status"] = "❌ NO BALANCING ENTRY FOUND"
            analysis["issues"].append("No balancing entry found")

        # Check for duplicate accounts (should be fixed)
        account_names = [acc["account"] for acc in accounts]
        account_counts = {}
        for acc_name in account_names:
            account_counts[acc_name] = account_counts.get(acc_name, 0) + 1

        duplicate_accounts = {acc: count for acc, count in account_counts.items() if count > 1}
        if duplicate_accounts:
            analysis["duplicate_accounts"] = duplicate_accounts
            analysis["issues"].append("Duplicate accounts found: {duplicate_accounts}")
        else:
            analysis["duplicate_accounts"] = None
            analysis["duplicate_status"] = "✅ NO DUPLICATES - Each account used appropriately"

        # Overall assessment
        if not analysis["issues"]:
            analysis[
                "overall_status"
            ] = "✅ SUCCESS - Mutation 1345 imported correctly with proper ledger mapping"
            analysis["fix_successful"] = True
        else:
            analysis["overall_status"] = "❌ ISSUES REMAIN - {len(analysis['issues'])} problems found"
            analysis["fix_successful"] = False

        return {"success": True, "analysis": analysis}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
