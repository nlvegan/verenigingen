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
        if not company:
            # Get company from E-Boekhouden Settings, not user defaults
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            frappe.throw(
                "No company specified for party extraction. Please configure E-Boekhouden Settings.",
                title="Company Required",
            )

        self.company = company

        # Bank internal transaction patterns (no party needed)
        self.bank_internal_patterns = [
            # Credit interest (interest earned)
            r"^CREDITRENTE\s+\d{2}-\d{2}-\d{2}\s+TOT\s+\d{2}-\d{2}-\d{2}",
            r"^Credit\s+(?:interest|rente)",
            r"^Rente\s+credit",
            # Debit interest (interest charged)
            r"^DEBETRENTE\s+\d{2}-\d{2}-\d{2}\s+TOT\s+\d{2}-\d{2}-\d{2}",
            r"^Debit\s+(?:interest|rente)",
            r"^Rente\s+debet",
            # Bank fees and charges
            r"^BANKKOSTEN",
            r"^Bank\s+(?:kosten|charges|fees)",
            r"^Administratiekosten",
            r"^Transactiekosten",
            r"^Servicekosten",
            # Other bank internal operations
            r"^Afsluitprovisie",
            r"^Valutacompensatie",
            r"^Rekening\s+correctie",
        ]

        # Dutch banking description patterns (adapted from MT940 logic)
        self.party_patterns = [
            # SEPA format: "NL##BANK#### BIC#### [Party Name] ..."
            # Example: "NL76ASNB0706938801 ASNBNL21 Elise Hiddinga TRIOD OS NL ..."
            r"NL\d{2}[A-Z]{4}\d+\s+[A-Z]{6,11}\s+([A-Z][a-zA-Z\s&\.\-\,]{2,40?})(?:\s+[A-Z]{2,}|\s+\d)",
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
            # Get mutation details - support both SOAP and REST API field names
            mutation_type = (
                mutation.get("type")
                or mutation.get("mutationType")  # REST API
                or mutation.get("MutatieType", 0)  # Alternative REST  # SOAP API
            )
            description = mutation.get("description") or mutation.get(  # REST API
                "Omschrijving", ""
            )  # SOAP API
            relation_id = mutation.get("relationId") or mutation.get("RelatieCode")  # REST API  # SOAP API

            # Only process Types 5 & 6 (Money Received/Paid)
            if int(mutation_type) not in [5, 6]:
                return None

            # Clean up the description first
            cleaned_description = self._clean_description(description)

            # Check if this is a bank internal transaction (interest, fees, etc.)
            if self._is_bank_internal_transaction(cleaned_description):
                # For bank internal transactions, the party should be the bank itself
                # We'll extract the bank name from the bank account later in the processor
                return {
                    "party_type": "Supplier",  # Banks are suppliers for fees/charges
                    "party_name": None,  # Will be set to bank name by processor
                    "relation_id": None,
                    "original_description": description,
                    "cleaned_description": cleaned_description,
                    "extraction_method": "bank_internal",
                    "is_bank_internal": True,
                    "bank_is_party": True,  # Signal to use bank as party
                }

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

    def _is_bank_internal_transaction(self, description: str) -> bool:
        """
        Check if description matches bank internal transaction patterns.
        These transactions (interest, fees, etc.) don't have external parties.

        Args:
            description: Cleaned transaction description

        Returns:
            True if this is a bank internal transaction
        """
        if not description:
            return False

        # Check against all bank internal patterns
        for pattern in self.bank_internal_patterns:
            if re.match(pattern, description, re.IGNORECASE):
                return True

        return False

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
        """
        Extract party name from description using bank transaction parser.

        Uses the existing BankTransactionParser which handles SEPA formats properly.
        """
        if not description:
            return None

        # First try using the BankTransactionParser (handles SEPA, MT940 formats)
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()
            parsed = parser.parse_description(description)

            if parsed and parsed.get("party_name"):
                party_name = parsed.get("party_name")
                # Validate the extracted name
                if self._is_valid_party_name(party_name):
                    return party_name
        except Exception as e:
            frappe.logger().debug(f"BankTransactionParser extraction failed: {str(e)}")

        # Fallback to pattern matching for non-SEPA formats
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
        # Support both SOAP and REST API field names
        mutation_type = int(
            mutation.get("type") or mutation.get("mutationType") or mutation.get("MutatieType", 0)
        )

        # Type 5 = Money Received (from customers)
        # Type 6 = Money Paid (to suppliers)
        if mutation_type == 5:
            return "Customer"
        elif mutation_type == 6:
            return "Supplier"

        # Fallback based on description patterns
        description = (mutation.get("description") or mutation.get("Omschrijving", "")).lower()

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
                from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

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
        """
        Resolve party by name using centralized BankTransactionParser logic.

        Uses the same matching strategy as MT940 import:
        1. IBAN match (not applicable here - no IBAN available)
        2. Exact name match (case-sensitive)
        3. Case-insensitive name match
        4. Fuzzy name match (handles initials, prefixes)
        5. Create new party if no match found

        Args:
            party_name: Party name extracted from description
            party_type: "Customer" or "Supplier"

        Returns:
            Party name if found/created, None on error
        """
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()

            # Use centralized find_or_create_party which has comprehensive matching
            # No IBAN available from e-boekhouden descriptions
            resolved_party, created = parser.find_or_create_party(
                party_name=party_name,
                party_type=party_type,
                iban=None,  # E-boekhouden descriptions don't have structured IBAN data
            )

            if created:
                frappe.logger().info(
                    f"EBoekhoudenPartyExtractor: Created new {party_type} '{resolved_party}' "
                    f"from description parsing"
                )
            else:
                frappe.logger().debug(
                    f"EBoekhoudenPartyExtractor: Matched '{party_name}' to existing {party_type} '{resolved_party}'"
                )

            return resolved_party

        except Exception as e:
            frappe.log_error(
                f"Error resolving party by name '{party_name}': {str(e)}",
                "EBoekhoudenPartyExtractor",
            )
            return None
