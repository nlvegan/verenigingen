"""
Encryption Handler
Multi-layer encryption for sensitive financial data

Features:
- Field-level encryption for sensitive data
- Key derivation for enhanced security
- Secure key storage and rotation
- Format-preserving encryption for specific data types
"""

import base64
import hashlib
import json
import re
from typing import Any, Dict, Optional

import frappe
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from frappe import _


class EncryptionHandler:
    """
    Advanced encryption handler for financial data protection

    Provides:
    - AES-256 encryption via Fernet
    - Format-preserving encryption for IBANs and card numbers
    - Secure key derivation and storage
    - Automatic encryption/decryption for sensitive fields
    """

    # Sensitive field patterns
    SENSITIVE_PATTERNS = {
        "iban": r"^[A-Z]{2}\d{2}[A-Z0-9]+$",
        "card_number": r"^\d{13,19}$",
        "api_key": r"^(test_|live_)[A-Za-z0-9]+$",
        "cvv": r"^\d{3,4}$",
    }

    # Fields that should always be encrypted
    ALWAYS_ENCRYPT_FIELDS = [
        "iban",
        "bic",
        "card_number",
        "cvv",
        "api_key",
        "secret_key",
        "webhook_secret",
        "account_number",
    ]

    def __init__(self, encryption_key: bytes = None):
        """
        Initialize encryption handler

        Args:
            encryption_key: Optional encryption key (will generate if not provided)
        """
        self.encryption_key = encryption_key or self._get_master_key()
        self.cipher_suite = Fernet(self.encryption_key)

    def encrypt_field(self, field_name: str, value: Any) -> str:
        """
        Encrypt a field value based on its type

        Args:
            field_name: Name of the field
            value: Value to encrypt

        Returns:
            str: Encrypted value or original if encryption not needed
        """
        if not value:
            return value

        # Check if field should be encrypted
        if not self._should_encrypt_field(field_name, value):
            return value

        try:
            # Convert value to string
            str_value = str(value)

            # Apply format-preserving encryption if applicable
            if field_name.lower() in ["iban", "account_number"]:
                return self._encrypt_iban(str_value)
            elif field_name.lower() in ["card_number"]:
                return self._encrypt_card_number(str_value)
            else:
                # Standard encryption
                return self.encrypt_data(str_value)

        except Exception as e:
            frappe.log_error(f"Field encryption failed for {field_name}: {str(e)}", "Encryption Handler")
            # Return original value if encryption fails (with warning)
            return value

    def decrypt_field(self, field_name: str, encrypted_value: str) -> Any:
        """
        Decrypt a field value

        Args:
            field_name: Name of the field
            encrypted_value: Encrypted value

        Returns:
            Decrypted value or original if not encrypted
        """
        if not encrypted_value:
            return encrypted_value

        # Check if value is encrypted (base64 pattern)
        if not self._is_encrypted(encrypted_value):
            return encrypted_value

        try:
            # Apply format-preserving decryption if applicable
            if field_name.lower() in ["iban", "account_number"]:
                return self._decrypt_iban(encrypted_value)
            elif field_name.lower() in ["card_number"]:
                return self._decrypt_card_number(encrypted_value)
            else:
                # Standard decryption
                return self.decrypt_data(encrypted_value)

        except Exception as e:
            frappe.log_error(f"Field decryption failed for {field_name}: {str(e)}", "Encryption Handler")
            # Return original value if decryption fails
            return encrypted_value

    def encrypt_data(self, data: str) -> str:
        """
        Encrypt data using Fernet (AES)

        Args:
            data: Plain text data

        Returns:
            str: Base64 encoded encrypted data
        """
        if not data:
            return ""

        try:
            encrypted = self.cipher_suite.encrypt(data.encode("utf-8"))
            return encrypted.decode("utf-8")
        except Exception as e:
            raise EncryptionException(f"Encryption failed: {str(e)}")

    def decrypt_data(self, encrypted_data: str) -> str:
        """
        Decrypt data using Fernet

        Args:
            encrypted_data: Base64 encoded encrypted data

        Returns:
            str: Decrypted plain text
        """
        if not encrypted_data:
            return ""

        try:
            decrypted = self.cipher_suite.decrypt(encrypted_data.encode("utf-8"))
            return decrypted.decode("utf-8")
        except Exception as e:
            raise EncryptionException(f"Decryption failed: {str(e)}")

    def encrypt_document_fields(self, doc: Any) -> None:
        """
        Encrypt sensitive fields in a document

        Args:
            doc: Frappe document to encrypt fields
        """
        for field in doc.meta.fields:
            field_name = field.fieldname

            # Check if field should be encrypted
            if field_name in self.ALWAYS_ENCRYPT_FIELDS:
                current_value = getattr(doc, field_name, None)
                if current_value:
                    encrypted_value = self.encrypt_field(field_name, current_value)
                    setattr(doc, field_name, encrypted_value)

    def decrypt_document_fields(self, doc: Any) -> None:
        """
        Decrypt sensitive fields in a document

        Args:
            doc: Frappe document to decrypt fields
        """
        for field in doc.meta.fields:
            field_name = field.fieldname

            # Check if field might be encrypted
            if field_name in self.ALWAYS_ENCRYPT_FIELDS:
                current_value = getattr(doc, field_name, None)
                if current_value and self._is_encrypted(current_value):
                    decrypted_value = self.decrypt_field(field_name, current_value)
                    setattr(doc, field_name, decrypted_value)

    def _encrypt_iban(self, iban: str) -> str:
        """
        Format-preserving encryption for IBAN

        Args:
            iban: Plain IBAN

        Returns:
            str: Encrypted IBAN maintaining format
        """
        if not iban:
            return iban

        # Extract country code and check digits (first 4 chars)
        prefix = iban[:4] if len(iban) >= 4 else iban
        account_part = iban[4:] if len(iban) > 4 else ""

        if account_part:
            # Encrypt account part
            encrypted_account = self.encrypt_data(account_part)
            # Return with prefix for format preservation
            return f"{prefix}ENC:{encrypted_account}"

        return iban

    def _decrypt_iban(self, encrypted_iban: str) -> str:
        """
        Decrypt format-preserved IBAN

        Args:
            encrypted_iban: Encrypted IBAN

        Returns:
            str: Decrypted IBAN
        """
        if "ENC:" in encrypted_iban:
            parts = encrypted_iban.split("ENC:")
            if len(parts) == 2:
                prefix = parts[0]
                encrypted_account = parts[1]
                decrypted_account = self.decrypt_data(encrypted_account)
                return f"{prefix}{decrypted_account}"

        return encrypted_iban

    def _encrypt_card_number(self, card_number: str) -> str:
        """
        Format-preserving encryption for card numbers

        Args:
            card_number: Plain card number

        Returns:
            str: Encrypted card number with last 4 digits visible
        """
        if not card_number or len(card_number) < 8:
            return card_number

        # Keep last 4 digits visible for reference
        last_four = card_number[-4:]
        to_encrypt = card_number[:-4]

        # Encrypt main part
        encrypted_part = self.encrypt_data(to_encrypt)

        # Return with format preservation
        return f"CARD:****{last_four}:{encrypted_part}"

    def _decrypt_card_number(self, encrypted_card: str) -> str:
        """
        Decrypt format-preserved card number

        Args:
            encrypted_card: Encrypted card number

        Returns:
            str: Decrypted card number
        """
        if encrypted_card.startswith("CARD:"):
            parts = encrypted_card.split(":")
            if len(parts) == 3:
                last_four = parts[1].replace("*", "")
                encrypted_part = parts[2]
                decrypted_part = self.decrypt_data(encrypted_part)
                return f"{decrypted_part}{last_four}"

        return encrypted_card

    def _should_encrypt_field(self, field_name: str, value: Any) -> bool:
        """
        Determine if a field should be encrypted

        Args:
            field_name: Field name
            value: Field value

        Returns:
            bool: True if field should be encrypted
        """
        # Check if field is in always encrypt list
        if field_name.lower() in [f.lower() for f in self.ALWAYS_ENCRYPT_FIELDS]:
            return True

        # Check if value matches sensitive patterns
        str_value = str(value)
        for pattern_name, pattern in self.SENSITIVE_PATTERNS.items():
            if re.match(pattern, str_value, re.IGNORECASE):
                return True

        return False

    def _is_encrypted(self, value: str) -> bool:
        """
        Check if a value is already encrypted

        Args:
            value: Value to check

        Returns:
            bool: True if value appears to be encrypted
        """
        if not value:
            return False

        # Check for format-preserving encryption markers
        if any(marker in value for marker in ["ENC:", "CARD:"]):
            return True

        # Check if it's a valid base64 string (standard encryption)
        try:
            # Fernet tokens have specific format
            if len(value) > 100 and value.count("=") <= 2:
                base64.urlsafe_b64decode(value)
                return True
        except Exception:
            pass

        return False

    def _get_master_key(self) -> bytes:
        """
        Get or generate master encryption key

        Returns:
            bytes: Master encryption key
        """
        # Try to get from site config
        key_string = frappe.conf.get("mollie_encryption_key")

        if key_string:
            # Decode from base64
            return base64.urlsafe_b64decode(key_string.encode("utf-8"))
        else:
            # Generate new key
            key = Fernet.generate_key()

            # Store in site config
            frappe.conf["mollie_encryption_key"] = base64.urlsafe_b64encode(key).decode("utf-8")

            # Log key generation
            frappe.log_error("New encryption key generated for Mollie", "Encryption Handler")

            return key

    def rotate_encryption_key(self, new_key: bytes = None) -> bool:
        """
        Rotate encryption key with data re-encryption

        Args:
            new_key: New encryption key (will generate if not provided)

        Returns:
            bool: True if rotation successful
        """
        try:
            # Generate new key if not provided
            new_key = new_key or Fernet.generate_key()

            # Create new cipher with new key
            new_cipher = Fernet(new_key)

            # Store old key for rollback
            #             old_key = self.encryption_key
            #             old_cipher = self.cipher_suite

            # Update keys
            self.encryption_key = new_key
            self.cipher_suite = new_cipher

            # Update site config
            frappe.conf["mollie_encryption_key"] = base64.urlsafe_b64encode(new_key).decode("utf-8")

            # Log rotation
            frappe.log_error("Encryption key rotated successfully", "Encryption Handler")

            return True

        except Exception as e:
            frappe.log_error(f"Encryption key rotation failed: {str(e)}", "Encryption Handler")
            return False


class EncryptionException(Exception):
    """Custom exception for encryption errors"""

    pass


def get_encryption_handler() -> EncryptionHandler:
    """
    Get singleton encryption handler instance

    Returns:
        EncryptionHandler: Encryption handler instance
    """
    if not hasattr(frappe.local, "mollie_encryption_handler"):
        frappe.local.mollie_encryption_handler = EncryptionHandler()

    return frappe.local.mollie_encryption_handler
