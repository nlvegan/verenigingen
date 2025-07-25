"""Debug item categorization"""

import frappe


@frappe.whitelist()
def debug_categorization():
    """Debug why kantoorartikelen is being categorized as Products"""

    from verenigingen.e_boekhouden.utils.field_mapping import ITEM_GROUP_KEYWORDS
    from verenigingen.e_boekhouden.utils.invoice_helpers import determine_item_group

    description = "Kantoorartikelen en paperclips"
    description_lower = description.lower()

    results = {"description": description, "description_lower": description_lower, "keyword_matches": {}}

    # Check which keywords match
    for group, keywords in ITEM_GROUP_KEYWORDS.items():
        matches = []
        for keyword in keywords:
            if keyword in description_lower:
                matches.append(keyword)
        if matches:
            results["keyword_matches"][group] = matches

    # Test the function
    result = determine_item_group(description, btw_code="HOOG_VERK_21", account_code="46500", price=25.00)

    results["final_result"] = result

    # Check if artikel is matching product
    results["artikel_in_desc"] = "artikel" in description_lower
    results["product_keywords"] = ITEM_GROUP_KEYWORDS.get("product", [])[:10]  # First 10
    results["office_keywords"] = ITEM_GROUP_KEYWORDS.get("office", [])[:10]  # First 10

    return results


@frappe.whitelist()
def analyze_journal_entries():
    """Analyze current Journal Entries with E-Boekhouden data"""

    # Query journal entries with E-Boekhouden mutation numbers
    journal_entries = frappe.db.sql(
        """
        SELECT
            name,
            posting_date,
            voucher_type,
            total_debit,
            total_credit,
            user_remark,
            eboekhouden_mutation_nr,
            creation,
            modified
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND eboekhouden_mutation_nr != ''
        ORDER BY eboekhouden_mutation_nr
        LIMIT 20
    """,
        as_dict=True,
    )

    result = {"total_count": len(journal_entries), "entries": journal_entries, "sample_details": None}

    # Get detailed entries for the first one
    if journal_entries:
        sample_je = journal_entries[0]
        accounts = frappe.db.sql(
            """
            SELECT
                account,
                debit_in_account_currency,
                credit_in_account_currency,
                user_remark
            FROM `tabJournal Entry Account`
            WHERE parent = %s
        """,
            (sample_je.name,),
            as_dict=True,
        )

        result["sample_details"] = {"journal_entry": sample_je, "accounts": accounts}

    return result


@frappe.whitelist()
def get_raw_eboekhouden_mutations():
    """Fetch raw E-Boekhouden data for specific mutations: 1339, 1344, 3697, 6334, 6738, 2461, 2457, 3688, 3698, 4595"""
    import json

    from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

    mutation_ids = [1339, 1344, 3697, 6334, 6738, 2461, 2457, 3688, 3698, 4595]

    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        results = {
            "success": True,
            "mutations": {},
            "errors": [],
            "analysis": {"total_requested": len(mutation_ids), "successful": 0, "failed": 0},
        }

        for mutation_id in mutation_ids:
            try:
                # Fetch specific mutation by ID
                result = api.make_request(f"v1/mutation/{mutation_id}")

                if result["success"]:
                    mutation_data = json.loads(result["data"])
                    results["mutations"][str(mutation_id)] = {
                        "raw_data": mutation_data,
                        "analysis": {
                            "mutation_type": mutation_data.get("type"),
                            "date": mutation_data.get("date"),
                            "description": mutation_data.get("description"),
                            "amount": mutation_data.get("amount"),
                            "debit": mutation_data.get("debit"),
                            "credit": mutation_data.get("credit"),
                            "invoice_number": mutation_data.get("invoiceNumber"),
                            "relation_id": mutation_data.get("relationId"),
                            "ledger_id": mutation_data.get("ledgerId"),
                            "is_memorial": mutation_data.get("type") == "Memorial",
                            "has_relation": bool(mutation_data.get("relationId")),
                            "has_invoice_number": bool(mutation_data.get("invoiceNumber")),
                            "amount_negative": (mutation_data.get("amount", 0) < 0),
                        },
                    }
                    results["analysis"]["successful"] += 1
                else:
                    results["errors"].append(
                        f"Failed to fetch mutation {mutation_id}: {result.get('error', 'Unknown error')}"
                    )
                    results["analysis"]["failed"] += 1

            except Exception as e:
                results["errors"].append(f"Error fetching mutation {mutation_id}: {str(e)}")
                results["analysis"]["failed"] += 1

        return results

    except Exception as e:
        return {"success": False, "error": f"Failed to initialize API: {str(e)}"}


