# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for MijnRoodSFTPClient (sftp_client.py).

The SFTP client talks to a REMOTE server over paramiko for which no credentials
exist in this environment. We stub ONLY the true external boundary — the
paramiko SFTPClient object (`_sftp`) and, for the connect-retry tests, the
paramiko.Transport / SFTPClient.from_transport constructors. Everything the
client itself does runs for real:

  - path-traversal rejection in download_file
  - the pre-download size cap (stat) + post-download size cap (defence in depth)
  - remote-path construction from documents_remote_path
  - FileNotFoundError / IOError translation
  - connect() retry/backoff behaviour and non-transient short-circuit
  - disconnect() crash-safety
  - context-manager wiring

No business logic of the client is mocked; the FakeSFTP is a data fixture that
returns canned bytes/attrs (the role a real SFTP server would play).
"""

import io
import unittest
from unittest.mock import MagicMock, patch

import paramiko

from verenigingen.mijnrood_sync.sftp_client import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    FileTooLargeError,
    MijnRoodSFTPClient,
)


class _Attrs:
    def __init__(self, st_size):
        self.st_size = st_size


class _FakeSFTP:
    """Stand-in for paramiko.SFTPClient. Records calls, returns canned data."""

    def __init__(self, files=None, sizes=None, listdir_result=None):
        # files: {remote_path: bytes}; sizes: {remote_path: st_size override}
        self._files = files or {}
        self._sizes = sizes or {}
        self.listdir_result = listdir_result if listdir_result is not None else []
        self.closed = False
        self.statted = []
        self.fetched = []

    def stat(self, path):
        self.statted.append(path)
        if path not in self._files and path not in self._sizes:
            raise FileNotFoundError(path)
        size = self._sizes.get(path)
        if size is None:
            size = len(self._files.get(path, b""))
        return _Attrs(size)

    def getfo(self, path, buf):
        self.fetched.append(path)
        if path not in self._files:
            raise FileNotFoundError(path)
        buf.write(self._files[path])

    def listdir(self, path):
        if isinstance(self.listdir_result, Exception):
            raise self.listdir_result
        return self.listdir_result

    def close(self):
        self.closed = True


def _make_client(remote_path="/home/mijnrood/documents", max_bytes=DEFAULT_MAX_DOWNLOAD_BYTES):
    settings = MagicMock()
    settings.documents_remote_path = remote_path
    return MijnRoodSFTPClient(settings=settings, max_download_bytes=max_bytes)


class TestRemoteBaseNormalisation(unittest.TestCase):
    def test_trailing_slash_stripped(self):
        client = _make_client(remote_path="/docs/")
        self.assertEqual(client._remote_base, "/docs")

    def test_none_remote_path_becomes_empty(self):
        client = _make_client(remote_path=None)
        self.assertEqual(client._remote_base, "")


class TestDownloadFile(unittest.TestCase):
    def test_requires_open_session(self):
        client = _make_client()
        # _sftp is None until connect()
        with self.assertRaises(ConnectionError):
            client.download_file("abc123")

    def test_downloads_bytes(self):
        client = _make_client(remote_path="/docs")
        client._sftp = _FakeSFTP(files={"/docs/abc123": b"file-content"})
        out = client.download_file("abc123")
        self.assertEqual(out, b"file-content")

    def test_path_traversal_dotdot_rejected(self):
        client = _make_client()
        client._sftp = _FakeSFTP()
        with self.assertRaises(ValueError):
            client.download_file("../etc/passwd")

    def test_path_traversal_slash_rejected(self):
        client = _make_client()
        client._sftp = _FakeSFTP()
        with self.assertRaises(ValueError):
            client.download_file("sub/dir/file")

    def test_path_traversal_backslash_rejected(self):
        client = _make_client()
        client._sftp = _FakeSFTP()
        with self.assertRaises(ValueError):
            client.download_file("sub\\file")

    def test_traversal_check_runs_before_stat(self):
        # A malicious filename must never reach the SFTP stat call.
        client = _make_client()
        fake = _FakeSFTP()
        client._sftp = fake
        with self.assertRaises(ValueError):
            client.download_file("../secret")
        self.assertEqual(fake.statted, [])

    def test_missing_file_raises_filenotfound(self):
        client = _make_client(remote_path="/docs")
        client._sftp = _FakeSFTP(files={})  # nothing
        with self.assertRaises(FileNotFoundError):
            client.download_file("missing")

    def test_oversized_file_rejected_before_download(self):
        client = _make_client(remote_path="/docs", max_bytes=10)
        # stat reports 5000 bytes → reject without ever calling getfo
        fake = _FakeSFTP(sizes={"/docs/big": 5000})
        client._sftp = fake
        with self.assertRaises(FileTooLargeError):
            client.download_file("big")
        self.assertEqual(fake.fetched, [])  # never downloaded

    def test_post_download_size_cap_enforced_when_stat_understates(self):
        # stat() lies (reports small), but the real payload exceeds the cap →
        # the defence-in-depth post-download check must catch it.
        client = _make_client(remote_path="/docs", max_bytes=10)
        fake = _FakeSFTP(files={"/docs/sneaky": b"x" * 5000}, sizes={"/docs/sneaky": 5})
        client._sftp = fake
        with self.assertRaises(FileTooLargeError):
            client.download_file("sneaky")
        # getfo WAS called (stat passed), proving the post-check fired
        self.assertEqual(fake.fetched, ["/docs/sneaky"])

    def test_exactly_at_cap_allowed(self):
        client = _make_client(remote_path="/docs", max_bytes=5)
        client._sftp = _FakeSFTP(files={"/docs/edge": b"12345"})
        out = client.download_file("edge")
        self.assertEqual(out, b"12345")

    def test_getfo_ioerror_translated(self):
        client = _make_client(remote_path="/docs")

        class _RaiseOnGet(_FakeSFTP):
            def getfo(self, path, buf):
                raise IOError("transfer broke")

        fake = _RaiseOnGet(sizes={"/docs/x": 5})
        client._sftp = fake
        with self.assertRaises(IOError):
            client.download_file("x")

    def test_stat_ioerror_translated(self):
        client = _make_client(remote_path="/docs")

        class _RaiseOnStat(_FakeSFTP):
            def stat(self, path):
                raise IOError("stat broke")

        client._sftp = _RaiseOnStat()
        with self.assertRaises(IOError):
            client.download_file("x")


class TestListFiles(unittest.TestCase):
    def test_requires_open_session(self):
        client = _make_client()
        with self.assertRaises(ConnectionError):
            client.list_files()

    def test_returns_listdir(self):
        client = _make_client(remote_path="/docs")
        client._sftp = _FakeSFTP(listdir_result=["a", "b", "c"])
        self.assertEqual(client.list_files(), ["a", "b", "c"])

    def test_listdir_ioerror_translated(self):
        client = _make_client(remote_path="/docs")
        client._sftp = _FakeSFTP(listdir_result=IOError("nope"))
        with self.assertRaises(IOError):
            client.list_files()


class TestDisconnect(unittest.TestCase):
    def test_closes_both_and_resets(self):
        client = _make_client()
        sftp = MagicMock()
        transport = MagicMock()
        client._sftp = sftp
        client._transport = transport
        client.disconnect()
        sftp.close.assert_called_once()
        transport.close.assert_called_once()
        self.assertIsNone(client._sftp)
        self.assertIsNone(client._transport)

    def test_swallows_close_errors(self):
        client = _make_client()
        sftp = MagicMock()
        sftp.close.side_effect = RuntimeError("boom")
        transport = MagicMock()
        transport.close.side_effect = RuntimeError("boom2")
        client._sftp = sftp
        client._transport = transport
        client.disconnect()  # must not raise
        self.assertIsNone(client._sftp)
        self.assertIsNone(client._transport)

    def test_disconnect_safe_when_nothing_open(self):
        client = _make_client()
        client.disconnect()  # no transport/sftp set — must not raise


class TestContextManager(unittest.TestCase):
    def test_enter_exit_wire_connect_disconnect(self):
        client = _make_client()
        client.connect = MagicMock()
        client.disconnect = MagicMock()
        with client as c:
            self.assertIs(c, client)
        client.connect.assert_called_once()
        client.disconnect.assert_called_once()

    def test_exit_returns_false_to_propagate_exceptions(self):
        client = _make_client()
        client.connect = MagicMock()
        client.disconnect = MagicMock()
        self.assertFalse(client.__exit__(None, None, None))


class TestConnectRetry(unittest.TestCase):
    """connect() retry/backoff and non-transient short-circuit.

    We patch _open_transport/_open_sftp (the methods that touch the real
    network) — NOT connect() itself, which is the unit under test. This is
    boundary mocking: those two methods are the seam between the client's retry
    loop and paramiko's socket I/O.
    """

    def test_succeeds_first_try(self):
        client = _make_client()
        client._open_transport = MagicMock()
        client._open_sftp = MagicMock()
        client.connect()
        client._open_transport.assert_called_once()
        client._open_sftp.assert_called_once()

    def test_auth_failure_short_circuits_no_retry(self):
        client = _make_client()
        client._open_transport = MagicMock(side_effect=paramiko.AuthenticationException("bad creds"))
        client._open_sftp = MagicMock()
        client.disconnect = MagicMock()
        with self.assertRaises(ConnectionError) as cm:
            client.connect()
        self.assertIn("authentication failed", str(cm.exception))
        # Only ONE attempt — auth errors must not burn retries.
        self.assertEqual(client._open_transport.call_count, 1)

    def test_bad_host_key_short_circuits(self):
        client = _make_client()
        client._open_transport = MagicMock(
            side_effect=paramiko.BadHostKeyException("h", MagicMock(), MagicMock())
        )
        client.disconnect = MagicMock()
        with self.assertRaises(ConnectionError):
            client.connect()
        self.assertEqual(client._open_transport.call_count, 1)

    @patch("verenigingen.mijnrood_sync.sftp_client.time.sleep", return_value=None)
    def test_transient_error_retries_then_fails(self, _sleep):
        client = _make_client()
        client._open_transport = MagicMock(side_effect=OSError("network down"))
        client._open_sftp = MagicMock()
        client.disconnect = MagicMock()
        with self.assertRaises(ConnectionError) as cm:
            client.connect(max_retries=3)
        self.assertIn("after 3 attempts", str(cm.exception))
        self.assertEqual(client._open_transport.call_count, 3)
        # backoff slept between the first 2 failures (not after the last)
        self.assertEqual(_sleep.call_count, 2)

    @patch("verenigingen.mijnrood_sync.sftp_client.time.sleep", return_value=None)
    def test_transient_then_success(self, _sleep):
        client = _make_client()
        client._open_transport = MagicMock(side_effect=[OSError("blip"), None])
        client._open_sftp = MagicMock()
        client.disconnect = MagicMock()
        client.connect(max_retries=3)
        self.assertEqual(client._open_transport.call_count, 2)
        client._open_sftp.assert_called_once()


class TestOpenSftp(unittest.TestCase):
    def test_open_sftp_uses_transport(self):
        client = _make_client()
        fake_transport = MagicMock()
        client._transport = fake_transport
        with patch.object(paramiko.SFTPClient, "from_transport", return_value="SFTP_OBJ") as from_transport:
            client._open_sftp()
        from_transport.assert_called_once_with(fake_transport)
        self.assertEqual(client._sftp, "SFTP_OBJ")


if __name__ == "__main__":
    unittest.main()
