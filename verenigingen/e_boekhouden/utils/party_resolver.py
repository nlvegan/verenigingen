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
        """
        Resolve relation ID to proper customer using E-Boekhouden as Single Source of Truth.

        ALWAYS fetches fresh API data and updates existing customers if better data is available.
        """
        if debug_info is None:
            debug_info = []

        if not relation_id:
            debug_info.append("No relation ID provided, using default customer")
            return self.get_default_customer()

        # Step 1: ALWAYS try to fetch fresh data from E-Boekhouden API first (SSoT approach)
        relation_details = None
        try:
            relation_details = self.fetch_relation_details(relation_id, debug_info)
        except Exception as e:
            debug_info.append(f"API fetch failed for relation {relation_id}: {str(e)}")

        # Step 2: Check if customer already exists
        existing = frappe.db.get_value(
            "Customer",
            {"eboekhouden_relation_code": str(relation_id)},
            ["name", "customer_name"],
            as_dict=True,
        )

        if existing:
            debug_info.append(f"Found existing customer: {existing['customer_name']} ({existing['name']})")

            # Step 3: Update existing customer with fresh API data if available
            if relation_details:
                updated = self.update_customer_with_fresh_data(existing["name"], relation_details, debug_info)
                if updated:
                    debug_info.append(f"Updated customer {existing['name']} with fresh API data")

            return existing["name"]

        # Step 4: Create new customer from API data if available
        if relation_details:
            return self.create_customer_from_relation(relation_details, debug_info)

        # Step 5: Only create provisional customer if API is completely unavailable
        debug_info.append(f"API unavailable for relation {relation_id}, creating provisional customer")
        return self.create_provisional_customer(relation_id, debug_info)

    def resolve_supplier(self, relation_id, debug_info=None):
        """
        Resolve relation ID to proper supplier using E-Boekhouden as Single Source of Truth.

        ALWAYS fetches fresh API data and updates existing suppliers if better data is available.
        """
        if debug_info is None:
            debug_info = []

        if not relation_id:
            debug_info.append("No relation ID provided, using default supplier")
            return self.get_default_supplier()

        # Step 1: ALWAYS try to fetch fresh data from E-Boekhouden API first (SSoT approach)
        relation_details = None
        try:
            relation_details = self.fetch_relation_details(relation_id, debug_info)
        except Exception as e:
            debug_info.append(f"API fetch failed for relation {relation_id}: {str(e)}")

        # Step 2: Check if supplier already exists
        existing = frappe.db.get_value(
            "Supplier",
            {"eboekhouden_relation_code": str(relation_id)},
            ["name", "supplier_name"],
            as_dict=True,
        )

        if existing:
            debug_info.append(f"Found existing supplier: {existing['supplier_name']} ({existing['name']})")

            # Step 3: Update existing supplier with fresh API data if available
            if relation_details:
                updated = self.update_supplier_with_fresh_data(existing["name"], relation_details, debug_info)
                if updated:
                    debug_info.append(f"Updated supplier {existing['name']} with fresh API data")

            return existing["name"]

        # Step 4: Create new supplier from API data if available
        if relation_details:
            return self.create_supplier_from_relation(relation_details, debug_info)

        # Step 5: Only create provisional supplier if API is completely unavailable
        debug_info.append(f"API unavailable for relation {relation_id}, creating provisional supplier")
        return self.create_provisional_supplier(relation_id, debug_info)

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
                # Check REST API fields and legacy Dutch (SOAP) field names
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

    def create_customer_from_relation(self, relation_details, debug_info=None):
        """Create customer with proper details from relation data"""
        if debug_info is None:
            debug_info = []

        customer = frappe.new_doc("Customer")

        # Determine customer name from E-Boekhouden REST API
        # According to swagger spec, relations have a "name" field and "type" field (B=Business, P=Personal)
        relation_name = relation_details.get("name")
        relation_type = relation_details.get("type", "P")  # Default to Personal if not specified

        if relation_name:
            customer_name = relation_name
            customer_type = "Company" if relation_type == "B" else "Individual"
        else:
            # Fallback to legacy Dutch field names for backwards compatibility
            company_name = relation_details.get("bedrijfsnaam") or relation_details.get("companyName")
            first_name = relation_details.get("voornaam") or relation_details.get("firstName")
            last_name = relation_details.get("achternaam") or relation_details.get("lastName")

            if company_name:
                customer_name = company_name
                customer_type = "Company"
            else:
                customer_name = f"{first_name or ''} {last_name or ''}".strip()
                customer_type = "Individual"

        if not customer_name or customer_name.isspace():
            # Try to extract name from description if available
            if debug_info and len(debug_info) > 0:
                # Look for description in debug info
                from .eboekhouden_payment_naming import get_meaningful_description

                for info in debug_info:
                    if "description" in info.lower():
                        try:
                            meaningful_desc = get_meaningful_description({"description": info})
                            if meaningful_desc and len(meaningful_desc) > 5:
                                customer_name = f"{meaningful_desc[:40]} (eBoekhouden Import)"
                                debug_info.append(f"Using description-based name: {customer_name}")
                                break
                        except ImportError as e:
                            frappe.log_error(
                                message=f"Failed to import get_meaningful_description function: {str(e)}",
                                title="Party Resolver - Import Error",
                                reference_doctype="Customer",
                                reference_name=relation_details.get("id", "Unknown"),
                            )
                            pass
                        except Exception as e:
                            frappe.log_error(
                                message=f"Failed to get meaningful description from debug info '{info}': {str(e)}",
                                title="Party Resolver - Description Processing Error",
                                reference_doctype="Customer",
                                reference_name=relation_details.get("id", "Unknown"),
                            )
                            pass

            # Final fallback
            if not customer_name or customer_name.isspace():
                customer_name = f"E-Boekhouden Relation {relation_details['id']}"

        customer.customer_name = customer_name
        customer.customer_type = customer_type
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"

        # Force the document name to use the customer name instead of auto-generated ID
        # This prevents "E-Boekhouden Relation 123" showing in UI
        customer.name = customer_name[:140]  # ERPNext name field limit

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

        # Determine supplier name from E-Boekhouden REST API
        # According to swagger spec, relations have a "name" field and "type" field (B=Business, P=Personal)
        relation_name = relation_details.get("name")
        relation_type = relation_details.get("type", "P")  # Default to Personal if not specified

        if relation_name:
            supplier_name = relation_name
            supplier_type = "Company" if relation_type == "B" else "Individual"
        else:
            # Fallback to legacy Dutch field names for backwards compatibility
            company_name = relation_details.get("bedrijfsnaam") or relation_details.get("companyName")
            first_name = relation_details.get("voornaam") or relation_details.get("firstName")
            last_name = relation_details.get("achternaam") or relation_details.get("lastName")

            if company_name:
                supplier_name = company_name
                supplier_type = "Company"
            else:
                supplier_name = f"{first_name or ''} {last_name or ''}".strip()
                supplier_type = "Individual"

        if not supplier_name or supplier_name.isspace():
            # Try to extract name from description if available
            if debug_info and len(debug_info) > 0:
                # Look for description in debug info
                from .eboekhouden_payment_naming import get_meaningful_description

                for info in debug_info:
                    if "description" in info.lower():
                        try:
                            meaningful_desc = get_meaningful_description({"description": info})
                            if meaningful_desc and len(meaningful_desc) > 5:
                                supplier_name = f"{meaningful_desc[:40]} (eBoekhouden Import)"
                                debug_info.append(f"Using description-based name: {supplier_name}")
                                break
                        except ImportError as e:
                            frappe.log_error(
                                message=f"Failed to import get_meaningful_description function for supplier: {str(e)}",
                                title="Party Resolver - Import Error (Supplier)",
                                reference_doctype="Supplier",
                                reference_name=relation_details.get("id", "Unknown"),
                            )
                            pass
                        except Exception as e:
                            frappe.log_error(
                                message=f"Failed to get meaningful description from debug info '{info}' for supplier: {str(e)}",
                                title="Party Resolver - Description Processing Error (Supplier)",
                                reference_doctype="Supplier",
                                reference_name=relation_details.get("id", "Unknown"),
                            )
                            pass

            # Final fallback - try to extract meaningful name from any available data
            if not supplier_name or supplier_name.isspace():
                # Try to extract from any other fields that might contain a name
                fallback_name = None

                # Check for any field containing name-like data
                name_fields = ["companyName", "company", "bedrijf", "naam", "contactName", "contact"]
                for field in name_fields:
                    if relation_details.get(field):
                        fallback_name = relation_details[field]
                        break

                # If still no name, check address fields for business names
                if not fallback_name:
                    address_fields = ["street", "straat", "address"]
                    for field in address_fields:
                        addr = relation_details.get(field)
                        if addr and len(addr) > 3 and not addr.isdigit():
                            # Extract potential business name from address (before street number)
                            import re

                            name_match = re.match(r"^([A-Za-z\s&.-]+)", addr)
                            if name_match:
                                potential_name = name_match.group(1).strip()
                                if len(potential_name) > 3:
                                    fallback_name = f"{potential_name} (eBoekhouden)"
                                    break

                if fallback_name:
                    supplier_name = fallback_name[:50]  # Limit length
                    debug_info.append(f"Using extracted fallback name: {supplier_name}")
                else:
                    # Last resort: include relation ID but make it more descriptive
                    supplier_name = f"Supplier {relation_details['id']} (eBoekhouden)"
                    debug_info.append(f"Using final fallback name: {supplier_name}")

        supplier.supplier_name = supplier_name
        supplier.supplier_type = supplier_type
        supplier.supplier_group = "All Supplier Groups"

        # Force the document name to use the supplier name instead of auto-generated ID
        # This prevents "E-Boekhouden Relation 123" showing in UI
        supplier.name = supplier_name[:140]  # ERPNext name field limit

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

    def update_customer_with_fresh_data(self, customer_name, relation_details, debug_info=None):
        """
        Update existing customer with fresh API data from E-Boekhouden.

        Returns True if customer was updated with better data, False otherwise.
        """
        if debug_info is None:
            debug_info = []

        try:
            customer = frappe.get_doc("Customer", customer_name)

            # Determine if we have better name data from API
            relation_name = relation_details.get("name")
            relation_type = relation_details.get("type", "P")

            current_name = customer.customer_name
            better_name = None

            if relation_name and relation_name.strip():
                better_name = relation_name.strip()
                customer_type = "Company" if relation_type == "B" else "Individual"
            else:
                # Try legacy field names
                company_name = relation_details.get("bedrijfsnaam") or relation_details.get("companyName")
                first_name = relation_details.get("voornaam") or relation_details.get("firstName")
                last_name = relation_details.get("achternaam") or relation_details.get("lastName")

                if company_name and company_name.strip():
                    better_name = company_name.strip()
                    customer_type = "Company"
                elif first_name or last_name:
                    better_name = f"{first_name or ''} {last_name or ''}".strip()
                    customer_type = "Individual"

            # Only update if we have significantly better data
            if better_name and not current_name.startswith("E-Boekhouden"):
                # Current name is already good, don't update
                debug_info.append(f"Customer {customer_name} already has good name: {current_name}")
                return False
            elif better_name and better_name != current_name:
                # Update with better name
                customer.customer_name = better_name
                customer.customer_type = customer_type

                # Update other fields if available
                if relation_details.get("email") and not customer.get("email_id"):
                    customer.email_id = relation_details["email"]

                customer.save()
                debug_info.append(f"Updated customer name: '{current_name}' → '{better_name}'")
                return True

            return False

        except Exception as e:
            debug_info.append(f"Failed to update customer {customer_name}: {str(e)}")
            return False

    def update_supplier_with_fresh_data(self, supplier_name, relation_details, debug_info=None):
        """
        Update existing supplier with fresh API data from E-Boekhouden.

        Returns True if supplier was updated with better data, False otherwise.
        """
        if debug_info is None:
            debug_info = []

        try:
            supplier = frappe.get_doc("Supplier", supplier_name)

            # Determine if we have better name data from API
            relation_name = relation_details.get("name")
            relation_type = relation_details.get("type", "P")

            current_name = supplier.supplier_name
            better_name = None

            if relation_name and relation_name.strip():
                better_name = relation_name.strip()
                supplier_type = "Company" if relation_type == "B" else "Individual"
            else:
                # Try legacy field names
                company_name = relation_details.get("bedrijfsnaam") or relation_details.get("companyName")
                first_name = relation_details.get("voornaam") or relation_details.get("firstName")
                last_name = relation_details.get("achternaam") or relation_details.get("lastName")

                if company_name and company_name.strip():
                    better_name = company_name.strip()
                    supplier_type = "Company"
                elif first_name or last_name:
                    better_name = f"{first_name or ''} {last_name or ''}".strip()
                    supplier_type = "Individual"

            # Only update if we have significantly better data
            if better_name and not current_name.startswith("E-Boekhouden"):
                # Current name is already good, don't update
                debug_info.append(f"Supplier {supplier_name} already has good name: {current_name}")
                return False
            elif better_name and better_name != current_name:
                # Update with better name
                supplier.supplier_name = better_name
                supplier.supplier_type = supplier_type

                # Update tax ID if available
                if relation_details.get("btwNummer") and not supplier.get("tax_id"):
                    supplier.tax_id = relation_details["btwNummer"]

                supplier.save()
                debug_info.append(f"Updated supplier name: '{current_name}' → '{better_name}'")
                return True

            return False

        except Exception as e:
            debug_info.append(f"Failed to update supplier {supplier_name}: {str(e)}")
            return False

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

        supplier_name = f"Supplier {relation_id} (eBoekhouden)"

        # Check if already exists
        if frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
            existing_name = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
            debug_info.append(f"Provisional supplier already exists: {existing_name}")
            return existing_name

        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_group = "All Supplier Groups"
        supplier.eboekhouden_relation_code = str(relation_id)

        # Use supplier name as document name to avoid generic IDs
        supplier.name = supplier_name[:140]

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
        """
        REMOVED: Generic customer creation disabled to prevent data corruption.

        All customers must be properly resolved from E-Boekhouden API.
        If this function is called, it indicates an API failure or missing relation data.
        """
        error_msg = (
            "CUSTOMER RESOLUTION FAILED: No customer could be resolved from E-Boekhouden API. "
            "This indicates either an API connectivity issue or missing relation data. "
            "Generic customer creation has been disabled to prevent data corruption. "
            "Please check API connectivity and ensure all relation IDs exist in E-Boekhouden."
        )

        frappe.logger().error(f"PARTY RESOLUTION FAILURE: {error_msg}")
        frappe.throw(error_msg, title="Customer Resolution Required", exc=frappe.ValidationError)

    def get_default_supplier(self):
        """
        REMOVED: Generic supplier creation disabled to prevent data corruption.

        All suppliers must be properly resolved from E-Boekhouden API.
        If this function is called, it indicates an API failure or missing relation data.
        """
        error_msg = (
            "SUPPLIER RESOLUTION FAILED: No supplier could be resolved from E-Boekhouden API. "
            "This indicates either an API connectivity issue or missing relation data. "
            "Generic supplier creation has been disabled to prevent data corruption. "
            "Please check API connectivity and ensure all relation IDs exist in E-Boekhouden."
        )

        frappe.logger().error(f"PARTY RESOLUTION FAILURE: {error_msg}")
        frappe.throw(error_msg, title="Supplier Resolution Required", exc=frappe.ValidationError)

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