@frappe.whitelist()
def compare_journal_entries_to_raw_data():
    """Compare existing Journal Entries to raw E-Boekhouden data for mutations: 1339, 1344, 3697, 6334, 6738, 2461, 2457, 3688, 3698, 4595"""

    mutation_ids = ["1339", "1344", "3697", "6334", "6738", "2461", "2457", "3688", "3698", "4595"]

    # Get Journal Entries with these mutation numbers
    journal_entries = frappe.db.sql(
        """
        SELECT
            name,
            posting_date,
            voucher_type,
            total_debit,
            total_credit,
            user_remark,
            eboekhouden_mutation_nr,
            creation,
            modified
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr IN ({})
        ORDER BY eboekhouden_mutation_nr
    """.format(
            ",".join(["%s"] * len(mutation_ids))
        ),
        tuple(mutation_ids),
        as_dict=True,
    )

    # Get account details for each journal entry
    je_details = {}
    for je in journal_entries:
        accounts = frappe.db.sql(
            """
            SELECT
                account,
                debit_in_account_currency,
                credit_in_account_currency,
                user_remark
            FROM `tabJournal Entry Account`
            WHERE parent = %s
            ORDER BY idx
        """,
            (je.name,),
            as_dict=True,
        )

        je_details[je.eboekhouden_mutation_nr] = {"journal_entry": je, "accounts": accounts}

    # Now get the raw E-Boekhouden data for comparison
    raw_data_result = get_raw_eboekhouden_mutations()

    # Compare each mutation
    comparison = {
        "found_in_system": [],
        "missing_from_system": [],
        "data_mismatches": [],
        "summary": {
            "total_mutations": len(mutation_ids),
            "found_in_system": 0,
            "missing_from_system": 0,
            "data_issues": 0,
        },
    }

    for mutation_id in mutation_ids:
        if mutation_id in je_details:
            # Found in system - compare data
            comparison["found_in_system"].append(mutation_id)
            comparison["summary"]["found_in_system"] += 1

            je_data = je_details[mutation_id]
            raw_data = raw_data_result["mutations"].get(mutation_id, {}).get("raw_data", {})

            # Compare key fields
            mismatch_details = []

            # Date comparison
            je_date = str(je_data["journal_entry"]["posting_date"])
            raw_date = raw_data.get("date", "")
            if je_date != raw_date:
                mismatch_details.append(f"Date mismatch: JE={je_date}, Raw={raw_date}")

            # Description comparison
            je_desc = je_data["journal_entry"]["user_remark"] or ""
            raw_desc = raw_data.get("description", "")
            if raw_desc not in je_desc and je_desc not in raw_desc:
                mismatch_details.append(f"Description mismatch: JE='{je_desc}', Raw='{raw_desc}'")

            # Amount comparison - need to calculate from rows
            raw_total = 0
            if "rows" in raw_data:
                for row in raw_data["rows"]:
                    raw_total += abs(row.get("amount", 0))

            je_total = float(je_data["journal_entry"]["total_debit"] or 0)
            if abs(raw_total - je_total) > 0.01:
                mismatch_details.append(f"Amount mismatch: JE={je_total}, Raw={raw_total}")

            if mismatch_details:
                comparison["data_mismatches"].append(
                    {
                        "mutation_id": mutation_id,
                        "journal_entry_name": je_data["journal_entry"]["name"],
                        "mismatches": mismatch_details,
                        "je_data": je_data,
                        "raw_data": raw_data,
                    }
                )
                comparison["summary"]["data_issues"] += 1

        else:
            # Missing from system
            comparison["missing_from_system"].append(mutation_id)
            comparison["summary"]["missing_from_system"] += 1

    return {
        "success": True,
        "comparison": comparison,
        "system_entries": je_details,
        "raw_data": raw_data_result["mutations"] if raw_data_result["success"] else {},
    }


