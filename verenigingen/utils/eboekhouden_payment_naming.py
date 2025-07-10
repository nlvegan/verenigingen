"""
Enhanced payment naming for E-Boekhouden imports
Provides better naming schemes for Payment Entries and Journal Entries
"""

import re

import frappe


def get_payment_entry_title(mutation, party_name, payment_type, relation_data=None):
    """
    Generate a descriptive title for Payment Entry

    Format: [Date] - [Party] - [Invoice#] - [Amount] - [Description]
    Example: "2024-01-15 - ABC Supplier - INV-001 - €250.00 - Office supplies"
    """
    parts = []

    # Date
    date_str = mutation.get("Datum", "")
    if date_str:
        date = date_str.split("T")[0] if "T" in date_str else date_str
        parts.append(date)

    # Enhanced party name resolution
    enhanced_party_name = get_enhanced_party_name(party_name, mutation, relation_data)
    if enhanced_party_name:
        short_name = (
            enhanced_party_name[:30] + "..." if len(enhanced_party_name) > 30 else enhanced_party_name
        )
        parts.append(short_name)

    # Payment type indicator
    type_indicators = {
        "Receive": "⬅",  # Money coming in
        "Pay": "➡",  # Money going out
    }
    if payment_type in type_indicators:
        parts.append(type_indicators[payment_type])

    # Invoice number
    invoice_no = mutation.get("Factuurnummer")
    if invoice_no:
        parts.append(f"#{invoice_no}")

    # Amount with currency
    amount = 0
    for regel in mutation.get("MutatieRegels", []):
        amount += abs(float(regel.get("BedragInvoer", 0) or regel.get("BedragInclBTW", 0)))
    if amount:
        parts.append("€{amount:,.2f}")

    # Description (shortened and cleaned)
    description = get_meaningful_description(mutation)
    if description:
        short_desc = description[:35] + "..." if len(description) > 35 else description
        parts.append(short_desc)

    return " - ".join(parts)


