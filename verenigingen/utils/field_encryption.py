# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Field-level encryption for sensitive data.

Uses Fernet symmetric encryption with keys stored in site_config.json.
Encrypted values are prefixed with "ENC:" for identification.

Configuration:
    Add to site_config.json:
    {
        "field_encryption_key": "<base64-encoded-32-byte-key>"
    }

    Generate a key:
    >>> from cryptography.fernet import Fernet
    >>> Fernet.generate_key().decode()

Example usage:
    >>> from verenigingen.utils.field_encryption import get_encryption
    >>> encryption = get_encryption()
    >>> encrypted = encryption.encrypt("NL91ABNA0417164300")
    >>> decrypted = encryption.decrypt(encrypted)
"""
import base64
import os
from typing import Optional

import frappe
from cryptography.fernet import Fernet


class FieldEncryption:
    """
    Encrypts and decrypts sensitive field values.

    Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
    Encrypted values are prefixed with "ENC:" for easy identification.

    Configuration (site_config.json):
        field_encryption_key: Base64-encoded 32-byte key

    Production Safety:
        In production (developer_mode=False), the encryption key MUST be
        configured. The service will throw an error if no key is present,
        preventing silent data loss from auto-generated ephemeral keys.

    Development Mode:
        In developer_mode, generates a temporary key with a warning.
        This key is lost on restart - only for development/testing.
    """

    PREFIX = "ENC:"

    def __init__(self):
        self._fernet: Optional[Fernet] = None
        self._generated_key: Optional[bytes] = None

    def _get_key(self) -> bytes:
        """
        Get the encryption key from configuration.

        Returns:
            bytes: The encryption key suitable for Fernet

        Raises:
            frappe.ValidationError: In production if no key is configured

        Note:
            In developer_mode, generates a temporary key with a warning.
            In production, fails fast with a clear error - no auto-generation.
            This prevents silent data loss from key changes on restart.
        """
        key = frappe.conf.get("field_encryption_key")

        if not key:
            # Check if we're in developer mode
            is_developer_mode = frappe.conf.get("developer_mode", False)

            if is_developer_mode:
                # Development: Generate temporary key with warning
                if self._generated_key is None:
                    self._generated_key = Fernet.generate_key()
                    frappe.logger("encryption").warning(
                        "DEVELOPMENT ONLY: No field_encryption_key configured. "
                        "Generated temporary key for this session. "
                        "To generate a persistent key, run:\n"
                        "  from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\n"
                        "Then add to site_config.json:\n"
                        '  "field_encryption_key": "<your-key>"'
                    )
                return self._generated_key
            else:
                # Production: Fail fast with clear error
                frappe.throw(
                    "Field encryption key not configured. "
                    "Add 'field_encryption_key' to site_config.json before using encryption. "
                    "Generate a key with: from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())",
                    title="Encryption Configuration Required",
                )

        # Ensure key is bytes
        if isinstance(key, str):
            return key.encode()
        return key

    def _get_fernet(self) -> Fernet:
        """
        Get Fernet instance (lazy initialization).

        Returns:
            Fernet: Initialized Fernet cipher instance
        """
        if self._fernet is None:
            self._fernet = Fernet(self._get_key())
        return self._fernet

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        """
        Encrypt a string value.

        Args:
            value: Plaintext string to encrypt, or None/empty

        Returns:
            Encrypted string with "ENC:" prefix, or original value if empty/None
            Returns value unchanged if already encrypted
        """
        if value is None:
            return None

        if not value:
            return value

        if self.is_encrypted(value):
            return value  # Already encrypted, return as-is

        fernet = self._get_fernet()
        encrypted_bytes = fernet.encrypt(value.encode("utf-8"))
        return self.PREFIX + base64.urlsafe_b64encode(encrypted_bytes).decode("utf-8")

    def decrypt(self, value: Optional[str]) -> Optional[str]:
        """
        Decrypt an encrypted value.

        Args:
            value: Encrypted string (with "ENC:" prefix), or plaintext

        Returns:
            Decrypted plaintext string, or original value if not encrypted
        """
        if value is None:
            return None

        if not value:
            return value

        if not self.is_encrypted(value):
            return value  # Not encrypted, return as-is

        # Remove prefix and decode
        encrypted_b64 = value[len(self.PREFIX) :]
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_b64.encode("utf-8"))

        fernet = self._get_fernet()
        decrypted_bytes = fernet.decrypt(encrypted_bytes)
        return decrypted_bytes.decode("utf-8")

    def is_encrypted(self, value: Optional[str]) -> bool:
        """
        Check if a value is encrypted.

        Args:
            value: Value to check

        Returns:
            True if value starts with "ENC:" prefix, False otherwise
        """
        if not value:
            return False
        return value.startswith(self.PREFIX)


# Singleton instance
_encryption: Optional[FieldEncryption] = None


def get_encryption() -> FieldEncryption:
    """
    Get the singleton FieldEncryption instance.

    Returns:
        FieldEncryption: Shared encryption instance

    Example:
        >>> encryption = get_encryption()
        >>> encrypted = encryption.encrypt("sensitive data")
    """
    global _encryption
    if _encryption is None:
        _encryption = FieldEncryption()
    return _encryption