@frappe.whitelist()
def verify_ledger_mappings():
    """Verify the ledger ID to ERPNext account mappings for mutation 1339"""

    # Ledger IDs from mutation 1339
    ledger_ids = [13201861, 13201953]

    results = {"ledger_mappings": {}, "account_details": {}, "mapping_source": {}, "inconsistencies": []}

    for ledger_id in ledger_ids:
        # Check E-Boekhouden Ledger Mapping table
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(ledger_id)},
            ["erpnext_account", "ledger_code", "ledger_name"],
            as_dict=True,
        )

        if mapping:
            results["ledger_mappings"][str(ledger_id)] = mapping
            results["mapping_source"][str(ledger_id)] = "E-Boekhouden Ledger Mapping"
        else:
            # Check if account exists with eboekhouden_grootboek_nummer
            account = frappe.db.get_value(
                "Account",
                {"eboekhouden_grootboek_nummer": str(ledger_id)},
                ["name", "account_name", "account_type", "is_group"],
                as_dict=True,
            )

            if account:
                results["ledger_mappings"][str(ledger_id)] = {
                    "erpnext_account": account.name,
                    "ledger_code": str(ledger_id),
                    "ledger_name": account.account_name,
                }
                results["mapping_source"][str(ledger_id)] = "Account.eboekhouden_grootboek_nummer"
            else:
                results["ledger_mappings"][str(ledger_id)] = None
                results["mapping_source"][str(ledger_id)] = "NOT FOUND"

    # Get details of the accounts used in Journal Entry 1339
    je_1339 = frappe.db.sql(
        """
        SELECT
            jea.account,
            jea.debit_in_account_currency,
            jea.credit_in_account_currency,
            acc.account_type,
            acc.eboekhouden_grootboek_nummer
        FROM `tabJournal Entry Account` jea
        JOIN `tabAccount` acc ON acc.name = jea.account
        JOIN `tabJournal Entry` je ON je.name = jea.parent
        WHERE je.eboekhouden_mutation_nr = '1339'
        ORDER BY jea.idx
    """,
        as_dict=True,
    )

    results["actual_je_accounts"] = je_1339

    # Cross-check: Do the JE accounts match the expected mappings?
    for je_account in je_1339:
        eboekhouden_code = je_account.get("eboekhouden_grootboek_nummer")
        if eboekhouden_code:
            expected_mapping = results["ledger_mappings"].get(str(eboekhouden_code))
            if expected_mapping:
                if expected_mapping["erpnext_account"] != je_account["account"]:
                    results["inconsistencies"].append(
                        {
                            "ledger_id": eboekhouden_code,
                            "expected_account": expected_mapping["erpnext_account"],
                            "actual_account": je_account["account"],
                            "issue": "Account mismatch",
                        }
                    )
        else:
            # Account used in JE but no E-Boekhouden code
            results["inconsistencies"].append(
                {
                    "account": je_account["account"],
                    "issue": "No E-Boekhouden code on account used in memorial booking",
                }
            )

    # Get raw E-Boekhouden ledger data for these IDs
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        for ledger_id in ledger_ids:
            try:
                result = api.make_request(f"v1/ledger/{ledger_id}")
                if result["success"]:
                    import json

                    ledger_data = json.loads(result["data"])
                    results["account_details"][str(ledger_id)] = {
                        "raw_data": ledger_data,
                        "account_code": ledger_data.get("code"),
                        "account_name": ledger_data.get("description"),
                        "account_type": ledger_data.get("category"),
                        "balance": ledger_data.get("balance"),
                    }
                else:
                    results["account_details"][str(ledger_id)] = {
                        "error": f"Failed to fetch: {result.get('error', 'Unknown error')}"
                    }
            except Exception as e:
                results["account_details"][str(ledger_id)] = {"error": f"Exception: {str(e)}"}

    except Exception as e:
        results["api_error"] = f"Failed to initialize API: {str(e)}"

    return {
        "success": True,
        "results": results,
        "summary": {
            "total_ledgers_checked": len(ledger_ids),
            "mappings_found": len([m for m in results["ledger_mappings"].values() if m]),
            "inconsistencies_found": len(results["inconsistencies"]),
        },
    }


