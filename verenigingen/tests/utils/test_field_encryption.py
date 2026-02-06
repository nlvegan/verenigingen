# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for Field Encryption utility.

Tests the FieldEncryption class used for encrypting sensitive data like IBANs.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.field_encryption import FieldEncryption, get_encryption


class TestFieldEncryption(FrappeTestCase):
    """Test suite for FieldEncryption class."""

    def setUp(self):
        """Set up test fixtures."""
        self.encryption = FieldEncryption()
        self.test_iban = "NL91ABNA0417164300"

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting and decrypting should return original value."""
        encrypted = self.encryption.encrypt(self.test_iban)
        decrypted = self.encryption.decrypt(encrypted)
        self.assertEqual(decrypted, self.test_iban)

    def test_encrypted_value_different(self):
        """Encrypted value should not be the same as plaintext."""
        encrypted = self.encryption.encrypt(self.test_iban)
        self.assertNotEqual(encrypted, self.test_iban)
        self.assertTrue(encrypted.startswith("ENC:"))

    def test_is_encrypted_check(self):
        """Should correctly identify encrypted vs plaintext values."""
        encrypted = self.encryption.encrypt(self.test_iban)
        self.assertTrue(self.encryption.is_encrypted(encrypted))
        self.assertFalse(self.encryption.is_encrypted(self.test_iban))

    def test_decrypt_plaintext_returns_as_is(self):
        """Decrypting a non-encrypted value should return it unchanged."""
        result = self.encryption.decrypt(self.test_iban)
        self.assertEqual(result, self.test_iban)

    def test_encrypt_already_encrypted_returns_as_is(self):
        """Encrypting an already encrypted value should return it unchanged."""
        encrypted = self.encryption.encrypt(self.test_iban)
        double_encrypted = self.encryption.encrypt(encrypted)
        self.assertEqual(encrypted, double_encrypted)

    def test_empty_value_handling(self):
        """Empty/None values should be handled gracefully."""
        self.assertEqual(self.encryption.encrypt(""), "")
        self.assertEqual(self.encryption.decrypt(""), "")
        self.assertFalse(self.encryption.is_encrypted(""))

    def test_none_value_handling(self):
        """None values should be handled gracefully."""
        self.assertIsNone(self.encryption.encrypt(None))
        self.assertIsNone(self.encryption.decrypt(None))
        self.assertFalse(self.encryption.is_encrypted(None))

    def test_get_encryption_singleton(self):
        """get_encryption() should return a singleton instance."""
        instance1 = get_encryption()
        instance2 = get_encryption()
        self.assertIs(instance1, instance2)

    def test_different_values_encrypt_differently(self):
        """Different plaintext values should produce different ciphertexts."""
        iban1 = "NL91ABNA0417164300"
        iban2 = "DE89370400440532013000"

        encrypted1 = self.encryption.encrypt(iban1)
        encrypted2 = self.encryption.encrypt(iban2)

        self.assertNotEqual(encrypted1, encrypted2)

    def test_encrypt_special_characters(self):
        """Should handle values with special characters."""
        special_value = "NL91 ABNA 0417 1643 00"  # IBAN with spaces
        encrypted = self.encryption.encrypt(special_value)
        decrypted = self.encryption.decrypt(encrypted)
        self.assertEqual(decrypted, special_value)

    def test_encrypt_unicode_characters(self):
        """Should handle values with unicode characters."""
        unicode_value = "Test with unicode: \u00e9\u00e8\u00ea"
        encrypted = self.encryption.encrypt(unicode_value)
        decrypted = self.encryption.decrypt(encrypted)
        self.assertEqual(decrypted, unicode_value)
