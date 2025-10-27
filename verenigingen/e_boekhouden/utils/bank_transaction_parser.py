"""
Bank Transaction Parser for E-Boekhouden Integration

Extracts party information from Dutch bank transaction descriptions to enable
proper Payment Entry creation with party references for Type 5/6 mutations.

Description Format:
    NL[IBAN] [BIC] [PARTY NAME] [REFERENCE KEYWORDS] [DESCRIPTION]

Examples:
    NL44ASNB0943117305 ASNBNL21 Anne Tilanus TRIODOS NL 20250128...
    NL60ABNA0828316139 ABNANL2A IMPACT SOCIALE MEDIA BV E REF NOTPROVIDED...
"""

import re
from typing import Dict, Optional, Tuple

import frappe


class BankTransactionParser:
    """Parse Dutch bank transaction descriptions to extract party information"""

    # Common Dutch bank BIC codes
    BIC_PATTERNS = [
        r"ABNANL2A",  # ABN AMRO
        r"RABONL2U",  # Rabobank
        r"INGBNL2A",  # ING
        r"SNSBNL2A",  # SNS Bank
        r"ASNBNL21",  # ASN Bank
        r"TRIONL2U",  # Triodos Bank
        r"BUNQNL2A",  # Bunq
        r"REVOLT21",  # Revolut
        r"KNABNL2H",  # Knab
        r"\w{6}NL\w{2}",  # Generic Dutch BIC pattern (6 chars + NL + 2 chars)
    ]

    # Keywords that typically follow the party name
    TERMINATOR_KEYWORDS = [
        "TRIODOS",
        "NOTPROVIDED",
        "REF",
        "ERE F",
        "EREF",
        "IBAN",
        r"\d{8}",  # Date patterns (YYYYMMDD)
        r"\d{10,}",  # Long reference numbers
    ]

    def __init__(self):
        """Initialize the parser"""
        self.bic_regex = re.compile("|".join(self.BIC_PATTERNS), re.IGNORECASE)
        self.terminator_regex = re.compile("|".join(self.TERMINATOR_KEYWORDS), re.IGNORECASE)

    def parse_description(self, description: str) -> Dict[str, Optional[str]]:
        """
        Parse bank transaction description to extract party information.

        Args:
            description: Bank transaction description string

        Returns:
            Dict with keys: iban, bic, party_name, remainder
        """
        if not description:
            return {"iban": None, "bic": None, "party_name": None, "remainder": description}

        # Try to find IBAN (NL followed by digits/letters)
        iban_match = re.match(r"(NL\d{2}[A-Z]{4}\d{10})\s+", description)
        iban = iban_match.group(1) if iban_match else None

        # Try to find BIC code
        bic_match = self.bic_regex.search(description)
        bic = bic_match.group(0) if bic_match else None

        # Extract party name (text between BIC and terminator keywords)
        party_name = None
        remainder = description

        if bic_match:
            # Start after the BIC code
            start_pos = bic_match.end()
            text_after_bic = description[start_pos:].strip()

            # Find the first terminator keyword
            terminator_match = self.terminator_regex.search(text_after_bic)

            if terminator_match:
                # Party name is between BIC and terminator
                party_name = text_after_bic[: terminator_match.start()].strip()
                remainder = text_after_bic[terminator_match.start() :].strip()
            else:
                # No terminator found, take first 50 chars as party name
                party_name = text_after_bic[:50].strip()
                remainder = text_after_bic[50:].strip() if len(text_after_bic) > 50 else ""

            # Clean up party name
            if party_name:
                # Remove extra whitespace
                party_name = " ".join(party_name.split())

                # Remove trailing punctuation
                party_name = party_name.rstrip(".,;:-")

                # Limit length
                if len(party_name) > 100:
                    party_name = party_name[:100]

        return {"iban": iban, "bic": bic, "party_name": party_name, "remainder": remainder}

    def find_or_create_party(
        self, party_name: str, party_type: str, iban: Optional[str] = None
    ) -> Tuple[str, bool]:
        """
        Find existing party or create a new one.

        Matching strategy (in priority order):
        1. IBAN match (strongest signal - bank account is unique)
        2. Exact name match (case-sensitive)
        3. Case-insensitive name match
        4. Fuzzy name match (handles initials, prefixes)
        5. Create new party

        Args:
            party_name: Name extracted from transaction
            party_type: "Customer" or "Supplier"
            iban: Optional IBAN for matching

        Returns:
            Tuple of (party_name, created_new)
        """
        if not party_name:
            # Use generic party for transactions without identifiable party
            return self._get_or_create_generic_party(party_type)

        # PRIORITY 1: IBAN match (strongest signal)
        # If we have an IBAN and it matches an existing party, use that party
        # This handles cases where the same person has multiple name variations
        if iban:
            bank_account_party = frappe.db.sql(
                """
                SELECT party, party_type
                FROM `tabBank Account`
                WHERE party_type = %s
                AND (bank_account_no = %s OR iban = %s)
                LIMIT 1
            """,
                (party_type, iban, iban),
            )

            if bank_account_party:
                matched_party = bank_account_party[0][0]
                frappe.logger().info(
                    f"Matched party by IBAN {iban}: {matched_party} " f"(extracted name was '{party_name}')"
                )
                return matched_party, False

        # PRIORITY 2: Exact name match (case-sensitive)
        field_name = "customer_name" if party_type == "Customer" else "supplier_name"
        existing = frappe.db.get_value(party_type, {field_name: party_name}, "name")

        if existing:
            return existing, False

        # PRIORITY 3: Case-insensitive name match
        similar = frappe.db.sql(
            f"""
            SELECT name
            FROM `tab{party_type}`
            WHERE LOWER({field_name}) = LOWER(%s)
            LIMIT 1
        """,
            (party_name,),
        )

        if similar:
            return similar[0][0], False

        # PRIORITY 4: Fuzzy name match (handles initials, common variations)
        fuzzy_match = self._fuzzy_name_match(party_name, party_type)
        if fuzzy_match:
            frappe.logger().info(f"Fuzzy matched '{party_name}' to existing party '{fuzzy_match}'")
            return fuzzy_match, False

        # PRIORITY 5: No match found, create new party
        return self._create_party(party_name, party_type, iban)

    def _fuzzy_name_match(self, party_name: str, party_type: str) -> Optional[str]:
        """
        Attempt fuzzy matching on party names to handle common variations.

        Handles cases like:
        - "Anne Tilanus" vs "A. Tilanus"
        - "Anne Tilanus" vs "A Tilanus"
        - "Jan de Vries" vs "J de Vries"
        - "John Smith Jr" vs "John Smith"

        Args:
            party_name: Name to match
            party_type: "Customer" or "Supplier"

        Returns:
            Matched party name if found, None otherwise
        """
        field_name = "customer_name" if party_type == "Customer" else "supplier_name"

        # Normalize the input name for comparison
        normalized_input = self._normalize_name(party_name)

        # Get all parties to compare against
        all_parties = frappe.db.sql(
            f"""
            SELECT name, {field_name}
            FROM `tab{party_type}`
        """,
            as_dict=True,
        )

        for party in all_parties:
            existing_name = party[field_name]
            if not existing_name:
                continue

            normalized_existing = self._normalize_name(existing_name)

            # Check if one name is a subset/abbreviation of the other
            if self._names_are_similar(normalized_input, normalized_existing):
                return party["name"]

        return None

    def _normalize_name(self, name: str) -> str:
        """
        Normalize a name for fuzzy comparison.

        - Convert to lowercase
        - Remove extra whitespace
        - Remove common suffixes (Jr, Sr, etc.)
        - Standardize Dutch name prefixes (van, de, der, etc.)

        Args:
            name: Name to normalize

        Returns:
            Normalized name
        """
        if not name:
            return ""

        # Lowercase and strip
        normalized = name.lower().strip()

        # Remove common suffixes
        suffixes = ["jr", "jr.", "sr", "sr.", "iii", "ii", "iv"]
        for suffix in suffixes:
            if normalized.endswith(f" {suffix}"):
                normalized = normalized[: -(len(suffix) + 1)].strip()

        # Normalize multiple spaces to single space
        normalized = " ".join(normalized.split())

        return normalized

    def _names_are_similar(self, name1: str, name2: str) -> bool:
        """
        Check if two normalized names are similar enough to be considered a match.

        Handles:
        - Initial abbreviations (Anne -> A., A)
        - Middle name variations
        - Partial matches

        Args:
            name1: First normalized name
            name2: Second normalized name

        Returns:
            True if names are similar enough to match
        """
        # Split into parts
        parts1 = name1.split()
        parts2 = name2.split()

        # If one has significantly more parts, likely not a match
        if abs(len(parts1) - len(parts2)) > 2:
            return False

        # Check if first and last names match (handling initials)
        if len(parts1) >= 2 and len(parts2) >= 2:
            # Compare first names (or initials)
            first1 = parts1[0]
            first2 = parts2[0]

            first_match = (
                first1 == first2
                or first1[0] == first2[0]  # Exact match
                or first1.startswith(first2)  # Same initial
                or first2.startswith(first1)  # One is abbreviation
            )

            # Compare last names (last part)
            last1 = parts1[-1]
            last2 = parts2[-1]

            last_match = last1 == last2 or last1 in last2 or last2 in last1  # Exact match  # Substring

            if first_match and last_match:
                return True

        # Check if one name is contained in the other (for company names)
        if name1 in name2 or name2 in name1:
            # But ensure it's substantial (at least 5 characters)
            min_len = min(len(name1), len(name2))
            if min_len >= 5:
                return True

        return False

    def _create_party(self, party_name: str, party_type: str, iban: Optional[str] = None) -> Tuple[str, bool]:
        """
        Create a new Customer or Supplier.

        Args:
            party_name: Party name
            party_type: "Customer" or "Supplier"
            iban: Optional IBAN

        Returns:
            Tuple of (party_name, True)
        """
        try:
            doc = frappe.new_doc(party_type)

            if party_type == "Customer":
                doc.customer_name = party_name
                doc.customer_type = "Individual"
                doc.customer_group = "Individual"  # Default group
                doc.territory = "Netherlands"  # Default territory
            else:  # Supplier
                doc.supplier_name = party_name
                doc.supplier_group = "All Supplier Groups"  # Default group
                doc.supplier_type = "Individual"

            # Mark as created from bank transaction
            doc.append("notes", {"note": f"Auto-created from E-Boekhouden bank transaction"})

            doc.insert(ignore_permissions=False)

            # If IBAN provided, create bank account
            if iban:
                self._create_bank_account(doc.name, party_type, iban)

            frappe.logger().info(f"Created new {party_type}: {doc.name} from bank transaction")

            return doc.name, True

        except Exception as e:
            frappe.logger().error(f"Failed to create {party_type} '{party_name}': {str(e)}")
            # Fall back to generic party
            return self._get_or_create_generic_party(party_type)

    def _create_bank_account(self, party: str, party_type: str, iban: str) -> None:
        """Create bank account for party"""
        try:
            if not frappe.db.exists("Bank Account", {"iban": iban}):
                bank_account = frappe.new_doc("Bank Account")
                bank_account.account_name = f"{party} - {iban[-4:]}"
                bank_account.bank = "Unknown"  # Could parse from BIC
                bank_account.iban = iban
                bank_account.party_type = party_type
                bank_account.party = party
                bank_account.is_default = 1
                bank_account.insert(ignore_permissions=False)

        except Exception as e:
            frappe.logger().warning(f"Could not create bank account for {party}: {str(e)}")

    def _get_or_create_generic_party(self, party_type: str) -> Tuple[str, bool]:
        """
        Get or create a generic party for unidentified transactions.

        Args:
            party_type: "Customer" or "Supplier"

        Returns:
            Tuple of (party_name, created_new)
        """
        generic_name = f"Bank Transfers - {party_type}s"

        existing = frappe.db.get_value(party_type, {"name": generic_name}, "name")

        if existing:
            return existing, False

        try:
            doc = frappe.new_doc(party_type)

            if party_type == "Customer":
                doc.customer_name = generic_name
                doc.customer_type = "Company"
                doc.customer_group = "Individual"
                doc.territory = "Netherlands"
            else:
                doc.supplier_name = generic_name
                doc.supplier_group = "All Supplier Groups"
                doc.supplier_type = "Company"

            doc.insert(ignore_permissions=False)

            return doc.name, True

        except Exception as e:
            frappe.logger().error(f"Failed to create generic {party_type}: {str(e)}")
            # Return a hardcoded name as last resort
            return generic_name, False


def parse_bank_transaction(description: str) -> Dict[str, Optional[str]]:
    """
    Convenience function to parse a bank transaction description.

    Args:
        description: Bank transaction description

    Returns:
        Dict with iban, bic, party_name, remainder
    """
    parser = BankTransactionParser()
    return parser.parse_description(description)


def get_party_for_transaction(description: str, mutation_type: int) -> Tuple[Optional[str], str]:
    """
    Get or create party for a bank transaction.

    Args:
        description: Bank transaction description
        mutation_type: 5 (Money Received) or 6 (Money Paid)

    Returns:
        Tuple of (party_name, party_type) where party_type is "Customer" or "Supplier"
    """
    parser = BankTransactionParser()
    parsed = parser.parse_description(description)

    # Type 5 = Money Received → Customer
    # Type 6 = Money Paid → Supplier
    party_type = "Customer" if mutation_type == 5 else "Supplier"

    if parsed["party_name"]:
        party_name, _ = parser.find_or_create_party(parsed["party_name"], party_type, parsed["iban"])
        return party_name, party_type
    else:
        # No party name found, use generic
        party_name, _ = parser._get_or_create_generic_party(party_type)
        return party_name, party_type
