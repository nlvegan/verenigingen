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

    def before_save(self):
        """Encrypt sensitive fields before saving"""
        self.encrypt_sensitive_fields()

    def has_permlevel_access(self):
        """Check if user has permlevel 1 access to this doctype"""
        return frappe.has_permission(self.doctype, ptype="read", permlevel=1)

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
        except:
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