@frappe.whitelist()
def analyze_debit_credit_pattern():
    """Analyze the debit/credit pattern across memorial bookings to understand why some are correct and others inverted"""

    mutation_ids = ["1339", "1344", "3697", "6334", "6738", "2461", "2457", "3688", "3698", "4595"]

    # Get raw data for all mutations
    raw_data_result = get_raw_eboekhouden_mutations()

    # Get system journal entries for comparison
    comparison_result = compare_journal_entries_to_raw_data()

    analysis = {
        "mutation_analysis": {},
        "patterns": {
            "correct_posting": [],
            "inverted_posting": [],
            "amount_signs": {},
            "ledger_categories": {},
        },
        "hypotheses": [],
    }

    for mutation_id in mutation_ids:
        if mutation_id not in raw_data_result["mutations"]:
            continue

        raw_data = raw_data_result["mutations"][mutation_id]["raw_data"]
        system_data = comparison_result["system_entries"].get(mutation_id)

        if not system_data:
            continue

        # Analyze the structure
        main_ledger_id = raw_data.get("ledgerId")
        rows = raw_data.get("rows", [])

        mutation_analysis = {
            "mutation_id": mutation_id,
            "description": raw_data.get("description", ""),
            "main_ledger_id": main_ledger_id,
            "rows": [],
            "system_accounts": system_data["accounts"],
            "amount_signs": [],
            "posting_pattern": "unknown",
        }

        # Analyze each row
        for i, row in enumerate(rows):
            row_ledger_id = row.get("ledgerId")
            row_amount = row.get("amount", 0)
            row_desc = row.get("description", "")

            mutation_analysis["rows"].append(
                {
                    "ledger_id": row_ledger_id,
                    "amount": row_amount,
                    "description": row_desc,
                    "amount_sign": "negative" if row_amount < 0 else "positive",
                }
            )

            analysis["patterns"]["amount_signs"][mutation_id] = {
                "row_amount": row_amount,
                "sign": "negative" if row_amount < 0 else "positive",
            }

        # Determine posting pattern by checking if the amounts match expected logic
        # For a typical entry, if row amount is negative, row ledger should be credited
        # and main ledger should be debited
        if len(system_data["accounts"]) == 2:
            acc1 = system_data["accounts"][0]
            acc2 = system_data["accounts"][1]

            # Find which account corresponds to main ledger vs row ledger
            # We'll use the grootboek_nummer to match
            main_account = None
            row_account = None

            for acc in system_data["accounts"]:
                if str(acc.get("eboekhouden_grootboek_nummer")) == str(main_ledger_id):
                    main_account = acc
                elif len(rows) > 0 and str(acc.get("eboekhouden_grootboek_nummer")) == str(
                    rows[0]["ledgerId"]
                ):
                    row_account = acc

            if main_account and row_account and len(rows) > 0:
                row_amount = rows[0]["amount"]

                # Expected logic: if row amount is negative, row account should be credited
                expected_row_credit = row_amount < 0
                actual_row_credit = row_account["credit_in_account_currency"] > 0

                if expected_row_credit == actual_row_credit:
                    mutation_analysis["posting_pattern"] = "correct"
                    analysis["patterns"]["correct_posting"].append(mutation_id)
                else:
                    mutation_analysis["posting_pattern"] = "inverted"
                    analysis["patterns"]["inverted_posting"].append(mutation_id)

                mutation_analysis["logic_check"] = {
                    "row_amount": row_amount,
                    "expected_row_credit": expected_row_credit,
                    "actual_row_credit": actual_row_credit,
                    "main_account": main_account["account"],
                    "row_account": row_account["account"],
                }

        analysis["mutation_analysis"][mutation_id] = mutation_analysis

    # Look for patterns
    # Check if there's a correlation with amount signs
    negative_amounts = [
        mid for mid, data in analysis["patterns"]["amount_signs"].items() if data["sign"] == "negative"
    ]
    positive_amounts = [
        mid for mid, data in analysis["patterns"]["amount_signs"].items() if data["sign"] == "positive"
    ]

    analysis["hypotheses"].append(
        {
            "hypothesis": "Amount sign correlation",
            "negative_amount_mutations": negative_amounts,
            "positive_amount_mutations": positive_amounts,
            "inverted_mutations": analysis["patterns"]["inverted_posting"],
            "correct_mutations": analysis["patterns"]["correct_posting"],
        }
    )

    # Check for date patterns
    date_analysis = {}
    for mutation_id, mut_data in analysis["mutation_analysis"].items():
        if mutation_id in raw_data_result["mutations"]:
            date = raw_data_result["mutations"][mutation_id]["raw_data"].get("date")
            date_analysis[mutation_id] = {"date": date, "pattern": mut_data["posting_pattern"]}

    analysis["date_correlation"] = date_analysis

    # Check for ledger ID patterns
    main_ledger_patterns = {}
    for mutation_id, mut_data in analysis["mutation_analysis"].items():
        main_ledger = mut_data["main_ledger_id"]
        if main_ledger not in main_ledger_patterns:
            main_ledger_patterns[main_ledger] = []
        main_ledger_patterns[main_ledger].append(
            {"mutation_id": mutation_id, "pattern": mut_data["posting_pattern"]}
        )

    analysis["ledger_id_patterns"] = main_ledger_patterns

    return {
        "success": True,
        "analysis": analysis,
        "summary": {
            "total_analyzed": len(analysis["mutation_analysis"]),
            "correct_postings": len(analysis["patterns"]["correct_posting"]),
            "inverted_postings": len(analysis["patterns"]["inverted_posting"]),
        },
    }


