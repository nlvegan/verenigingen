"""
Shared SSH authentication helpers for MijnRood sync.

Used by both the database client and SFTP client (both use paramiko).
Extracts the key parsing and auth kwargs logic to avoid duplication.
"""

import io
import os

import paramiko

from verenigingen.utils.service_logger import get_service_logger

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="ssh_auth")


# Host-key algorithms we accept, modern first, legacy as fallback. Filtered
# at call time to whatever this paramiko build actually recognises — ssh-dss
# was dropped from _key_info in paramiko 4.x and would raise "unknown cipher".
_DESIRED_HOST_KEY_TYPES = (
    "rsa-sha2-512",
    "rsa-sha2-256",
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ssh-rsa",
    "ssh-dss",
)


def build_host_key_types() -> tuple[str, ...]:
    """Return host-key algorithms supported by this paramiko build.

    Needed because some shared hosts (e.g. DirectAdmin / OpenSSH 5.3)
    only offer ssh-rsa or ssh-dss host keys, and paramiko 3.x+ disables
    them by default → "no acceptable host key".
    """
    known = set(getattr(paramiko.Transport, "_key_info", {}).keys())
    return tuple(k for k in _DESIRED_HOST_KEY_TYPES if k in known)


def build_disabled_algorithms(settings) -> dict | None:
    """Return a paramiko ``disabled_algorithms`` dict for legacy SSH servers.

    Why: OpenSSH < 7.2 (e.g. CentOS 5/6, RHEL 6 with OpenSSH 5.3) predates
    RFC 8332 and only understands plain ``ssh-rsa`` (SHA-1) signatures for
    RSA pubkey auth. Paramiko 3.x offers ``rsa-sha2-512`` and ``rsa-sha2-256``
    first and relies on the ``server-sig-algs`` extension to fall back —
    but very old servers never send that extension, so the fallback is
    unreliable and auth fails with "Authentication failed" despite a
    correctly-installed public key.

    When ``ssh_legacy_compat`` is enabled on the settings, this disables
    rsa-sha2 signatures so paramiko sends ``ssh-rsa`` only. Default-off
    so modern servers still negotiate strong signatures.
    """
    if not getattr(settings, "ssh_legacy_compat", 0):
        return None
    return {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}


def load_system_host_keys() -> paramiko.HostKeys:
    """Load SSH known_hosts for host key verification.

    Checks ~/.ssh/known_hosts (standard location). Returns an empty
    HostKeys object if the file doesn't exist — host key verification
    will then log a warning but not block the connection (TOFU).
    """
    host_keys = paramiko.HostKeys()
    known_hosts = os.path.expanduser("~/.ssh/known_hosts")
    if os.path.isfile(known_hosts):
        try:
            host_keys.load(known_hosts)
            logger.debug("Loaded %d host keys from %s", len(host_keys), known_hosts)
        except Exception:
            logger.warning("Failed to parse %s — host key verification disabled", known_hosts)
    else:
        logger.debug("No known_hosts file at %s", known_hosts)
    return host_keys


def verify_host_key(
    transport: paramiko.Transport,
    host: str,
    port: int,
    host_keys: paramiko.HostKeys,
):
    """Verify the remote host key against known_hosts after connect.

    Logs a warning if the host is unknown (no entry in known_hosts).
    Raises paramiko.SSHException if the host key CHANGED (possible MITM).
    """
    remote_key = transport.get_remote_server_key()
    if remote_key is None:
        logger.warning("No host key received from %s:%s", host, port)
        return

    # paramiko HostKeys uses "[host]:port" format for non-standard ports
    host_entry = f"[{host}]:{port}" if port != 22 else host
    known_key = host_keys.lookup(host_entry)
    if known_key is None and port != 22:
        known_key = host_keys.lookup(host)

    if known_key is None:
        logger.warning(
            "Host key for %s:%s not found in known_hosts. Proceeding without "
            "verification. Pre-populate ~/.ssh/known_hosts for production use.",
            host,
            port,
        )
        return

    key_type = remote_key.get_name()
    expected = known_key.get(key_type)
    if expected is None:
        logger.warning(
            "Host %s:%s known_hosts has no %s key entry — cannot verify",
            host,
            port,
            key_type,
        )
        return

    if remote_key != expected:
        raise paramiko.SSHException(
            f"Host key for {host}:{port} has CHANGED "
            f"(expected {expected.get_fingerprint().hex()}, "
            f"got {remote_key.get_fingerprint().hex()}). "
            f"Possible man-in-the-middle attack. Update ~/.ssh/known_hosts "
            f"if the server key was intentionally rotated."
        )

    logger.info("Host key verified for %s:%s (%s)", host, port, key_type)


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
    key_classes = [
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
    ]
    # DSSKey removed in paramiko 4.0; skip if unavailable
    if hasattr(paramiko, "DSSKey"):
        key_classes.append(paramiko.DSSKey)
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

    The caller decides how to pass these to paramiko.Transport.

    Authentication priority: stored key > key file > password.

    Args:
        settings: MijnRood Sync Settings document.

    Returns:
        Dict with auth kwargs. Keys present depend on configured auth method.
    """
    import frappe

    result: dict = {}

    # ssh_key_passphrase is the canonical field for key passphrases.
    # ssh_password kept dedicated to SSH-login password auth. For
    # back-compat with installations that pre-date the split, fall back
    # to ssh_password when ssh_key_passphrase is empty.
    key_passphrase = (
        settings.get_password("ssh_key_passphrase") if getattr(settings, "ssh_key_passphrase", None) else None
    )
    login_password = settings.get_password("ssh_password") if settings.ssh_password else None
    if not key_passphrase:
        key_passphrase = login_password  # back-compat fallback

    # Priority 1: stored key (in Frappe's encrypted password store)
    stored_key = None
    if settings.ssh_private_key:
        try:
            stored_key = settings.get_password("ssh_private_key")
        except frappe.ValidationError:
            logger.debug("ssh_private_key field set but no key in password store — skipping")
    if stored_key and stored_key.strip().startswith("-----BEGIN"):
        pkey = parse_pkey_from_string(stored_key, key_passphrase)
        result["pkey"] = pkey
        logger.info("Using stored SSH private key (parsed in-memory)")
        return result

    # Priority 2: key file on disk
    if settings.ssh_private_key_path:
        key_path = settings.ssh_private_key_path
        if not os.path.isabs(key_path) or key_path.startswith("/private/"):
            key_path = frappe.get_site_path(key_path.lstrip("/"))
        result["key_filename"] = key_path
        if key_passphrase:
            result["passphrase"] = key_passphrase
        logger.info("Using SSH private key from file: %s", key_path)
        return result

    # Priority 3: password-only auth (no key configured)
    if login_password:
        result["password"] = login_password

    return result
