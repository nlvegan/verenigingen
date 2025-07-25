import json
from collections import defaultdict

import frappe


@frappe.whitelist()
def analyze_tegenrekening_patterns():
    """Analyze E-Boekhouden transaction data to discover tegenrekening usage patterns"""
    try:
        response = []
        response.append("=== TEGENREKENING USAGE ANALYSIS ===")

        # Get E-Boekhouden API settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Import API class
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI(settings)

        # Fetch mutations (transactions)
        response.append("Fetching mutations from E-Boekhouden...")
        mutations_result = api.get_mutations()

        if not mutations_result["success"]:
            return f"Error fetching mutations: {mutations_result.get('error', 'Unknown error')}"

        try:
            mutations_data = json.loads(mutations_result["data"])
            mutations = mutations_data.get("items", [])
        except (json.JSONDecodeError, KeyError) as e:
            return f"Error parsing mutations data: {str(e)}"

        response.append(f"Found {len(mutations)} mutations")

        # Analyze tegenrekening usage
        tegenrekening_stats = defaultdict(
            lambda: {
                "count": 0,
                "total_amount": 0,
                "descriptions": set(),
                "transaction_types": set(),
                "sample_descriptions": [],
            }
        )

        account_patterns = defaultdict(int)

        for mut in mutations[:1000]:  # Analyze first 1000 for performance
            mut_type = mut.get("type", "")

            # Get mutation rows which contain the tegenrekening info
            rows = mut.get("rows", [])
            if not rows:
                continue

            for row in rows:
                ledger_id = row.get("ledgerId", "")
                amount = abs(float(row.get("amount", 0)))
                description = row.get("description", "") or mut.get("description", "")

                if ledger_id:
                    # Convert ledger_id to account code (need to map this)
                    # For now, use ledger_id directly
                    account_code = str(ledger_id)

                    stats = tegenrekening_stats[account_code]
                    stats["count"] += 1
                    stats["total_amount"] += amount
                    stats["descriptions"].add(description[:100])  # Limit description length
                    stats["transaction_types"].add(mut_type)

                    if len(stats["sample_descriptions"]) < 5:
                        stats["sample_descriptions"].append(description[:100])

                    # Analyze account patterns
                    if account_code.isdigit() and len(account_code) >= 3:
                        pattern = account_code[:2] + "xx"  # First 2 digits + xx
                        account_patterns[pattern] += 1

        # Convert sets to lists for JSON serialization
        for account_code, stats in tegenrekening_stats.items():
            stats["descriptions"] = list(stats["descriptions"])[:10]  # Limit to 10
            stats["transaction_types"] = list(stats["transaction_types"])

        response.append("\n=== TOP TEGENREKENING ACCOUNTS ===")

        # Sort by usage frequency
        sorted_accounts = sorted(tegenrekening_stats.items(), key=lambda x: x[1]["count"], reverse=True)

        for account_code, stats in sorted_accounts[:20]:  # Top 20
            avg_amount = stats["total_amount"] / stats["count"] if stats["count"] > 0 else 0
            response.append(f"\nAccount: {account_code}")
            response.append(f"  Usage: {stats['count']} transactions")
            response.append(f"  Avg Amount: €{avg_amount:.2f}")
            response.append(f"  Types: {', '.join(stats['transaction_types'])}")
            response.append("  Sample descriptions:")
            for desc in stats["sample_descriptions"][:3]:
                response.append(f"    - {desc}")

        response.append("\n=== ACCOUNT PATTERNS ===")
        sorted_patterns = sorted(account_patterns.items(), key=lambda x: x[1], reverse=True)

        for pattern, count in sorted_patterns[:15]:
            response.append(f"{pattern}: {count} transactions")

        response.append("\n=== MAPPING RECOMMENDATIONS ===")

        # Generate smart mapping suggestions based on patterns
        mapping_suggestions = []

        for account_code, stats in sorted_accounts[:10]:
            # Analyze descriptions to suggest item names
            common_words = []
            for desc in stats["descriptions"]:
                words = desc.lower().split()
                for word in words:
                    if len(word) > 3 and word not in ["voor", "van", "een", "het", "de", "en", "aan", "bij"]:
                        common_words.append(word)

            # Get most common words
            word_freq = defaultdict(int)
            for word in common_words:
                word_freq[word] += 1

            top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:3]
            suggested_name = " ".join([word.capitalize() for word, freq in top_words])

            if not suggested_name:
                suggested_name = f"Account {account_code} Services"

            mapping_suggestions.append(
                {
                    "account_code": account_code,
                    "suggested_item_name": suggested_name,
                    "usage_count": stats["count"],
                    "sample_description": stats["sample_descriptions"][0]
                    if stats["sample_descriptions"]
                    else "",
                }
            )

        response.append("Top mapping suggestions:")
        for suggestion in mapping_suggestions:
            response.append(
                f"  {suggestion['account_code']} → '{suggestion['suggested_item_name']}' ({suggestion['usage_count']} uses)"
            )

        return "\n".join(response)

    except Exception as e:
        return f"Error: {e}\n{frappe.get_traceback()}"