def get_enhanced_party_name(party_name, mutation, relation_data=None):
    """Get the most meaningful party name from available data"""
    # If we have relation data, use it to get a better name
    if relation_data:
        # Try company name first
        if relation_data.get("Bedrij") and relation_data["Bedrijf"].strip():
            return relation_data["Bedrijf"].strip()

        # Try contact person
        if relation_data.get("Contactpersoon") and relation_data["Contactpersoon"].strip():
            return relation_data["Contactpersoon"].strip()

        # Try name field
        if relation_data.get("Naam") and relation_data["Naam"].strip():
            return relation_data["Naam"].strip()

    # Try to extract meaningful name from mutation description
    description = mutation.get("Omschrijving", "")
    if description:
        # Look for patterns like "Payment from ABC Company" or "Betaling van XYZ"
        import re

        patterns = [
            r"(?:van|from|to|naar)\s+([A-Za-z][A-Za-z\s&\.\-]{2,30})",
            r"([A-Za-z][A-Za-z\s&\.\-]{3,30})\s+(?:payment|betaling|invoice|factuur)",
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                extracted_name = match.group(1).strip()
                # Avoid generic terms
                if not any(
                    word in extracted_name.lower()
                    for word in ["payment", "betaling", "invoice", "factuur", "customer", "supplier"]
                ):
                    return extracted_name

    # Fall back to provided party name if it's meaningful
    if party_name and party_name.strip():
        # Check if it's a generic name
        if not re.match(r"^(Customer|Supplier)\s+\d+$", party_name):
            return party_name.strip()

    # Extract relation code for display
    relation_code = mutation.get("RelatieCode")
    if relation_code:
        return f"Relation {relation_code}"

    return party_name or "Unknown Party"


def get_meaningful_description(mutation):
    """Extract the most meaningful description from mutation data"""
    description = mutation.get("Omschrijving", "").strip()

    if not description:
        return ""

    # Clean up common redundant phrases
    cleanup_patterns = [
        r"^(Payment|Betaling|Invoice|Factuur)\s+(from|van|to|naar)\s+",
        r"\s+\(.*\)$",  # Remove trailing parentheses
        r"^Mutatie\s+\d+:\s*",  # Remove mutation number prefix
    ]

    cleaned = description
    for pattern in cleanup_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    # If nothing meaningful left, return original
    if len(cleaned) < 3:
        return description

    return cleaned


def get_journal_entry_title(mutation, transaction_type):
    """
    Generate a descriptive title for Journal Entry

    Format: [Date] - [Type] - [Account] - [Amount] - [Description]
    Example: "2024-01-15 - Bank Payment - Triodos - €150.00 - Rent payment"
    """
    parts = []

    # Date
    date_str = mutation.get("Datum", "")
    if date_str:
        date = date_str.split("T")[0] if "T" in date_str else date_str
        parts.append(date)

    # Transaction type
    type_mapping = {
        "GeldOntvangen": "Money Received",
        "GeldUitgegeven": "Money Spent",
        "FactuurbetalingOntvangen": "Customer Payment",
        "FactuurbetalingVerstuurd": "Supplier Payment",
        "Memoriaal": "Manual Entry",
    }
    readable_type = type_mapping.get(transaction_type, transaction_type)
    parts.append(readable_type)

    # Account info
    account_code = mutation.get("Rekening")
    if account_code:
        parts.append(f"AC-{account_code}")

    # Amount
    amount = 0
    for regel in mutation.get("MutatieRegels", []):
        amount += abs(float(regel.get("BedragInclBTW", 0) or regel.get("BedragExclBTW", 0)))
    if amount:
        parts.append("€{amount:,.2f}")

    # Description (shortened)
    description = mutation.get("Omschrijving", "")
    if description:
        short_desc = description[:40] + "..." if len(description) > 40 else description
        parts.append(short_desc)

    return " - ".join(parts)


def enhance_payment_entry_fields(pe, mutation):
    """
    Add additional fields to Payment Entry for better identification
    """
    # Add custom remarks combining multiple pieces of information
    remarks_parts = []

    # Original description
    if mutation.get("Omschrijving"):
        remarks_parts.append("Description: {mutation.get('Omschrijving')}")

    # E-Boekhouden references
    if mutation.get("MutatieNr"):
        remarks_parts.append("Mutation Nr: {mutation.get('MutatieNr')}")

    if mutation.get("Factuurnummer"):
        remarks_parts.append("Invoice Nr: {mutation.get('Factuurnummer')}")

    if mutation.get("RelatieCode"):
        remarks_parts.append("Relation Code: {mutation.get('RelatieCode')}")

    pe.remarks = "\n".join(remarks_parts)

    # Set custom fields if they exist
    if hasattr(pe, "eboekhouden_mutation_nr"):
        pe.eboekhouden_mutation_nr = mutation.get("MutatieNr")

    if hasattr(pe, "eboekhouden_invoice_number"):
        pe.eboekhouden_invoice_number = mutation.get("Factuurnummer")

    return pe


def enhance_journal_entry_fields(je, mutation, transaction_category=None):
    """
    Add additional fields to Journal Entry for better identification
    """
    # Enhanced user remark
    remark_parts = []

    if transaction_category:
        remark_parts.append(f"[{transaction_category}]")

    if mutation.get("Omschrijving"):
        remark_parts.append(mutation.get("Omschrijving"))

    # Add mutation details
    details = []
    if mutation.get("MutatieNr"):
        details.append("Mut#{mutation.get('MutatieNr')}")
    if mutation.get("Factuurnummer"):
        details.append("Inv#{mutation.get('Factuurnummer')}")
    if mutation.get("RelatieCode"):
        details.append("Rel#{mutation.get('RelatieCode')}")

    if details:
        remark_parts.append("({', '.join(details)})")

    je.user_remark = " ".join(remark_parts)

    return je


@frappe.whitelist()
def analyze_payment_classification():
    """
    Analyze how payments are currently classified in the system
    """
    company = frappe.db.get_single_value("E-Boekhouden Settings", "default_company")

    if not company:
        return {"error": "No default company set in E-Boekhouden Settings"}

    results = {
        "payment_entries": {"total": 0, "by_type": {}, "sample_titles": []},
        "journal_entries": {"total": 0, "payment_related": 0, "by_remark_pattern": {}, "sample_titles": []},
        "other_payment_docs": {},
    }

    # Analyze Payment Entries
    payment_entries = frappe.get_all(
        "Payment Entry",
        filters={"company": company, "docstatus": 1},
        fields=[
            "name",
            "payment_type",
            "party_type",
            "party",
            "posting_date",
            "paid_amount",
            "reference_no",
            "remarks",
        ],
        limit=500,
    )

    results["payment_entries"]["total"] = len(payment_entries)

    for pe in payment_entries:
        # Count by type
        key = "{pe.payment_type} - {pe.party_type}"
        results["payment_entries"]["by_type"][key] = results["payment_entries"]["by_type"].get(key, 0) + 1

        # Sample titles
        if len(results["payment_entries"]["sample_titles"]) < 10:
            results["payment_entries"]["sample_titles"].append(
                {
                    "name": pe.name,
                    "party": pe.party,
                    "date": str(pe.posting_date),
                    "amount": pe.paid_amount,
                    "reference": pe.reference_no,
                }
            )

    # Analyze Journal Entries that might be payments
    journal_entries = frappe.db.sql(
        """
        SELECT
            je.name,
            je.posting_date,
            je.user_remark,
            je.total_debit,
            je.eboekhouden_mutation_nr,
            COUNT(jea.name) as account_count
        FROM `tabJournal Entry` je
        LEFT JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
        WHERE je.company = %s
        AND je.docstatus = 1
        AND (
            je.user_remark LIKE '%%payment%%'
            OR je.user_remark LIKE '%%betaling%%'
            OR je.user_remark LIKE '%%invoice%%'
            OR je.user_remark LIKE '%%factuur%%'
            OR je.eboekhouden_mutation_nr IS NOT NULL
        )
        GROUP BY je.name
        LIMIT 500
    """,
        company,
        as_dict=True,
    )

    results["journal_entries"]["total"] = len(journal_entries)

    for je in journal_entries:
        # Check if it's payment-related
        remark_lower = (je.user_remark or "").lower()
        if any(word in remark_lower for word in ["payment", "betaling", "invoice", "factuur"]):
            results["journal_entries"]["payment_related"] += 1

        # Pattern analysis
        if "geld" in remark_lower:
            if "ontvangen" in remark_lower:
                pattern = "Money Received"
            elif "uitgegeven" in remark_lower:
                pattern = "Money Spent"
            else:
                pattern = "Other Money Transaction"
            results["journal_entries"]["by_remark_pattern"][pattern] = (
                results["journal_entries"]["by_remark_pattern"].get(pattern, 0) + 1
            )

        # Sample titles
        if len(results["journal_entries"]["sample_titles"]) < 10:
            results["journal_entries"]["sample_titles"].append(
                {
                    "name": je.name,
                    "date": str(je.posting_date),
                    "remark": (je.user_remark or "")[:100],
                    "amount": je.total_debit,
                    "mutation_nr": je.eboekhouden_mutation_nr,
                }
            )

    # Check for other payment-related doctypes
    # Bank Transaction
    bank_trans_count = frappe.db.count("Bank Transaction", {"company": company})
    if bank_trans_count > 0:
        results["other_payment_docs"]["Bank Transaction"] = bank_trans_count

    # Get summary of all E-Boekhouden imported documents
    eb_summary = frappe.db.sql(
        """
        SELECT
            'Payment Entry' as doctype,
            COUNT(*) as count
        FROM `tabPayment Entry`
        WHERE company = %s
        AND (reference_no LIKE 'EB-%%' OR reference_no REGEXP '^[0-9]+$')

        UNION ALL

        SELECT
            'Journal Entry' as doctype,
            COUNT(*) as count
        FROM `tabJournal Entry`
        WHERE company = %s
        AND eboekhouden_mutation_nr IS NOT NULL
    """,
        (company, company),
        as_dict=True,
    )

    results["eboekhouden_imported"] = {row.doctype: row.count for row in eb_summary}

    return results
