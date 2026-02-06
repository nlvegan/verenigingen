"""
MijnRood Database Client

Read-only client for MijnRood's MariaDB via SSH tunnel.
Uses sshtunnel for SSH port forwarding and pymysql for database access.
All queries are SELECT-only — no writes to MijnRood.
"""

import logging
from typing import Optional

import pymysql
import pymysql.cursors
from sshtunnel import SSHTunnelForwarder

from verenigingen.mijnrood_sync.field_mapping import TABLE_COLUMNS, TABLE_PRIMARY_KEY

logger = logging.getLogger("verenigingen.mijnrood_sync.client")


class MijnRoodDatabaseClient:
    """Read-only client for MijnRood's MariaDB via SSH tunnel."""

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

    def connect(self):
        """Open SSH tunnel then MariaDB connection."""
        self._open_tunnel()
        self._open_connection()

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

    def _open_tunnel(self):
        """Open SSH tunnel to MijnRood server."""
        s = self._settings
        ssh_kwargs = {
            "ssh_address_or_host": (s.ssh_host, int(s.ssh_port or 22)),
            "ssh_username": s.ssh_username,
            "remote_bind_address": (s.db_host or "127.0.0.1", int(s.db_port or 3306)),
        }

        # Authentication: prefer key file, fall back to password
        if s.ssh_private_key_path:
            ssh_kwargs["ssh_pkey"] = s.ssh_private_key_path
            password = s.get_password("ssh_password") if s.ssh_password else None
            if password:
                ssh_kwargs["ssh_private_key_password"] = password
        else:
            password = s.get_password("ssh_password") if s.ssh_password else None
            if password:
                ssh_kwargs["ssh_password"] = password

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
        """Compute CRC32 checksum for each row in a table, DB-side.

        Uses MySQL's CRC32(CONCAT_WS('|', col1, col2, ...)) so the hash is
        computed server-side in a single query. Only the ID and checksum are
        transferred — no need to fetch full rows for unchanged records.

        Args:
            table: MijnRood table name (e.g. 'admin_member')

        Returns:
            Dict mapping row ID → checksum hex string
        """
        pk = TABLE_PRIMARY_KEY.get(table, "id")
        columns = TABLE_COLUMNS.get(table)

        if columns:
            # Build CONCAT_WS of specific columns, coalescing NULLs
            col_expressions = ", ".join(f"COALESCE(`{col}`, '')" for col in columns)
            concat_expr = f"CONCAT_WS('|', {col_expressions})"
        else:
            # Fallback: use all columns via SELECT * approach
            # First get column names from information_schema
            col_names = self._get_table_columns(table)
            col_expressions = ", ".join(f"COALESCE(`{col}`, '')" for col in col_names)
            concat_expr = f"CONCAT_WS('|', {col_expressions})"

        query = f"SELECT `{pk}`, CRC32({concat_expr}) AS checksum FROM `{table}`"  # noqa: S608

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
        """Fetch full row data for specific IDs.

        Args:
            table: MijnRood table name
            ids: List of primary key values to fetch

        Returns:
            List of row dicts
        """
        if not ids:
            return []

        pk = TABLE_PRIMARY_KEY.get(table, "id")
        placeholders = ", ".join(["%s"] * len(ids))
        query = f"SELECT * FROM `{table}` WHERE `{pk}` IN ({placeholders})"  # noqa: S608

        with self._connection.cursor() as cursor:
            cursor.execute(query, ids)
            rows = cursor.fetchall()

        # Convert non-serializable types to strings for JSON storage
        return [self._serialize_row(row) for row in rows]

    def fetch_all_rows(self, table: str) -> list[dict]:
        """Fetch all rows from a table.

        Args:
            table: MijnRood table name

        Returns:
            List of row dicts
        """
        query = f"SELECT * FROM `{table}`"  # noqa: S608

        with self._connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        return [self._serialize_row(row) for row in rows]

    def _get_table_columns(self, table: str) -> list[str]:
        """Get column names for a table from information_schema."""
        query = (
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(query, (self._settings.db_name or "rood", table))
            rows = cursor.fetchall()
        return [row["COLUMN_NAME"] for row in rows]

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
                serialized[key] = value.decode("utf-8", errors="replace")
            elif value is None:
                serialized[key] = None
            else:
                serialized[key] = value
        return serialized
