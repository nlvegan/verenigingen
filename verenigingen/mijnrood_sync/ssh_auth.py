"""
Shared SSH authentication helpers for MijnRood sync.

Used by both the database client (sshtunnel) and SFTP client (paramiko).
Extracts the key parsing and auth kwargs logic to avoid duplication.
"""

import io
import logging
import os
from typing import Optional

import paramiko

logger = logging.getLogger("verenigingen.mijnrood_sync.ssh_auth")


def parse_pkey_from_string(key_content: str, passphrase: str | None = None) -> paramiko.PKey:
    """Parse an SSH private key from a string into a paramiko PKey object.

    Tries RSA, Ed25519, ECDSA, and DSS key types in order.

    Args:
        key_content: PEM-encoded private key string.
        passphrase: Optional passphrase for encrypted keys.

    Returns:
        A paramiko PKey instance.

    Raises:
        ValueError: If the key cannot be parsed as any supported type.
    """
    key_classes = (
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.DSSKey,
    )
    for key_class in key_classes:
        try:
            return key_class.from_private_key(io.StringIO(key_content), password=passphrase)
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("Unable to parse SSH private key — unsupported key type or wrong passphrase")


def build_ssh_auth_kwargs(settings) -> dict:
    """Build SSH authentication kwargs from MijnRood Sync Settings.

    Returns a dict with:
    - 'pkey': parsed paramiko.PKey (if key auth configured)
    - 'password': str (if password-only auth)

    The caller decides how to pass these to sshtunnel or paramiko.Transport.

    Authentication priority: stored key > key file > password.

    Args:
        settings: MijnRood Sync Settings document.

    Returns:
        Dict with auth kwargs. Keys present depend on configured auth method.
    """
    import frappe

    result: dict = {}

    passphrase = settings.get_password("ssh_password") if settings.ssh_password else None

    # Priority 1: stored key (in Frappe's encrypted password store)
    stored_key = settings.get_password("ssh_private_key") if settings.ssh_private_key else None
    if stored_key:
        pkey = parse_pkey_from_string(stored_key, passphrase)
        result["pkey"] = pkey
        logger.info("Using stored SSH private key (parsed in-memory)")
        return result

    # Priority 2: key file on disk
    if settings.ssh_private_key_path:
        key_path = settings.ssh_private_key_path
        if not os.path.isabs(key_path) or key_path.startswith("/private/"):
            key_path = frappe.get_site_path(key_path.lstrip("/"))
        result["key_filename"] = key_path
        if passphrase:
            result["passphrase"] = passphrase
        logger.info("Using SSH private key from file: %s", key_path)
        return result

    # Priority 3: password only
    if passphrase:
        result["password"] = passphrase

    return result
