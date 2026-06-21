# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Extra coverage for MijnRoodDatabaseClient (client.py).

Complements test_client_unit.py (which covers serialization, column resolution,
checksum shaping, FK email resolution, chunking). This file targets the
remaining gaps:

  - the connect/tunnel/pymysql dispatch (_open_tunnel auth branches,
    _open_connection) — paramiko.Transport + pymysql.connect are the true
    external boundary and are the ONLY things stubbed
  - connect() retry / non-transient short-circuit
  - _get_resolved_columns schema-drift logging branch + fallback branch
  - _get_table_columns table-name validation
  - SQL-injection guards on the column path (_build_select_columns)
  - _validate_table_name error-message details

No business logic of the client is mocked; FakeConnection/cursor are data
fixtures (same pattern as test_client_unit.py).
"""

import unittest
from unittest.mock import MagicMock, patch

import paramiko

from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

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
    settings = MagicMock()
    settings.db_name = "rood"
    return MijnRoodDatabaseClient(settings=settings)


# ---------------------------------------------------------------------------
# _validate_table_name — allowlist + identifier details
# ---------------------------------------------------------------------------
class TestValidateTableName(unittest.TestCase):
    def test_rejected_table_message_lists_allowed(self):
        with self.assertRaises(ValueError) as cm:
            MijnRoodDatabaseClient._validate_table_name("admin_password")
        self.assertIn("ALLOWED_TABLES", str(cm.exception))

    def test_injection_table_rejected(self):
        # Even if it somehow passed the allowlist, an identifier with SQL meta
        # chars must be rejected. (Allowlist rejects it first, but assert ValueError.)
        for bad in ["admin_member; DROP TABLE x", "admin member", "admin_member`"]:
            with self.assertRaises(ValueError):
                MijnRoodDatabaseClient._validate_table_name(bad)


# ---------------------------------------------------------------------------
# _get_table_columns — validates table before querying information_schema
# ---------------------------------------------------------------------------
class TestGetTableColumns(unittest.TestCase):
    def test_rejects_non_allowlisted_table(self):
        client = _make_client()
        # No DB needed — validation happens before the query.
        with self.assertRaises(ValueError):
            client._get_table_columns("not_a_table")

    def test_passes_db_name_and_table_as_params(self):
        client = _make_client()
        remote = [{"COLUMN_NAME": "id"}, {"COLUMN_NAME": "name"}]
        client._connection = _FakeConnection([remote])
        cols = client._get_table_columns("admin_division")
        self.assertEqual(cols, ["id", "name"])
        # information_schema query must be parameterised (db_name, table)
        query, params = client._connection.cursors[0].executed[0]
        self.assertIn("information_schema.COLUMNS", query)
        self.assertEqual(params, ("rood", "admin_division"))


# ---------------------------------------------------------------------------
# _get_resolved_columns — schema-drift (missing-cols) logging branch
# ---------------------------------------------------------------------------
class TestResolvedColumnsDrift(unittest.TestCase):
    def test_missing_columns_logged_and_dropped(self):
        client = _make_client()
        # admin_member expects ~22 cols; remote only has a subset → the rest
        # are "missing" and must be dropped (and an INFO log emitted).
        remote_cols = [{"COLUMN_NAME": c} for c in ["id", "first_name", "email"]]
        client._connection = _FakeConnection([remote_cols])
        with patch("verenigingen.mijnrood_sync.client.logger") as log:
            resolved = client._get_resolved_columns("admin_member")
        self.assertEqual(resolved, ["id", "first_name", "email"])
        # The drift INFO log fired (a column was missing)
        self.assertTrue(log.info.called)

    def test_no_missing_columns_no_drift_log(self):
        client = _make_client()
        # Provide ALL expected admin_division columns → nothing missing.
        from verenigingen.mijnrood_sync.field_mapping import DIVISION_COLUMNS

        remote_cols = [{"COLUMN_NAME": c} for c in DIVISION_COLUMNS]
        client._connection = _FakeConnection([remote_cols])
        with patch("verenigingen.mijnrood_sync.client.logger") as log:
            resolved = client._get_resolved_columns("admin_division")
        self.assertEqual(resolved, list(DIVISION_COLUMNS))
        self.assertFalse(log.info.called)


# ---------------------------------------------------------------------------
# _build_select_columns — quoting + injection guard on resolved columns
# ---------------------------------------------------------------------------
class TestBuildSelectColumnsGuard(unittest.TestCase):
    def test_rejects_malicious_column_from_remote_schema(self):
        # Defence in depth: if information_schema returns a column name with SQL
        # meta-characters (e.g. a tampered remote), _validate_identifier must
        # reject it before it is interpolated into the SELECT.
        client = _make_client()
        # admin_division has no expected col with this name; we force the
        # fallback path by using a table whose expected cols all match, then
        # use _get_table_columns directly. Simpler: drive via _build_select_columns
        # on a table whose resolved cols include a bad name. Use the
        # no-expected fallback by patching TABLE_COLUMNS lookup via a bad remote.
        remote = [{"COLUMN_NAME": "id"}, {"COLUMN_NAME": "name); DROP TABLE x;--"}]
        client._connection = _FakeConnection([remote])
        # admin_division HAS expected columns, so the bad name (not in expected)
        # would be filtered out by intersection — proving the allowlist defends.
        col_list = client._build_select_columns("admin_division")
        self.assertNotIn("DROP TABLE", col_list)

    def test_all_columns_backtick_quoted(self):
        client = _make_client()
        from verenigingen.mijnrood_sync.field_mapping import DIVISION_COLUMNS

        remote = [{"COLUMN_NAME": c} for c in DIVISION_COLUMNS]
        client._connection = _FakeConnection([remote])
        col_list = client._build_select_columns("admin_division")
        for col in DIVISION_COLUMNS:
            self.assertIn(f"`{col}`", col_list)


# ---------------------------------------------------------------------------
# _open_connection — pymysql boundary (read-only enforcement)
# ---------------------------------------------------------------------------
class TestOpenConnection(unittest.TestCase):
    @patch("verenigingen.mijnrood_sync.client.pymysql.connect")
    def test_connects_read_only_through_local_bind_port(self, connect):
        client = _make_client()
        client._local_bind_port = 54321
        client._settings.db_username = "rooduser"
        client._settings.db_password = "x"  # truthy → get_password called
        client._settings.get_password.return_value = "secret"
        client._settings.db_name = "rood"
        connect.return_value = "CONN"

        client._open_connection()

        connect.assert_called_once()
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 54321)
        self.assertEqual(kwargs["user"], "rooduser")
        self.assertEqual(kwargs["password"], "secret")
        # Read-only is enforced at the protocol layer — the critical guarantee.
        self.assertEqual(kwargs["init_command"], "SET SESSION TRANSACTION READ ONLY")
        self.assertEqual(client._connection, "CONN")

    @patch("verenigingen.mijnrood_sync.client.pymysql.connect")
    def test_blank_db_name_defaults_to_rood(self, connect):
        client = _make_client()
        client._local_bind_port = 1
        client._settings.db_username = "u"
        client._settings.db_password = ""  # falsy → password becomes ""
        client._settings.db_name = ""
        connect.return_value = "CONN"
        client._open_connection()
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["database"], "rood")
        self.assertEqual(kwargs["password"], "")


# ---------------------------------------------------------------------------
# _open_tunnel — auth-branch dispatch (paramiko boundary stubbed)
# ---------------------------------------------------------------------------
class TestOpenTunnelDispatch(unittest.TestCase):
    """_open_tunnel chooses pkey / key_filename / password / raise based on the
    kwargs that build_ssh_auth_kwargs returns. We stub paramiko.Transport and
    build_ssh_auth_kwargs's RESULT (by configuring the settings the helper reads)
    — never the method under test."""

    def _patched_transport(self):
        # Returns a context where paramiko.Transport is a MagicMock factory.
        return patch("verenigingen.mijnrood_sync.client.paramiko.Transport")

    def _settings(self):
        s = MagicMock()
        s.ssh_host = "ssh.example.org"
        s.ssh_port = 22
        s.db_host = "127.0.0.1"
        s.db_port = 3306
        s.ssh_username = "rood"
        s.ssh_legacy_compat = 0
        return s

    def test_no_auth_method_raises_connectionerror(self):
        # build_ssh_auth_kwargs returns {} when nothing configured → _open_tunnel
        # must raise ConnectionError (unlike the SFTP client which tries agent auth).
        s = self._settings()
        s.ssh_private_key = None
        s.ssh_private_key_path = None
        s.ssh_password = None
        s.ssh_key_passphrase = None
        client = MijnRoodDatabaseClient(settings=s)
        with self._patched_transport() as T:
            transport_obj = T.return_value
            transport_obj.get_security_options.return_value = MagicMock()
            with self.assertRaises(ConnectionError) as cm:
                client._open_tunnel()
        self.assertIn("No SSH authentication method", str(cm.exception))

    def test_password_auth_branch(self):
        s = self._settings()
        s.ssh_private_key = None
        s.ssh_private_key_path = None
        s.ssh_password = "x"
        s.ssh_key_passphrase = None
        s.get_password.return_value = "mypw"
        client = MijnRoodDatabaseClient(settings=s)
        # Pre-seed host_keys to a real empty HostKeys so verify_host_key warns.
        client._host_keys = paramiko.HostKeys()
        with self._patched_transport() as T:
            transport_obj = T.return_value
            transport_obj.get_security_options.return_value = MagicMock()
            transport_obj.get_remote_server_key.return_value = None  # → warn path
            try:
                client._open_tunnel()
            finally:
                # Tear down the forwarding thread the method starts.
                client.disconnect()
        transport_obj.connect.assert_called_once_with(username="rood", password="mypw")

    def test_pkey_auth_branch(self):
        # Stored key → build_ssh_auth_kwargs returns {'pkey': <RSAKey>}.
        import io as _io

        rsa = paramiko.RSAKey.generate(2048)
        buf = _io.StringIO()
        rsa.write_private_key(buf)
        pem = buf.getvalue()

        s = self._settings()
        s.ssh_private_key = "x"
        s.ssh_private_key_path = None
        s.ssh_password = None
        s.ssh_key_passphrase = None

        def _get_password(field):
            if field == "ssh_private_key":
                return pem
            raise paramiko.ssh_exception.SSHException("no")

        s.get_password.side_effect = _get_password
        client = MijnRoodDatabaseClient(settings=s)
        client._host_keys = paramiko.HostKeys()
        with self._patched_transport() as T:
            transport_obj = T.return_value
            transport_obj.get_security_options.return_value = MagicMock()
            transport_obj.get_remote_server_key.return_value = None
            try:
                client._open_tunnel()
            finally:
                client.disconnect()
        # connect called with a pkey kwarg
        _, kwargs = transport_obj.connect.call_args
        self.assertIn("pkey", kwargs)
        self.assertIsInstance(kwargs["pkey"], paramiko.RSAKey)

    def test_legacy_compat_passes_disabled_algorithms(self):
        s = self._settings()
        s.ssh_legacy_compat = 1
        s.ssh_private_key = None
        s.ssh_private_key_path = None
        s.ssh_password = "x"
        s.ssh_key_passphrase = None
        s.get_password.return_value = "pw"
        client = MijnRoodDatabaseClient(settings=s)
        client._host_keys = paramiko.HostKeys()
        with self._patched_transport() as T:
            transport_obj = T.return_value
            transport_obj.get_security_options.return_value = MagicMock()
            transport_obj.get_remote_server_key.return_value = None
            try:
                client._open_tunnel()
            finally:
                client.disconnect()
        # Transport constructed WITH disabled_algorithms when legacy compat on.
        _, ctor_kwargs = T.call_args
        self.assertIn("disabled_algorithms", ctor_kwargs)
        self.assertEqual(ctor_kwargs["disabled_algorithms"], {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]})


# ---------------------------------------------------------------------------
# connect() retry / short-circuit (mirrors SFTP client logic)
# ---------------------------------------------------------------------------
class TestConnectRetry(unittest.TestCase):
    def test_success_first_try(self):
        client = _make_client()
        client._open_tunnel = MagicMock()
        client._open_connection = MagicMock()
        client.connect()
        client._open_tunnel.assert_called_once()
        client._open_connection.assert_called_once()

    def test_auth_failure_short_circuits(self):
        client = _make_client()
        client._open_tunnel = MagicMock(side_effect=paramiko.AuthenticationException("bad"))
        client.disconnect = MagicMock()
        with self.assertRaises(ConnectionError) as cm:
            client.connect()
        self.assertIn("authentication failed", str(cm.exception))
        self.assertEqual(client._open_tunnel.call_count, 1)

    @patch("verenigingen.mijnrood_sync.client.time.sleep", return_value=None)
    def test_transient_retries_then_fails(self, _sleep):
        client = _make_client()
        client._open_tunnel = MagicMock(side_effect=OSError("down"))
        client.disconnect = MagicMock()
        with self.assertRaises(ConnectionError) as cm:
            client.connect(max_retries=3)
        self.assertIn("after 3 attempts", str(cm.exception))
        self.assertEqual(client._open_tunnel.call_count, 3)
        self.assertEqual(_sleep.call_count, 2)

    @patch("verenigingen.mijnrood_sync.client.time.sleep", return_value=None)
    def test_transient_then_success(self, _sleep):
        client = _make_client()
        client._open_tunnel = MagicMock(side_effect=[OSError("blip"), None])
        client._open_connection = MagicMock()
        client.disconnect = MagicMock()
        client.connect(max_retries=3)
        self.assertEqual(client._open_tunnel.call_count, 2)
        client._open_connection.assert_called_once()


# ---------------------------------------------------------------------------
# _parse_pkey_from_string delegation + fetch_* boundary error path
# ---------------------------------------------------------------------------
class TestMisc(unittest.TestCase):
    def test_parse_pkey_delegates_to_ssh_auth(self):
        import io as _io

        rsa = paramiko.RSAKey.generate(2048)
        buf = _io.StringIO()
        rsa.write_private_key(buf)
        key = MijnRoodDatabaseClient._parse_pkey_from_string(buf.getvalue())
        self.assertIsInstance(key, paramiko.RSAKey)

    def test_fetch_rows_by_ids_rejects_bad_table(self):
        client = _make_client()
        with self.assertRaises(ValueError):
            client.fetch_rows_by_ids("admin_password", [1, 2])

    def test_fetch_all_rows_rejects_bad_table(self):
        client = _make_client()
        with self.assertRaises(ValueError):
            client.fetch_all_rows("admin_password")

    def test_key_file_branch_supports_non_rsa_keys(self):
        """REGRESSION: _open_tunnel's key_filename branch must accept non-RSA
        key files (Ed25519/ECDSA/DSS), matching sftp_client.py and the
        stored-key path.

        Previously it hard-coded ``paramiko.RSAKey.from_private_key_file()``,
        so an Ed25519 key FILE made the DB tunnel fail with SSHException while
        SFTP downloads worked with the same key. The fix delegates to the
        shared ``parse_pkey_from_string`` helper. This test feeds an Ed25519
        key file and asserts the tunnel connects with the parsed Ed25519 key.
        """
        import os
        import tempfile

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        # An Ed25519 key FILE on disk.
        ed = Ed25519PrivateKey.generate()
        pem = ed.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        ).decode()
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
            fh.write(pem)
            key_path = fh.name

        s = MagicMock()
        s.ssh_host = "ssh.example.org"
        s.ssh_port = 22
        s.db_host = "127.0.0.1"
        s.db_port = 3306
        s.ssh_username = "rood"
        s.ssh_legacy_compat = 0
        s.ssh_private_key = None
        s.ssh_private_key_path = key_path  # absolute → used verbatim
        s.ssh_password = None
        s.ssh_key_passphrase = None
        client = MijnRoodDatabaseClient(settings=s)
        client._host_keys = paramiko.HostKeys()
        try:
            with patch("verenigingen.mijnrood_sync.client.paramiko.Transport") as T:
                transport_obj = T.return_value
                transport_obj.get_security_options.return_value = MagicMock()
                transport_obj.get_remote_server_key.return_value = None
                try:
                    client._open_tunnel()
                finally:
                    client.disconnect()
        finally:
            os.unlink(key_path)

        # The tunnel connected with the parsed Ed25519 key — not RSA-rejected.
        _, kwargs = transport_obj.connect.call_args
        self.assertIn("pkey", kwargs)
        self.assertIsInstance(kwargs["pkey"], paramiko.Ed25519Key)


if __name__ == "__main__":
    unittest.main()
