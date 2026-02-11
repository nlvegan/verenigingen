"""
SFTP client for downloading files from MijnRood server.

Reuses SSH credentials from MijnRood Sync Settings.
Uses paramiko Transport + SFTPClient directly (no sshtunnel dependency).

Security notes:
- Host key verification uses ~/.ssh/known_hosts when available. If the host
  is not found in known_hosts, the connection proceeds with a warning (same
  behaviour as sshtunnel's MijnRoodDatabaseClient). Administrators should
  pre-populate known_hosts on the server or use network-level controls.
- Private key material is never logged. Only metadata (key type, file path)
  appears in log output.
"""

import io
import logging
import os
import time
from typing import Optional

import paramiko

from verenigingen.mijnrood_sync.ssh_auth import build_ssh_auth_kwargs, parse_pkey_from_string

logger = logging.getLogger("verenigingen.mijnrood_sync.sftp_client")


class MijnRoodSFTPClient:
    """SFTP client for downloading files from MijnRood server.

    Reuses SSH credentials from MijnRood Sync Settings.
    Uses paramiko Transport + SFTPClient directly.
    """

    def __init__(self, settings=None):
        """Initialize with MijnRood Sync Settings document or load from DB.

        Args:
            settings: MijnRood Sync Settings document (or None to load).
        """
        if settings is None:
            import frappe

            settings = frappe.get_single("MijnRood Sync Settings")

        self._settings = settings
        self._transport: Optional[paramiko.Transport] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._remote_base = (settings.documents_remote_path or "").rstrip("/")
        self._host_keys = self._load_system_host_keys()

    def connect(self, *, max_retries: int = 3):
        """Open paramiko Transport and SFTP session.

        Retries up to *max_retries* times with exponential backoff.
        """
        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                self._open_transport()
                self._open_sftp()
                return
            except Exception as exc:
                last_error = exc
                self.disconnect()
                if attempt < max_retries:
                    delay = 2**attempt
                    logger.warning(
                        "SFTP connection attempt %d/%d failed: %s — retrying in %ds",
                        attempt,
                        max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        raise ConnectionError(f"SFTP: failed to connect after {max_retries} attempts") from last_error

    def disconnect(self):
        """Close SFTP session and transport."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None

        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def download_file(self, remote_filename: str) -> bytes:
        """Download a file from the remote documents directory.

        Args:
            remote_filename: The filename on the remote server (e.g. SHA1 hash name
                from MijnRood's admin_document.uploadFileName).

        Returns:
            File content as bytes.

        Raises:
            FileNotFoundError: If the remote file doesn't exist.
            IOError: On SFTP transfer errors.
        """
        if not self._sftp:
            raise ConnectionError("SFTP session not open — call connect() first")

        # Prevent path traversal — filenames from MijnRood's admin_document.uploadFileName
        # are SHA1 hashes (e.g. "a1b2c3d4...") but validate defensively
        if ".." in remote_filename or "/" in remote_filename or "\\" in remote_filename:
            raise ValueError(f"Invalid filename (path traversal attempt): {remote_filename!r}")

        remote_path = f"{self._remote_base}/{remote_filename}"

        buf = io.BytesIO()
        try:
            self._sftp.getfo(remote_path, buf)
        except FileNotFoundError:
            raise FileNotFoundError(f"Remote file not found: {remote_path}")
        except IOError as exc:
            raise IOError(f"SFTP download failed for {remote_path}: {exc}") from exc

        content = buf.getvalue()
        logger.debug("Downloaded %d bytes from %s", len(content), remote_path)
        return content

    def list_files(self) -> list[str]:
        """List files in the remote documents directory.

        Returns:
            List of filenames in the documents directory.
        """
        if not self._sftp:
            raise ConnectionError("SFTP session not open — call connect() first")

        try:
            return self._sftp.listdir(self._remote_base)
        except IOError as exc:
            raise IOError(f"SFTP listdir failed for {self._remote_base}: {exc}") from exc

    @staticmethod
    def _load_system_host_keys() -> paramiko.HostKeys:
        """Load SSH known_hosts for host key verification.

        Checks ~/.ssh/known_hosts (standard location). Returns an empty
        HostKeys object if the file doesn't exist — host key verification
        will log a warning but not block the connection (matching sshtunnel
        behaviour in MijnRoodDatabaseClient).
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

    def _verify_host_key(self, host: str, port: int):
        """Verify the remote host key against known_hosts after connecting.

        Logs a warning if the host is unknown (no entry in known_hosts).
        Raises SSHException if the host key CHANGED (possible MITM).
        """
        if not self._transport:
            return

        remote_key = self._transport.get_remote_server_key()
        if remote_key is None:
            logger.warning("No host key received from %s:%s", host, port)
            return

        # paramiko HostKeys uses "[host]:port" format for non-standard ports
        if port != 22:
            host_entry = f"[{host}]:{port}"
        else:
            host_entry = host

        known_key = self._host_keys.lookup(host_entry)
        if known_key is None:
            # Also try without port bracket for standard port entries
            known_key = self._host_keys.lookup(host) if port != 22 else None

        if known_key is None:
            logger.warning(
                "Host key for %s:%s not found in known_hosts. "
                "Proceeding without verification. Pre-populate ~/.ssh/known_hosts "
                "for production use.",
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

    def _open_transport(self):
        """Open paramiko Transport to MijnRood server."""
        s = self._settings
        host = s.ssh_host
        port = int(s.ssh_port or 22)

        self._transport = paramiko.Transport((host, port))

        auth = build_ssh_auth_kwargs(s)
        username = s.ssh_username

        if "pkey" in auth:
            self._transport.connect(username=username, pkey=auth["pkey"])
        elif "key_filename" in auth:
            # Load key from file — read content and parse via shared helper
            # to support all key types (RSA, Ed25519, ECDSA, DSS)
            passphrase = auth.get("passphrase")
            with open(auth["key_filename"], encoding="utf-8") as f:
                key_content = f.read()
            pkey = parse_pkey_from_string(key_content, passphrase)
            self._transport.connect(username=username, pkey=pkey)
        elif "password" in auth:
            self._transport.connect(username=username, password=auth["password"])
        else:
            # Try with no auth (e.g. agent-based)
            self._transport.connect(username=username)

        # Verify host key after connection (warns if unknown, raises if changed)
        self._verify_host_key(host, port)

        logger.info("SSH transport opened to %s:%s", host, port)

    def _open_sftp(self):
        """Open SFTP session on the existing transport."""
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        logger.info("SFTP session opened (remote base: %s)", self._remote_base)
