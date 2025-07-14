# Enhanced party management for E-Boekhouden integration
import json

import frappe
from frappe.utils import add_days, now, today


class EBoekhoudenPartyResolver:
    """Intelligent party resolution with API integration and provisional management"""

    def __init__(self):
        self.settings = frappe.get_single("E-Boekhouden Settings")
        self.enrichment_queue = []

    def resolve_customer(self, relation_id, debug_info=None):
        """Resolve relation ID to proper customer with intelligent fallback"""
        if debug_info is None:
            debug_info = []

        if not relation_id:
            debug_info.append("No relation ID provided, using default customer")
            return self.get_default_customer()

        # Step 1: Check existing mapping
        existing = frappe.db.get_value(
            "Customer",
            {"eboekhouden_relation_code": str(relation_id)},
            ["name", "customer_name"],
            as_dict=True,
        )

        if existing:
            debug_info.append(f"Found existing customer: {existing['customer_name']} ({existing['name']})")
            return existing["name"]

        # Step 2: Try to fetch relation details from e-boekhouden API
        try:
            relation_details = self.fetch_relation_details(relation_id, debug_info)
            if relation_details:
                return self.create_customer_from_relation(relation_details, debug_info)
        except Exception as e:
            debug_info.append(f"Could not fetch relation details for {relation_id}: {str(e)}")

        # Step 3: Create provisional customer
        return self.create_provisional_customer(relation_id, debug_info)

    def resolve_supplier(self, relation_id, debug_info=None):
        """Resolve relation ID to proper supplier with intelligent fallback"""
        if debug_info is None:
            debug_info = []

        if not relation_id:
            debug_info.append("No relation ID provided, using default supplier")
            return self.get_default_supplier()

        # Check existing mapping
        existing = frappe.db.get_value(
            "Supplier",
            {"eboekhouden_relation_code": str(relation_id)},
            ["name", "supplier_name"],
            as_dict=True,
        )

        if existing:
            debug_info.append(f"Found existing supplier: {existing['supplier_name']} ({existing['name']})")
            return existing["name"]

        # Try to fetch relation details
        try:
            relation_details = self.fetch_relation_details(relation_id, debug_info)
            if relation_details:
                return self.create_supplier_from_relation(relation_details, debug_info)
        except Exception as e:
            debug_info.append(f"Could not fetch relation details for {relation_id}: {str(e)}")

        # Create provisional supplier
        return self.create_provisional_supplier(relation_id, debug_info)

    def fetch_relation_details(self, relation_id, debug_info=None):
        """Fetch relation details from E-Boekhouden REST API"""
        if debug_info is None:
            debug_info = []

        try:
            from verenigingen.utils.eboekhouden.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

            iterator = EBoekhoudenRESTIterator()

            # Call the relation detail endpoint
            import requests

            url = f"{iterator.base_url}/v1/relation/{relation_id}"
            response = requests.get(url, headers=iterator._get_headers(), timeout=30)

            if response.status_code == 200:
                relation_data = response.json()
                debug_info.append(f"Successfully fetched relation details for {relation_id}")
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

    def create_customer_from_relation(self, relation_details, debug_info=None):
        """Create customer with proper details from relation data"""
        if debug_info is None:
            debug_info = []

        customer = frappe.new_doc("Customer")

        # Determine customer name
        if relation_details.get("bedrijfsnaam"):
            customer_name = relation_details["bedrijfsnaam"]
            customer_type = "Company"
        else:
            customer_name = (
                f"{relation_details.get('voornaam', '')} {relation_details.get('achternaam', '')}".strip()
            )
            customer_type = "Individual"

        if not customer_name:
            customer_name = f"E-Boekhouden Relation {relation_details['id']}"

        customer.customer_name = customer_name
        customer.customer_type = customer_type
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"

        # Store relation ID for future matching
        customer.eboekhouden_relation_code = str(relation_details["id"])

        # Add contact information if available
        if relation_details.get("email"):
            customer.email_id = relation_details["email"]

        # Add address information
        if any(
            [relation_details.get("adres"), relation_details.get("postcode"), relation_details.get("plaats")]
        ):
            self.add_customer_address(customer, relation_details, debug_info)

        # Add phone number
        if relation_details.get("telefoon"):
            customer.mobile_no = relation_details["telefoon"]

        # Add tax ID if available
        if relation_details.get("btwNummer"):
            customer.tax_id = relation_details["btwNummer"]

        customer.insert()
        debug_info.append(f"Created customer from relation data: {customer.name} ({customer_name})")

        # Create contact if we have contact details
        if relation_details.get("email") or relation_details.get("telefoon"):
            self.create_contact(customer, relation_details, debug_info)

        return customer.name

    def create_supplier_from_relation(self, relation_details, debug_info=None):
        """Create supplier with proper details from relation data"""
        if debug_info is None:
            debug_info = []

        supplier = frappe.new_doc("Supplier")

        # Determine supplier name
        if relation_details.get("bedrijfsnaam"):
            supplier_name = relation_details["bedrijfsnaam"]
            supplier_type = "Company"
        else:
            supplier_name = (
                f"{relation_details.get('voornaam', '')} {relation_details.get('achternaam', '')}".strip()
            )
            supplier_type = "Individual"

        if not supplier_name:
            supplier_name = f"E-Boekhouden Relation {relation_details['id']}"

        supplier.supplier_name = supplier_name
        supplier.supplier_type = supplier_type
        supplier.supplier_group = "All Supplier Groups"

        # Store relation ID
        supplier.eboekhouden_relation_code = str(relation_details["id"])

        # Add tax ID
        if relation_details.get("btwNummer"):
            supplier.tax_id = relation_details["btwNummer"]

        supplier.insert()
        debug_info.append(f"Created supplier from relation data: {supplier.name} ({supplier_name})")

        # Create contact and address
        if relation_details.get("email") or relation_details.get("telefoon"):
            self.create_contact(supplier, relation_details, debug_info)

        if any(
            [relation_details.get("adres"), relation_details.get("postcode"), relation_details.get("plaats")]
        ):
            self.add_supplier_address(supplier, relation_details, debug_info)

        return supplier.name

    def create_provisional_customer(self, relation_id, debug_info=None):
        """Create provisional customer for later enrichment"""
        if debug_info is None:
            debug_info = []

        customer_name = f"E-Boekhouden Customer {relation_id}"

        # Check if already exists
        if frappe.db.exists("Customer", {"customer_name": customer_name}):
            existing_name = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
            debug_info.append(f"Provisional customer already exists: {existing_name}")
            return existing_name

        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"
        customer.eboekhouden_relation_code = str(relation_id)

        # Mark for enrichment (basic tracking)

        customer.insert()

        debug_info.append(f"Created provisional customer: {customer.name}")

        # Note: Enrichment queue functionality to be implemented later
        debug_info.append(f"Customer {customer.name} marked for future enrichment")

        return customer.name

    def create_provisional_supplier(self, relation_id, debug_info=None):
        """Create provisional supplier for later enrichment"""
        if debug_info is None:
            debug_info = []

        supplier_name = f"E-Boekhouden Supplier {relation_id}"

        # Check if already exists
        if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
            existing_name = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
            debug_info.append(f"Provisional supplier already exists: {existing_name}")
            return existing_name

        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_group = "All Supplier Groups"
        supplier.eboekhouden_relation_code = str(relation_id)

        # Mark for enrichment (basic tracking)

        supplier.insert()

        debug_info.append(f"Created provisional supplier: {supplier.name}")

        # Note: Enrichment queue functionality to be implemented later
        debug_info.append(f"Supplier {supplier.name} marked for future enrichment")

        return supplier.name

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

    def add_customer_address(self, customer, relation_details, debug_info=None):
        """Add address to customer"""
        # This would be implemented to create Address documents
        # For now, just log that we have address data
        if debug_info:
            debug_info.append("Address data available for customer (not implemented yet)")

    def add_supplier_address(self, supplier, relation_details, debug_info=None):
        """Add address to supplier"""
        # This would be implemented to create Address documents
        # For now, just log that we have address data
        if debug_info:
            debug_info.append("Address data available for supplier (not implemented yet)")

    def get_default_customer(self):
        """Get or create default customer"""
        customer_name = "E-Boekhouden Import Customer"
        if not frappe.db.exists("Customer", customer_name):
            customer = frappe.new_doc("Customer")
            customer.customer_name = customer_name
            customer.customer_group = "All Customer Groups"
            customer.territory = "All Territories"
            customer.insert()
        return customer_name

    def get_default_supplier(self):
        """Get or create default supplier"""
        supplier_name = "E-Boekhouden Import Supplier"
        if not frappe.db.exists("Supplier", supplier_name):
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = supplier_name
            supplier.supplier_group = "All Supplier Groups"
            supplier.insert()
        return supplier_name

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

        # Update name if it was provisional
        if "E-Boekhouden" in party.get_title() and relation_details.get("bedrijfsnaam"):
            if doctype == "Customer":
                party.customer_name = relation_details["bedrijfsnaam"]
            else:
                party.supplier_name = relation_details["bedrijfsnaam"]

        # Add contact details
        if relation_details.get("email") and not party.get("email_id"):
            party.email_id = relation_details["email"]

        if relation_details.get("telefoon") and not party.get("mobile_no"):
            party.mobile_no = relation_details["telefoon"]

        if relation_details.get("btwNummer") and not party.get("tax_id"):
            party.tax_id = relation_details["btwNummer"]

        # Mark as enriched (basic tracking)

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