@frappe.whitelist()
def analyze_account_categories():
    """Analyze E-Boekhouden account categories for all ledgers involved in memorial bookings"""

    mutation_ids = ["1339", "1344", "3697", "6334", "6738", "2461", "2457", "3688", "3698", "4595"]

    # Get raw data for all mutations
    raw_data_result = get_raw_eboekhouden_mutations()

    # Collect all unique ledger IDs
    all_ledger_ids = set()
    for mutation_id in mutation_ids:
        if mutation_id in raw_data_result["mutations"]:
            raw_data = raw_data_result["mutations"][mutation_id]["raw_data"]
            all_ledger_ids.add(raw_data.get("ledgerId"))
            for row in raw_data.get("rows", []):
                all_ledger_ids.add(row.get("ledgerId"))

    # Fetch account details for all ledger IDs
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        ledger_details = {}
        for ledger_id in all_ledger_ids:
            if ledger_id:
                try:
                    result = api.make_request(f"v1/ledger/{ledger_id}")
                    if result["success"]:
                        import json

                        ledger_data = json.loads(result["data"])
                        ledger_details[str(ledger_id)] = {
                            "id": ledger_id,
                            "code": ledger_data.get("code"),
                            "description": ledger_data.get("description"),
                            "category": ledger_data.get("category"),
                            "group": ledger_data.get("group"),
                            "balance": ledger_data.get("balance"),
                        }
                except Exception as e:
                    ledger_details[str(ledger_id)] = {"error": str(e)}

        # Now analyze each mutation with account categories
        mutation_analysis = {}

        for mutation_id in mutation_ids:
            if mutation_id not in raw_data_result["mutations"]:
                continue

            raw_data = raw_data_result["mutations"][mutation_id]["raw_data"]
            main_ledger_id = raw_data.get("ledgerId")
            rows = raw_data.get("rows", [])

            analysis = {
                "mutation_id": mutation_id,
                "description": raw_data.get("description", ""),
                "main_ledger": {"id": main_ledger_id, "details": ledger_details.get(str(main_ledger_id), {})},
                "row_ledgers": [],
                "category_combination": "",
                "posting_pattern": "unknown",
            }

            for row in rows:
                row_ledger_id = row.get("ledgerId")
                analysis["row_ledgers"].append(
                    {
                        "id": row_ledger_id,
                        "amount": row.get("amount"),
                        "details": ledger_details.get(str(row_ledger_id), {}),
                    }
                )

            # Create category combination string
            main_category = ledger_details.get(str(main_ledger_id), {}).get("category", "UNKNOWN")
            row_categories = []
            for row in analysis["row_ledgers"]:
                row_cat = row["details"].get("category", "UNKNOWN")
                row_categories.append(row_cat)

            analysis["category_combination"] = f"{main_category} -> {', '.join(row_categories)}"

            # Determine if this is correct or inverted based on user feedback
            # You mentioned 4595 is correct, all others are inverted
            if mutation_id == "4595":
                analysis["posting_pattern"] = "correct"
            else:
                analysis["posting_pattern"] = "inverted"

            mutation_analysis[mutation_id] = analysis

        # Group by category combinations
        category_patterns = {}
        for mutation_id, analysis in mutation_analysis.items():
            combo = analysis["category_combination"]
            pattern = analysis["posting_pattern"]

            if combo not in category_patterns:
                category_patterns[combo] = {"correct": [], "inverted": []}

            category_patterns[combo][pattern].append(mutation_id)

        # Analyze the correct vs inverted pattern
        correct_mutation = mutation_analysis.get("4595", {})
        correct_main_cat = correct_mutation.get("main_ledger", {}).get("details", {}).get("category")
        correct_row_cats = [row["details"].get("category") for row in correct_mutation.get("row_ledgers", [])]

        return {
            "success": True,
            "ledger_details": ledger_details,
            "mutation_analysis": mutation_analysis,
            "category_patterns": category_patterns,
            "correct_pattern": {
                "mutation_id": "4595",
                "main_category": correct_main_cat,
                "row_categories": correct_row_cats,
                "category_combination": correct_mutation.get("category_combination", ""),
            },
            "api_categories": {
                "BAL": "Balans (Balance Sheet)",
                "VW": "Verlies & Winst (P&L)",
                "BTM": "Betalingsmiddelen (Payment Methods)",
                "DEB": "Debiteuren (Debtors)",
                "CRED": "Crediteuren (Creditors)",
            },
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to analyze account categories: {str(e)}"}
