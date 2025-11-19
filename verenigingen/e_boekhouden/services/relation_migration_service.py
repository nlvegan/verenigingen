"""
E-Boekhouden Relation Migration Service
========================================

Centralized service for migrating eBoekhouden relations (customers/suppliers) to ERPNext.
Handles data transformation, party creation, and related contact/address management.

Primary Purpose:
    Transforms eBoekhouden relation data (both SOAP and REST API formats) into ERPNext
    Customer and Supplier records with proper classification, contacts, and addresses.

Key Features:
    * Unified party creation logic (eliminates customer/supplier duplication)
    * SOAP and REST API format compatibility
    * Company/Individual classification based on multiple heuristics
    * Territory determination with intelligent defaults
    * Contact and address creation with proper linking
    * VAT number handling for suppliers
    * Relation code preservation for ongoing sync operations

Business Value:
    Ensures accurate party data migration from eBoekhouden to ERPNext with proper
    classification and complete contact information, enabling seamless transaction
    processing and ongoing synchronization.

Architecture:
    Service-based extraction from EBoekhoudenMigration DocType controller to:
    * Reduce DocType complexity (~360 lines extracted)
    * Enable isolated testing of party creation logic
    * Support reuse for sync operations beyond initial migration
    * Eliminate duplication between customer and supplier creation

API Format Compatibility:
    SOAP Format: {ID, Bedrijf, Contactpersoon, Email, BP, Geslacht, BTWNummer, Adres, Plaats, Postcode}
    REST Format: {id, name, companyName, contactName, email, vatNumber, address, city, postalCode}
"""

import frappe

from verenigingen.e_boekhouden.utils.security_helper import validate_and_insert


