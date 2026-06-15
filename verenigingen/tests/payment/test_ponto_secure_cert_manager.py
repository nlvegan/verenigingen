"""
Tests for Ponto Secure Certificate Manager.

Integration tests for SecureCertManager: setup from real PEM strings (encrypted
and unencrypted private keys), setup from the Ponto Settings singleton, secure
deletion / cleanup, context-manager protocol, and file-permission hardening.

Real cryptographic material is generated at runtime (self-signed cert + RSA key),
so the decrypt path in _prepare_private_key is genuinely exercised — nothing is
mocked. No external HTTP is involved.

Usage:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_ponto_secure_cert_manager
"""

import datetime
import os
import stat

import frappe
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.verenigingen_payments.ponto.utils.secure_cert_manager import SecureCertManager


def _generate_cert_and_key(passphrase: bytes = None):
    """Generate a self-signed cert and matching RSA private key.

    Returns:
        (cert_pem: str, key_pem: str) — key is encrypted if passphrase given.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    if passphrase:
        encryption = serialization.BestAvailableEncryption(passphrase)
    else:
        encryption = serialization.NoEncryption()

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=encryption,
    ).decode("utf-8")

    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "ponto-test.local")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return cert_pem, key_pem


class TestSecureCertManagerFromPEM(FrappeTestCase):
    """setup_from_pem and cleanup behaviour with real key material."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cert_pem, cls.key_pem = _generate_cert_and_key()
        cls.enc_passphrase = b"s3cr3t-pass"
        cls.enc_cert_pem, cls.enc_key_pem = _generate_cert_and_key(cls.enc_passphrase)

    def test_setup_from_pem_unencrypted_key(self):
        mgr = SecureCertManager()
        try:
            self.assertTrue(mgr.setup_from_pem(self.cert_pem, self.key_pem))
            self.assertTrue(mgr.is_configured)
            cert_files = mgr.get_cert_files()
            self.assertIsNotNone(cert_files)
            cert_path, key_path = cert_files
            self.assertTrue(os.path.exists(cert_path))
            self.assertTrue(os.path.exists(key_path))
        finally:
            mgr._cleanup()

    def test_setup_from_pem_encrypted_key_decrypts(self):
        """An encrypted key + passphrase is decrypted to an unencrypted temp file."""
        mgr = SecureCertManager()
        try:
            ok = mgr.setup_from_pem(
                self.enc_cert_pem, self.enc_key_pem, passphrase=self.enc_passphrase.decode()
            )
            self.assertTrue(ok)
            _, key_path = mgr.get_cert_files()
            with open(key_path, "rb") as fh:
                written = fh.read()
            # The decrypted key must NOT carry an ENCRYPTED header.
            self.assertNotIn(b"ENCRYPTED", written)
            self.assertIn(b"PRIVATE KEY", written)
        finally:
            mgr._cleanup()

    def test_key_file_has_restrictive_permissions(self):
        mgr = SecureCertManager()
        try:
            mgr.setup_from_pem(self.cert_pem, self.key_pem)
            _, key_path = mgr.get_cert_files()
            mode = stat.S_IMODE(os.stat(key_path).st_mode)
            self.assertEqual(mode, 0o600)
        finally:
            mgr._cleanup()

    def test_cert_files_written_with_expected_content(self):
        mgr = SecureCertManager()
        try:
            mgr.setup_from_pem(self.cert_pem, self.key_pem)
            cert_path, _ = mgr.get_cert_files()
            with open(cert_path) as fh:
                self.assertIn("BEGIN CERTIFICATE", fh.read())
        finally:
            mgr._cleanup()

    def test_cleanup_removes_files(self):
        mgr = SecureCertManager()
        mgr.setup_from_pem(self.cert_pem, self.key_pem)
        cert_path, key_path = mgr.get_cert_files()
        mgr._cleanup()
        self.assertFalse(os.path.exists(cert_path))
        self.assertFalse(os.path.exists(key_path))
        self.assertFalse(mgr.is_configured)
        self.assertIsNone(mgr.get_cert_files())

    def test_get_cert_files_before_setup_returns_none(self):
        mgr = SecureCertManager()
        self.assertIsNone(mgr.get_cert_files())
        self.assertFalse(mgr.is_configured)

    def test_context_manager_cleans_up_on_exit(self):
        """Files created inside a `with` block are gone after it exits."""
        with SecureCertManager() as mgr:
            mgr.setup_from_pem(self.cert_pem, self.key_pem)
            cert_path, key_path = mgr.get_cert_files()
            self.assertTrue(os.path.exists(cert_path))
        self.assertFalse(os.path.exists(cert_path))
        self.assertFalse(os.path.exists(key_path))

    def test_context_manager_does_not_suppress_exception(self):
        """__exit__ returns False, so exceptions propagate out of the block."""
        with self.assertRaises(ValueError):
            with SecureCertManager() as mgr:
                mgr.setup_from_pem(self.cert_pem, self.key_pem)
                raise ValueError("boom")

    def test_setup_from_pem_invalid_key_returns_false(self):
        """A malformed (claims-encrypted) key with a passphrase fails gracefully."""
        mgr = SecureCertManager()
        try:
            bad_key = "-----BEGIN ENCRYPTED PRIVATE KEY-----\nnot-real\n-----END ENCRYPTED PRIVATE KEY-----"
            ok = mgr.setup_from_pem(self.cert_pem, bad_key, passphrase="whatever")
            self.assertFalse(ok)
            # On failure, cleanup runs => not configured.
            self.assertFalse(mgr.is_configured)
        finally:
            mgr._cleanup()

    def test_secure_delete_missing_file_is_noop(self):
        """_secure_delete on a non-existent path must not raise."""
        mgr = SecureCertManager()
        mgr._secure_delete("/tmp/ponto_does_not_exist_xyz.pem")  # should not raise


