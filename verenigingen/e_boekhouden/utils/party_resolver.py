# Enhanced party management for E-Boekhouden integration
import json
import re
from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import now

# Party type configuration - defines differences between Customer and Supplier
PARTY_CONFIG = {
    "Customer": {
        "doctype": "Customer",
        "name_field": "customer_name",
        "type_field": "customer_type",
        "group_field": "customer_group",
        "default_group": "All Customer Groups",
        "territory_field": "territory",
        "default_territory": "All Territories",
        "provisional_prefix": "E-Boekhouden Customer",
    },
    "Supplier": {
        "doctype": "Supplier",
        "name_field": "supplier_name",
        "type_field": "supplier_type",
        "group_field": "supplier_group",
        "default_group": "All Supplier Groups",
        "territory_field": None,  # Suppliers don't have territory
        "default_territory": None,
        "provisional_prefix": "Supplier",
        "provisional_suffix": "(eBoekhouden)",
    },
}


class EBoekhoudenPartyResolver:
    """Intelligent party resolution with API integration and provisional management"""

    def __init__(self):
        self.settings = frappe.get_single("E-Boekhouden Settings")
        self.enrichment_queue = []

    def resolve_customer(self, relation_id, debug_info=None):
        """
        Resolve relation ID to proper customer using E-Boekhouden as Single Source of Truth.

        ALWAYS fetches fresh API data and updates existing customers if better data is available.
        """
        return self._resolve_party("Customer", relation_id, debug_info)

    def resolve_supplier(self, relation_id, debug_info=None):
        """
        Resolve relation ID to proper supplier using E-Boekhouden as Single Source of Truth.

        ALWAYS fetches fresh API data and updates existing suppliers if better data is available.
        """
        return self._resolve_party("Supplier", relation_id, debug_info)

    def _resolve_party(self, party_type: str, relation_id, debug_info=None):
        """
        Generic party resolution logic used by both resolve_customer and resolve_supplier.

        Steps:
            1. Fetch fresh data from E-Boekhouden API (SSoT approach)
            2. Check if party already exists by relation code
            3. Update existing party with fresh API data if available
            4. Create new party from API data if available
            5. Create provisional party if API is unavailable

        Args:
            party_type: "Customer" or "Supplier"
            relation_id: E-Boekhouden relation ID
            debug_info: Optional list for debug messages

        Returns:
            Party document name
        """
        if debug_info is None:
            debug_info = []

        config = PARTY_CONFIG[party_type]
        doctype = config["doctype"]
        name_field = config["name_field"]

        if not relation_id:
            debug_info.append(f"No relation ID provided, using default {party_type.lower()}")
            return self._get_default_party(party_type)

        # Step 1: ALWAYS try to fetch fresh data from E-Boekhouden API first (SSoT approach)
        relation_details = None
        try:
            relation_details = self.fetch_relation_details(relation_id, debug_info)
        except Exception as e:
            debug_info.append(f"API fetch failed for relation {relation_id}: {str(e)}")

        # Step 2: Check if party already exists
        existing = frappe.db.get_value(
            doctype,
            {"eboekhouden_relation_code": str(relation_id)},
            ["name", name_field],
            as_dict=True,
        )

        if existing:
            debug_info.append(
                f"Found existing {party_type.lower()}: {existing[name_field]} ({existing['name']})"
            )

            # Step 3: Update existing party with fresh API data if available
            if relation_details:
                updated = self._update_party_with_fresh_data(
                    party_type, existing["name"], relation_details, debug_info
                )
                if updated:
                    debug_info.append(f"Updated {party_type.lower()} {existing['name']} with fresh API data")

            return existing["name"]

        # Step 4: Create new party from API data if available
        if relation_details:
            return self._create_party_from_relation(party_type, relation_details, debug_info)

        # Step 5: Only create provisional party if API is completely unavailable
        debug_info.append(
            f"API unavailable for relation {relation_id}, creating provisional {party_type.lower()}"
        )
        return self._create_provisional_party(party_type, relation_id, debug_info)

    def fetch_relation_details(self, relation_id, debug_info=None):
        """Fetch relation details from E-Boekhouden REST API"""
        if debug_info is None:
            debug_info = []

        try:
            from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

            iterator = EBoekhoudenRESTIterator()

            # Call the relation detail endpoint
            import requests

            url = f"{iterator.base_url}/v1/relation/{relation_id}"
            response = requests.get(url, headers=iterator._get_headers(), timeout=30)

            if response.status_code == 200:
                relation_data = response.json()
                debug_info.append(f"Successfully fetched relation details for {relation_id}")

                # Log what fields we actually received
                important_fields = [
                    "name",
                    "type",
                    "email",
                    "bedrijfsnaam",
                    "companyName",
                    "voornaam",
                    "firstName",
                    "achternaam",
                    "lastName",
                    "telefoon",
                    "phone",
                ]
                received_fields = {
                    field: relation_data.get(field) for field in important_fields if relation_data.get(field)
                }
                if received_fields:
                    debug_info.append(f"Relation {relation_id} has fields: {list(received_fields.keys())}")
                else:
                    debug_info.append(f"WARNING: Relation {relation_id} has no name fields!")
                    frappe.log_error(
                        f"Empty relation data for {relation_id}: {json.dumps(relation_data, indent=2)}",
                        "E-Boekhouden Empty Relation",
                    )

                return relation_data
            elif response.status_code == 404:
                debug_info.append(f"Relation {relation_id} missing from e-boekhouden database")
                return None
            else:
                debug_info.append(f"API error fetching relation {relation_id}: {response.status_code}")
                return None

        except Exception as e:
            debug_info.append(f"Exception fetching relation {relation_id}: {str(e)}")
            return None

    def _extract_party_name_and_type(
        self, relation_details: Dict, party_type: str, debug_info: List
    ) -> Tuple[str, str]:
        """
        Extract party name and type from relation details.

        Handles multiple field name conventions (REST API vs legacy SOAP).

        Args:
            relation_details: API response data
            party_type: "Customer" or "Supplier"
            debug_info: Debug log list

        Returns:
            Tuple of (party_name, entity_type) where entity_type is "Company" or "Individual"
        """
        # Try REST API "name" field first
        relation_name = relation_details.get("name")
        relation_type_code = relation_details.get("type", "P")  # B=Business, P=Personal

        if relation_name and relation_name.strip():
            entity_type = "Company" if relation_type_code == "B" else "Individual"
            return relation_name.strip(), entity_type

        # Fallback to legacy Dutch field names
        company_name = relation_details.get("bedrijfsnaam") or relation_details.get("companyName")
        first_name = relation_details.get("voornaam") or relation_details.get("firstName")
        last_name = relation_details.get("achternaam") or relation_details.get("lastName")

        if company_name and company_name.strip():
            return company_name.strip(), "Company"

        if first_name or last_name:
            full_name = f"{first_name or ''} {last_name or ''}".strip()
            if full_name:
                return full_name, "Individual"

        # Try description-based name extraction
        party_name = self._extract_name_from_description(debug_info)
        if party_name:
            debug_info.append(f"Using description-based name: {party_name}")
            return party_name, "Individual"

        # Supplier-specific: try additional name fields
        if party_type == "Supplier":
            fallback_name = self._extract_supplier_fallback_name(relation_details, debug_info)
            if fallback_name:
                return fallback_name, "Company"

        # Final fallback
        relation_id = relation_details.get("id", "Unknown")
        if party_type == "Customer":
            return f"E-Boekhouden Relation {relation_id}", "Individual"
        else:
            return f"Supplier {relation_id} (eBoekhouden)", "Individual"

    def _extract_name_from_description(self, debug_info: List) -> Optional[str]:
        """Try to extract a meaningful name from debug info descriptions."""
        if not debug_info:
            return None

        try:
            from .eboekhouden_payment_naming import get_meaningful_description

            for info in debug_info:
                if "description" in info.lower():
                    try:
                        meaningful_desc = get_meaningful_description({"description": info})
                        if meaningful_desc and len(meaningful_desc) > 5:
                            return f"{meaningful_desc[:40]} (eBoekhouden Import)"
                    except Exception:
                        pass
        except ImportError:
            pass

        return None

    def _extract_supplier_fallback_name(self, relation_details: Dict, debug_info: List) -> Optional[str]:
        """Extract fallback name for suppliers from additional fields."""
        # Check for any field containing name-like data
        name_fields = ["companyName", "company", "bedrijf", "naam", "contactName", "contact"]
        for field in name_fields:
            if relation_details.get(field):
                return relation_details[field][:50]

        # Try to extract from address fields
        address_fields = ["street", "straat", "address"]
        for field in address_fields:
            addr = relation_details.get(field)
            if addr and len(addr) > 3 and not addr.isdigit():
                name_match = re.match(r"^([A-Za-z\s&.-]+)", addr)
                if name_match:
                    potential_name = name_match.group(1).strip()
                    if len(potential_name) > 3:
                        debug_info.append(f"Using extracted fallback name from address: {potential_name}")
                        return f"{potential_name} (eBoekhouden)"

        return None

    def _handle_duplicate_name(
        self, party_type: str, proposed_name: str, relation_id: str, debug_info: List
    ) -> Tuple[str, bool]:
        """
        Handle duplicate party name scenarios.

        Args:
            party_type: "Customer" or "Supplier"
            proposed_name: The proposed party name
            relation_id: E-Boekhouden relation ID
            debug_info: Debug log list

        Returns:
            Tuple of (final_name, already_exists) where already_exists means
            we found the exact same party and should return it directly
        """
        config = PARTY_CONFIG[party_type]
        doctype = config["doctype"]

        # Truncate to ERPNext name field limit
        proposed_name = proposed_name[:140]

        if not frappe.db.exists(doctype, proposed_name):
            return proposed_name, False

        # Check if it's the same relation (missed in earlier check)
        existing_relation_code = frappe.db.get_value(doctype, proposed_name, "eboekhouden_relation_code")

        if existing_relation_code == str(relation_id):
            debug_info.append(f"{party_type} {proposed_name} already exists with same relation code")
            return proposed_name, True  # Already exists - return directly

        # Different relation - make name unique
        unique_name = f"{proposed_name[:120]} ({relation_id})"

        # Check if unique name already exists (from partial retry)
        if frappe.db.exists(doctype, unique_name):
            debug_info.append(f"{party_type} {unique_name} already exists (from previous attempt)")
            return unique_name, True

        debug_info.append(
            f"{party_type} name '{proposed_name}' exists with different relation, using unique name: {unique_name}"
        )
        return unique_name, False

    def _create_party_from_relation(self, party_type: str, relation_details: Dict, debug_info=None) -> str:
        """
        Create party (Customer or Supplier) from relation details.

        Args:
            party_type: "Customer" or "Supplier"
            relation_details: API response data
            debug_info: Optional debug log list

        Returns:
            Created party document name
        """
        if debug_info is None:
            debug_info = []

        config = PARTY_CONFIG[party_type]
        doctype = config["doctype"]
        name_field = config["name_field"]
        type_field = config["type_field"]
        group_field = config["group_field"]

        # Create new document
        party = frappe.new_doc(doctype)

        # Extract name and type
        party_name, entity_type = self._extract_party_name_and_type(relation_details, party_type, debug_info)

        # Handle duplicate names
        final_name, already_exists = self._handle_duplicate_name(
            party_type, party_name, relation_details["id"], debug_info
        )

        if already_exists:
            return final_name

        # Set party fields
        setattr(party, name_field, final_name)
        setattr(party, type_field, entity_type)
        setattr(party, group_field, config["default_group"])

        # Customer-specific: territory
        if config.get("territory_field"):
            setattr(party, config["territory_field"], config["default_territory"])

        # Force document name
        party.name = final_name

        # Store relation ID for future matching
        party.eboekhouden_relation_code = str(relation_details["id"])

        # Add contact information
        if relation_details.get("email"):
            party.email_id = relation_details["email"]

        if relation_details.get("telefoon"):
            party.mobile_no = relation_details["telefoon"]

        # Add tax ID
        if relation_details.get("btwNummer"):
            party.tax_id = relation_details["btwNummer"]

        # Insert party
        party.insert()
        debug_info.append(f"Created {party_type.lower()} from relation data: {party.name} ({party_name})")

        # Create contact if we have contact details
        if relation_details.get("email") or relation_details.get("telefoon"):
            self.create_contact(party, relation_details, debug_info)

        # Add address if available
        if any(
            [relation_details.get("adres"), relation_details.get("postcode"), relation_details.get("plaats")]
        ):
            self._add_party_address(party, relation_details, debug_info)

        return party.name

    def _update_party_with_fresh_data(
        self, party_type: str, party_name: str, relation_details: Dict, debug_info=None
    ) -> bool:
        """
        Update existing party with fresh API data from E-Boekhouden.

        Args:
            party_type: "Customer" or "Supplier"
            party_name: Existing party document name
            relation_details: Fresh API data
            debug_info: Optional debug log list

        Returns:
            True if party was updated with better data, False otherwise
        """
        if debug_info is None:
            debug_info = []

        config = PARTY_CONFIG[party_type]
        doctype = config["doctype"]
        name_field = config["name_field"]
        type_field = config["type_field"]

        try:
            party = frappe.get_doc(doctype, party_name)

            # Extract better name from API data
            better_name, entity_type = self._extract_party_name_and_type(
                relation_details, party_type, debug_info
            )
            current_name = getattr(party, name_field)

            # Only update if current name looks provisional
            if (
                better_name
                and not current_name.startswith("E-Boekhouden")
                and "eBoekhouden" not in current_name
            ):
                debug_info.append(f"{party_type} {party_name} already has good name: {current_name}")
                return False

            if better_name and better_name != current_name:
                setattr(party, name_field, better_name)
                setattr(party, type_field, entity_type)

                # Update other fields if available and not set
                if relation_details.get("email") and not party.get("email_id"):
                    party.email_id = relation_details["email"]

                if relation_details.get("btwNummer") and not party.get("tax_id"):
                    party.tax_id = relation_details["btwNummer"]

                party.save()
                debug_info.append(f"Updated {party_type.lower()} name: '{current_name}' → '{better_name}'")
                return True

            return False

        except Exception as e:
            debug_info.append(f"Failed to update {party_type.lower()} {party_name}: {str(e)}")
            return False

    def _create_provisional_party(self, party_type: str, relation_id, debug_info=None) -> str:
        """
        Create provisional party for later enrichment.

        Args:
            party_type: "Customer" or "Supplier"
            relation_id: E-Boekhouden relation ID
            debug_info: Optional debug log list

        Returns:
            Created party document name
        """
        if debug_info is None:
            debug_info = []

        config = PARTY_CONFIG[party_type]
        doctype = config["doctype"]
        name_field = config["name_field"]
        group_field = config["group_field"]

        # Build provisional name
        if party_type == "Customer":
            provisional_name = f"{config['provisional_prefix']} {relation_id}"
        else:
            provisional_name = (
                f"{config['provisional_prefix']} {relation_id} {config.get('provisional_suffix', '')}"
            )
            provisional_name = provisional_name.strip()

        # Check if already exists
        if frappe.db.exists(doctype, {name_field: provisional_name}):
            existing_name = frappe.db.get_value(doctype, {name_field: provisional_name}, "name")
            debug_info.append(f"Provisional {party_type.lower()} already exists: {existing_name}")
            return existing_name

        # Create new provisional party
        party = frappe.new_doc(doctype)
        setattr(party, name_field, provisional_name)
        setattr(party, group_field, config["default_group"])

        if config.get("territory_field"):
            setattr(party, config["territory_field"], config["default_territory"])

        party.eboekhouden_relation_code = str(relation_id)

        # For suppliers, set document name explicitly
        if party_type == "Supplier":
            party.name = provisional_name[:140]

        party.insert()

        debug_info.append(f"Created provisional {party_type.lower()}: {party.name}")
        debug_info.append(f"{party_type} {party.name} marked for future enrichment")

        return party.name

    def _get_default_party(self, party_type: str):
        """
        REMOVED: Generic party creation disabled to prevent data corruption.

        All parties must be properly resolved from E-Boekhouden API.
        If this function is called, it indicates an API failure or missing relation data.
        """
        error_msg = (
            f"{party_type.upper()} RESOLUTION FAILED: No {party_type.lower()} could be resolved from E-Boekhouden API. "
            f"This indicates either an API connectivity issue or missing relation data. "
            f"Generic {party_type.lower()} creation has been disabled to prevent data corruption. "
            f"Please check API connectivity and ensure all relation IDs exist in E-Boekhouden."
        )

        frappe.logger().error(f"PARTY RESOLUTION FAILURE: {error_msg}")
        frappe.throw(error_msg, title=f"{party_type} Resolution Required", exc=frappe.ValidationError)

    # Keep legacy methods as thin wrappers for backwards compatibility
    def create_customer_from_relation(self, relation_details, debug_info=None):
        """Create customer with proper details from relation data"""
        return self._create_party_from_relation("Customer", relation_details, debug_info)

    def create_supplier_from_relation(self, relation_details, debug_info=None):
        """Create supplier with proper details from relation data"""
        return self._create_party_from_relation("Supplier", relation_details, debug_info)

    def update_customer_with_fresh_data(self, customer_name, relation_details, debug_info=None):
        """Update existing customer with fresh API data from E-Boekhouden."""
        return self._update_party_with_fresh_data("Customer", customer_name, relation_details, debug_info)

    def update_supplier_with_fresh_data(self, supplier_name, relation_details, debug_info=None):
        """Update existing supplier with fresh API data from E-Boekhouden."""
        return self._update_party_with_fresh_data("Supplier", supplier_name, relation_details, debug_info)

    def create_provisional_customer(self, relation_id, debug_info=None):
        """Create provisional customer for later enrichment"""
        return self._create_provisional_party("Customer", relation_id, debug_info)

    def create_provisional_supplier(self, relation_id, debug_info=None):
        """Create provisional supplier for later enrichment"""
        return self._create_provisional_party("Supplier", relation_id, debug_info)

    def get_default_customer(self):
        """REMOVED: Generic customer creation disabled to prevent data corruption."""
        return self._get_default_party("Customer")

    def get_default_supplier(self):
        """REMOVED: Generic supplier creation disabled to prevent data corruption."""
        return self._get_default_party("Supplier")

    def add_to_enrichment_queue(self, doctype, docname, relation_id, debug_info=None):
        """Add party to enrichment queue for later processing"""
        if debug_info is None:
            debug_info = []

        # Check if already in queue
        existing = frappe.db.exists(
            "Party Enrichment Queue",
            {"party_doctype": doctype, "party_name": docname, "status": ["in", ["Pending", "In Progress"]]},
        )

        if existing:
            debug_info.append(f"Party already in enrichment queue: {docname}")
            return existing

        # Create queue entry
        queue_entry = frappe.new_doc("Party Enrichment Queue")
        queue_entry.party_doctype = doctype
        queue_entry.party_name = docname
        queue_entry.eboekhouden_relation_id = str(relation_id)
        queue_entry.status = "Pending"
        queue_entry.priority = "High"
        queue_entry.creation_date = now()
        queue_entry.retry_count = 0

        queue_entry.insert()
        debug_info.append(f"Added to enrichment queue: {docname}")

        return queue_entry.name

    def create_contact(self, party, relation_details, debug_info=None):
        """Create contact for customer/supplier"""
        if debug_info is None:
            debug_info = []

        try:
            contact = frappe.new_doc("Contact")

            # Contact name
            if relation_details.get("voornaam") or relation_details.get("achternaam"):
                contact.first_name = relation_details.get("voornaam", "")
                contact.last_name = relation_details.get("achternaam", "")
            else:
                contact.first_name = party.get_title()

            # Link to party
            contact.append("links", {"link_doctype": party.doctype, "link_name": party.name})

            # Add email
            if relation_details.get("email"):
                contact.append("email_ids", {"email_id": relation_details["email"], "is_primary": 1})

            # Add phone
            if relation_details.get("telefoon"):
                contact.append("phone_nos", {"phone": relation_details["telefoon"], "is_primary_phone": 1})

            contact.insert()
            debug_info.append(f"Created contact for {party.name}: {contact.name}")

        except Exception as e:
            debug_info.append(f"Failed to create contact for {party.name}: {str(e)}")

    def _add_party_address(self, party, relation_details, debug_info=None):
        """Add address to party (stub for future implementation)"""
        if debug_info:
            debug_info.append(f"Address data available for {party.doctype.lower()} (not implemented yet)")

    # Legacy address methods for backwards compatibility
    def add_customer_address(self, customer, relation_details, debug_info=None):
        """Add address to customer"""
        self._add_party_address(customer, relation_details, debug_info)

    def add_supplier_address(self, supplier, relation_details, debug_info=None):
        """Add address to supplier"""
        self._add_party_address(supplier, relation_details, debug_info)

    def enrich_provisional_parties(self, limit=50):
        """Process enrichment queue to enhance provisional parties"""
        # Get pending enrichment entries
        queue_entries = frappe.get_all(
            "Party Enrichment Queue",
            filters={"status": "Pending"},
            fields=["name", "party_doctype", "party_name", "eboekhouden_relation_id"],
            order_by="priority desc, creation_date",
            limit=limit,
        )

        results = {"processed": 0, "enriched": 0, "failed": 0}

        for entry in queue_entries:
            try:
                # Update status to in progress
                frappe.db.set_value("Party Enrichment Queue", entry.name, "status", "In Progress")
                frappe.db.commit()

                debug_info = []

                # Try to fetch relation details
                relation_details = self.fetch_relation_details(entry.eboekhouden_relation_id, debug_info)

                if relation_details:
                    # Enrich the party
                    self.enrich_party(entry.party_doctype, entry.party_name, relation_details, debug_info)

                    # Mark as completed
                    frappe.db.set_value(
                        "Party Enrichment Queue",
                        entry.name,
                        {
                            "status": "Completed",
                            "completion_date": now(),
                            "notes": "; ".join(debug_info[-5:]),  # Last 5 debug messages
                        },
                    )
                    results["enriched"] += 1
                else:
                    # Mark as failed
                    frappe.db.set_value(
                        "Party Enrichment Queue",
                        entry.name,
                        {
                            "status": "Failed",
                            "completion_date": now(),
                            "notes": "Could not fetch relation details from API",
                        },
                    )
                    results["failed"] += 1

                results["processed"] += 1

            except Exception as e:
                # Mark as failed
                frappe.db.set_value(
                    "Party Enrichment Queue",
                    entry.name,
                    {"status": "Failed", "completion_date": now(), "notes": f"Error: {str(e)}"},
                )
                results["failed"] += 1
                results["processed"] += 1

        frappe.db.commit()
        return results

    def enrich_party(self, doctype, docname, relation_details, debug_info=None):
        """Enrich existing party with relation details"""
        if debug_info is None:
            debug_info = []

        party = frappe.get_doc(doctype, docname)
        name_field = "customer_name" if doctype == "Customer" else "supplier_name"

        # Update name if it was provisional
        current_title = party.get_title()
        if "E-Boekhouden" in current_title or "eBoekhouden" in current_title:
            if relation_details.get("bedrijfsnaam"):
                setattr(party, name_field, relation_details["bedrijfsnaam"])

        # Add contact details
        if relation_details.get("email") and not party.get("email_id"):
            party.email_id = relation_details["email"]

        if relation_details.get("telefoon") and not party.get("mobile_no"):
            party.mobile_no = relation_details["telefoon"]

        if relation_details.get("btwNummer") and not party.get("tax_id"):
            party.tax_id = relation_details["btwNummer"]

        party.save()
        debug_info.append(f"Enriched {doctype} {docname} with API data")


# Convenience functions for backward compatibility
def resolve_customer(relation_id, debug_info=None):
    """Convenience function for customer resolution"""
    resolver = EBoekhoudenPartyResolver()
    return resolver.resolve_customer(relation_id, debug_info)


def resolve_supplier(relation_id, debug_info=None):
    """Convenience function for supplier resolution"""
    resolver = EBoekhoudenPartyResolver()
    return resolver.resolve_supplier(relation_id, debug_info)
