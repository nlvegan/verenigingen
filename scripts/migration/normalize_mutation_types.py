"""
Normalize E-Boekhouden mutation types to handle both full and abbreviated forms
"""


def normalize_mutation_type(soort):
    """
    Normalize mutation type to standard full form
    Handles both full names and potential abbreviations

    Args:
        soort: The mutation type from E-Boekhouden

    Returns:
        Normalized mutation type string
    """
    if not soort:
        return "Unknown"

    # Convert to string and clean
    soort = str(soort).strip()

    # Direct mappings for known full names (already correct)
    full_names = {
        "FactuurVerstuurd": "FactuurVerstuurd",
        "FactuurOntvangen": "FactuurOntvangen",
        "FactuurbetalingOntvangen": "FactuurbetalingOntvangen",
        "FactuurbetalingVerstuurd": "FactuurbetalingVerstuurd",
        "GeldOntvangen": "GeldOntvangen",
        "GeldUitgegeven": "GeldUitgegeven",
        "Memoriaal": "Memoriaal",
        "BeginBalans": "BeginBalans",
        "Beginbalans": "BeginBalans",
    }

    # Return if already in correct form
    if soort in full_names:
        return full_names[soort]

    # Normalize case-insensitively
    soort_lower = soort.lower()

    # Check for abbreviated forms
    abbreviation_mappings = {
        # Factuur betaling variants
        "factbet ontv": "FactuurbetalingOntvangen",
        "factbet verst": "FactuurbetalingVerstuurd",
        "fact bet ontv": "FactuurbetalingOntvangen",
        "fact bet verst": "FactuurbetalingVerstuurd",
        "factuur betaling ontvangen": "FactuurbetalingOntvangen",
        "factuur betaling verstuurd": "FactuurbetalingVerstuurd",
        "factuurbetaling ontvangen": "FactuurbetalingOntvangen",
        "factuurbetaling verstuurd": "FactuurbetalingVerstuurd",
        # Other potential variants
        "factuur verstuurd": "FactuurVerstuurd",
        "factuur ontvangen": "FactuurOntvangen",
        "geld ontvangen": "GeldOntvangen",
        "geld uitgegeven": "GeldUitgegeven",
        "memoriaal": "Memoriaal",
        "beginbalans": "BeginBalans",
        "begin balans": "BeginBalans",
    }

    # Check abbreviation mappings
    for abbrev, full_name in abbreviation_mappings.items():
        if soort_lower == abbrev:
            return full_name

    # Partial matching for common patterns
    if "factbet" in soort_lower or "fact bet" in soort_lower:
        if "ontv" in soort_lower:
            return "FactuurbetalingOntvangen"
        elif "verst" in soort_lower:
            return "FactuurbetalingVerstuurd"

    if "factuurbetaling" in soort_lower or "factuur betaling" in soort_lower:
        if "ontvangen" in soort_lower:
            return "FactuurbetalingOntvangen"
        elif "verstuurd" in soort_lower:
            return "FactuurbetalingVerstuurd"

    if "factuur" in soort_lower:
        if "verstuurd" in soort_lower:
            return "FactuurVerstuurd"
        elif "ontvangen" in soort_lower:
            return "FactuurOntvangen"

    if "geld" in soort_lower:
        if "ontvangen" in soort_lower:
            return "GeldOntvangen"
        elif "uitgegeven" in soort_lower:
            return "GeldUitgegeven"

    # Return original if no mapping found
    return soort


def get_mutation_type_mapping():
    """
    Get a dictionary of all known mutation type mappings

    Returns:
        Dictionary mapping abbreviated forms to full names
    """
    return {
        # Full names
        "FactuurVerstuurd": "Sales Invoice",
        "FactuurOntvangen": "Purchase Invoice",
        "FactuurbetalingOntvangen": "Customer Payment",
        "FactuurbetalingVerstuurd": "Supplier Payment",
        "GeldOntvangen": "Money Received",
        "GeldUitgegeven": "Money Spent",
        "Memoriaal": "Manual Entry",
        # Abbreviated forms
        "Factbet ontv": "Customer Payment",
        "Factbet verst": "Supplier Payment",
        "FactBet Ontv": "Customer Payment",
        "FactBet Verst": "Supplier Payment",
    }
