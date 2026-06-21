# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for the shared SSH authentication helpers (ssh_auth.py).

ssh_auth is a PURE module: it parses real SSH keys, builds paramiko kwargs,
and inspects paramiko's own algorithm tables. There is NO business logic to
mock here — every test generates REAL keys (RSA/Ed25519/ECDSA/DSS) and feeds
them through the real parse path, or builds a lightweight settings stand-in
that mirrors the MijnRood Sync Settings field surface.

The only thing standing in for the DB is a tiny `_FakeSettings` object that
emulates the `get_password()` + attribute access contract of a Frappe Single
document. This is NOT mocking the function under test or any Frappe internal —
it is supplying a plain data object the helper reads from (the same role
MagicMock plays in the existing test_client_unit.py).
"""

import io
import os
import tempfile
import unittest

import frappe
import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from verenigingen.mijnrood_sync import ssh_auth


# ---------------------------------------------------------------------------
# Real-key generation helpers (no mocking — genuine cryptographic material)
# ---------------------------------------------------------------------------
def _rsa_pem(password=None):
    key = paramiko.RSAKey.generate(2048)
    s = io.StringIO()
    key.write_private_key(s, password=password)
    return s.getvalue()


def _ecdsa_pem():
    key = paramiko.ECDSAKey.generate()
    s = io.StringIO()
    key.write_private_key(s)
    return s.getvalue()


def _dss_pem():
    key = paramiko.DSSKey.generate(1024)
    s = io.StringIO()
    key.write_private_key(s)
    return s.getvalue()


def _ed25519_pem():
    ed = Ed25519PrivateKey.generate()
    return ed.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()


class _FakeSettings:
    """Plain stand-in for a MijnRood Sync Settings document.

    Supplies the attributes + get_password() contract that build_ssh_auth_kwargs
    reads. Secrets are stored in a private dict and returned by get_password,
    mirroring Frappe's encrypted-password store. This is a data fixture, not a
    mock of any code under test.
    """

    def __init__(self, **fields):
        # Field defaults matching the doctype surface the helper touches.
        self.ssh_legacy_compat = 0
        self.ssh_key_passphrase = None
        self.ssh_password = None
        self.ssh_private_key = None
        self.ssh_private_key_path = None
        self._secrets = {}
        for k, v in fields.items():
            if k == "_secrets":
                self._secrets = v
            else:
                setattr(self, k, v)

    def get_password(self, fieldname):
        if fieldname in self._secrets:
            return self._secrets[fieldname]
        raise frappe.ValidationError(f"No password set for {fieldname}")


# ---------------------------------------------------------------------------
# build_host_key_types
# ---------------------------------------------------------------------------
class TestBuildHostKeyTypes(unittest.TestCase):
    def test_returns_only_algorithms_known_to_this_paramiko(self):
        known = set(getattr(paramiko.Transport, "_key_info", {}).keys())
        result = ssh_auth.build_host_key_types()
        # Every returned algorithm must actually be recognised by paramiko —
        # otherwise transport.connect() would raise "unknown cipher".
        for algo in result:
            self.assertIn(algo, known)

    def test_preserves_desired_preference_order(self):
        # Modern algorithms must come before legacy ssh-rsa/ssh-dss so strong
        # signatures are negotiated first.
        result = ssh_auth.build_host_key_types()
        self.assertIn("ssh-ed25519", result)
        self.assertIn("ssh-rsa", result)
        self.assertLess(result.index("ssh-ed25519"), result.index("ssh-rsa"))

    def test_is_subset_of_desired_list(self):
        result = ssh_auth.build_host_key_types()
        self.assertTrue(set(result).issubset(set(ssh_auth._DESIRED_HOST_KEY_TYPES)))

    def test_returns_tuple(self):
        self.assertIsInstance(ssh_auth.build_host_key_types(), tuple)


# ---------------------------------------------------------------------------
# build_disabled_algorithms
# ---------------------------------------------------------------------------
class TestBuildDisabledAlgorithms(unittest.TestCase):
    def test_none_when_legacy_compat_off(self):
        self.assertIsNone(ssh_auth.build_disabled_algorithms(_FakeSettings(ssh_legacy_compat=0)))

    def test_disables_rsa_sha2_when_legacy_compat_on(self):
        out = ssh_auth.build_disabled_algorithms(_FakeSettings(ssh_legacy_compat=1))
        self.assertEqual(out, {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]})

    def test_missing_attribute_treated_as_off(self):
        class _NoAttr:
            pass

        self.assertIsNone(ssh_auth.build_disabled_algorithms(_NoAttr()))


# ---------------------------------------------------------------------------
# parse_pkey_from_string — REAL keys of every supported type
# ---------------------------------------------------------------------------
class TestParsePkeyFromString(unittest.TestCase):
    def test_parses_rsa(self):
        key = ssh_auth.parse_pkey_from_string(_rsa_pem())
        self.assertIsInstance(key, paramiko.RSAKey)
        self.assertEqual(key.get_name(), "ssh-rsa")

    def test_parses_ed25519(self):
        key = ssh_auth.parse_pkey_from_string(_ed25519_pem())
        self.assertIsInstance(key, paramiko.Ed25519Key)
        self.assertEqual(key.get_name(), "ssh-ed25519")

    def test_parses_ecdsa(self):
        key = ssh_auth.parse_pkey_from_string(_ecdsa_pem())
        self.assertIsInstance(key, paramiko.ECDSAKey)

    def test_parses_dss(self):
        key = ssh_auth.parse_pkey_from_string(_dss_pem())
        self.assertIsInstance(key, paramiko.DSSKey)

    def test_parses_encrypted_rsa_with_passphrase(self):
        pem = _rsa_pem(password="secret123")
        key = ssh_auth.parse_pkey_from_string(pem, passphrase="secret123")
        self.assertIsInstance(key, paramiko.RSAKey)

    def test_encrypted_key_wrong_passphrase_raises_valueerror(self):
        pem = _rsa_pem(password="correct-pass")
        with self.assertRaises(ValueError):
            ssh_auth.parse_pkey_from_string(pem, passphrase="WRONG")

    def test_encrypted_key_no_passphrase_raises_valueerror(self):
        pem = _rsa_pem(password="needed")
        with self.assertRaises(ValueError):
            ssh_auth.parse_pkey_from_string(pem, passphrase=None)

    def test_garbage_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ssh_auth.parse_pkey_from_string("not a key at all")

    def test_empty_string_raises_valueerror(self):
        with self.assertRaises(ValueError):
            ssh_auth.parse_pkey_from_string("")


# ---------------------------------------------------------------------------
# load_system_host_keys
# ---------------------------------------------------------------------------
class TestLoadSystemHostKeys(unittest.TestCase):
    def test_returns_hostkeys_object(self):
        # Reads the real ~/.ssh/known_hosts (may be absent) — must always
        # return a HostKeys instance, never raise.
        result = ssh_auth.load_system_host_keys()
        self.assertIsInstance(result, paramiko.HostKeys)

    def test_loads_entries_from_a_real_known_hosts(self):
        # Build a real known_hosts file with a generated host key, point HOME
        # at it, and confirm the entry is loaded. Exercises the os.path.isfile
        # + host_keys.load() success branch with genuine data.
        host_key = paramiko.RSAKey.generate(2048)
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = os.path.join(tmp, ".ssh")
            os.makedirs(ssh_dir)
            kh_path = os.path.join(ssh_dir, "known_hosts")
            line = f"example.test {host_key.get_name()} {host_key.get_base64()}\n"
            with open(kh_path, "w") as fh:
                fh.write(line)

            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                result = ssh_auth.load_system_host_keys()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

        self.assertIsNotNone(result.lookup("example.test"))

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            # tmp has no .ssh/known_hosts
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                result = ssh_auth.load_system_host_keys()
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# verify_host_key — uses a real HostKeys + a fake transport returning a real key
# ---------------------------------------------------------------------------
class _FakeTransport:
    """Returns a fixed remote server key. Stands in for the network boundary
    (paramiko.Transport.get_remote_server_key) only — the verify logic runs for
    real against real HostKeys + real PKey objects."""

    def __init__(self, remote_key):
        self._remote_key = remote_key

    def get_remote_server_key(self):
        return self._remote_key


class TestVerifyHostKey(unittest.TestCase):
    def test_no_remote_key_returns_without_raising(self):
        host_keys = paramiko.HostKeys()
        ssh_auth.verify_host_key(_FakeTransport(None), "host", 22, host_keys)  # no raise

    def test_unknown_host_warns_and_returns(self):
        host_keys = paramiko.HostKeys()  # empty
        key = paramiko.RSAKey.generate(2048)
        # No entry for this host → warn-and-proceed (TOFU), no raise.
        ssh_auth.verify_host_key(_FakeTransport(key), "unknown.host", 22, host_keys)

    def test_matching_key_passes(self):
        key = paramiko.RSAKey.generate(2048)
        host_keys = paramiko.HostKeys()
        host_keys.add("good.host", key.get_name(), key)
        ssh_auth.verify_host_key(_FakeTransport(key), "good.host", 22, host_keys)  # no raise

    def test_changed_key_raises_sshexception(self):
        known = paramiko.RSAKey.generate(2048)
        attacker = paramiko.RSAKey.generate(2048)
        host_keys = paramiko.HostKeys()
        host_keys.add("good.host", known.get_name(), known)
        with self.assertRaises(paramiko.SSHException):
            ssh_auth.verify_host_key(_FakeTransport(attacker), "good.host", 22, host_keys)

    def test_nonstandard_port_uses_bracket_format(self):
        key = paramiko.RSAKey.generate(2048)
        host_keys = paramiko.HostKeys()
        # Entry stored under "[host]:port" form for non-22 ports.
        host_keys.add("[good.host]:2222", key.get_name(), key)
        ssh_auth.verify_host_key(_FakeTransport(key), "good.host", 2222, host_keys)  # no raise

    def test_known_host_but_different_keytype_warns_not_raises(self):
        # known_hosts has an RSA entry but server presents an Ed25519 key —
        # cannot verify, so warn-and-proceed rather than raise.
        rsa = paramiko.RSAKey.generate(2048)
        ed = ssh_auth.parse_pkey_from_string(_ed25519_pem())
        host_keys = paramiko.HostKeys()
        host_keys.add("good.host", rsa.get_name(), rsa)
        ssh_auth.verify_host_key(_FakeTransport(ed), "good.host", 22, host_keys)  # no raise


# ---------------------------------------------------------------------------
# build_ssh_auth_kwargs — the priority chain (stored key > key file > password)
# ---------------------------------------------------------------------------
class TestBuildSSHAuthKwargs(unittest.TestCase):
    def test_stored_key_takes_priority_and_is_parsed(self):
        pem = _rsa_pem()
        s = _FakeSettings(
            ssh_private_key="x",
            ssh_private_key_path="/some/path",  # should be ignored — key wins
            _secrets={"ssh_private_key": pem},
        )
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertIn("pkey", result)
        self.assertIsInstance(result["pkey"], paramiko.RSAKey)
        self.assertNotIn("key_filename", result)
        self.assertNotIn("password", result)

    def test_stored_encrypted_key_uses_key_passphrase(self):
        pem = _rsa_pem(password="kp")
        s = _FakeSettings(
            ssh_private_key="x",
            ssh_key_passphrase="x",
            _secrets={"ssh_private_key": pem, "ssh_key_passphrase": "kp"},
        )
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertIsInstance(result["pkey"], paramiko.RSAKey)

    def test_stored_encrypted_key_falls_back_to_ssh_password_as_passphrase(self):
        # Back-compat: when ssh_key_passphrase is empty, ssh_password is used as
        # the key passphrase.
        pem = _rsa_pem(password="loginpw")
        s = _FakeSettings(
            ssh_private_key="x",
            ssh_password="x",
            _secrets={"ssh_private_key": pem, "ssh_password": "loginpw"},
        )
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertIsInstance(result["pkey"], paramiko.RSAKey)

    def test_field_set_but_no_secret_skips_to_next_method(self):
        # ssh_private_key flag set but password store empty (raises ValidationError)
        # → must NOT crash, falls through to key file.
        s = _FakeSettings(
            ssh_private_key="x",  # flag set, but no secret in store
            ssh_private_key_path="/etc/keys/id_rsa",
        )
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertNotIn("pkey", result)
        self.assertIn("key_filename", result)

    def test_non_pem_stored_key_skips_to_next_method(self):
        # Secret present but doesn't start with -----BEGIN → not a real key,
        # falls through to password.
        s = _FakeSettings(
            ssh_private_key="x",
            ssh_password="x",
            _secrets={"ssh_private_key": "garbage-not-a-pem", "ssh_password": "pw"},
        )
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertNotIn("pkey", result)
        self.assertEqual(result.get("password"), "pw")

    def test_key_file_absolute_path_used_verbatim(self):
        s = _FakeSettings(ssh_private_key_path="/abs/key.pem")
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertEqual(result["key_filename"], "/abs/key.pem")
        self.assertNotIn("passphrase", result)

    def test_key_file_with_passphrase_includes_passphrase(self):
        s = _FakeSettings(
            ssh_private_key_path="/abs/key.pem",
            ssh_key_passphrase="x",
            _secrets={"ssh_key_passphrase": "kp"},
        )
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertEqual(result["key_filename"], "/abs/key.pem")
        self.assertEqual(result["passphrase"], "kp")

    def test_key_file_relative_path_resolved_under_site(self):
        s = _FakeSettings(ssh_private_key_path="private/keys/id_rsa")
        result = ssh_auth.build_ssh_auth_kwargs(s)
        # Relative path → resolved via frappe.get_site_path (the site dir is
        # prepended). It still ends with the rel part and now includes the
        # site directory in the path.
        self.assertTrue(result["key_filename"].endswith("private/keys/id_rsa"))
        self.assertIn(frappe.local.site, result["key_filename"])
        self.assertNotEqual(result["key_filename"], "private/keys/id_rsa")

    def test_private_prefixed_path_resolved_under_site(self):
        # An absolute path under /private/ is treated as site-relative: the
        # leading slash is stripped and the path resolved under the site dir.
        s = _FakeSettings(ssh_private_key_path="/private/files/id_rsa")
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertTrue(result["key_filename"].endswith("private/files/id_rsa"))
        self.assertIn(frappe.local.site, result["key_filename"])
        # Must be resolved under the site, NOT the literal /private/... root path
        self.assertNotEqual(result["key_filename"], "/private/files/id_rsa")

    def test_password_only_auth(self):
        s = _FakeSettings(ssh_password="x", _secrets={"ssh_password": "mypw"})
        result = ssh_auth.build_ssh_auth_kwargs(s)
        self.assertEqual(result, {"password": "mypw"})

    def test_no_auth_configured_returns_empty(self):
        s = _FakeSettings()
        self.assertEqual(ssh_auth.build_ssh_auth_kwargs(s), {})


if __name__ == "__main__":
    unittest.main()
