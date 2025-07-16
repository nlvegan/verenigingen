#!/usr/bin/env python3
"""
Recalculate opening balance totals correctly
"""

import frappe


@frappe.whitelist()
def recalculate_opening_balance_totals():
    """Recalculate opening balance totals correctly"""

    print("Recalculating opening balance totals...")

    # Get opening balance entries from eBoekhouden
    import requests

    from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

    iterator = EBoekhoudenRESTIterator()
    url = f"{iterator.base_url}/v1/mutation"
    params = {"type": 0}
    response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

    if response.status_code == 200:
        data = response.json()
        entries = data.get("items", [])

        assets_total = 0
        liabilities_total = 0
        equity_total = 0
        receivable_total = 0
        payable_total = 0

        print(f"\nFound {len(entries)} opening balance entries:")
        print("=" * 80)
        print(f"{'ACCOUNT TYPE':>15} | {'LEDGER':>6} | {'AMOUNT':>12} | {'ACCOUNT'}")
        print("=" * 80)

        for entry in entries:
            amount = frappe.utils.flt(entry.get("amount", 0), 2)
            ledger_id = entry.get("ledgerId")

            if amount == 0:
                continue

            # Get account mapping
            mapping = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "erpnext_account"
            )

            if mapping:
                account_details = frappe.db.get_value(
                    "Account", mapping, ["account_type", "root_type"], as_dict=True
                )

                if account_details:
                    account_type = account_details.account_type
                    root_type = account_details.root_type

                    if account_type == "Receivable":
                        receivable_total += amount
                        category = "RECEIVABLE"
                    elif account_type == "Payable":
                        payable_total += amount
                        category = "PAYABLE"
                    elif root_type == "Asset":
                        assets_total += amount
                        category = "ASSET"
                    elif root_type == "Liability":
                        liabilities_total += amount
                        category = "LIABILITY"
                    elif root_type == "Equity":
                        equity_total += amount
                        category = "EQUITY"
                    else:
                        category = f"{root_type or 'UNKNOWN'}"
                else:
                    category = "NO_DETAILS"
            else:
                category = "UNMAPPED"

            print(f"{category:>15} | {ledger_id:>6} | {amount:>12.2f} | {mapping or 'Not mapped'}")

        print("=" * 80)
        print(f"{'TOTALS BY TYPE':>15} | {'':>6} | {'':>12} |")
        print("=" * 80)
        print(f"{'Assets':>15} | {'':>6} | {assets_total:>12.2f} |")
        print(f"{'Receivables':>15} | {'':>6} | {receivable_total:>12.2f} |")
        print(f"{'Liabilities':>15} | {'':>6} | {liabilities_total:>12.2f} |")
        print(f"{'Payables':>15} | {'':>6} | {payable_total:>12.2f} |")
        print(f"{'Equity':>15} | {'':>6} | {equity_total:>12.2f} |")

        # Calculate the accounting equation
        total_debits = assets_total + receivable_total  # Assets and receivables are debits
        total_credits = (
            liabilities_total + payable_total + equity_total
        )  # Liabilities, payables, and equity are credits

        print("=" * 80)
        print(f"{'ACCOUNTING EQUATION':>15} | {'':>6} | {'':>12} |")
        print("=" * 80)
        print(f"{'Total Debits':>15} | {'':>6} | {total_debits:>12.2f} | (Assets + Receivables)")
        print(f"{'Total Credits':>15} | {'':>6} | {total_credits:>12.2f} | (Liabilities + Payables + Equity)")
        print(
            f"{'Difference':>15} | {'':>6} | {total_debits - total_credits:>12.2f} | (Should be close to 0)"
        )

        if abs(total_debits - total_credits) > 0.01:
            print(f"\n⚠️  IMBALANCE: Difference is {abs(total_debits - total_credits):.2f}")
            print("This difference will be posted to account 9999 for balancing.")
        else:
            print(f"\n✅ BALANCED: Difference is {total_debits - total_credits:.2f} (essentially zero)")

    return {"success": True}


if __name__ == "__main__":
    print("Recalculate opening balance totals")
