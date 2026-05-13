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
import time
from typing import Optional

import paramiko

from verenigingen.mijnrood_sync.ssh_auth import (
    build_disabled_algorithms,
    build_host_key_types,
    build_ssh_auth_kwargs,
    load_system_host_keys,
    parse_pkey_from_string,
    verify_host_key,
)

logger = logging.getLogger("verenigingen.mijnrood_sync.sftp_client")


DEFAULT_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB per file


class FileTooLargeError(IOError):
    """Raised when a remote file exceeds the configured size cap."""


class MijnRoodSFTPClient:
    """SFTP client for downloading files from MijnRood server.

    Reuses SSH credentials from MijnRood Sync Settings.
    Uses paramiko Transport + SFTPClient directly.
    """

    def __init__(self, settings=None, max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES):
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
        self._host_keys = load_system_host_keys()
        self._max_download_bytes = max_download_bytes

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
            except (paramiko.AuthenticationException, paramiko.BadHostKeyException) as exc:
                # Non-transient: bad credentials or host-key mismatch.
                # Don't burn retries (3 attempts × 14s backoff) on a config error.
                self.disconnect()
                raise ConnectionError(f"SFTP authentication failed: {exc}") from exc
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

        # Reject oversized files before allocating memory — protects workers
        # from OOM on a single huge remote file. stat() is cheap (one SFTP
        # round-trip) and the size is authoritative for legitimate uploads.
        try:
            attrs = self._sftp.stat(remote_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Remote file not found: {remote_path}")
        except IOError as exc:
            raise IOError(f"SFTP stat failed for {remote_path}: {exc}") from exc

        size = getattr(attrs, "st_size", None)
        if size is not None and size > self._max_download_bytes:
            raise FileTooLargeError(
                f"Remote file {remote_path} is {size} bytes, "
                f"exceeds cap of {self._max_download_bytes} bytes"
            )

        buf = io.BytesIO()
        try:
            self._sftp.getfo(remote_path, buf)
        except FileNotFoundError:
            raise FileNotFoundError(f"Remote file not found: {remote_path}")
        except IOError as exc:
            raise IOError(f"SFTP download failed for {remote_path}: {exc}") from exc

        content = buf.getvalue()
        # Defence in depth: stat() can be stale; verify post-download too.
        if len(content) > self._max_download_bytes:
            raise FileTooLargeError(
                f"Remote file {remote_path} downloaded {len(content)} bytes, "
                f"exceeds cap of {self._max_download_bytes} bytes"
            )
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

    def _open_transport(self):
        """Open paramiko Transport to MijnRood server."""
        s = self._settings
        host = s.ssh_host
        port = int(s.ssh_port or 22)

        # ssh_legacy_compat (settings) disables rsa-sha2 pubkey signatures
        # so paramiko sends ssh-rsa (SHA-1) only — needed for OpenSSH < 7.2.
        # See ssh_auth.build_disabled_algorithms() for rationale.
        disabled_algorithms = build_disabled_algorithms(s)
        if disabled_algorithms:
            self._transport = paramiko.Transport((host, port), disabled_algorithms=disabled_algorithms)
        else:
            self._transport = paramiko.Transport((host, port))

        # Some shared hosts (e.g. DirectAdmin / OpenSSH 5.3) only offer
        # ssh-rsa and ssh-dss for the host key. paramiko 3.x rejects both
        # by default, producing "no acceptable host key". Re-enable them
        # as fallbacks while keeping modern algorithms preferred. Filter
        # against this paramiko build's known algorithms — ssh-dss was
        # removed from _key_info in paramiko 4.x and would raise
        # "unknown cipher" otherwise.
        opts = self._transport.get_security_options()
        opts.key_types = build_host_key_types()

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
        verify_host_key(self._transport, host, port, self._host_keys)

        logger.info("SSH transport opened to %s:%s", host, port)

    def _open_sftp(self):
        """Open SFTP session on the existing transport."""
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        logger.info("SFTP session opened (remote base: %s)", self._remote_base)
