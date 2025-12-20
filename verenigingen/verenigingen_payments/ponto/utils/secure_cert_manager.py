# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Secure Certificate Manager

Handles temporary certificate and key files with secure cleanup.

Features:
- Context manager protocol for guaranteed cleanup
- Secure deletion (overwrite before delete) for sensitive key material
- Centralized certificate preparation logic
- Works with both encrypted and unencrypted private keys

Usage:
    from verenigingen.verenigingen_payments.ponto.utils.secure_cert_manager import (
        SecureCertManager,
    )

    with SecureCertManager() as cert_manager:
        cert_files = cert_manager.get_cert_files()
        # Use cert_files tuple (cert_path, key_path) with requests
        response = requests.post(url, cert=cert_files, ...)
    # Files are securely cleaned up when context exits
"""

import os
import tempfile
from typing import Optional, Tuple

import frappe
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class SecureCertManager:
    """
    Secure manager for temporary certificate and key files.

    Uses context manager protocol to ensure files are always cleaned up,
    even on exceptions. Implements secure deletion by overwriting files
    with random data before unlinking.
    """

    # Number of bytes for secure overwrite (matches typical cert/key sizes)
    SECURE_OVERWRITE_PASSES = 3

    def __init__(self):
        """Initialize certificate manager."""
        self._cert_path: Optional[str] = None
        self._key_path: Optional[str] = None
        self._is_setup = False

    def __enter__(self) -> "SecureCertManager":
        """Enter context manager - files created on demand."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - securely clean up temp files."""
        self._cleanup()
        return False  # Don't suppress exceptions

    def _secure_delete(self, filepath: str):
        """
        Securely delete a file by overwriting with random data before unlinking.

        This helps prevent recovery of sensitive key material from disk.

        Args:
            filepath: Path to file to securely delete
        """
        try:
            if not os.path.exists(filepath):
                return

            # Get file size
            file_size = os.path.getsize(filepath)

            # Overwrite with random data multiple times
            for _ in range(self.SECURE_OVERWRITE_PASSES):
                with open(filepath, "wb") as f:
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())

            # Now unlink the file
            os.unlink(filepath)
            frappe.logger().debug(f"Securely deleted temp file: {filepath}")

        except Exception as e:
            # Fall back to simple delete
            frappe.logger().warning(f"Secure delete failed, using simple delete: {e}")
            try:
                os.unlink(filepath)
            except Exception:
                pass

    def _cleanup(self):
        """Clean up temporary certificate and key files."""
        for filepath in [self._cert_path, self._key_path]:
            if filepath:
                self._secure_delete(filepath)

        self._cert_path = None
        self._key_path = None
        self._is_setup = False

    def _prepare_private_key(self, key_pem: str, passphrase: Optional[str] = None) -> bytes:
        """
        Prepare private key for use with requests library.

        If the key is encrypted and a passphrase is provided, decrypt it.
        The requests library cannot handle encrypted keys directly.

        Args:
            key_pem: PEM-encoded private key (possibly encrypted)
            passphrase: Passphrase for encrypted key (optional)

        Returns:
            bytes: Decrypted PEM-encoded private key
        """
        key_bytes = key_pem.encode("utf-8")

        # Check if key is encrypted (contains ENCRYPTED in header)
        if b"ENCRYPTED" in key_bytes and passphrase:
            password = passphrase.encode("utf-8")
            private_key = load_pem_private_key(key_bytes, password=password)
            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )

        return key_bytes

    def setup_from_settings(self) -> bool:
        """
        Set up certificate files from Ponto Settings.

        Reads certificate and private key from settings, decrypts if needed,
        and writes to secure temporary files.

        Returns:
            bool: True if mTLS is configured and files are set up
        """
        try:
            settings = frappe.get_single("Ponto Settings")

            if not settings.use_ibanity_mtls:
                return False

            if not settings.ibanity_certificate or not settings.ibanity_private_key:
                frappe.logger().warning("mTLS enabled but certificate/key not configured")
                return False

            # Write certificate to temp file
            cert_fd, self._cert_path = tempfile.mkstemp(suffix=".pem", prefix="ponto_cert_")
            try:
                os.write(cert_fd, settings.ibanity_certificate.encode("utf-8"))
            finally:
                os.close(cert_fd)

            # Prepare and write private key (decrypt if needed)
            passphrase = settings.get_password("ibanity_key_passphrase")
            key_content = self._prepare_private_key(settings.ibanity_private_key, passphrase)

            key_fd, self._key_path = tempfile.mkstemp(suffix=".pem", prefix="ponto_key_")
            try:
                os.write(key_fd, key_content)
            finally:
                os.close(key_fd)

            # Set restrictive permissions on key file
            os.chmod(self._key_path, 0o600)

            self._is_setup = True
            frappe.logger().debug("Secure certificate manager initialized")
            return True

        except Exception as e:
            frappe.logger().error(f"Failed to setup mTLS certificates: {e}")
            self._cleanup()
            return False

    def setup_from_pem(
        self,
        certificate_pem: str,
        private_key_pem: str,
        passphrase: Optional[str] = None,
    ) -> bool:
        """
        Set up certificate files from PEM strings.

        Args:
            certificate_pem: PEM-encoded certificate
            private_key_pem: PEM-encoded private key (possibly encrypted)
            passphrase: Passphrase for encrypted key (optional)

        Returns:
            bool: True if files are set up successfully
        """
        try:
            # Write certificate to temp file
            cert_fd, self._cert_path = tempfile.mkstemp(suffix=".pem", prefix="ponto_cert_")
            try:
                os.write(cert_fd, certificate_pem.encode("utf-8"))
            finally:
                os.close(cert_fd)

            # Prepare and write private key
            key_content = self._prepare_private_key(private_key_pem, passphrase)

            key_fd, self._key_path = tempfile.mkstemp(suffix=".pem", prefix="ponto_key_")
            try:
                os.write(key_fd, key_content)
            finally:
                os.close(key_fd)

            # Set restrictive permissions on key file
            os.chmod(self._key_path, 0o600)

            self._is_setup = True
            return True

        except Exception as e:
            frappe.logger().error(f"Failed to setup certificates from PEM: {e}")
            self._cleanup()
            return False

    def get_cert_files(self) -> Optional[Tuple[str, str]]:
        """
        Get the certificate file paths for use with requests.

        Returns:
            Tuple of (cert_path, key_path) or None if not set up
        """
        if self._is_setup and self._cert_path and self._key_path:
            return (self._cert_path, self._key_path)
        return None

    @property
    def is_configured(self) -> bool:
        """Check if certificates are configured and ready."""
        return self._is_setup