@frappe.whitelist()
def get_chart_of_accounts_mapping():
    """Get mapping between ledger IDs and account codes from E-Boekhouden Chart of Accounts"""
    try:
        response = []
        response.append("=== CHART OF ACCOUNTS MAPPING ===")

        # Get E-Boekhouden API settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Import API class
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI(settings)

        # Fetch chart of accounts
        response.append("Fetching Chart of Accounts from E-Boekhouden...")
        coa_result = api.get_chart_of_accounts()

        if not coa_result["success"]:
            return f"Error fetching CoA: {coa_result.get('error', 'Unknown error')}"

        try:
            coa_data = json.loads(coa_result["data"])
            accounts = coa_data.get("items", [])
        except (json.JSONDecodeError, KeyError) as e:
            return f"Error parsing CoA data: {str(e)}"

        response.append(f"Found {len(accounts)} accounts in Chart of Accounts")

        # Create mapping between ID and Code
        ledger_mapping = {}
        account_categories = defaultdict(list)

        for account in accounts:
            account_id = account.get("id", "")
            account_code = account.get("code", "")
            account_desc = account.get("description", "")
            account_category = account.get("category", "")

            if account_id and account_code:
                ledger_mapping[str(account_id)] = {
                    "code": account_code,
                    "description": account_desc,
                    "category": account_category,
                }

                account_categories[account_category].append(
                    {"id": account_id, "code": account_code, "description": account_desc}
                )

        response.append(f"\nCreated mapping for {len(ledger_mapping)} accounts")

        response.append("\n=== ACCOUNT CATEGORIES ===")
        for category, accts in account_categories.items():
            response.append(f"\n{category}: {len(accts)} accounts")
            for acc in accts[:5]:  # Show first 5 in each category
                response.append(f"  {acc['code']}: {acc['description']}")
            if len(accts) > 5:
                response.append(f"  ... and {len(accts) - 5} more")

        # Store mapping for future use
        frappe.cache().set_value("eboekhouden_ledger_mapping", ledger_mapping, expires_in_sec=3600)

        return "\n".join(response)

    except Exception as e:
        return f"Error: {e}\n{frappe.get_traceback()}"


@frappe.whitelist()
def generate_item_mapping_suggestions():
    """Generate intelligent item mapping suggestions based on account usage and descriptions"""
    try:
        response = []
        response.append("=== GENERATING ITEM MAPPING SUGGESTIONS ===")

        # Get cached ledger mapping
        ledger_mapping = frappe.cache().get_value("eboekhouden_ledger_mapping")
        if not ledger_mapping:
            response.append("No ledger mapping found. Please run get_chart_of_accounts_mapping first.")
            return "\n".join(response)

        # Analyze existing ERPNext accounts to understand current structure
        existing_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type, root_type, eboekhouden_grootboek_nummer
            FROM `tabAccount`
            WHERE company = 'Ned Ver Vegan'
            AND eboekhouden_grootboek_nummer IS NOT NULL
            ORDER BY eboekhouden_grootboek_nummer
        """,
            as_dict=True,
        )

        response.append(f"Found {len(existing_accounts)} ERPNext accounts with E-Boekhouden codes")

        # Generate mapping suggestions by account type
        suggestions = {"Income Account": [], "Expense Account": [], "Other": []}

        for account in existing_accounts:
            eb_code = account.eboekhouden_grootboek_nummer
            account_type = account.account_type or "Other"

            # Find ledger ID for this account code
            ledger_id = None
            for lid, data in ledger_mapping.items():
                if data["code"] == eb_code:
                    ledger_id = lid
                    break

            if ledger_id:
                # Generate item suggestion based on account name and type
                item_name = account.account_name

                # Clean up account name for item name
                item_name = item_name.replace(" - NVV", "")
                item_name = item_name.replace(f"{eb_code} - ", "")

                # Make it more item-like
                if account_type == "Income Account":
                    if "contributie" in item_name.lower():
                        item_name = "Membership Contributions"
                    elif "donatie" in item_name.lower():
                        item_name = "Donations"
                    elif "verkoop" in item_name.lower():
                        item_name = "Product Sales"
                    elif "advertentie" in item_name.lower():
                        item_name = "Advertising Revenue"
                elif account_type == "Expense Account":
                    if "kantoor" in item_name.lower():
                        item_name = "Office Expenses"
                    elif "reis" in item_name.lower():
                        item_name = "Travel Expenses"
                    elif "marketing" in item_name.lower():
                        item_name = "Marketing Services"

                suggestion = {
                    "ledger_id": ledger_id,
                    "account_code": eb_code,
                    "account_name": account.account_name,
                    "account_type": account_type,
                    "suggested_item_name": item_name,
                    "suggested_item_code": f"EB-{eb_code}",
                    "erpnext_account": account.name,
                }

                suggestions[account_type].append(suggestion)

        # Display suggestions
        for account_type, items in suggestions.items():
            if items:
                response.append(f"\n=== {account_type.upper()} ITEMS ===")
                for item in items[:10]:  # Show first 10
                    response.append(f"Code: {item['account_code']} → Item: '{item['suggested_item_name']}'")
                    response.append(f"  ERPNext Account: {item['erpnext_account']}")
                    response.append(f"  Item Code: {item['suggested_item_code']}")
                    response.append("")

        # Store suggestions for Phase 2
        frappe.cache().set_value("item_mapping_suggestions", suggestions, expires_in_sec=3600)

        return "\n".join(response)

    except Exception as e:
        return f"Error: {e}\n{frappe.get_traceback()}"
