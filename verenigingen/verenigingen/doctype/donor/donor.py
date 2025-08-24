# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import cstr, validate_email_address
from frappe.utils.password import decrypt, encrypt


class Donor(Document):
    def onload(self):
        """Load address and contacts in `__onload`"""
        load_address_and_contact(self)

        # Decrypt BSN/RSIN for authorized users only
        if self.has_permlevel_access():
            self.decrypt_sensitive_fields()

    def validate(self):
        if self.donor_email:
            validate_email_address(self.donor_email.strip(), True)

        # Validate BSN/RSIN format before encryption
        self.validate_tax_identifiers()

        # Set ANBI consent date if consent is given
        if self.anbi_consent and not self.anbi_consent_date:
            self.anbi_consent_date = frappe.utils.now()

        # NOTE: Customer sync handled by document event handlers in hooks.py

    def before_save(self):
        """Encrypt sensitive fields before saving"""
        self.encrypt_sensitive_fields()

    def has_permlevel_access(self):
        """Check if user has permlevel 1 access to this doctype"""
        # Check if user has read permission on the document first
        if not frappe.has_permission(self.doctype, ptype="read"):
            return False

        # Check if user has permlevel 1 access by checking user permissions
        # This is a simplified check - in production you might want more sophisticated logic
        user_roles = frappe.get_roles(frappe.session.user)

        # System Manager and Administrator roles typically have all permissions
        if "System Manager" in user_roles or "Administrator" in user_roles:
            return True

        # Check if user has specific roles that should have permlevel access
        # You can customize this based on your role structure
        privileged_roles = ["Verenigingen Administrator", "Donor Administrator", "Finance Manager"]
        return any(role in user_roles for role in privileged_roles)

    def validate_tax_identifiers(self):
        """Validate BSN and RSIN format"""
        # BSN validation (9 digits)
        if self.bsn_citizen_service_number:
            bsn = re.sub(r"\D", "", self.bsn_citizen_service_number)  # Remove non-digits
            if len(bsn) != 9:
                frappe.throw(_("BSN must be exactly 9 digits"))

            # BSN eleven-proof validation
            if not self.validate_bsn_eleven_proof(bsn):
                frappe.throw(_("Invalid BSN number (failed eleven-proof validation)"))

            # Store cleaned BSN
            self.bsn_citizen_service_number = bsn

        # RSIN validation (8 or 9 digits)
        if self.rsin_organization_tax_number:
            rsin = re.sub(r"\D", "", self.rsin_organization_tax_number)  # Remove non-digits
            if len(rsin) not in [8, 9]:
                frappe.throw(_("RSIN must be 8 or 9 digits"))

            # Store cleaned RSIN
            self.rsin_organization_tax_number = rsin

    def validate_bsn_eleven_proof(self, bsn):
        """Validate BSN using eleven-proof algorithm"""
        if len(bsn) != 9:
            return False

        try:
            # Convert to list of integers
            digits = [int(d) for d in bsn]

            # Apply eleven-proof algorithm
            # (9×A + 8×B + 7×C + 6×D + 5×E + 4×F + 3×G + 2×H + -1×I) must be divisible by 11
            weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
            total = sum(digit * weight for digit, weight in zip(digits, weights))

            return total % 11 == 0
        except (ValueError, TypeError) as e:
            frappe.log_error(f"BSN eleven-proof validation failed for {bsn}: {e}", "DonorValidation")
            return False

    def encrypt_sensitive_fields(self):
        """Encrypt BSN and RSIN fields before saving"""
        # Check if fields need encryption (not already encrypted)
        if self.bsn_citizen_service_number and not self.is_encrypted(self.bsn_citizen_service_number):
            self.bsn_citizen_service_number = self.encrypt_field(self.bsn_citizen_service_number)

        if self.rsin_organization_tax_number and not self.is_encrypted(self.rsin_organization_tax_number):
            self.rsin_organization_tax_number = self.encrypt_field(self.rsin_organization_tax_number)

    def decrypt_sensitive_fields(self):
        """Decrypt BSN and RSIN fields for authorized users"""
        try:
            if self.bsn_citizen_service_number and self.is_encrypted(self.bsn_citizen_service_number):
                decrypted_bsn = self.decrypt_field(self.bsn_citizen_service_number)
                # Mask for display (show only last 4 digits)
                self.bsn_citizen_service_number = self.mask_identifier(decrypted_bsn)

            if self.rsin_organization_tax_number and self.is_encrypted(self.rsin_organization_tax_number):
                decrypted_rsin = self.decrypt_field(self.rsin_organization_tax_number)
                # Mask for display (show only last 4 digits)
                self.rsin_organization_tax_number = self.mask_identifier(decrypted_rsin)
        except Exception as e:
            frappe.log_error(f"Failed to decrypt donor fields: {str(e)}", "Donor Decryption Error")

    def encrypt_field(self, value):
        """Encrypt a field value"""
        if not value:
            return value

        # Add prefix to indicate encryption
        return f"ENC:{encrypt(cstr(value))}"

    def decrypt_field(self, value):
        """Decrypt a field value"""
        if not value or not value.startswith("ENC:"):
            return value

        try:
            # Remove prefix and decrypt
            encrypted_value = value[4:]  # Remove "ENC:" prefix
            return decrypt(encrypted_value)
        except Exception:
            return value

    def is_encrypted(self, value):
        """Check if a value is encrypted"""
        return value and value.startswith("ENC:")

    def mask_identifier(self, identifier):
        """Mask identifier for display, showing only last 4 digits"""
        if not identifier or len(identifier) < 4:
            return identifier

        return "*" * (len(identifier) - 4) + identifier[-4:]

    def get_decrypted_bsn(self):
        """Get decrypted BSN for authorized users (for ANBI reporting)"""
        if not self.has_permlevel_access():
            frappe.throw(_("Insufficient permissions to access BSN"))

        if self.bsn_citizen_service_number and self.is_encrypted(self.bsn_citizen_service_number):
            return self.decrypt_field(self.bsn_citizen_service_number)

        return self.bsn_citizen_service_number

    def get_decrypted_rsin(self):
        """Get decrypted RSIN for authorized users (for ANBI reporting)"""
        if not self.has_permlevel_access():
            frappe.throw(_("Insufficient permissions to access RSIN"))

        if self.rsin_organization_tax_number and self.is_encrypted(self.rsin_organization_tax_number):
            return self.decrypt_field(self.rsin_organization_tax_number)

        return self.rsin_organization_tax_number

    # ========== Customer Integration Methods ==========

    def sync_with_customer(self):
        """Create or sync with corresponding Customer record"""
        # Skip sync if explicitly disabled (to prevent loops)
        if self.flags.ignore_customer_sync:
            return

        # During tests, only sync if explicitly enabled
        if frappe.flags.get("in_test") and not self.flags.get("enable_customer_sync_in_test"):
            return

        try:
            # Find existing customer by donor reference or create new one
            customer_name = self.get_or_create_customer()

            if customer_name and customer_name != self.customer:
                # Update donor's customer link
                self.customer = customer_name

                # Sync data to customer (without triggering validation loop)
                self.sync_data_to_customer(customer_name)

                # Update sync status
                self.customer_sync_status = "Synced"
                self.last_customer_sync = frappe.utils.now()

                # Save the donor with the updated customer link
                # Use db update to avoid triggering hooks again
                frappe.db.set_value(
                    "Donor",
                    self.name,
                    {
                        "customer": self.customer,
                        "customer_sync_status": self.customer_sync_status,
                        "last_customer_sync": self.last_customer_sync,
                    },
                )

        except Exception as e:
            # Update sync status on error
            self.customer_sync_status = "Error"
            frappe.db.set_value("Donor", self.name, "customer_sync_status", "Error")
            frappe.log_error(
                f"Error syncing donor {self.name} with customer: {str(e)}", "Donor-Customer Sync Error"
            )

    def get_or_create_customer(self):
        """Get existing customer or create new one"""
        # First, check if we already have a customer linked
        if self.customer and frappe.db.exists("Customer", self.customer):
            return self.customer

        # Look for customer with donor reference
        existing_customer = frappe.db.get_value("Customer", {"donor": self.name}, "name")

        if existing_customer:
            return existing_customer

        # Look for customer with matching email
        if self.donor_email:
            email_customer = frappe.db.get_value("Customer", {"email_id": self.donor_email}, "name")

            if email_customer:
                # Link existing customer to this donor
                frappe.db.set_value("Customer", email_customer, "donor", self.name)
                return email_customer

        # Create new customer
        return self.create_customer_from_donor()

    def create_customer_from_donor(self):
        """Create new Customer record from Donor data"""
        try:
            # Ensure required customer group exists
            self.ensure_donor_customer_group()

            customer = frappe.new_doc("Customer")
            customer.customer_name = self.donor_name
            customer.customer_type = "Company" if self.donor_type == "Organization" else "Individual"

            # Set territory (default or from settings)
            customer.territory = (
                frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
            )

            # Get donor customer group from configuration
            donor_group = self._get_donor_customer_group()
            customer.customer_group = donor_group

            # Copy contact information
            if self.donor_email:
                customer.email_id = self.donor_email
            if hasattr(self, "phone") and self.phone:
                customer.mobile_no = self.phone

            # Link back to donor
            customer.donor = self.name

            # Set flags to prevent validation loops
            customer.flags.ignore_mandatory = True
            customer.flags.ignore_permissions = True
            customer.flags.from_donor_sync = True

            customer.insert()

            frappe.logger().info(f"Created customer {customer.name} for donor {self.name}")
            return customer.name

        except Exception as e:
            frappe.log_error(
                f"Error creating customer for donor {self.name}: {str(e)}", "Donor Customer Creation Error"
            )
            return None

    def sync_data_to_customer(self, customer_name):
        """Sync donor data to customer record"""
        if not customer_name:
            return

        try:
            customer_doc = frappe.get_doc("Customer", customer_name)

            # Track if any changes were made
            changes_made = False

            # Sync basic information
            if customer_doc.customer_name != self.donor_name:
                customer_doc.customer_name = self.donor_name
                changes_made = True

            if self.donor_email and customer_doc.email_id != self.donor_email:
                customer_doc.email_id = self.donor_email
                changes_made = True

            if hasattr(self, "phone") and self.phone and customer_doc.mobile_no != self.phone:
                customer_doc.mobile_no = self.phone
                changes_made = True

            # Sync customer type
            expected_type = "Company" if self.donor_type == "Organization" else "Individual"
            if customer_doc.customer_type != expected_type:
                customer_doc.customer_type = expected_type
                changes_made = True

            # Ensure donor reference is set
            if customer_doc.donor != self.name:
                customer_doc.donor = self.name
                changes_made = True

            # Save if changes were made
            if changes_made:
                customer_doc.flags.ignore_mandatory = True
                customer_doc.flags.ignore_permissions = True
                customer_doc.flags.from_donor_sync = True
                customer_doc.save()

                frappe.logger().info(f"Synced donor {self.name} data to customer {customer_name}")

        except Exception as e:
            frappe.log_error(
                f"Error syncing data from donor {self.name} to customer {customer_name}: {str(e)}",
                "Donor-Customer Data Sync Error",
            )

    def _get_donor_customer_group(self):
        """Get donor customer group from configuration"""
        # Check Verenigingen Settings for donor customer group configuration
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "donor_customer_group") and settings.donor_customer_group:
                if frappe.db.exists("Customer Group", settings.donor_customer_group):
                    return settings.donor_customer_group
                else:
                    frappe.log_error(
                        f"Configured donor customer group '{settings.donor_customer_group}' does not exist",
                        "Donor Customer Group Configuration Error",
                    )
        except Exception:
            pass

        # Check if "Donors" group exists (legacy default)
        if frappe.db.exists("Customer Group", "Donors"):
            return "Donors"

        # Get selling settings default
        default_group = frappe.db.get_single_value("Selling Settings", "customer_group")
        if default_group and frappe.db.exists("Customer Group", default_group):
            return default_group

        # Final fallback with validation
        if frappe.db.exists("Customer Group", "All Customer Groups"):
            return "All Customer Groups"

        frappe.throw(
            "No suitable customer group found for donors. Please either:\n"
            "1. Configure 'donor_customer_group' in Verenigingen Settings\n"
            "2. Create a 'Donors' customer group\n"
            "3. Configure default customer group in Selling Settings\n"
            "4. Ensure 'All Customer Groups' exists"
        )

    def ensure_donor_customer_group(self):
        """Ensure 'Donors' customer group exists"""
        if not frappe.db.exists("Customer Group", "Donors"):
            donor_group = frappe.new_doc("Customer Group")
            donor_group.customer_group_name = "Donors"
            donor_group.parent_customer_group = "All Customer Groups"
            donor_group.is_group = 0
            donor_group.flags.ignore_permissions = True
            donor_group.insert()

    def get_customer_info(self):
        """Get related customer information for display"""
        if not self.customer:
            return {}

        try:
            customer_data = frappe.db.get_value(
                "Customer",
                self.customer,
                [
                    "name",
                    "customer_name",
                    "customer_type",
                    "territory",
                    "customer_group",
                    "email_id",
                    "mobile_no",
                ],
                as_dict=True,
            )

            if customer_data:
                # Get customer's total outstanding
                outstanding = frappe.db.sql(
                    """
                    SELECT COALESCE(SUM(outstanding_amount), 0) as outstanding
                    FROM `tabSales Invoice`
                    WHERE customer = %s AND docstatus = 1
                """,
                    (self.customer,),
                )[0][0]

                customer_data["outstanding_amount"] = outstanding

            return customer_data or {}

        except Exception as e:
            frappe.log_error(f"Error getting customer info for donor {self.name}: {str(e)}")
            return {}

    @frappe.whitelist()
    def refresh_customer_sync(self):
        """Manual refresh of customer synchronization"""
        self.flags.ignore_customer_sync = False
        self.sync_with_customer()
        # Reload document to get updated values from database
        self.reload()
        return {"message": "Customer synchronization refreshed successfully"}