class TestSecureCertManagerFromSettings(FrappeTestCase):
    """setup_from_settings reads the Ponto Settings singleton."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._singleton_backup = SingletonBackup("Ponto Settings")
        cls._singleton_backup.backup()
        cls.cert_pem, cls.key_pem = _generate_cert_and_key()

    @classmethod
    def tearDownClass(cls):
        cls._singleton_backup.restore()
        super().tearDownClass()

    def _set_settings(self, **fields):
        settings = frappe.get_single("Ponto Settings")
        # Keep credential validation happy regardless of mode.
        settings.sandbox_mode = 1
        settings.sandbox_client_id = "test_sandbox_client"
        settings.sandbox_client_secret = "test_sandbox_secret"
        for k, v in fields.items():
            setattr(settings, k, v)
        settings.save()
        frappe.db.commit()

    def test_setup_from_settings_disabled_returns_false(self):
        self._set_settings(use_ibanity_mtls=0)
        mgr = SecureCertManager()
        try:
            self.assertFalse(mgr.setup_from_settings())
            self.assertFalse(mgr.is_configured)
        finally:
            mgr._cleanup()

    def test_setup_from_settings_enabled_without_certs_returns_false(self):
        """mTLS on but no cert/key configured -> graceful False."""
        self._set_settings(
            use_ibanity_mtls=1, ibanity_certificate="", ibanity_private_key=""
        )
        mgr = SecureCertManager()
        try:
            self.assertFalse(mgr.setup_from_settings())
        finally:
            mgr._cleanup()

    def test_setup_from_settings_enabled_with_certs(self):
        """Valid cert + key in settings produces usable temp files."""
        self._set_settings(
            use_ibanity_mtls=1,
            ibanity_certificate=self.cert_pem,
            ibanity_private_key=self.key_pem,
        )
        mgr = SecureCertManager()
        try:
            self.assertTrue(mgr.setup_from_settings())
            cert_files = mgr.get_cert_files()
            self.assertIsNotNone(cert_files)
            cert_path, key_path = cert_files
            self.assertTrue(os.path.exists(cert_path))
            self.assertTrue(os.path.exists(key_path))
            self.assertEqual(stat.S_IMODE(os.stat(key_path).st_mode), 0o600)
        finally:
            mgr._cleanup()