class RelationMigrationService:
    """Service for migrating eBoekhouden relations to ERPNext parties."""

    def __init__(self, migration_doc=None, settings=None):
        """
        Initialize relation migration service.

        Args:
            migration_doc: Optional EBoekhoudenMigration document for logging and context
            settings: Optional E-Boekhouden Settings document (will be loaded if not provided)
        """
        self.migration_doc = migration_doc
        self._settings = settings

    @property
    def settings(self):
        """Lazy-load E-Boekhouden Settings."""
        if not self._settings:
            self._settings = frappe.get_single("E-Boekhouden Settings")
        return self._settings

    def create_customer(self, customer_data):
        """
        Create Customer in ERPNext with SOAP/REST API compatibility.

        Args:
            customer_data (dict): Customer data from eBoekhouden API
                SOAP format: {ID, Bedrijf, Contactpersoon, Email, BP, Geslacht, ...}
                REST format: {id, name, companyName, contactName, email, ...}

        Returns:
            bool: True if customer was created, False if skipped or failed
        """
        try:
            # Extract fields from either API format
            customer_id = customer_data.get("ID") or customer_data.get("id", "")
            company_name = (
                customer_data.get("Bedrijf", "").strip() or customer_data.get("companyName", "").strip()
            )
            contact_name = (
                customer_data.get("Contactpersoon", "").strip()
                or customer_data.get("contactName", "").strip()
            )
            email = customer_data.get("Email", "").strip() or customer_data.get("email", "").strip()
            name = customer_data.get("name", "").strip()

            # SOAP-specific fields for better classification
            bp_type = customer_data.get("BP", "")  # P=Person, B=Business

            # Determine display name and customer type
            display_name = company_name or contact_name or name

            # Determine if this is a company or individual
            is_company = self._determine_party_type(
                bp_type=bp_type,
                company_name=company_name,
                contact_name=contact_name,
                vat_number=None,  # Customers typically don't have VAT in eBoekhouden
            )

            # If we have meaningful display name, create the customer
            if display_name:
                return self._create_party(
                    party_type="Customer",
                    party_data=customer_data,
                    display_name=display_name,
                    is_company=is_company,
                    relation_id=customer_id,
                    email=email,
                    contact_name=contact_name,
                    vat_number=None,
                )

            # If we only have ID (common case with REST API), skip creation during Chart of Accounts import
            if customer_id and not display_name:
                frappe.logger().info(
                    f"Skipping customer {customer_id} during Chart of Accounts import - "
                    "no meaningful name data. Will be created during transaction import."
                )
                return False

            # If we have no usable data at all, log and skip
            frappe.logger().warning(f"Customer data has no usable information: {customer_data}")
            return False

        except Exception as e:
            frappe.logger().warning(f"Error in customer creation: {str(e)}")
            self._log_error(f"Error in customer creation: {str(e)}", "Customer", customer_data)
            return False

    def create_supplier(self, supplier_data):
        """
        Create Supplier in ERPNext with SOAP/REST API compatibility.

        Args:
            supplier_data (dict): Supplier data from eBoekhouden API
                SOAP format: {ID, Bedrijf, Contactpersoon, Email, BP, Geslacht, BTWNummer, ...}
                REST format: {id, name, companyName, contactName, email, vatNumber, ...}

        Returns:
            bool: True if supplier was created, False if skipped or failed
        """
        try:
            # Extract fields from either API format
            supplier_id = supplier_data.get("ID") or supplier_data.get("id", "")
            company_name = (
                supplier_data.get("Bedrijf", "").strip() or supplier_data.get("companyName", "").strip()
            )
            contact_name = (
                supplier_data.get("Contactpersoon", "").strip()
                or supplier_data.get("contactName", "").strip()
            )
            email = supplier_data.get("Email", "").strip() or supplier_data.get("email", "").strip()
            name = supplier_data.get("name", "").strip()

            # SOAP-specific fields for better classification
            bp_type = supplier_data.get("BP", "")  # P=Person, B=Business
            vat_number = (
                supplier_data.get("BTWNummer", "").strip() or supplier_data.get("vatNumber", "").strip()
            )

            # Determine display name
            display_name = company_name or contact_name or name

            # Determine if this is a company or individual
            is_company = self._determine_party_type(
                bp_type=bp_type,
                company_name=company_name,
                contact_name=contact_name,
                vat_number=vat_number,
            )

            # If we have meaningful display name, create the supplier
            if display_name:
                return self._create_party(
                    party_type="Supplier",
                    party_data=supplier_data,
                    display_name=display_name,
                    is_company=is_company,
                    relation_id=supplier_id,
                    email=email,
                    contact_name=contact_name,
                    vat_number=vat_number,
                )

            # If we only have ID (common case with REST API), skip creation during Chart of Accounts import
            if supplier_id and not display_name:
                frappe.logger().info(
                    f"Skipping supplier {supplier_id} during Chart of Accounts import - "
                    "no meaningful name data. Will be created during transaction import."
                )
                return False

            # If we have no usable data at all, log and skip
            frappe.logger().warning(f"Supplier data has no usable information: {supplier_data}")
            return False

        except Exception as e:
            frappe.logger().warning(f"Error in supplier creation: {str(e)}")
            self._log_error(f"Error in supplier creation: {str(e)}", "Supplier", supplier_data)
            return False

    def _determine_party_type(self, bp_type, company_name, contact_name, vat_number):
        """
        Determine if party should be classified as Company or Individual.

        Uses multiple heuristics based on available data:
        1. SOAP BP field (most reliable when available)
        2. Presence of company name without contact name
        3. Presence of contact name without company name
        4. Presence of VAT number (suppliers)

        Args:
            bp_type (str): SOAP business partner type (B=Business, P=Person)
            company_name (str): Company name if available
            contact_name (str): Contact person name if available
            vat_number (str): VAT number if available (suppliers only)

        Returns:
            bool: True if should be classified as Company, False for Individual
        """
        # Priority 1: SOAP BP type (most reliable)
        if bp_type == "B":  # Business type in SOAP
            return True
        elif bp_type == "P":  # Person type in SOAP
            return False

        # Priority 2: Name pattern analysis
        if company_name and not contact_name:  # REST API: only company name
            return True
        elif contact_name and not company_name:  # REST API: only contact name
            return False

        # Priority 3: VAT number presence (suppliers)
        if vat_number:  # Has VAT number, likely a business
            return True

        # Default: if we have company name, assume company
        return bool(company_name)

    def _create_party(
        self,
        party_type,
        party_data,
        display_name,
        is_company,
        relation_id,
        email,
        contact_name,
        vat_number=None,
    ):
        """
        Unified party creation logic for both customers and suppliers.

        This method eliminates the duplication between customer and supplier creation
        by providing a single, well-tested implementation for both party types.

        Args:
            party_type (str): "Customer" or "Supplier"
            party_data (dict): Raw relation data from eBoekhouden API
            display_name (str): Display name for the party
            is_company (bool): Whether party should be classified as Company
            relation_id (str): eBoekhouden relation ID for future sync
            email (str): Email address if available
            contact_name (str): Contact person name if available
            vat_number (str): VAT number if available (suppliers only)

        Returns:
            bool: True if party was created, False if skipped or failed
        """
        try:
            # Check if party already exists
            name_field = f"{party_type.lower()}_name"
            if frappe.db.exists(party_type, {name_field: display_name}):
                frappe.logger().info(f"{party_type} '{display_name}' already exists, skipping")
                return False

            # Get currency for party
            currency = self._get_migration_currency()

            # Build party document
            party_doc_data = {
                "doctype": party_type,
                name_field: display_name,
                f"{party_type.lower()}_type": "Company" if is_company else "Individual",
                f"{party_type.lower()}_group": f"All {party_type} Groups",
                "default_currency": currency,
                "disabled": 0,
            }

            # Add territory for customers
            if party_type == "Customer":
                territory = self._get_proper_territory(party_data)
                party_doc_data["territory"] = territory

            party = frappe.get_doc(party_doc_data)

            # Save relation ID for future updates (both SOAP and REST formats)
            if relation_id:
                try:
                    party.eboekhouden_relation_code = str(relation_id)
                except Exception as rel_e:
                    frappe.logger().warning(f"Could not save relation ID {relation_id}: {str(rel_e)}")

            # Add VAT number if available (suppliers)
            if party_type == "Supplier" and vat_number:
                party.tax_id = vat_number

            validate_and_insert(party)

            # Create contact if contact details are available
            if contact_name or email:
                self._create_contact(party_type, party.name, party_data)

            # Create address if address details are available
            address_fields = ["Adres", "Plaats", "Postcode", "address", "city", "postalCode"]
            if any(party_data.get(field) for field in address_fields):
                self._create_address(party_type, party.name, party_data)

            party_type_str = "Company" if is_company else "Individual"
            frappe.logger().info(
                f"Created {party_type_str} {party_type.lower()}: {display_name} (ID: {relation_id})"
            )
            return True

        except Exception as e:
            self._log_error(f"Failed to create {party_type.lower()} {display_name}: {str(e)}")
            return False

    def _create_contact(self, party_type, party_name, party_data):
        """
        Create contact for customer or supplier.

        Args:
            party_type (str): "Customer" or "Supplier"
            party_name (str): Name of the party document
            party_data (dict): Raw relation data from eBoekhouden API
        """
        try:
            # Handle both SOAP and REST formats
            contact_name = (
                party_data.get("Contactpersoon", "").strip() or party_data.get("contactName", "").strip()
            )
            email = party_data.get("Email", "").strip() or party_data.get("email", "").strip()
            phone = party_data.get("Telefoon", "").strip() or party_data.get("phone", "").strip()

            if not contact_name and not email:
                return

            contact = frappe.get_doc(
                {
                    "doctype": "Contact",
                    "first_name": contact_name or email.split("@")[0],
                    "email_ids": [{"email_id": email, "is_primary": 1}] if email else [],
                    "phone_nos": [{"phone": phone, "is_primary_phone": 1}] if phone else [],
                    "links": [{"link_doctype": party_type, "link_name": party_name}],
                }
            )

            validate_and_insert(contact)
            frappe.logger().info(f"Created contact for {party_type.lower()}: {party_name}")

        except Exception as e:
            self._log_error(f"Failed to create contact for {party_type.lower()} {party_name}: {str(e)}")

    def _create_address(self, party_type, party_name, party_data):
        """
        Create address for customer or supplier.

        Args:
            party_type (str): "Customer" or "Supplier"
            party_name (str): Name of the party document
            party_data (dict): Raw relation data from eBoekhouden API
        """
        try:
            # Handle both SOAP and REST formats
            address_line1 = party_data.get("Adres", "").strip() or party_data.get("address", "").strip()
            city = party_data.get("Plaats", "").strip() or party_data.get("city", "").strip()
            postal_code = party_data.get("Postcode", "").strip() or party_data.get("postalCode", "").strip()
            country = (
                party_data.get("Land", "Netherlands").strip()
                or party_data.get("country", "Netherlands").strip()
            )

            if not address_line1 and not city:
                return

            address = frappe.get_doc(
                {
                    "doctype": "Address",
                    "address_title": f"{party_name} Address",
                    "address_line1": address_line1,
                    "city": city,
                    "pincode": postal_code,
                    "country": country,
                    "links": [{"link_doctype": party_type, "link_name": party_name}],
                }
            )

            validate_and_insert(address)
            frappe.logger().info(f"Created address for {party_type.lower()}: {party_name}")

        except Exception as e:
            self._log_error(f"Failed to create address for {party_type.lower()} {party_name}: {str(e)}")

    def _get_proper_territory(self, party_data):
        """
        Get appropriate territory for customer, avoiding 'Rest Of The World'.

        Uses multiple fallback strategies:
        1. Territory matching customer's country
        2. Company's home country territory
        3. Preferred territories (excluding generic ones)
        4. Any available territory

        Args:
            party_data (dict): Raw relation data from eBoekhouden API

        Returns:
            str: Territory name
        """
        try:
            # Try to determine territory from customer data
            country = party_data.get("Land", "").strip() or party_data.get("country", "").strip()
            if country:
                # Check if territory exists for this country
                territory = frappe.db.get_value("Territory", {"territory_name": country}, "name")
                if territory:
                    return territory

            # Get the company's home country territory
            default_country = frappe.db.get_default("country")
            if default_country:
                home_territory = frappe.db.get_value("Territory", {"territory_name": default_country}, "name")
                if home_territory:
                    return home_territory

            # Get territories, preferring specific ones over "Rest Of The World"
            territories = frappe.get_all(
                "Territory",
                filters={"is_group": 0},
                fields=["name", "territory_name"],
                order_by="territory_name",
            )

            # Filter out "Rest Of The World" and similar generic territories
            preferred_territories = [
                t
                for t in territories
                if not any(
                    word in t.territory_name.lower() for word in ["rest", "world", "other", "misc", "unknown"]
                )
            ]

            if preferred_territories:
                return preferred_territories[0].name

            # Fall back to any territory if needed
            return territories[0].name if territories else "All Territories"

        except Exception as e:
            self._log_error(f"Error determining territory: {str(e)}")
            return "All Territories"

    def _get_migration_currency(self):
        """
        Get currency for migration with explicit validation.

        Priority order:
        1. E-Boekhouden Settings default currency
        2. Company default currency (if migration doc available)
        3. EUR fallback with logging

        Returns:
            str: Currency code
        """
        # Check settings default currency
        if hasattr(self.settings, "default_currency") and self.settings.default_currency:
            return self.settings.default_currency

        # Get company default currency
        if self.migration_doc and hasattr(self.migration_doc, "company") and self.migration_doc.company:
            company_currency = frappe.db.get_value("Company", self.migration_doc.company, "default_currency")
            if company_currency:
                return company_currency

        # Final fallback with logging
        migration_name = self.migration_doc.name if self.migration_doc else "unknown"
        frappe.log_error(
            f"No currency configured in E-Boekhouden Settings or Company settings for migration '{migration_name}', using 'EUR' fallback",
            "E-Boekhouden Migration Currency Configuration",
        )
        return "EUR"

    def _log_error(self, message, record_type=None, record_data=None):
        """
        Log error through migration document if available, otherwise use standard logging.

        Args:
            message (str): Error message
            record_type (str): Type of record being processed
            record_data (dict): Raw record data for debugging
        """
        if self.migration_doc and hasattr(self.migration_doc, "log_error"):
            self.migration_doc.log_error(message, record_type, record_data)
        else:
            frappe.log_error(message, f"RelationMigrationService - {record_type or 'Unknown'}")
