"""
E-Boekhouden Account Analyzer
Analyzes chart of accounts (grootboekrekeningen) to suggest mappings for two-stage import
"""

import re
from collections import defaultdict

import frappe


def analyze_account_patterns(accounts):
    """Analyze patterns in account names and codes"""
    categorized_accounts = {
        "wages_salaries": [],
        "social_charges": [],
        "tax_payments": [],
        "pension": [],
        "bank_charges": [],
        "general_expenses": [],
        "other": [],
    }

    # Pattern definitions for Dutch accounting terms
    patterns = {
        "wages_salaries": [
            r"loon|lonen|salaris|salarissen|wage|salary|brutoloon|nettoloon",
            r"personeel|personnel|medewerker|employee",
            r"vakantiegeld|holiday|thirteenth|dertiende maand",
        ],
        "social_charges": [
            r"sociale\s+lasten|social\s+charges|werkgeverslasten",
            r"premie|premium|aov|awf|azv|sv\b",
            r"werknemersverzekering|uwv|arbeidsongeschiktheid",
            r"zvw|wia|ww\b",
        ],
        "tax_payments": [
            r"belasting|tax|btw|vat|omzetbelasting",
            r"loonheffing|wage\s+tax|loonbelasting",
            r"vennootschapsbelasting|vpb|income\s+tax",
            r"belastingdienst|fiscus",
        ],
        "pension": [
            r"pensioen|pension|oudedagsvoorziening|retirement",
            r"pensioenfonds|pensioenuitvoerder",
            r"aov\b|anw\b",
        ],
        "bank_charges": [
            r"bankkosten|bank\s+charges|bank\s+fee|banking\s+fees",
            r"provisie\s+bank|commission\s+bank",
            r"rente\s+bank|bank\s+interest",
            r"betalingsverkeer|transaction\s+costs",
        ],
    }

    # Compile patterns
    compiled_patterns = {}
    for category, pattern_list in patterns.items():
        compiled_patterns[category] = re.compile("|".join(pattern_list), re.IGNORECASE)

    # Analyze each account
    for account in accounts:
        code = account.get("Code", "")
        name = account.get("Omschrijving", "")
        account_type = account.get("Soort", "")

        # Skip balance sheet accounts
        if account_type in ["Balans", "Balance"]:
            continue

        account_info = {
            "code": code,
            "name": name,
            "type": account_type,
            "suggested_doc_type": "Purchase Invoice",  # Default
            "confidence": "low",
            "matching_patterns": [],
        }

        # Check against patterns
        matched = False
        for category, pattern in compiled_patterns.items():
            if pattern.search(name):
                categorized_accounts[category].append(account_info)
                account_info["matching_patterns"].append(category)
                account_info["suggested_doc_type"] = "Journal Entry"
                account_info["confidence"] = "high"
                matched = True
                break

        # Use account code ranges as fallback
        if not matched and code:
            # Adjust for custom numbering (extra digit)
            if code.startswith("40") or code.startswith("41"):
                # Likely wages or social charges
                if code.startswith("400"):
                    categorized_accounts["wages_salaries"].append(account_info)
                    account_info["suggested_doc_type"] = "Journal Entry"
                    account_info["confidence"] = "medium"
                elif code.startswith("410"):
                    categorized_accounts["social_charges"].append(account_info)
                    account_info["suggested_doc_type"] = "Journal Entry"
                    account_info["confidence"] = "medium"
                else:
                    categorized_accounts["general_expenses"].append(account_info)
            else:
                categorized_accounts["other"].append(account_info)

    return categorized_accounts


def generate_account_mapping_suggestions(analysis):
    """Generate mapping suggestions based on account analysis"""
    suggestions = []

    category_mapping = {
        "wages_salaries": "Wages and Salaries",
        "social_charges": "Social Charges",
        "tax_payments": "Tax Payments",
        "pension": "Pension Contributions",
        "bank_charges": "Bank Charges",
        "general_expenses": "General Expenses",
    }

    for category, accounts in analysis.items():
        if category == "other":
            continue

        for account in accounts:
            suggestion = {
                "account_code": account["code"],
                "account_name": account["name"],
                "suggested_type": account["suggested_doc_type"],
                "category": category_mapping.get(category, "General Expenses"),
                "confidence": account["confidence"],
                "reasons": [],
            }

            # Add reasoning
            if account["matching_patterns"]:
                suggestion["reasons"].append("Account name matches {category} patterns")

            if account["suggested_doc_type"] == "Journal Entry":
                suggestion["reasons"].append("Complex accounting entry requiring journal voucher")

            if account["code"].startswith("40") or account["code"].startswith("41"):
                suggestion["reasons"].append("Account code suggests expense category requiring journal entry")

            suggestions.append(suggestion)

    # Sort by confidence and then by account code
    suggestions.sort(key=lambda x: (x["confidence"], x["account_code"]), reverse=True)

    return suggestions


