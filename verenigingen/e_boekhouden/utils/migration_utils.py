"""
Migration Utilities - Conservative Refactor

This file contains methods moved from the EBoekhoudenMigration class
for better organization, but preserves all original code exactly as-is.
"""

import json

import frappe
from frappe.utils import getdate


def stage_eboekhouden_data(migration_doc, settings):
    """Analyze E-Boekhouden data structure and provide insights"""
    try:
        from vereiningen.utils.eboekhouden_api import EBoekhoudenAPI

        # Get E-Boekhouden settings
        api = EBoekhoudenAPI(settings)

        # Fetch different types of data for analysis
        results = {}

        # 1. Chart of Accounts analysis
        coa_result = api.get_chart_of_accounts()
        if coa_result["success"]:
            coa_data = json.loads(coa_result["data"])
            accounts = coa_data.get("items", [])

            account_analysis = migration_doc.analyze_account_structure(accounts)
            results["chart_of_accounts"] = account_analysis

        # 2. Get sample mutations for structure analysis
        mutation_result = api.get_mutations_by_date_range(
            migration_doc.date_from or "2024-01-01",
            migration_doc.date_to or "2024-12-31",
            limit=50,  # Just sample for analysis
        )

        if mutation_result["success"]:
            import json

            mutation_data = json.loads(mutation_result["data"])
            mutations = mutation_data.get("items", [])

            mapping_analysis = migration_doc.analyze_mapping_requirements(mutations)
            results["mapping_requirements"] = mapping_analysis

        return {
            "success": True,
            "analysis": results,
            "recommendations": [
                "Review account type suggestions before proceeding",
                "Configure account group mappings if needed",
                "Ensure root accounts exist in your company",
            ],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_account_structure(migration_doc, accounts):
    """Analyze the structure of E-Boekhouden accounts"""
    try:
        analysis = {
            "total_accounts": len(accounts),
            "account_types": {},
            "categories": {},
            "groups": {},
            "number_ranges": {},
            "problematic_accounts": [],
            "account_usage": {},
        }

        for account in accounts:
            code = account.get("code", "")
            category = account.get("category", "")
            group = account.get("group", "")

            # Count by category
            if category:
                analysis["categories"][category] = analysis["categories"].get(category, 0) + 1

            # Count by group
            if group:
                analysis["groups"][group] = analysis["groups"].get(group, 0) + 1

            # Analyze number ranges
            try:
                code_num = int(code) if code.isdigit() else 0
                range_key = f"{code_num // 1000}xxx"
                analysis["number_ranges"][range_key] = analysis["number_ranges"].get(range_key, 0) + 1
            except:
                pass

            # Suggest account type
            suggested_type = migration_doc.suggest_account_type(
                code, account.get("description", ""), category
            )
            analysis["account_types"][suggested_type] = analysis["account_types"].get(suggested_type, 0) + 1

            # Flag problematic accounts
            if code.startswith("05") or (code.startswith("8") and len(code) > 1):
                analysis["problematic_accounts"].append(
                    {
                        "code": code,
                        "description": account.get("description", ""),
                        "category": category,
                        "suggested_type": suggested_type,
                    }
                )

        return analysis
    except Exception as e:
        frappe.log_error(f"Error analyzing account structure: {str(e)}")
        return {"error": str(e)}


def suggest_account_type(migration_doc, code, name, category):
    """Suggest ERPNext account type based on E-Boekhouden data"""
    try:
        # Try to use smart account typing if available
        from verenigingen.e_boekhouden.utils.eboekhouden_smart_account_typing import (
            suggest_account_type_smart,
        )

        return suggest_account_type_smart(code, name, category)
    except ImportError:
        # Fallback to basic logic
        try:
            code_num = int(code) if code and code.isdigit() else 0
        except (ValueError, TypeError):
            return "Expense Account"

        # Dutch chart of accounts mapping
        if 1000 <= code_num <= 1199:
            return "Receivable"
        elif 1200 <= code_num <= 1299:
            return "Bank"
        elif 1300 <= code_num <= 1399:
            return "Receivable"
        elif 1400 <= code_num <= 1599:
            return "Stock"
        elif 1600 <= code_num <= 1999:
            return "Fixed Asset"
        elif 2000 <= code_num <= 2999:
            return "Payable"
        elif 3000 <= code_num <= 3999:
            return "Equity"
        elif 4000 <= code_num <= 6999:
            return "Expense Account"
        elif 8000 <= code_num <= 8999:
            return "Income Account"
        else:
            return "Expense Account"


def analyze_mapping_requirements(migration_doc, mutations):
    """Analyze mutations to understand mapping requirements"""
    try:
        analysis = {
            "total_mutations": len(mutations),
            "mutation_types": {},
            "account_usage": {},
            "party_requirements": {"customers": set(), "suppliers": set()},
            "ledger_usage": {},
        }

        for mutation in mutations:
            mut_type = mutation.get("soort", "")
            if mut_type:
                analysis["mutation_types"][mut_type] = analysis["mutation_types"].get(mut_type, 0) + 1

            # Analyze accounts used in mutation lines
            lines = mutation.get("Regels", [])
            for line in lines:
                # Safe extraction of nested account code
                boekstuk_data = line.get("Boekstuk")
                if not boekstuk_data or not isinstance(boekstuk_data, dict):
                    account_code = ""
                else:
                    account_code = boekstuk_data.get("Grootboekrekening", "")
                if account_code:
                    if account_code not in analysis["account_usage"]:
                        analysis["account_usage"][account_code] = {
                            "count": 0,
                            "sample_descriptions": [],
                            "amount_range": {"min": None, "max": None},
                        }

                    usage = analysis["account_usage"][account_code]
                    usage["count"] += 1

                    # Store sample descriptions
                    desc = line.get("Omschrijving") or mutation.get("Omschrijving", "")
                    if desc and len(usage["sample_descriptions"]) < 5:
                        usage["sample_descriptions"].append(desc)

                    # Track amount ranges
                    amount = float(line.get("BedragExclBTW", 0) or 0)
                    if amount:
                        if usage["amount_range"]["min"] is None or amount < usage["amount_range"]["min"]:
                            usage["amount_range"]["min"] = amount
                        if usage["amount_range"]["max"] is None or amount > usage["amount_range"]["max"]:
                            usage["amount_range"]["max"] = amount

        return analysis
    except Exception as e:
        frappe.log_error(f"Error analyzing mapping requirements: {str(e)}")
        return {"error": str(e)}
