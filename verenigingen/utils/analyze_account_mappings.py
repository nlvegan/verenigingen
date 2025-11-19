"""
Analyze E-Boekhouden account mappings to understand why transactions are mapped incorrectly
"""

import json
from collections import defaultdict

import frappe


@frappe.whitelist()
def analyze_imported_transactions():
    """Analyze how transactions were mapped to accounts"""

    try:
        # Get all accounts that have been used in recent transactions
        account_usage = frappe.db.sql(
            """
            SELECT
                gle.account,
                a.account_name,
                a.account_number,
                COUNT(*) as transaction_count,
                SUM(gle.debit) as total_debit,
                SUM(gle.credit) as total_credit
            FROM `tabGL Entry` gle
            JOIN `tabAccount` a ON gle.account = a.name
            WHERE gle.posting_date >= '2025-01-01'
            AND gle.company = 'Ned Ver Vegan'
            GROUP BY gle.account
            ORDER BY transaction_count DESC
            LIMIT 20
        """,
            as_dict=True,
        )

        # Get sample transactions for the most used accounts
        top_accounts = [
            "99998 - Eindresultaat - NVV",
            "48010 - Afschrijving Inventaris - NVV",
            "18100 - Te ontvangen BTW - NVV",
            "14700 - Crediteuren handelsschulden - NVV",
            "13900 - Debiteuren handelsvorderingen - NVV",
            "10620 - ABN AMRO zakelijke rekening - NVV",
        ]

        account_samples = {}

        for account in top_accounts:
            if frappe.db.exists("Account", account):
                # Get sample GL entries
                samples = frappe.db.sql(
                    """
                    SELECT
                        gle.voucher_type,
                        gle.voucher_no,
                        gle.posting_date,
                        gle.debit,
                        gle.credit,
                        gle.remarks
                    FROM `tabGL Entry` gle
                    WHERE gle.account = %s
                    AND gle.posting_date >= '2025-01-01'
                    ORDER BY gle.posting_date DESC
                    LIMIT 5
                """,
                    account,
                    as_dict=True,
                )

                account_samples[account] = samples

        return {"success": True, "account_usage": account_usage, "account_samples": account_samples}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_tegenrekening_mappings():
    """Check how tegenrekening codes are being mapped"""

    try:
        # Get E-Boekhouden REST mutation cache to see original data
        cache_samples = frappe.db.sql(
            """
            SELECT
                mutation_id,
                ledger_id,
                description,
                amount,
                mutation_type,
                mutation_data
            FROM `tabEBoekhouden REST Mutation Cache`
            WHERE mutation_type IN (1, 2, 5, 6, 7)
            ORDER BY mutation_id DESC
            LIMIT 20
        """,
            as_dict=True,
        )

        # Parse mutation data to see ledger accounts
        ledger_analysis = defaultdict(lambda: {"count": 0, "descriptions": [], "types": set()})

        for cache in cache_samples:
            if cache.mutation_data:
                try:
                    data = json.loads(cache.mutation_data)

                    # Check rows for ledger accounts
                    rows = data.get("rows", [])
                    for row in rows:
                        ledger_id = row.get("ledgerId")
                        if ledger_id:
                            ledger_analysis[ledger_id]["count"] += 1
                            ledger_analysis[ledger_id]["descriptions"].append(
                                cache.description[:50] if cache.description else ""
                            )
                            ledger_analysis[ledger_id]["types"].add(cache.mutation_type)

                except Exception:
                    pass

        # Get tegenrekening mappings
        mappings = frappe.get_all(
            "E-Boekhouden Tegenrekening Mapping",
            fields=["name", "tegenrekening_code", "account", "description"],
            limit=50,
        )

        return {
            "success": True,
            "cache_samples": cache_samples[:10],  # First 10 for detail
            "ledger_analysis": dict(ledger_analysis),
            "existing_mappings": mappings,
            "mappings_count": len(mappings),
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def trace_specific_mutation(mutation_id):
    """Trace how a specific mutation was imported"""

    try:
        # Get mutation from cache
        cache = frappe.db.get_value(
            "EBoekhouden REST Mutation Cache",
            {"mutation_id": mutation_id},
            ["mutation_data", "mutation_type", "description", "amount", "ledger_id"],
            as_dict=True,
        )

        if not cache:
            return {"success": False, "error": "Mutation {mutation_id} not found in cache"}  # noqa: E713

        result = {
            "mutation_id": mutation_id,
            "cache_data": cache,
            "parsed_data": None,
            "ledger_accounts": [],
            "created_documents": [],
        }

        # Parse mutation data
        if cache.mutation_data:
            data = json.loads(cache.mutation_data)
            result["parsed_data"] = data

            # Extract ledger accounts from rows
            rows = data.get("rows", [])
            for row in rows:
                ledger_info = {
                    "ledger_id": row.get("ledgerId"),
                    "ledger_name": row.get("ledgerName"),
                    "amount": row.get("amount"),
                    "debit_credit": row.get("debitCredit"),
                }
                result["ledger_accounts"].append(ledger_info)

        # Try to find created documents
        invoice_no = f"EBH-{mutation_id}"

        # Check Purchase Invoices
        pinv = frappe.db.get_value(
            "Purchase Invoice",
            {"bill_no": invoice_no},
            ["name", "supplier", "total", "docstatus"],
            as_dict=True,
        )
        if pinv:
            result["created_documents"].append({"type": "Purchase Invoice", "doc": pinv})

        # Check Sales Invoices
        sinv = frappe.db.get_value(
            "Sales Invoice",
            {"customer": "E-Boekhouden Import"},
            ["name", "customer", "total", "docstatus"],
            as_dict=True,
            order_by="creation desc",
            limit=1,
        )
        if sinv:
            result["created_documents"].append({"type": "Sales Invoice", "doc": sinv})

        return {"success": True, "result": result}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
