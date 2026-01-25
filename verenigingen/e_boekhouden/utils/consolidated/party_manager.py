"""
Consolidated Party Manager for E-Boekhouden Integration

.. deprecated:: 2026.01
   This module is deprecated in favor of ``party_resolver.py``.
   Use ``EBoekhoudenPartyResolver`` from
   ``verenigingen.e_boekhouden.utils.party_resolver`` instead.

   Migration guide:
   - resolve_customer() -> EBoekhoudenPartyResolver().resolve_customer()
   - resolve_supplier() -> EBoekhoudenPartyResolver().resolve_supplier()
   - process_enrichment_queue() -> EBoekhoudenPartyResolver().enrich_provisional_parties()

   This module will be removed in a future release.

Original documentation:
This module consolidated all party (customer/supplier) creation and management
functionality from the previous scattered implementations:
- party_extractor.py (344 lines)
- party_resolver.py (552 lines)
- simple_party_handler.py (68 lines)

Total consolidated: 964 lines → ~400 lines of focused functionality
"""

import json
import warnings
from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import add_days, now, today

from verenigingen.e_boekhouden.utils.security_helper import migration_context, validate_and_insert


class EBoekhoudenPartyManager:
    """
    Consolidated party management for E-Boekhouden integration.

    Features:
    - Intelligent customer/supplier resolution
    - Fallback strategies for missing data
    - Custom field integration
    - Provisional party creation with enrichment queue
    - Proper security and transaction management
    """

    def __init__(self):
        warnings.warn(
            "EBoekhoudenPartyManager is deprecated. "
            "Use EBoekhoudenPartyResolver from verenigingen.e_boekhouden.utils.party_resolver instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.settings = frappe.get_single("E-Boekhouden Settings")
        self.enrichment_queue = []
        self.debug_log = []

    def resolve_customer(self, relation_id: str, debug_info: Optional[List[str]] = None) -> Optional[str]:
        """
        Resolve E-Boekhouden relation ID to Frappe customer.

        Resolution strategy:
        1. Check existing customer with eboekhouden_relation_code
        2. Try pattern matching on customer names
        3. Create provisional customer
        4. Queue for enrichment if API available

        Args:
            relation_id: E-Boekhouden relation ID
            debug_info: Optional debug log list

        Returns:
            Customer name if found/created, None if failed
        """
        if debug_info is None:
            debug_info = self.debug_log

        if not relation_id:
            debug_info.append("No relation ID provided, using default customer")
            return self._get_default_customer()

        # Strategy 1: Direct mapping via custom field
        existing = self._find_customer_by_relation_id(relation_id)
        if existing:
            debug_info.append(f"Found existing customer: {existing['customer_name']} ({existing['name']})")
            return existing["name"]

        # Strategy 2: Pattern matching for partial matches
        pattern_match = self._find_customer_by_pattern(relation_id)
        if pattern_match:
            debug_info.append(f"Found customer by pattern: {pattern_match}")
            return pattern_match

        # Strategy 3: Create provisional customer
        try:
            customer_name = self._create_provisional_customer(relation_id, debug_info)

            # Queue for enrichment if API is available
            if self.settings and self.settings.api_token:
                self._queue_for_enrichment("Customer", customer_name, relation_id)

            return customer_name

        except Exception as e:
            debug_info.append(f"Failed to create customer for relation {relation_id}: {str(e)}")
            return self._get_default_customer()

    def resolve_supplier(
        self, relation_id: str, description: str = "", debug_info: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Resolve E-Boekhouden relation ID to Frappe supplier.

        Args:
            relation_id: E-Boekhouden relation ID
            description: Transaction description for name hints
            debug_info: Optional debug log list

        Returns:
            Supplier name if found/created, None if failed
        """
        if debug_info is None:
            debug_info = self.debug_log

        if not relation_id:
            debug_info.append("No supplier relation ID provided")
            return None

        # Strategy 1: Direct mapping via custom field
        existing = self._find_supplier_by_relation_id(relation_id)
        if existing:
            debug_info.append(f"Found existing supplier: {existing['supplier_name']} ({existing['name']})")
            return existing["name"]

        # Strategy 2: Create provisional supplier
        try:
            supplier_name = self._create_provisional_supplier(relation_id, description, debug_info)

            # Queue for enrichment
            if self.settings and self.settings.api_token:
                self._queue_for_enrichment("Supplier", supplier_name, relation_id)

            return supplier_name

        except Exception as e:
            debug_info.append(f"Failed to create supplier for relation {relation_id}: {str(e)}")
            return None

    def get_or_create_customer_simple(
        self, relation_id: str, debug_log: Optional[List] = None
    ) -> Optional[str]:
        """
        Simple customer creation without custom fields (for payment processing fallback).

        Uses centralized BankTransactionParser for party creation to ensure
        consistent matching and creation logic across the codebase.
        """
        if not relation_id:
            return None

        if debug_log is None:
            debug_log = self.debug_log

        # Try pattern matching first
        customer_name_pattern = f"%{relation_id}%"
        existing = frappe.db.get_value("Customer", {"customer_name": ["like", customer_name_pattern]}, "name")

        if existing:
            debug_log.append(f"Found existing customer: {existing}")
            return existing

        # Use centralized party creation via BankTransactionParser
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()
            customer_name = f"E-Boekhouden Customer {relation_id}"

            party_name, created = parser.find_or_create_party(
                party_name=customer_name,
                party_type="Customer",
                iban=None,
            )

            if created:
                debug_log.append(f"Created simple customer: {party_name}")
            else:
                debug_log.append(f"Found existing customer via parser: {party_name}")

            return party_name

        except Exception as e:
            debug_log.append(f"Failed to create simple customer: {str(e)}")
            return None

    def get_or_create_supplier_simple(
        self, relation_id: str, description: str = "", debug_log: Optional[List] = None
    ) -> Optional[str]:
        """
        Simple supplier creation without custom fields (for payment processing fallback).

        Uses centralized BankTransactionParser for party creation to ensure
        consistent matching and creation logic across the codebase.
        """
        if not relation_id:
            return None

        if debug_log is None:
            debug_log = self.debug_log

        # Try pattern matching first
        supplier_name_pattern = f"%{relation_id}%"
        existing = frappe.db.get_value("Supplier", {"supplier_name": ["like", supplier_name_pattern]}, "name")

        if existing:
            debug_log.append(f"Found existing supplier: {existing}")
            return existing

        # Use centralized party creation via BankTransactionParser
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()

            # Use description as name hint if more descriptive than just the relation ID
            if description and len(description) > len(f"Supplier {relation_id}"):
                supplier_name = description[:100]
            else:
                supplier_name = f"E-Boekhouden Supplier {relation_id}"

            party_name, created = parser.find_or_create_party(
                party_name=supplier_name,
                party_type="Supplier",
                iban=None,
            )

            if created:
                debug_log.append(f"Created simple supplier: {party_name}")
            else:
                debug_log.append(f"Found existing supplier via parser: {party_name}")

            return party_name

        except Exception as e:
            debug_log.append(f"Failed to create simple supplier: {str(e)}")
            return None

    def process_enrichment_queue(self) -> Dict:
        """Process the party enrichment queue with E-Boekhouden API data."""
        if not self.enrichment_queue:
            return {"processed": 0, "errors": []}

        results = {"processed": 0, "errors": []}

        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_client import EBoekhoudenRESTClient

            client = EBoekhoudenRESTClient()

            for queue_item in self.enrichment_queue:
                try:
                    if queue_item["party_type"] == "Customer":
                        self._enrich_customer(client, queue_item)
                    else:
                        self._enrich_supplier(client, queue_item)

                    results["processed"] += 1

                except Exception as e:
                    results["errors"].append(f"{queue_item['party_name']}: {str(e)}")

            # Clear processed queue
            self.enrichment_queue = []

        except ImportError:
            results["errors"].append("E-Boekhouden REST client not available")
        except Exception as e:
            results["errors"].append(f"Enrichment processing failed: {str(e)}")

        return results

    # Private helper methods

    def _find_customer_by_relation_id(self, relation_id: str) -> Optional[Dict]:
        """Find customer by E-Boekhouden relation code."""
        try:
            return frappe.db.get_value(
                "Customer",
                {"eboekhouden_relation_code": str(relation_id)},
                ["name", "customer_name"],
                as_dict=True,
            )
        except frappe.DoesNotExistError:
            return None
        except Exception:
            # Custom field might not exist
            return None

    def _find_supplier_by_relation_id(self, relation_id: str) -> Optional[Dict]:
        """Find supplier by E-Boekhouden relation code."""
        try:
            return frappe.db.get_value(
                "Supplier",
                {"eboekhouden_relation_code": str(relation_id)},
                ["name", "supplier_name"],
                as_dict=True,
            )
        except frappe.DoesNotExistError:
            return None
        except Exception:
            # Custom field might not exist
            return None

    def _find_customer_by_pattern(self, relation_id: str) -> Optional[str]:
        """Find customer by name pattern matching."""
        patterns = [f"%{relation_id}%", f"%Customer {relation_id}%", f"%E-Boekhouden {relation_id}%"]

        for pattern in patterns:
            customer = frappe.db.get_value("Customer", {"customer_name": ["like", pattern]}, "name")
            if customer:
                return customer

        return None

    def _create_provisional_customer(self, relation_id: str, debug_info: List) -> str:
        """
        Create a provisional customer that can be enriched later.

        Uses centralized BankTransactionParser for party creation to ensure
        consistent matching and creation logic across the codebase.
        """
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()
            customer_name = f"E-Boekhouden Customer {relation_id}"

            party_name, created = parser.find_or_create_party(
                party_name=customer_name,
                party_type="Customer",
                iban=None,
            )

            if created:
                # Set additional fields specific to provisional customers
                try:
                    updates = {}
                    if frappe.get_meta("Customer").has_field("eboekhouden_relation_code"):
                        updates["eboekhouden_relation_code"] = str(relation_id)
                    if frappe.get_meta("Customer").has_field("provisional_party"):
                        updates["provisional_party"] = 1
                    if updates:
                        frappe.db.set_value("Customer", party_name, updates)
                except Exception:
                    pass  # Fields might not exist

                debug_info.append(f"Created provisional customer: {party_name}")
            else:
                debug_info.append(f"Found existing customer via parser: {party_name}")

            return party_name

        except Exception as e:
            debug_info.append(f"Failed to create provisional customer: {str(e)}")
            raise

    def _create_provisional_supplier(self, relation_id: str, description: str, debug_info: List) -> str:
        """
        Create a provisional supplier that can be enriched later.

        Uses centralized BankTransactionParser for party creation to ensure
        consistent matching and creation logic across the codebase.
        """
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()

            # Use description as name hint or fallback to relation ID
            if description and len(description.strip()) > 5 and relation_id not in description:
                supplier_name = f"{description.strip()[:80]} ({relation_id})"
            else:
                supplier_name = f"E-Boekhouden Supplier {relation_id}"

            party_name, created = parser.find_or_create_party(
                party_name=supplier_name,
                party_type="Supplier",
                iban=None,
            )

            if created:
                # Set additional fields specific to provisional suppliers
                try:
                    updates = {}
                    if frappe.get_meta("Supplier").has_field("eboekhouden_relation_code"):
                        updates["eboekhouden_relation_code"] = str(relation_id)
                    if frappe.get_meta("Supplier").has_field("provisional_party"):
                        updates["provisional_party"] = 1
                    if updates:
                        frappe.db.set_value("Supplier", party_name, updates)
                except Exception:
                    pass  # Fields might not exist

                debug_info.append(f"Created provisional supplier: {party_name}")
            else:
                debug_info.append(f"Found existing supplier via parser: {party_name}")

            return party_name

        except Exception as e:
            debug_info.append(f"Failed to create provisional supplier: {str(e)}")
            raise

    def _get_default_customer(self) -> Optional[str]:
        """
        Get or create default customer for fallback cases.

        Uses centralized BankTransactionParser for party creation to ensure
        consistent matching and creation logic across the codebase.
        """
        default_customer = frappe.db.get_value(
            "Customer", {"customer_name": "Default E-Boekhouden Customer"}, "name"
        )

        if not default_customer:
            try:
                from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

                parser = BankTransactionParser()
                party_name, _ = parser.find_or_create_party(
                    party_name="Default E-Boekhouden Customer",
                    party_type="Customer",
                    iban=None,
                )
                return party_name
            except Exception:
                return None

        return default_customer

    def _get_default_customer_group(self) -> str:
        """Get default customer group."""
        # First try to get a reasonable default customer group
        default_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        if default_group:
            return default_group

        # "All Customer Groups" is ERPNext's default root group, this is safe
        return "All Customer Groups"

    def _get_default_territory(self) -> str:
        """Get default territory using consistent error handling."""
        from verenigingen.e_boekhouden.utils.error_handling_framework import ErrorHandler, safe_get_value

        handler = ErrorHandler("Party Manager")

        # Try to get default territory configured for company
        company_territory = frappe.db.get_value("Company", self.company, "default_territory")
        if company_territory:
            return company_territory

        # Get any territory using safe method
        return safe_get_value(
            "Territory", {"is_group": 0}, "name", handler, context="party creation", required=True
        )

    def _get_default_supplier_group(self) -> str:
        """Get default supplier group."""
        # Get any supplier group, but don't use random fallback text
        supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
        if supplier_group:
            return supplier_group

        frappe.throw(
            "No supplier group found. Please create supplier groups first.", title="Supplier Group Required"
        )

    def _queue_for_enrichment(self, party_type: str, party_name: str, relation_id: str):
        """Queue party for enrichment with API data."""
        self.enrichment_queue.append(
            {
                "party_type": party_type,
                "party_name": party_name,
                "relation_id": relation_id,
                "queued_at": now(),
            }
        )

    def _enrich_customer(self, client, queue_item: Dict):
        """Enrich customer with API data."""
        # This would fetch detailed customer data from E-Boekhouden API
        # and update the customer record with additional information
        pass  # Implementation depends on specific API structure

    def _enrich_supplier(self, client, queue_item: Dict):
        """Enrich supplier with API data."""
        # This would fetch detailed supplier data from E-Boekhouden API
        # and update the supplier record with additional information
        pass  # Implementation depends on specific API structure

    def get_debug_log(self) -> List[str]:
        """Get debug log for inspection."""
        return self.debug_log

    def clear_debug_log(self):
        """Clear debug log."""
        self.debug_log = []


# Backward compatibility functions for existing code
def get_or_create_customer_simple(relation_id: str, debug_log: Optional[List] = None) -> Optional[str]:
    """Backward compatibility wrapper."""
    manager = EBoekhoudenPartyManager()
    return manager.get_or_create_customer_simple(relation_id, debug_log)


def get_or_create_supplier_simple(
    relation_id: str, description: str = "", debug_log: Optional[List] = None
) -> Optional[str]:
    """Backward compatibility wrapper."""
    manager = EBoekhoudenPartyManager()
    return manager.get_or_create_supplier_simple(relation_id, description, debug_log)
