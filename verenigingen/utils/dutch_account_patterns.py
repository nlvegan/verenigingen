"""
Dutch account naming patterns for E-Boekhouden
Helps with better account type detection based on Dutch terminology
"""

# Common Dutch account terms and their suggested ERPNext types
DUTCH_ACCOUNT_PATTERNS = {
    # Assets
    "liquide middelen": "Cash",
    "kas": "Cash",
    "kasgeld": "Cash",
    "bank": "Bank",
    "bankrekening": "Bank",
    "spaarrekening": "Bank",
    "debiteuren": "Receivable",
    "vorderingen": "Receivable",
    "te ontvangen": "Receivable",
    "voorraad": "Stock",
    "inventaris": "Fixed Asset",
    "vaste activa": "Fixed Asset",
    "materiële vaste activa": "Fixed Asset",
    # Liabilities
    "crediteuren": "Payable",
    "te betalen": "Payable",
    "schulden": "Payable",
    "lening": "Loan",
    "hypotheek": "Loan",
    # Equity
    "eigen vermogen": "Equity",
    "kapitaal": "Equity",
    "reserve": "Equity",
    "resultaat": "Equity",
    # Income
    "omzet": "Income",
    "opbrengsten": "Income",
    "verkoop": "Income",
    "inkomsten": "Income",
    "contributie": "Income",
    "donatie": "Income",
    # Expenses
    "kosten": "Expense",
    "uitgaven": "Expense",
    "inkoop": "Expense",
    "personeelskosten": "Expense",
    "lonen": "Expense",
    "salarissen": "Expense",
    "huur": "Expense",
    "afschrijving": "Depreciation",
    # Tax
    "btw": "Tax",
    "belasting": "Tax",
    "omzetbelasting": "Tax",
    "loonbelasting": "Tax",
    # Other
    "tussenrekening": "Temporary",
    "kruispost": "Temporary",
}

# Group code patterns (when group codes follow specific numbering)
GROUP_CODE_PATTERNS = {
    "00": "Equity",  # Often eigen vermogen
    "01": "Fixed Asset",  # Often vaste activa
    "02": "Current Asset",  # Often vlottende activa
    "03": "Stock",  # Often voorraad
    "10": "Cash",  # Often liquide middelen
    "11": "Bank",  # Often bank accounts
    "12": "Receivable",  # Often debiteuren
    "13": "Receivable",  # Often overige vorderingen
    "20": "Payable",  # Often crediteuren
    "21": "Payable",  # Often overige schulden
    "40": "Income",  # Often omzet
    "41": "Income",  # Often overige opbrengsten
    "60": "Expense",  # Often inkoop
    "61": "Expense",  # Often personeelskosten
    "62": "Expense",  # Often overige kosten
}


def suggest_account_type_from_dutch(name, group_code=None):
    """
    Suggest account type based on Dutch naming patterns

    Args:
        name: Account or group name in Dutch
        group_code: Optional group code for additional context

    Returns:
        tuple: (suggested_type, confidence, reason)
    """
    name_lower = name.lower()

    # Check exact patterns first
    for pattern, account_type in DUTCH_ACCOUNT_PATTERNS.items():
        if pattern in name_lower:
            confidence = "high" if len(pattern.split()) > 1 else "medium"
            return account_type, confidence, f"Name contains '{pattern}'"

    # Check group code patterns if no name match
    if group_code and len(group_code) >= 2:
        prefix = group_code[:2]
        if prefix in GROUP_CODE_PATTERNS:
            return GROUP_CODE_PATTERNS[prefix], "medium", f"Group code starts with {prefix}"

    # Special cases for combined patterns
    if "te vorderen" in name_lower and "btw" in name_lower:
        return "Tax", "high", "VAT receivable account"
    elif "te betalen" in name_lower and "btw" in name_lower:
        return "Tax", "high", "VAT payable account"
    elif "vooruit" in name_lower and "ontvangen" in name_lower:
        return "Current Liability", "medium", "Advance received"
    elif "vooruit" in name_lower and "betaald" in name_lower:
        return "Current Asset", "medium", "Advance paid"

    return None, "low", "No pattern matched"
