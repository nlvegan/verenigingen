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

    def create_new_customer_contact(self, customer_name, max_retries=3):
        """Create a new Contact record for the customer with retry logic"""
        import time

        for attempt in range(max_retries):
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
                attempt_num = attempt + 1
                is_last_attempt = attempt_num == max_retries

                if frappe.flags.get("in_test"):
                    print(f"❌ Contact creation attempt {attempt_num}/{max_retries} failed: {str(e)}")

                if is_last_attempt:
                    # Final failure - log comprehensive error
                    frappe.log_error(
                        f"Error creating contact for customer {customer_name} and donor {self.name} "
                        f"after {max_retries} attempts: {str(e)}",
                        "Donor Customer Contact Creation Error",
                    )
                    if frappe.flags.get("in_test"):
                        print(
                            f"❌ All {max_retries} Contact creation attempts failed for customer {customer_name}"
                        )
                    return None
                else:
                    # Wait before retry with exponential backoff (0.5s, 1s, 2s)
                    wait_time = 0.5 * (2**attempt)
                    if frappe.flags.get("in_test"):
                        print(f"⏳ Retrying Contact creation in {wait_time}s...")
                    time.sleep(wait_time)

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
        Set Customer's primary contact reference - ERPNext handles fetch_from automatically.

        Args:
            customer_name: Customer name
            contact_name: Contact name
            customer_doc: Optional Customer document with pending changes
        """
        try:
            # Use provided customer_doc if available, otherwise fetch fresh
            customer = customer_doc if customer_doc else frappe.get_doc("Customer", customer_name)

            # Set the primary contact reference - ERPNext will handle fetch_from automatically
            if customer.customer_primary_contact != contact_name:
                customer.customer_primary_contact = contact_name
                customer.flags.from_donor_sync = True
                customer.save()

                if frappe.flags.get("in_test"):
                    print(f"🔄 Set Customer {customer_name} primary contact to {contact_name}")
                    print("   ERPNext will handle fetch_from fields automatically")

        except Exception as e:
            frappe.log_error(
                f"Error setting customer {customer_name} primary contact to {contact_name}: {str(e)}",
                "Customer Contact Link Error",
            )

    def _get_donor_customer_group(self):
        """Get donor customer group from configuration with auto-repair"""
        # Check Verenigingen Settings for donor customer group configuration
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "donor_customer_group") and settings.donor_customer_group:
                if frappe.db.exists("Customer Group", settings.donor_customer_group):
                    return settings.donor_customer_group
                else:
                    if frappe.flags.get("in_test"):
                        print(
                            f"⚠️ Configured donor customer group '{settings.donor_customer_group}' does not exist"
                        )
                    frappe.log_error(
                        f"Configured donor customer group '{settings.donor_customer_group}' does not exist, "
                        f"falling back to auto-creation",
                        "Donor Customer Group Configuration Error",
                    )
        except Exception:
            pass

        # Check if "Donors" group exists (legacy default)
        if frappe.db.exists("Customer Group", "Donors"):
            return "Donors"

        # Auto-create "Donors" customer group proactively
        if frappe.flags.get("in_test"):
            print("🔧 Auto-creating 'Donors' customer group")
        try:
            self._create_donor_customer_group()
            return "Donors"
        except Exception as e:
            if frappe.flags.get("in_test"):
                print(f"❌ Failed to auto-create 'Donors' customer group: {str(e)}")
            frappe.log_error(
                f"Failed to auto-create 'Donors' customer group: {str(e)}",
                "Customer Group Auto-Creation Error",
            )

        # Get selling settings default as secondary fallback
        default_group = frappe.db.get_single_value("Selling Settings", "customer_group")
        if default_group and frappe.db.exists("Customer Group", default_group):
            if frappe.flags.get("in_test"):
                print(f"📋 Using Selling Settings default customer group: {default_group}")
            return default_group

        # Final fallback with validation
        if frappe.db.exists("Customer Group", "All Customer Groups"):
            if frappe.flags.get("in_test"):
                print("📋 Using final fallback customer group: All Customer Groups")
            return "All Customer Groups"

        # This should rarely happen now due to auto-creation
        frappe.throw(
            "No suitable customer group found for donors. Please either:\n"
            "1. Configure 'donor_customer_group' in Verenigingen Settings\n"
            "2. Create a 'Donors' customer group manually\n"
            "3. Configure default customer group in Selling Settings\n"
            "4. Ensure 'All Customer Groups' exists"
        )

    def ensure_donor_customer_group(self):
        """Ensure 'Donors' customer group exists - legacy method, calls _create_donor_customer_group"""
        self._create_donor_customer_group()

    def _create_donor_customer_group(self):
        """Create 'Donors' customer group if it doesn't exist"""
        if not frappe.db.exists("Customer Group", "Donors"):
            try:
                donor_group = frappe.new_doc("Customer Group")
                donor_group.customer_group_name = "Donors"
                donor_group.parent_customer_group = "All Customer Groups"
                donor_group.is_group = 0
                donor_group.flags.ignore_permissions = True
                donor_group.insert()

                if frappe.flags.get("in_test"):
                    print("✅ Successfully created 'Donors' customer group")

                frappe.logger().info("Auto-created 'Donors' customer group for donor-customer integration")

            except Exception as e:
                if frappe.flags.get("in_test"):
                    print(f"❌ Error creating 'Donors' customer group: {str(e)}")
                raise

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