def get_existing_mappings():
    """Get summary of existing mappings"""
    mappings = frappe.get_all(
        "E-Boekhouden Account Mapping",
        filters={"is_active": 1},
        fields=[
            "name",
            "account_code",
            "account_name",
            "document_type",
            "category",
            "sample_description",
            "usage_count",
        ],
    )

    summary = {
        "total": len(mappings),
        "by_type": defaultdict(int),
        "by_category": defaultdict(int),
        "mapped_accounts": set(),
        "mappings": mappings,
    }

    for m in mappings:
        summary["by_type"][m["document_type"]] += 1
        if m["category"]:
            summary["by_category"][m["category"]] += 1
        if m["account_code"]:
            summary["mapped_accounts"].add(m["account_code"])

    # Convert set to list for JSON serialization
    summary["mapped_accounts"] = list(summary["mapped_accounts"])

    return dict(summary)


@frappe.whitelist()
def create_mapping_from_suggestion(suggestion):
    """Create a single mapping from a suggestion"""
    if isinstance(suggestion, str):
        import json

        suggestion = json.loads(suggestion)

    # Check if mapping already exists
    existing = frappe.db.exists("E-Boekhouden Account Mapping", {"account_code": suggestion["account_code"]})

    if existing:
        frappe.throw(f"Mapping already exists for account {suggestion['account_code']}")

    # Create new mapping
    mapping = frappe.new_doc("E-Boekhouden Account Mapping")
    mapping.account_code = suggestion["account_code"]
    mapping.account_name = suggestion["account_name"]
    mapping.document_type = suggestion["suggested_type"]
    mapping.category = suggestion["category"]

    # Set priority based on confidence (field removed, logic preserved for reference)
    if suggestion["confidence"] == "high":
        pass  # Previously: mapping.priority = 100
    elif suggestion["confidence"] == "medium":
        pass  # Previously: mapping.priority = 50
    else:
        pass  # Previously: mapping.priority = 10

    mapping.insert(ignore_permissions=True)

    return {
        "success": True,
        "mapping": mapping.name,
        "message": "Created mapping for account {suggestion['account_code']}",
    }


@frappe.whitelist()
def bulk_create_mappings(suggestions):
    """Create multiple mappings from suggestions"""
    if isinstance(suggestions, str):
        import json

        suggestions = json.loads(suggestions)

    created = 0
    skipped = 0
    errors = []

    for suggestion in suggestions:
        try:
            # Check if mapping already exists
            existing = frappe.db.exists(
                "E-Boekhouden Account Mapping", {"account_code": suggestion["account_code"]}
            )

            if existing:
                skipped += 1
                continue

            # Create new mapping
            mapping = frappe.new_doc("E-Boekhouden Account Mapping")
            mapping.account_code = suggestion["account_code"]
            mapping.account_name = suggestion["account_name"]
            mapping.document_type = suggestion["suggested_type"]
            mapping.category = suggestion["category"]

            # Set priority based on confidence (field removed, logic preserved for reference)
            if suggestion.get("confidence") == "high":
                pass  # Previously: mapping.priority = 100
            elif suggestion.get("confidence") == "medium":
                pass  # Previously: mapping.priority = 50
            else:
                pass  # Previously: mapping.priority = 10

            mapping.insert(ignore_permissions=True)
            created += 1

        except Exception as e:
            errors.append(f"Account {suggestion['account_code']}: {str(e)}")

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "message": "Created {created} mappings, skipped {skipped} existing",
    }


@frappe.whitelist()
def create_default_range_mappings():
    """Create default mappings based on account ranges"""
    default_ranges = [
        {
            # "account_range_start": "40000",
            # "account_range_end": "40999",
            "account_name": "Wages and Salaries (4000x range)",
            "document_type": "Journal Entry",
            "category": "Wages and Salaries",
        },
        {
            # "account_range_start": "41000",
            # "account_range_end": "41999",
            "account_name": "Social Charges (4100x range)",
            "document_type": "Journal Entry",
            "category": "Social Charges",
        },
        {
            # "account_range_start": "42000",
            # "account_range_end": "42999",
            "account_name": "Pension Costs (4200x range)",
            "document_type": "Journal Entry",
            "category": "Pension Contributions",
        },
    ]

    created = 0
    for mapping_data in default_ranges:
        if not frappe.db.exists(
            "E-Boekhouden Account Mapping", {"account_name": mapping_data["account_name"]}
        ):
            doc = frappe.new_doc("E-Boekhouden Account Mapping")
            doc.update(mapping_data)
            doc.insert(ignore_permissions=True)
            created += 1

    return {"created": created, "message": "Created {created} default range mappings"}
