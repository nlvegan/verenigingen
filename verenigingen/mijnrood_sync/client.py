"""
MijnRood Database Client

Read-only client for MijnRood's MariaDB via SSH tunnel.
Uses sshtunnel for SSH port forwarding and pymysql for database access.
All queries are SELECT-only — no writes to MijnRood.
"""

import base64
import logging
import os
import re
import time
from typing import Optional

import pymysql
import pymysql.cursors
from sshtunnel import SSHTunnelForwarder

from verenigingen.mijnrood_sync.field_mapping import (
    ALLOWED_TABLES,
    TABLE_COLUMNS,
    TABLE_PRIMARY_KEY,
)
from verenigingen.mijnrood_sync.ssh_auth import build_ssh_auth_kwargs, parse_pkey_from_string

logger = logging.getLogger("verenigingen.mijnrood_sync.client")


_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_CHUNK_SIZE = 500


class MijnRoodDatabaseClient:
    """Read-only client for MijnRood's MariaDB via SSH tunnel.

    Security assumptions:
    - Table and column names are validated against ALLOWED_TABLES and a strict
      identifier regex before interpolation into SQL. No user-supplied strings
      reach SQL without validation.
    - SSH authentication uses private keys stored in Frappe's encrypted password
      store (preferred) or key files on the filesystem. When using file-based keys,
      file permissions must be restricted to 0600 by the administrator.
    - sshtunnel does NOT verify SSH host keys by default. Administrators must
      ensure host authenticity via known_hosts, network-level controls, or VPN.
    - Credentials and secrets are never written to logs. Only table names, row
      counts, and non-sensitive metadata appear in log output.
    """

    def __init__(self, settings=None):
        """Initialize with MijnRood Sync Settings document or load from DB.

        Args:
            settings: MijnRood Sync Settings document (or None to load)
        """
        if settings is None:
            import frappe

            settings = frappe.get_single("MijnRood Sync Settings")

        self._settings = settings
        self._tunnel: Optional[SSHTunnelForwarder] = None
        self._connection: Optional[pymysql.Connection] = None

    def connect(self, *, max_retries: int = 3):
        """Open SSH tunnel then MariaDB connection.

        Retries up to *max_retries* times with exponential backoff (2s, 4s, 8s)
        on transient connection failures. Partial state is cleaned up between
        attempts via disconnect().
        """
        last_error: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                self._open_tunnel()
                self._open_connection()
                return
            except Exception as exc:
                last_error = exc
                self.disconnect()
                if attempt < max_retries:
                    delay = 2**attempt
                    logger.warning(
                        "Connection attempt %d/%d failed: %s — retrying in %ds",
                        attempt,
                        max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        raise ConnectionError(f"Failed to connect after {max_retries} attempts") from last_error

    def disconnect(self):
        """Close connection and tunnel."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

        if self._tunnel:
            try:
                self._tunnel.stop()
            except Exception:
                pass
            self._tunnel = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    @staticmethod
    def _validate_identifier(name: str, label: str = "identifier") -> None:
        """Validate that a name is a safe SQL identifier.

        Args:
            name: The identifier to validate.
            label: Human-readable label for error messages.

        Raises:
            ValueError: If the name contains unsafe characters.
        """
        if not _IDENTIFIER_RE.match(name):
            raise ValueError(f"Invalid {label}: {name!r}")

    @staticmethod
    def _validate_table_name(table: str) -> None:
        """Validate that a table name is in the allowed whitelist.

        Args:
            table: MijnRood table name to validate.

        Raises:
            ValueError: If the table is not in ALLOWED_TABLES or has invalid characters.
        """
        if table not in ALLOWED_TABLES:
            raise ValueError(
                f"Table {table!r} is not in ALLOWED_TABLES. " f"Allowed: {sorted(ALLOWED_TABLES)}"
            )
        if not _IDENTIFIER_RE.match(table):
            raise ValueError(f"Invalid table name: {table!r}")

    @staticmethod
    def _parse_pkey_from_string(key_content: str, passphrase: str | None = None) -> "paramiko.PKey":
        """Parse an SSH private key from a string. Delegates to ssh_auth module."""
        return parse_pkey_from_string(key_content, passphrase)

    def _open_tunnel(self):
        """Open SSH tunnel to MijnRood server."""
        s = self._settings
        ssh_kwargs = {
            "ssh_address_or_host": (s.ssh_host, int(s.ssh_port or 22)),
            "ssh_username": s.ssh_username,
            "remote_bind_address": (s.db_host or "127.0.0.1", int(s.db_port or 3306)),
        }

        # Build auth kwargs from shared helper, then translate to sshtunnel's API
        auth = build_ssh_auth_kwargs(s)
        if "pkey" in auth:
            ssh_kwargs["ssh_pkey"] = auth["pkey"]
        elif "key_filename" in auth:
            ssh_kwargs["ssh_pkey"] = auth["key_filename"]
            if "passphrase" in auth:
                ssh_kwargs["ssh_private_key_password"] = auth["passphrase"]
        elif "password" in auth:
            ssh_kwargs["ssh_password"] = auth["password"]

        # NOTE: SSHTunnelForwarder does not verify SSH host keys by default.
        # Administrators must ensure host authenticity through one of:
        #   1. Pre-populating ~/.ssh/known_hosts on the server
        #   2. Network-level controls (VPN, private network)
        #   3. Passing ssh_host_key to SSHTunnelForwarder
        self._tunnel = SSHTunnelForwarder(**ssh_kwargs)
        self._tunnel.start()
        logger.info(
            "SSH tunnel opened to %s:%s → local port %s",
            s.ssh_host,
            s.ssh_port,
            self._tunnel.local_bind_port,
        )

    def _open_connection(self):
        """Open pymysql connection through the SSH tunnel."""
        s = self._settings
        db_password = s.get_password("db_password") if s.db_password else ""

        self._connection = pymysql.connect(
            host="127.0.0.1",
            port=self._tunnel.local_bind_port,
            user=s.db_username,
            password=db_password,
            database=s.db_name or "rood",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=30,
            read_timeout=120,
        )
        logger.info("Connected to MijnRood database: %s", s.db_name)

    def test_query(self) -> int:
        """Run a simple test query. Returns row count of admin_member."""
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM admin_member")
            result = cursor.fetchone()
            return result["cnt"] if result else 0

    def fetch_row_checksums(self, table: str) -> dict[int, str]:
        """Compute MD5 checksum for each row in a table, DB-side.

        Uses MySQL's MD5(CONCAT_WS('|', col1, col2, ...)) so the hash is
        computed server-side in a single query. Only the ID and checksum are
        transferred — no need to fetch full rows for unchanged records.

        MD5 returns a 32-char hex string (128-bit) which is vastly more
        collision-resistant than CRC32 (32-bit) with negligible performance cost.

        Args:
            table: MijnRood table name (e.g. 'admin_member')

        Returns:
            Dict mapping row ID → checksum hex string
        """
        self._validate_table_name(table)
        pk = TABLE_PRIMARY_KEY[table]
        self._validate_identifier(pk, "primary key")

        columns = TABLE_COLUMNS.get(table)
        if columns:
            col_names = columns
        else:
            col_names = self._get_table_columns(table)

        for col in col_names:
            self._validate_identifier(col, "column")

        col_expressions = ", ".join(f"COALESCE(`{col}`, '')" for col in col_names)
        concat_expr = f"CONCAT_WS('|', {col_expressions})"

        query = f"SELECT `{pk}`, MD5({concat_expr}) AS checksum FROM `{table}`"  # noqa: S608

        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        result = {}
        for row in rows:
            row_id = row[pk]
            checksum = str(row["checksum"])
            result[row_id] = checksum

        logger.debug("Fetched %d checksums from %s", len(result), table)
        return result

    def fetch_rows_by_ids(self, table: str, ids: list[int]) -> list[dict]:
        """Fetch row data for specific IDs (explicit columns only).

        IDs are batched into chunks of _CHUNK_SIZE to stay within MariaDB's
        parameter limits. Results from all chunks are combined.

        Only columns listed in TABLE_COLUMNS are fetched — sensitive columns
        (password_hash, new_password_token, etc.) are never transferred.

        Args:
            table: MijnRood table name
            ids: List of primary key values to fetch

        Returns:
            List of row dicts
        """
        if not ids:
            return []

        self._validate_table_name(table)
        pk = TABLE_PRIMARY_KEY[table]
        self._validate_identifier(pk, "primary key")
        col_list = self._build_select_columns(table)

        all_rows: list[dict] = []
        for i in range(0, len(ids), _CHUNK_SIZE):
            chunk = ids[i : i + _CHUNK_SIZE]
            placeholders = ", ".join(["%s"] * len(chunk))
            query = f"SELECT {col_list} FROM `{table}` WHERE `{pk}` IN ({placeholders})"  # noqa: S608

            with self._connection.cursor() as cursor:
                cursor.execute(query, chunk)
                rows = cursor.fetchall()
            all_rows.extend(self._serialize_row(row) for row in rows)

        if table == "admin_division":
            self._resolve_division_emails(all_rows)

        return all_rows

    def fetch_all_rows(self, table: str) -> list[dict]:
        """Fetch all rows from a table (explicit columns only).

        Only columns listed in TABLE_COLUMNS are fetched — sensitive columns
        (password_hash, new_password_token, etc.) are never transferred.

        Args:
            table: MijnRood table name

        Returns:
            List of row dicts
        """
        self._validate_table_name(table)
        col_list = self._build_select_columns(table)
        query = f"SELECT {col_list} FROM `{table}`"  # noqa: S608

        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        return [self._serialize_row(row) for row in rows]

    def _build_select_columns(self, table: str) -> str:
        """Build a backtick-quoted, comma-separated column list for SELECT.

        Uses TABLE_COLUMNS if available, otherwise falls back to
        information_schema (for tables not yet registered in TABLE_COLUMNS).
        Each column name is validated against the identifier regex.

        Args:
            table: MijnRood table name (already validated)

        Returns:
            SQL column list string, e.g. "`id`, `first_name`, `last_name`"
        """
        columns = TABLE_COLUMNS.get(table)
        if not columns:
            logger.warning(
                "Table '%s' not in TABLE_COLUMNS — falling back to information_schema (all columns selected)",
                table,
            )
            columns = self._get_table_columns(table)
        for col in columns:
            self._validate_identifier(col, "column")
        return ", ".join(f"`{col}`" for col in columns)

    def _get_table_columns(self, table: str) -> list[str]:
        """Get column names for a table from information_schema."""
        self._validate_table_name(table)
        query = (
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(query, (self._settings.db_name or "rood", table))
            rows = cursor.fetchall()
        return [row["COLUMN_NAME"] for row in rows]

    def _resolve_division_emails(self, rows: list[dict]) -> None:
        """Resolve email_id FKs on admin_division rows to actual email addresses.

        MijnRood stores division emails as a FK chain:
            admin_division.email_id → admin_email.id (user + domain_id)
            admin_email.domain_id → admin_email_domain.id (domain)
            Full address = admin_email.user + '@' + admin_email_domain.domain

        This method batch-resolves all email_id values in the given rows and
        replaces the numeric FK with the resolved email string (or None).
        """
        email_ids = [r["email_id"] for r in rows if r.get("email_id")]
        if not email_ids:
            return

        placeholders = ", ".join(["%s"] * len(email_ids))
        query = (
            f"SELECT e.`id`, CONCAT(e.`user`, '@', d.`domain`) AS `email_address` "  # noqa: S608
            f"FROM `admin_email` e "
            f"JOIN `admin_email_domain` d ON e.`domain_id` = d.`id` "
            f"WHERE e.`id` IN ({placeholders})"
        )

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, email_ids)
                result = cursor.fetchall()
            email_map = {r["id"]: r["email_address"] for r in result}
        except Exception:
            logger.warning("Failed to resolve division email_id FKs — leaving as numeric IDs", exc_info=True)
            return

        for row in rows:
            eid = row.get("email_id")
            if eid and eid in email_map:
                row["email_id"] = email_map[eid]
            elif eid:
                # FK exists but no matching email record — clear rather than keep numeric ID
                row["email_id"] = None

    def fetch_division_contacts(self) -> dict[int, list[int]]:
        """Fetch division_member join table, grouped by member_id.

        This is a junction table (~50 rows) mapping admin_member ↔ admin_division
        for ROLE_DIVISION_CONTACT assignments. Not part of the regular sync
        (no ALLOWED_TABLES entry) — queried directly with hardcoded column names.

        Returns:
            Dict mapping member_id → sorted list of division_ids they manage.
        """
        query = "SELECT `member_id`, `division_id` FROM `division_member` ORDER BY `member_id`"
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        contacts: dict[int, list[int]] = {}
        for row in rows:
            mid = row["member_id"]
            did = row["division_id"]
            contacts.setdefault(mid, []).append(did)

        # Sort division lists for consistent comparison
        for mid in contacts:
            contacts[mid].sort()

        logger.info("Fetched %d division contact assignments (%d members)", len(rows), len(contacts))
        return contacts

    def fetch_membership_statuses(self) -> list[dict]:
        """Fetch all rows from admin_membershipstatus (id, name, allowed_access).

        This is a static lookup table, not part of the regular sync.
        Column names are hardcoded — no user input reaches SQL.
        """
        query = "SELECT `id`, `name`, `allowed_access` FROM `admin_membershipstatus` ORDER BY `id`"
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        logger.info("Fetched %d membership statuses from admin_membershipstatus", len(rows))
        return [self._serialize_row(row) for row in rows]

    def fetch_document_folders(self) -> list[dict]:
        """Fetch all document folders (id, name, parent_id).

        Queries admin_document_folder directly — not part of the regular
        checksum-based sync. Column names are hardcoded.

        Returns:
            List of dicts with id, name, parent_id keys.
        """
        query = "SELECT `id`, `name`, `parent_id` FROM `admin_document_folder` ORDER BY `id`"
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        logger.info("Fetched %d document folders from admin_document_folder", len(rows))
        return [self._serialize_row(row) for row in rows]

    def fetch_documents(self) -> list[dict]:
        """Fetch all documents (id, name, uploadFileName, sizeInBytes, dateUploaded, folder_id).

        Queries admin_document directly — not part of the regular
        checksum-based sync. Column names are hardcoded.

        Returns:
            List of dicts with document metadata.
        """
        query = (
            "SELECT `id`, `name`, `uploadFileName`, `sizeInBytes`, "
            "`dateUploaded`, `folder_id` "
            "FROM `admin_document` ORDER BY `id`"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
        logger.info("Fetched %d documents from admin_document", len(rows))
        return [self._serialize_row(row) for row in rows]

    @staticmethod
    def _serialize_row(row: dict) -> dict:
        """Convert row values to JSON-serializable types.

        Handles datetime, date, bytes, Decimal, etc.
        """
        import datetime
        from decimal import Decimal

        serialized = {}
        for key, value in row.items():
            if isinstance(value, (datetime.datetime, datetime.date)):
                serialized[key] = value.isoformat()
            elif isinstance(value, Decimal):
                serialized[key] = float(value)
            elif isinstance(value, bytes):
                serialized[key] = base64.b64encode(value).decode("ascii")
            elif value is None:
                serialized[key] = None
            else:
                serialized[key] = value
        return serialized
