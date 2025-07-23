"""
eBoekhouden Party Extractor for Types 5&6 Money Transfers
Combines MT940-style description parsing with eBoekhouden party resolution
"""

import re
from typing import Any, Dict, Optional, Tuple

import frappe


class EBoekhoudenPartyExtractor:
    """
    Extract and resolve parties from eBoekhouden mutation descriptions
    Combines description parsing patterns with existing party resolution
    """

    def __init__(self, company: str = None):
        self.company = company or frappe.defaults.get_user_default("Company")

        # Dutch banking description patterns (adapted from MT940 logic)
        self.party_patterns = [
            # Dutch patterns: "van/naar [Party Name]"
            r"(?:van|from|naar|to)\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40})",
            # Payment description patterns: "[Party] payment/betaling"
            r"([A-Za-z][A-Za-z\s&\.\-\,]{3,40})\s+(?:payment|betaling|invoice|factuur)",
            # Transfer patterns: "overboeking van/naar [Party]"
            r"(?:overboeking|transfer|overschrijving)\s+(?:van|from|naar|to)\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40})",
            # Direct debit patterns: "incasso [Party]" and "automatische incasso [Party]"
            r"(?:incasso|direct debit|automatische incasso)\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40})",
            # General money movement: "ontvangen van/betaald aan [Party]"
            r"(?:ontvangen van|received from|betaald aan|paid to)\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40})",
            # "aan [Party]" patterns for payments to suppliers
            r"(?:huur|kosten|betaling|payment)\s+aan\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40})",
            # "naar [Party]" patterns for transfers
            r"(?:overboeking|transfer)\s+naar\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40})",
            # Simple "naar [Party]" without overboeking prefix
            r"\bnaar\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40}(?:\s+BV|\s+NV|\s+Ltd|\s+Inc|\s+Company)?)\b",
            # Bank/incasso with specific party (avoid generic bank names)
            r"(?:incasso|automatische incasso)\s+([A-Za-z][A-Za-z\s&\.\-\,]{2,40}(?:Bank|BV|NV|Ltd|Inc|Company))",
            # Simple pattern: just the party name after cleaning common prefixes
            r"^([A-Za-z][A-Za-z\s&\.\-\,]{3,40})\s+(?:voor|for)\s+",
        ]

        # Description cleanup patterns (adapted from MT940 logic)
        self.cleanup_patterns = [
            r"^(Payment|Betaling|Invoice|Factuur|Transfer|Overboeking)\s+(from|van|to|naar)\s+",
            r"\s+\(.*\)$",  # Remove trailing parentheses
            r"^Mutatie\s+\d+:\s*",  # Remove mutation number prefix
            r"^EBH-Money\s+(Received|Paid)-\d+:\s*",  # Remove eBoekhouden prefix
            r"\s*-\s*From$",  # Remove " - From" suffix
            r"\s*-\s*To$",  # Remove " - To" suffix
        ]

    def extract_party_from_mutation(self, mutation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract party information from eBoekhouden mutation
        Returns party details or None if no party could be identified

        Args:
            mutation: eBoekhouden mutation dictionary

        Returns:
            Dict with party_type, party_name, relation_id (if available)
        """
        try:
            # Get mutation details
            mutation_type = mutation.get("MutatieType") or mutation.get("mutationType", 0)
            description = mutation.get("Omschrijving") or mutation.get("description", "")
            relation_id = mutation.get("RelatieCode") or mutation.get("relationId")

            # Only process Types 5 & 6 (Money Received/Paid)
            if int(mutation_type) not in [5, 6]:
                return None

            # Clean up the description first
            cleaned_description = self._clean_description(description)

            # Try to extract party name from description
            extracted_party_name = self._extract_party_name_from_description(cleaned_description)

            # Determine party type based on mutation type and account context
            party_type = self._determine_party_type(mutation, extracted_party_name)

            # If we have a party name or relation_id, return the party info
            if extracted_party_name or relation_id:
                return {
                    "party_type": party_type,
                    "party_name": extracted_party_name,
                    "relation_id": relation_id,
                    "original_description": description,
                    "cleaned_description": cleaned_description,
                    "extraction_method": "description_pattern" if extracted_party_name else "relation_id",
                }

            return None

        except Exception as e:
            frappe.log_error(f"Error extracting party from mutation: {str(e)}", "EBoekhoudenPartyExtractor")
            return None

    def resolve_party_for_journal_entry(
        self, party_info: Dict[str, Any], account: str
    ) -> Optional[Tuple[str, str]]:
        """
        Resolve party information for journal entry assignment

        Args:
            party_info: Party information from extract_party_from_mutation
            account: ERPNext account name

        Returns:
            Tuple of (party_type, party_name) or None
        """
        try:
            if not party_info:
                return None

            # Get account type to determine if party assignment is appropriate
            account_type = frappe.db.get_value("Account", account, "account_type")

            # Only assign parties to Receivable/Payable accounts
            if account_type not in ["Receivable", "Payable"]:
                return None

            # Determine expected party type based on account type
            expected_party_type = "Customer" if account_type == "Receivable" else "Supplier"

            # If we have a relation_id, use existing party resolution
            if party_info.get("relation_id"):
                resolved_party = self._resolve_party_by_relation_id(
                    party_info["relation_id"], expected_party_type
                )
                if resolved_party:
                    return (expected_party_type, resolved_party)

            # If we have a party name from description, try to find or create party
            if party_info.get("party_name"):
                resolved_party = self._resolve_party_by_name(party_info["party_name"], expected_party_type)
                if resolved_party:
                    return (expected_party_type, resolved_party)

            return None

        except Exception as e:
            frappe.log_error(
                f"Error resolving party for journal entry: {str(e)}", "EBoekhoudenPartyExtractor"
            )
            return None

    def _clean_description(self, description: str) -> str:
        """Clean up mutation description using MT940-style patterns"""
        if not description:
            return ""

        cleaned = description.strip()

        # Apply cleanup patterns
        for pattern in self.cleanup_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

        # If nothing meaningful left, return original
        if len(cleaned) < 3:
            return description

        return cleaned

    def _extract_party_name_from_description(self, description: str) -> Optional[str]:
        """Extract party name from description using pattern matching"""
        if not description:
            return None

        # Try each pattern to extract party name
        for pattern in self.party_patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                extracted_name = match.group(1).strip()

                # Clean up extracted name
                extracted_name = self._clean_extracted_name(extracted_name)

                # Validate extracted name
                if self._is_valid_party_name(extracted_name):
                    return extracted_name

        return None

    def _clean_extracted_name(self, name: str) -> str:
        """Clean up extracted party name"""
        if not name:
            return ""

        # Remove common suffixes/prefixes that aren't part of the name
        cleanup = [
            r"\s+(?:voor|for|van|from|payment|betaling).*$",  # Remove trailing purpose
            r"^(?:de|het|the)\s+",  # Remove articles
            r"\s*,.*$",  # Remove everything after comma
        ]

        cleaned = name.strip()
        for pattern in cleanup:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

        return cleaned

    def _is_valid_party_name(self, name: str) -> bool:
        """Validate if extracted name is a valid party name"""
        if not name or len(name) < 3:
            return False

        # Avoid generic terms (but allow "Bank" if it's part of a company name like "ABN AMRO Bank")
        generic_terms = [
            "payment",
            "betaling",
            "invoice",
            "factuur",
            "customer",
            "supplier",
            "transfer",
            "overboeking",
            "incasso",
            "unknown",
            "onbekend",
        ]

        # Allow "bank" if it's part of a longer company name
        if any(term in name.lower() for term in generic_terms):
            return False

        # Specific check for standalone "bank" (but allow "SomeCompany Bank")
        if name.lower().strip() == "bank":
            return False

        # Avoid pure numbers or codes
        if re.match(r"^\d+$", name):
            return False

        return True

    def _determine_party_type(self, mutation: Dict[str, Any], party_name: str) -> str:
        """Determine whether party should be Customer or Supplier based on context"""
        mutation_type = int(mutation.get("MutatieType") or mutation.get("mutationType", 0))

        # Type 5 = Money Received (from customers)
        # Type 6 = Money Paid (to suppliers)
        if mutation_type == 5:
            return "Customer"
        elif mutation_type == 6:
            return "Supplier"

        # Fallback based on description patterns
        description = (mutation.get("Omschrijving") or mutation.get("description", "")).lower()

        # Income-related terms suggest customer
        if any(term in description for term in ["ontvangen", "received", "contribution", "contributie"]):
            return "Customer"

        # Expense-related terms suggest supplier
        if any(term in description for term in ["betaald", "paid", "huur", "rent", "kosten", "expense"]):
            return "Supplier"

        # Default based on mutation type
        return "Customer" if mutation_type == 5 else "Supplier"

    def _resolve_party_by_relation_id(self, relation_id: str, party_type: str) -> Optional[str]:
        """Resolve party using eBoekhouden relation_id"""
        try:
            # Try to find existing party with this relation_id
            doctype = party_type
            existing_party = frappe.db.get_value(
                doctype, {"eboekhouden_relation_code": str(relation_id)}, "name"
            )

            if existing_party:
                return existing_party

            # Use existing EBoekhoudenPartyResolver if available
            try:
                from verenigingen.utils.eboekhouden.party_resolver import EBoekhoudenPartyResolver

                resolver = EBoekhoudenPartyResolver(self.company)

                if party_type == "Customer":
                    return resolver.resolve_customer(relation_id)
                else:
                    return resolver.resolve_supplier(relation_id)

            except ImportError:
                frappe.log_error("EBoekhoudenPartyResolver not available", "EBoekhoudenPartyExtractor")
                return None

        except Exception as e:
            frappe.log_error(
                f"Error resolving party by relation_id {relation_id}: {str(e)}", "EBoekhoudenPartyExtractor"
            )
            return None

    def _resolve_party_by_name(self, party_name: str, party_type: str) -> Optional[str]:
        """Resolve party by name - find existing or create new"""
        try:
            doctype = party_type

            # Try to find existing party by name (fuzzy match)
            existing_parties = frappe.get_all(
                doctype,
                filters={"name": ["like", f"%{party_name}%"]},
                fields=["name", f"{doctype.lower()}_name"],
                limit=5,
            )

            # Look for exact or close matches
            for party in existing_parties:
                party_full_name = party.get(f"{doctype.lower()}_name", "")
                if (
                    party_name.lower() in party_full_name.lower()
                    or party_full_name.lower() in party_name.lower()
                ):
                    return party["name"]

            # Create new party if none found (basic creation)
            new_party = frappe.new_doc(doctype)
            new_party.update(
                {
                    f"{doctype.lower()}_name": party_name,
                    "customer_group": "Individual" if doctype == "Customer" else None,
                    "supplier_group": "Local" if doctype == "Supplier" else None,
                    "territory": "Netherlands" if doctype == "Customer" else None,
                }
            )

            new_party.insert(ignore_permissions=True)

            frappe.log_error(
                f"Created new {doctype} '{party_name}' from eBoekhouden description parsing",
                "EBoekhoudenPartyExtractor",
            )

            return new_party.name

        except Exception as e:
            frappe.log_error(
                f"Error resolving party by name '{party_name}': {str(e)}", "EBoekhoudenPartyExtractor"
            )
            return None
