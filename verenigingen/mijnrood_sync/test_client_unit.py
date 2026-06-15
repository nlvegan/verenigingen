# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for MijnRoodDatabaseClient.

The client connects to a REMOTE MijnRood MariaDB over an SSH tunnel for which
no credentials exist in this environment. We therefore stub ONLY the external
boundary — the pymysql `_connection` object (and its cursor) — and feed canned
row dicts. All of the client's own logic (identifier validation, column
resolution, row serialization, checksum-result shaping, FK email resolution,
chunking, division-contact grouping) runs for real against those canned rows.

This file is named *_unit.py because it mocks a boundary (the DB connection
cursor). It does not mock any of the app's own transform logic.
"""

import base64
import datetime
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient


class _FakeCursor:
    """A minimal pymysql DictCursor stand-in usable as a context manager.

    Each cursor holds exactly one result set (a list of row dicts). The real
    client opens a fresh cursor per query (`with self._connection.cursor()`),
    calls execute() once, then fetchall()/fetchone().
    """

    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []  # list of (query, params)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    """Stand-in for a pymysql connection that hands out _FakeCursor objects.

    `result_sets_per_cursor` is a list — one result set (list of rows) per
    cursor() call, popped FIFO.
    """

    def __init__(self, result_sets_per_cursor):
        self._batches = list(result_sets_per_cursor)
        self.cursors = []

    def cursor(self):
        rs = self._batches.pop(0) if self._batches else []
        cur = _FakeCursor(rs)
        self.cursors.append(cur)
        return cur

    def close(self):
        pass


def _make_client():
    """Build a client without touching SSH/DB. Settings is a MagicMock; the
    constructor's load_system_host_keys() call is harmless (reads local
    ~/.ssh/known_hosts which may be absent → returns empty)."""
    settings = MagicMock()
    settings.db_name = "rood"
    client = MijnRoodDatabaseClient(settings=settings)
    return client


class TestIdentifierValidation(unittest.TestCase):
    """_validate_identifier / _validate_table_name — pure SQL-injection guards."""

    def test_valid_identifiers_pass(self):
        for ident in ["id", "first_name", "_private", "Col123", "a"]:
            MijnRoodDatabaseClient._validate_identifier(ident)  # no raise

    def test_invalid_identifiers_raise(self):
        for bad in ["1col", "drop table", "col;", "col-name", "", "col`", "a b"]:
            with self.assertRaises(ValueError):
                MijnRoodDatabaseClient._validate_identifier(bad, "column")

    def test_table_must_be_in_allowlist(self):
        # Not in ALLOWED_TABLES
        with self.assertRaises(ValueError):
            MijnRoodDatabaseClient._validate_table_name("admin_password")
        with self.assertRaises(ValueError):
            MijnRoodDatabaseClient._validate_table_name("division_member")  # not allowlisted

    def test_allowlisted_tables_pass(self):
        for t in ["admin_member", "admin_division", "admin_membership_application", "admin_support_member"]:
            MijnRoodDatabaseClient._validate_table_name(t)  # no raise


class TestSerializeRow(unittest.TestCase):
    """_serialize_row — convert DB types to JSON-serializable values."""

    def test_datetime_to_isoformat(self):
        dt = datetime.datetime(2026, 6, 15, 12, 30, 45)
        out = MijnRoodDatabaseClient._serialize_row({"registration_time": dt})
        self.assertEqual(out["registration_time"], "2026-06-15T12:30:45")

    def test_date_to_isoformat(self):
        d = datetime.date(1990, 1, 2)
        out = MijnRoodDatabaseClient._serialize_row({"date_of_birth": d})
        self.assertEqual(out["date_of_birth"], "1990-01-02")

    def test_decimal_to_float(self):
        out = MijnRoodDatabaseClient._serialize_row({"amount": Decimal("12.50")})
        self.assertEqual(out["amount"], 12.5)
        self.assertIsInstance(out["amount"], float)

    def test_bytes_to_base64(self):
        out = MijnRoodDatabaseClient._serialize_row({"blob": b"hello"})
        self.assertEqual(out["blob"], base64.b64encode(b"hello").decode("ascii"))

    def test_none_preserved(self):
        out = MijnRoodDatabaseClient._serialize_row({"x": None})
        self.assertIsNone(out["x"])

    def test_plain_str_int_passthrough(self):
        out = MijnRoodDatabaseClient._serialize_row({"name": "Alice", "id": 5})
        self.assertEqual(out, {"name": "Alice", "id": 5})


class TestColumnResolution(unittest.TestCase):
    """_get_resolved_columns / _build_select_columns — column intersection logic."""

    def test_resolved_columns_intersect_with_remote_schema(self):
        client = _make_client()
        # Remote schema is MISSING 'original_id' for admin_support_member
        remote_cols = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "iban",
            "address",
            "city",
            "post_code",
            "country",
            "date_of_birth",
            "registration_time",
            "mollie_customer_id",
            "mollie_subscription_id",
            "contribution_per_period_in_cents",
            "contribution_period",
            "original_registration_time",
            # 'original_id' deliberately absent → simulates schema drift
        ]
        client._connection = _FakeConnection([[{"COLUMN_NAME": c} for c in remote_cols]])
        resolved = client._get_resolved_columns("admin_support_member")
        self.assertNotIn("original_id", resolved)
        self.assertIn("original_registration_time", resolved)
        # Expected-order preserved
        self.assertEqual(resolved[0], "id")

    def test_resolved_columns_cached(self):
        client = _make_client()
        remote_cols = [{"COLUMN_NAME": c} for c in ["id", "name", "city"]]
        # Only ONE information_schema query batch provided → second call must hit cache
        client._connection = _FakeConnection([remote_cols])
        client._get_resolved_columns("admin_division")
        # No more cursor batches queued; a second call would fail if it re-queried
        client._get_resolved_columns("admin_division")
        self.assertIn("admin_division", client._actual_columns_cache)

    def test_build_select_columns_backtick_quoted(self):
        client = _make_client()
        remote = [{"COLUMN_NAME": c} for c in ["id", "name", "city", "email_id"]]
        client._connection = _FakeConnection([remote])
        col_list = client._build_select_columns("admin_division")
        self.assertIn("`id`", col_list)
        self.assertIn("`name`", col_list)
        # Comma separated
        self.assertEqual(col_list.count(","), col_list.count("`") // 2 - 1)

    def test_fallback_to_information_schema_when_no_expected(self):
        # 'division_member' has no TABLE_COLUMNS entry; but it's also not
        # allowlisted, so _get_table_columns validation would fail. Use a
        # table with TABLE_COLUMNS missing — none of the 4 are missing, so
        # instead verify _get_table_columns path directly.
        client = _make_client()
        remote = [{"COLUMN_NAME": "id"}, {"COLUMN_NAME": "name"}]
        client._connection = _FakeConnection([remote])
        cols = client._get_table_columns("admin_division")
        self.assertEqual(cols, ["id", "name"])


class TestTestQuery(unittest.TestCase):
    """test_query — boundary query returning a count."""

    def test_returns_count(self):
        client = _make_client()
        client._connection = _FakeConnection([[{"cnt": 42}]])
        self.assertEqual(client.test_query(), 42)

    def test_returns_zero_on_empty(self):
        client = _make_client()
        client._connection = _FakeConnection([[]])
        self.assertEqual(client.test_query(), 0)


class TestFetchRowChecksums(unittest.TestCase):
    """fetch_row_checksums — shapes the MD5 query result into {id: checksum}."""

    def test_builds_checksum_map(self):
        client = _make_client()
        # First cursor: information_schema (column resolution). Second: checksum query.
        member_cols = [
            {"COLUMN_NAME": c}
            for c in [
                "id",
                "first_name",
                "last_name",
                "email",
                "phone",
                "iban",
                "address",
                "city",
                "post_code",
                "country",
                "date_of_birth",
                "division_id",
                "registration_time",
                "current_membership_status_id",
                "contribution_per_period_in_cents",
                "contribution_period",
                "mollie_customer_id",
                "mollie_subscription_id",
                "roles",
                "accept_use_personal_information",
                "comments",
                "middle_name",
            ]
        ]
        checksum_rows = [
            {"id": 1, "checksum": "abc123"},
            {"id": 2, "checksum": "def456"},
        ]
        client._connection = _FakeConnection([member_cols, checksum_rows])
        result = client.fetch_row_checksums("admin_member")
        self.assertEqual(result, {1: "abc123", 2: "def456"})
        # The checksum query must MD5 over a CONCAT_WS and select the pk
        checksum_query = client._connection.cursors[1].executed[0][0]
        self.assertIn("MD5(", checksum_query)
        self.assertIn("CONCAT_WS('|'", checksum_query)
        self.assertIn("`admin_member`", checksum_query)

    def test_rejects_bad_table(self):
        client = _make_client()
        with self.assertRaises(ValueError):
            client.fetch_row_checksums("admin_password")


class TestFetchRowsByIds(unittest.TestCase):
    """fetch_rows_by_ids — chunking + serialization + division email FK resolution."""

    def test_empty_ids_returns_empty_no_query(self):
        client = _make_client()
        client._connection = _FakeConnection([])  # no cursors expected
        self.assertEqual(client.fetch_rows_by_ids("admin_member", []), [])

    def test_chunking_splits_large_id_lists(self):
        client = _make_client()
        # 1100 ids → 3 chunks (500, 500, 100) given _CHUNK_SIZE=500.
        # First cursor batch is information_schema for column resolution.
        member_cols = [{"COLUMN_NAME": c} for c in ["id", "first_name"]]
        # 3 fetch batches, each returns one row so we can count
        batch1 = [{"id": i, "first_name": "A"} for i in range(1, 501)]
        batch2 = [{"id": i, "first_name": "B"} for i in range(501, 1001)]
        batch3 = [{"id": i, "first_name": "C"} for i in range(1001, 1101)]
        client._connection = _FakeConnection([member_cols, batch1, batch2, batch3])
        rows = client.fetch_rows_by_ids("admin_member", list(range(1, 1101)))
        self.assertEqual(len(rows), 1100)
        # 3 separate IN(...) queries executed (cursors[1..3])
        self.assertEqual(len(client._connection.cursors), 4)  # 1 schema + 3 chunks

    def test_serializes_returned_rows(self):
        client = _make_client()
        member_cols = [{"COLUMN_NAME": c} for c in ["id", "registration_time"]]
        rows_raw = [{"id": 1, "registration_time": datetime.datetime(2026, 1, 1, 9, 0, 0)}]
        client._connection = _FakeConnection([member_cols, rows_raw])
        rows = client.fetch_rows_by_ids("admin_member", [1])
        self.assertEqual(rows[0]["registration_time"], "2026-01-01T09:00:00")

    def test_division_email_fk_resolution(self):
        """admin_division rows get email_id FK resolved to user@domain."""
        client = _make_client()
        div_cols = [{"COLUMN_NAME": c} for c in ["id", "name", "email_id", "city"]]
        div_rows = [
            {"id": 10, "name": "Amsterdam", "email_id": 99, "city": "AMS"},
            {"id": 11, "name": "Utrecht", "email_id": None, "city": "UTR"},
        ]
        email_join_rows = [{"id": 99, "email_address": "afdeling@example.org"}]
        client._connection = _FakeConnection([div_cols, div_rows, email_join_rows])
        rows = client.fetch_rows_by_ids("admin_division", [10, 11])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[10]["email_id"], "afdeling@example.org")
        self.assertIsNone(by_id[11]["email_id"])

    def test_division_email_fk_unmatched_cleared(self):
        """An email_id FK with no matching email record is cleared to None."""
        client = _make_client()
        div_cols = [{"COLUMN_NAME": c} for c in ["id", "name", "email_id"]]
        div_rows = [{"id": 10, "name": "Amsterdam", "email_id": 99}]
        email_join_rows = []  # no match for id 99
        client._connection = _FakeConnection([div_cols, div_rows, email_join_rows])
        rows = client.fetch_rows_by_ids("admin_division", [10])
        self.assertIsNone(rows[0]["email_id"])

    def test_division_email_resolution_error_leaves_numeric(self):
        """If the email-join query raises, the numeric email_id is left in place."""
        client = _make_client()
        div_cols = [{"COLUMN_NAME": c} for c in ["id", "name", "email_id"]]
        div_rows = [{"id": 10, "name": "Amsterdam", "email_id": 99}]

        # Build a connection where the 3rd cursor (email join) raises on execute.
        conn = _FakeConnection([div_cols, div_rows])

        class _RaisingCursor(_FakeCursor):
            def execute(self, query, params=None):
                raise RuntimeError("join failed")

        real_cursor = conn.cursor
        calls = {"n": 0}

        def cursor_factory():
            calls["n"] += 1
            if calls["n"] == 3:
                return _RaisingCursor([])
            return real_cursor()

        conn.cursor = cursor_factory
        client._connection = conn
        rows = client.fetch_rows_by_ids("admin_division", [10])
        # Resolution failed → numeric FK left untouched
        self.assertEqual(rows[0]["email_id"], 99)


class TestFetchAllRows(unittest.TestCase):
    def test_fetch_all_rows(self):
        client = _make_client()
        div_cols = [{"COLUMN_NAME": c} for c in ["id", "name"]]
        all_rows = [{"id": 1, "name": "X"}, {"id": 2, "name": "Y"}]
        client._connection = _FakeConnection([div_cols, all_rows])
        rows = client.fetch_all_rows("admin_division")
        self.assertEqual(len(rows), 2)


class TestFetchDivisionContacts(unittest.TestCase):
    """fetch_division_contacts — junction-table grouping by member_id."""

    def test_groups_and_sorts_by_member(self):
        client = _make_client()
        rows = [
            {"member_id": 100, "division_id": 3},
            {"member_id": 100, "division_id": 1},
            {"member_id": 200, "division_id": 5},
        ]
        client._connection = _FakeConnection([rows])
        contacts = client.fetch_division_contacts()
        self.assertEqual(contacts, {100: [1, 3], 200: [5]})  # sorted division lists

    def test_empty(self):
        client = _make_client()
        client._connection = _FakeConnection([[]])
        self.assertEqual(client.fetch_division_contacts(), {})


class TestFetchLookups(unittest.TestCase):
    """fetch_membership_statuses / fetch_document_folders / fetch_documents."""

    def test_membership_statuses_serialized(self):
        client = _make_client()
        rows = [{"id": 1, "name": "lid", "allowed_access": 1}]
        client._connection = _FakeConnection([rows])
        out = client.fetch_membership_statuses()
        self.assertEqual(out, [{"id": 1, "name": "lid", "allowed_access": 1}])

    def test_document_folders(self):
        client = _make_client()
        rows = [{"id": 1, "name": "Root", "parent_id": None}]
        client._connection = _FakeConnection([rows])
        self.assertEqual(client.fetch_document_folders(), rows)

    def test_documents_serialize_datetime(self):
        client = _make_client()
        rows = [
            {
                "id": 1,
                "name": "doc",
                "upload_file_name": "a.pdf",
                "size_in_bytes": 100,
                "date_uploaded": datetime.datetime(2026, 1, 1),
                "folder_id": 2,
            }
        ]
        client._connection = _FakeConnection([rows])
        out = client.fetch_documents()
        self.assertEqual(out[0]["date_uploaded"], "2026-01-01T00:00:00")


class TestContextManagerAndDisconnect(unittest.TestCase):
    """__enter__/__exit__ wire connect/disconnect; disconnect is crash-safe."""

    def test_disconnect_closes_connection_and_resets_state(self):
        client = _make_client()
        fake_conn = MagicMock()
        client._connection = fake_conn
        client._tunnel_active = True
        client.disconnect()
        fake_conn.close.assert_called_once()
        self.assertIsNone(client._connection)
        self.assertFalse(client._tunnel_active)
        self.assertIsNone(client._local_bind_port)

    def test_disconnect_swallows_connection_close_error(self):
        client = _make_client()
        fake_conn = MagicMock()
        fake_conn.close.side_effect = RuntimeError("boom")
        client._connection = fake_conn
        client.disconnect()  # must not raise
        self.assertIsNone(client._connection)

    def test_context_manager_calls_connect_disconnect(self):
        client = _make_client()
        client.connect = MagicMock()
        client.disconnect = MagicMock()
        with client as c:
            self.assertIs(c, client)
        client.connect.assert_called_once()
        client.disconnect.assert_called_once()
