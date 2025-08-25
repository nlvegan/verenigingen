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

        # NOTE: Customer sync handled by document event handlers in hooks.py after save

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

    def _calculate_sync_hash(self):
        """Calculate a hash of the syncable donor fields to detect changes"""
        import hashlib

        # Include fields that should trigger customer sync
        sync_data = f"{self.donor_name}|{self.donor_email}|{getattr(self, 'phone', '')}"
        return hashlib.md5(sync_data.encode()).hexdigest()

    def sync_with_customer(self):
        """Create or sync with corresponding Customer record"""
        # Debug logging during tests
        if frappe.flags.get("in_test"):
            print(f"🚀 sync_with_customer called for donor {self.name}")
            print(f"   flags.ignore_customer_sync: {self.flags.get('ignore_customer_sync')}")
            print(f"   in_test: {frappe.flags.get('in_test')}")
            print(f"   flags.enable_customer_sync_in_test: {self.flags.get('enable_customer_sync_in_test')}")

        # Skip sync if explicitly disabled (to prevent loops)
        if self.flags.ignore_customer_sync:
            if frappe.flags.get("in_test"):
                print("❌ Sync skipped: ignore_customer_sync flag is set")
            return

        # Check if donor data has changed since last sync to determine if we need to sync again
        current_sync_hash = self._calculate_sync_hash()
        last_sync_hash = getattr(self, "_last_sync_hash", None)

        if (
            hasattr(self, "_sync_already_done")
            and self._sync_already_done
            and current_sync_hash == last_sync_hash
        ):
            if frappe.flags.get("in_test"):
                print("❌ Sync skipped: already completed in this transaction with same data")
            return

        # Clear sync flag if data has changed
        if current_sync_hash != last_sync_hash:
            if frappe.flags.get("in_test"):
                print("🔄 Data changed, clearing sync deduplication flag")
            self._sync_already_done = False
            self._last_sync_hash = current_sync_hash

        # During tests, only sync if explicitly enabled
        if frappe.flags.get("in_test") and not self.flags.get("enable_customer_sync_in_test"):
            if frappe.flags.get("in_test"):
                print("❌ Sync skipped: enable_customer_sync_in_test flag not set")
            return

        try:
            # Find existing customer by donor reference or create new one
            customer_name = self.get_or_create_customer()

            # Debug logging during tests
            if frappe.flags.get("in_test"):
                print(f"🔄 sync_with_customer called for donor {self.name}, found customer: {customer_name}")

            if customer_name:
                # Update donor's customer link if it changed
                if customer_name != self.customer:
                    self.customer = customer_name
                    if frappe.flags.get("in_test"):
                        print(f"🔗 Donor customer link updated to: {customer_name}")

                # Always sync data to customer to ensure it's up to date
                if frappe.flags.get("in_test"):
                    print(f"📤 Syncing data from donor {self.name} to customer {customer_name}")
                self.sync_data_to_customer(customer_name)

                # Update sync status
                self.customer_sync_status = "Synced"
                self.last_customer_sync = frappe.utils.now()

                # Mark sync as completed to prevent duplicate syncs in same transaction
                self._sync_already_done = True

                # DON'T save here - just update the in-memory object
                # The calling code will handle the save
                # This avoids timestamp mismatch errors

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

            # Set flags to prevent validation loops
            customer.flags.ignore_mandatory = True
            customer.flags.ignore_permissions = True
            customer.flags.from_donor_sync = True

            customer.insert()

            # Now set the donor link after both documents exist
            if self.name:  # Only if donor has been saved
                frappe.db.set_value("Customer", customer.name, "donor", self.name)

            # Create Contact record for email/mobile (Customer fields are read-only)
            contact = self.create_new_customer_contact(customer.name)
            if not contact and frappe.flags.get("in_test"):
                print("⚠️ Warning: Could not create Contact during customer creation")

            frappe.logger().info(f"Created customer {customer.name} for donor {self.name}")
            return customer.name

        except Exception as e:
            # Enhanced error logging for debugging
            import traceback

            error_details = traceback.format_exc()
            frappe.log_error(
                f"Error creating customer for donor {self.name}:\n"
                f"Error: {str(e)}\n"
                f"Full traceback:\n{error_details}",
                "Donor Customer Creation Error",
            )
            # Also print to console during tests for immediate feedback
            if frappe.flags.get("in_test"):
                print(f"❌ Customer creation failed for donor {self.name}")
                print(f"❌ Error: {str(e)}")
                print(f"❌ Full traceback:\n{error_details}")
            return None

    def sync_data_to_customer(self, customer_name):
        """Sync donor data to customer record"""
        if not customer_name:
            return

        try:
            customer_doc = frappe.get_doc("Customer", customer_name)

            # Debug logging during tests
            if frappe.flags.get("in_test"):
                print(f"📋 Comparing values for sync (Donor: {self.name}):")
                print(f"  customer_name: '{customer_doc.customer_name}' vs donor_name: '{self.donor_name}'")
                print(f"  email_id: '{customer_doc.email_id}' vs donor_email: '{self.donor_email}'")
                if hasattr(self, "phone"):
                    print(f"  mobile_no: '{customer_doc.mobile_no}' vs phone: '{self.phone}'")

            # Track if any changes were made
            changes_made = False

            # Sync basic information
            if customer_doc.customer_name != self.donor_name:
                if frappe.flags.get("in_test"):
                    print(f"✏️ Updating customer_name: '{customer_doc.customer_name}' -> '{self.donor_name}'")
                customer_doc.customer_name = self.donor_name
                changes_made = True

            # Handle contact info via Contact record (Customer email/mobile are read-only)
            contact_updated = self.sync_donor_to_customer_contact(customer_name)
            if frappe.flags.get("in_test"):
                print(f"📞 Contact sync returned: contact_updated={contact_updated}")

            # Always trigger Customer save if we have contact info to sync
            # This ensures fetch_from fields are refreshed from Contact
            has_contact_info = bool(self.donor_email or (hasattr(self, "phone") and self.phone))
            if contact_updated or has_contact_info:
                changes_made = True
                if frappe.flags.get("in_test"):
                    print(
                        f"📞 Marking Customer for save due to contact info (contact_updated={contact_updated}, has_contact_info={has_contact_info})"
                    )

            # Sync customer type
            expected_type = "Company" if self.donor_type == "Organization" else "Individual"
            if customer_doc.customer_type != expected_type:
                customer_doc.customer_type = expected_type
                changes_made = True

            # Ensure donor reference is set
            if customer_doc.donor != self.name:
                customer_doc.donor = self.name
                changes_made = True

            # Check if Customer was already saved during Contact sync
            customer_already_saved = getattr(frappe.local, "_contact_triggered_customer_save", {}).get(
                customer_name, False
            )

            # Save if changes were made and Customer wasn't already saved during Contact sync
            if changes_made and not customer_already_saved:
                if frappe.flags.get("in_test"):
                    print(f"💾 Saving customer changes (changes_made: {changes_made})")
                customer_doc.flags.ignore_mandatory = True
                customer_doc.flags.ignore_permissions = True
                customer_doc.flags.from_donor_sync = True

                try:
                    # Debug: Check field values just before save
                    if frappe.flags.get("in_test"):
                        print("🔍 Pre-save field values:")
                        print(f"   customer_name: '{customer_doc.customer_name}'")
                        print(f"   email_id: '{customer_doc.email_id}'")
                        print(f"   mobile_no: '{customer_doc.mobile_no}'")

                        # Check for any validation errors that might prevent save
                        customer_doc.validate()
                        print("✅ Customer validation passed")

                    customer_doc.save()

                    # Commit during tests to ensure visibility
                    if frappe.flags.get("in_test"):
                        frappe.db.commit()
                        print("✅ Customer saved and committed successfully!")

                        # Verify the save actually worked by reloading
                        customer_doc.reload()
                        print("🔍 Post-save verification:")
                        print(f"   customer_name: '{customer_doc.customer_name}'")
                        print(f"   email_id: '{customer_doc.email_id}'")
                        print(f"   mobile_no: '{customer_doc.mobile_no}'")

                except Exception as e:
                    if frappe.flags.get("in_test"):
                        print(f"❌ Customer save failed: {str(e)}")
                    # Re-raise to preserve original behavior
                    raise

                frappe.logger().info(f"Synced donor {self.name} data to customer {customer_name}")
            elif customer_already_saved:
                if frappe.flags.get("in_test"):
                    print("⏭️ Customer already saved during Contact sync, skipping duplicate save")
            else:
                if frappe.flags.get("in_test"):
                    print("⏭️ No changes made, skipping customer save")

        except Exception as e:
            frappe.log_error(
                f"Error syncing data from donor {self.name} to customer {customer_name}: {str(e)}",
                "Donor-Customer Data Sync Error",
            )

    def sync_donor_to_customer_contact(self, customer_name):
        """
        Create or update Contact record for Customer with donor contact info.
        Returns True if contact was updated, False otherwise.
        """
        try:
            # Find existing primary contact for this customer
            contact = self.get_or_create_customer_contact(customer_name)
            if not contact:
                return False

            changes_made = False

            # Update contact with donor information using child tables
            if self.donor_email and contact.email_id != self.donor_email:
                if frappe.flags.get("in_test"):
                    print(f"📧 Updating Contact email: '{contact.email_id}' -> '{self.donor_email}'")

                # Clear existing emails and add new primary email
                contact.email_ids = []
                contact.append("email_ids", {"email_id": self.donor_email, "is_primary": 1})
                changes_made = True

            if hasattr(self, "phone") and self.phone and contact.mobile_no != self.phone:
                if frappe.flags.get("in_test"):
                    print(f"📱 Updating Contact mobile: '{contact.mobile_no}' -> '{self.phone}'")

                # Clear existing phone numbers and add new primary mobile
                contact.phone_nos = []
                contact.append("phone_nos", {"phone": self.phone, "is_primary_mobile_no": 1})
                changes_made = True

            # Update contact name based on donor name
            expected_first_name, expected_last_name = self.parse_donor_name_for_contact()
            if contact.first_name != expected_first_name or contact.last_name != expected_last_name:
                if frappe.flags.get("in_test"):
                    print(
                        f"👤 Updating Contact name: '{contact.first_name} {contact.last_name}' -> '{expected_first_name} {expected_last_name}'"
                    )
                contact.first_name = expected_first_name
                contact.last_name = expected_last_name
                changes_made = True

            # Save contact if changes were made
            if changes_made:
                contact.flags.ignore_permissions = True
                contact.save()

                # Debug: Check contact data right after save
                if frappe.flags.get("in_test"):
                    # Force commit to ensure data is saved
                    frappe.db.commit()
                    # Check what was actually saved
                    saved_contact_data = frappe.db.get_value(
                        "Contact", contact.name, ["email_id", "mobile_no"], as_dict=True
                    )
                    print(f"📋 Contact {contact.name} after save: {saved_contact_data}")

                # Trigger Customer field refresh from Contact
                # This saves the Customer, so mark it to prevent double-save later
                # Pass the customer_doc to ensure pending changes are included
                self.refresh_customer_from_contact(customer_name, contact.name, customer_doc)

                # Set flag to prevent double Customer save in main sync logic
                if hasattr(frappe.local, "_contact_triggered_customer_save"):
                    frappe.local._contact_triggered_customer_save[customer_name] = True
                else:
                    frappe.local._contact_triggered_customer_save = {customer_name: True}

                if frappe.flags.get("in_test"):
                    print(f"✅ Contact {contact.name} updated successfully")

            return changes_made

        except Exception as e:
            frappe.log_error(
                f"Error syncing donor {self.name} contact info to customer {customer_name}: {str(e)}",
                "Donor-Customer Contact Sync Error",
            )
            return False

    def get_or_create_customer_contact(self, customer_name):
        """Get existing or create new primary contact for customer"""
        try:
            # First, check if customer already has a primary contact
            customer = frappe.get_doc("Customer", customer_name)
            if customer.customer_primary_contact:
                return frappe.get_doc("Contact", customer.customer_primary_contact)

            # Look for existing contact linked to this customer
            contacts = frappe.get_all(
                "Dynamic Link",
                filters={"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Contact"},
                fields=["parent"],
            )

            if contacts:
                # Use the first existing contact
                contact = frappe.get_doc("Contact", contacts[0].parent)
                # Set as primary contact on customer if not already set
                if not customer.customer_primary_contact:
                    frappe.db.set_value("Customer", customer_name, "customer_primary_contact", contact.name)
                return contact

            # Create new contact
            return self.create_new_customer_contact(customer_name)

        except Exception as e:
            frappe.log_error(
                f"Error getting/creating contact for customer {customer_name}: {str(e)}",
                "Customer Contact Creation Error",
            )
            return None

    def create_new_customer_contact(self, customer_name):
        """Create a new Contact record for the customer"""
        try:
            first_name, last_name = self.parse_donor_name_for_contact()

            contact = frappe.new_doc("Contact")
            contact.first_name = first_name
            contact.last_name = last_name

            # Add email to email_ids child table (don't set read-only email_id field)
            if self.donor_email:
                contact.append("email_ids", {"email_id": self.donor_email, "is_primary": 1})

            # Add phone to phone_nos child table (don't set read-only mobile_no field)
            if hasattr(self, "phone") and self.phone:
                contact.append("phone_nos", {"phone": self.phone, "is_primary_mobile_no": 1})

            # Link to customer
            contact.append("links", {"link_doctype": "Customer", "link_name": customer_name})

            contact.flags.ignore_permissions = True
            contact.insert()

            # Set as primary contact on customer
            frappe.db.set_value("Customer", customer_name, "customer_primary_contact", contact.name)

            if frappe.flags.get("in_test"):
                print(f"✨ Created new Contact {contact.name} for customer {customer_name}")

            return contact

        except Exception as e:
            frappe.log_error(
                f"Error creating new contact for customer {customer_name}: {str(e)}",
                "New Contact Creation Error",
            )
            return None

    def parse_donor_name_for_contact(self):
        """Parse donor name into first/last name for Contact record"""
        if not self.donor_name:
            return "", ""

        # Simple parsing - split on last space
        name_parts = self.donor_name.strip().split()
        if len(name_parts) == 1:
            return name_parts[0], ""
        else:
            return " ".join(name_parts[:-1]), name_parts[-1]

    def refresh_customer_from_contact(self, customer_name, contact_name, customer_doc=None):
        """
        Refresh Customer's fetch_from fields after Contact update.
        Uses Frappe's fetch mechanism to manually trigger field updates.

        Args:
            customer_name: Customer name
            contact_name: Contact name
            customer_doc: Optional Customer document with pending changes
        """
        try:
            from frappe.model.utils import get_fetch_values

            # Use provided customer_doc if available, otherwise fetch fresh
            customer = customer_doc if customer_doc else frappe.get_doc("Customer", customer_name)

            # Set the primary contact reference if needed
            if customer.customer_primary_contact != contact_name:
                customer.customer_primary_contact = contact_name
                customer.flags.ignore_permissions = True
                customer.flags.from_donor_sync = True
                customer.save()
                customer.reload()

            # Debug: Check the actual Contact data before trying to fetch
            if frappe.flags.get("in_test"):
                contact_data = frappe.db.get_value(
                    "Contact", contact_name, ["email_id", "mobile_no"], as_dict=True
                )
                print(f"🔍 Contact {contact_name} actual data: {contact_data}")

            # Manual fetch_from trigger using Frappe's built-in mechanism
            fetch_values = get_fetch_values("Customer", "customer_primary_contact", contact_name)

            if frappe.flags.get("in_test"):
                print(f"🔍 Fetch values for {customer_name}: {fetch_values}")

            # Apply fetch values to customer if they contain data
            changes_made = False
            for field, value in fetch_values.items():
                if value and getattr(customer, field) != value:
                    setattr(customer, field, value)
                    changes_made = True
                    if frappe.flags.get("in_test"):
                        print(f"   Setting {field} = '{value}'")

            # Always save customer to trigger fetch_from mechanism, even if no manual changes
            # The fetch_from fields should be populated automatically by ERPNext
            if changes_made or (fetch_values and any(fetch_values.values())):
                customer.flags.ignore_permissions = True
                customer.flags.from_donor_sync = True
                customer.save()
                if frappe.flags.get("in_test"):
                    print("   Customer saved to trigger fetch_from update")

            # Force reload to get updated fetch_from values
            customer.reload()
            if frappe.flags.get("in_test"):
                print(f"   After reload - email_id: '{customer.email_id}', mobile_no: '{customer.mobile_no}'")

            if frappe.flags.get("in_test"):
                print(f"🔄 Customer {customer_name} refreshed from Contact {contact_name}")
                print(f"   Final email_id: '{customer.email_id}'")
                print(f"   Final mobile_no: '{customer.mobile_no}'")

        except Exception as e:
            frappe.log_error(
                f"Error refreshing customer {customer_name} from contact {contact_name}: {str(e)}",
                "Customer Contact Refresh Error",
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
        # Ensure sync works even in test environment
        if frappe.flags.get("in_test"):
            self.flags.enable_customer_sync_in_test = True
        self.sync_with_customer()
        # Save the donor to persist any customer link updates
        self.save()
        # Reload document to get updated values from database
        self.reload()
        return {"message": "Customer synchronization refreshed successfully"}
