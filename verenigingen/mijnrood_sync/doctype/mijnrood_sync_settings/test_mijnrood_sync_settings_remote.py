# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Integration tests for the remote/client-backed methods of MijnRood Sync Settings.

Covers the methods that talk to the genuine external boundary (SSH+DB remote
via MijnRoodDatabaseClient, the background queue via frappe.enqueue, and the
DocumentImportService):

- test_connection (success + failure paths)
- fetch_lidmaatschapstypes_from_mijnrood (merge / skip / rate-limit / empty)
- fetch_document_folders + auto_classify_folders (controller wiring + rate limit)
- diagnose_ssh_auth (static inspection with REAL generated keys; no live SSH)
- trigger_sync_now (enqueue wiring)
- import_documents (success path)

ONLY genuine external boundaries are mocked:
- ``verenigingen.mijnrood_sync.client.MijnRoodDatabaseClient`` — the SSH+DB
  remote, patched where the methods import it.
- ``frappe.enqueue`` — the background-job queue (framework I/O).
- For folder fetch/classify, the DocumentImportService method is patched at its
  own boundary (its internals are covered by another suite) — the assertions
  verify the *controller wiring* (delegation + rate-limit + cache-set), not the
  service's behavior.

No business logic is mocked. The diagnose_ssh_auth tests use REAL paramiko keys
generated in-process and exercise the real ``build_ssh_auth_kwargs`` parsing.

MijnRood Sync Settings is a Single doctype, so the three child tables (and the
scalar fields we mutate) are snapshotted in setUp and restored in tearDown to
avoid leaking state across tests.
"""

import io
from unittest.mock import MagicMock, patch

import frappe
import paramiko

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_CHILD_TABLES = ("status_mapping", "role_mapping", "document_folder_mapping")

_CLIENT_PATH = "verenigingen.mijnrood_sync.client.MijnRoodDatabaseClient"

# Rate-limit cache keys used by the controller.
_LIDM_RATE_KEY = "mijnrood_fetch_lidmaatschapstypes_ratelimit"
_FOLDER_RATE_KEY = "mijnrood_fetch_document_folders_ratelimit"


def _make_fake_client(*, statuses=None, row_count=None, raises=None):
    """Build a MagicMock that mimics MijnRoodDatabaseClient as a context manager.

    The real client is used as ``with MijnRoodDatabaseClient(settings=self) as
    client:`` (via __enter__/__exit__) OR via ``client = MijnRoodDatabaseClient(...)``
    then ``with client:``. Either way the patched class is *called* to construct
    an instance, and that instance is the context manager.
    """
    client = MagicMock(name="MijnRoodDatabaseClient instance")
    # Context-manager protocol: `with client:` yields `client` itself
    # (matches the real __enter__ which returns self).
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    if raises is not None:
        # Make entering the context raise (simulating a connection failure).
        client.__enter__.side_effect = raises

    if statuses is not None:
        client.fetch_membership_statuses.return_value = statuses
    if row_count is not None:
        client.test_query.return_value = row_count

    return client


class TestMijnRoodSyncSettingsRemote(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("MijnRood Sync Settings")
        self._snapshot = {
            tbl: [row.as_dict() for row in (self.settings.get(tbl) or [])] for tbl in _CHILD_TABLES
        }
        self._scalar_snapshot = {
            "tables_to_sync": self.settings.tables_to_sync,
            "poll_interval_minutes": self.settings.poll_interval_minutes,
            "ssh_port": self.settings.ssh_port,
            "db_port": self.settings.db_port,
            "ssh_host": self.settings.ssh_host,
            "ssh_username": self.settings.ssh_username,
            "ssh_private_key": self.settings.ssh_private_key,
            "ssh_private_key_path": self.settings.ssh_private_key_path,
            "ssh_password": self.settings.ssh_password,
            "ssh_key_passphrase": self.settings.ssh_key_passphrase,
            "ssh_legacy_compat": self.settings.ssh_legacy_compat,
            "connection_status": self.settings.connection_status,
            "document_import_status": self.settings.document_import_status,
        }
        for tbl in _CHILD_TABLES:
            self.settings.set(tbl, [])
        # Ensure no leftover rate-limit cache from a prior run.
        frappe.cache.delete_value(_LIDM_RATE_KEY)
        frappe.cache.delete_value(_FOLDER_RATE_KEY)

    def tearDown(self):
        settings = frappe.get_single("MijnRood Sync Settings")
        for tbl in _CHILD_TABLES:
            settings.set(tbl, [])
            for row in self._snapshot[tbl]:
                settings.append(tbl, row)
        for field, value in self._scalar_snapshot.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache.delete_value(_LIDM_RATE_KEY)
        frappe.cache.delete_value(_FOLDER_RATE_KEY)
        super().tearDown()

    def _reload_status_rows(self):
        """Return the persisted status_mapping rows keyed by status id."""
        reloaded = frappe.get_single("MijnRood Sync Settings")
        return {r.mijnrood_status_id: r for r in reloaded.status_mapping}

    # ---- test_connection -------------------------------------------------

    def test_connection_success_sets_status_and_returns_count(self):
        """Success path: client.test_query() count is surfaced, connection_status
        is persisted with the count, and the return dict reflects success."""
        fake = _make_fake_client(row_count=42)
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.test_connection()

        self.assertTrue(result["success"])
        self.assertEqual(result["row_count"], 42)
        # test_query must have been called inside the context.
        fake.test_query.assert_called_once()
        # connection_status persisted with the row count.
        persisted = frappe.db.get_single_value("MijnRood Sync Settings", "connection_status")
        self.assertIn("42", persisted)
        self.assertIn("Connected", persisted)

    def test_connection_failure_records_error_and_returns_false(self):
        """Failure path: client raises on connect → returns success:False with
        the error message, and connection_status is set to the failure string."""
        # test_connection deliberately frappe.log_error()s on failure; mark that
        # Error Log expected so the base ErrorLogGuard tearDown doesn't fail.
        self._expect_connection_error_log()
        fake = _make_fake_client(raises=RuntimeError("tunnel refused"))
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.test_connection()

        self.assertFalse(result["success"])
        self.assertIn("tunnel refused", result["message"])
        persisted = frappe.db.get_single_value("MijnRood Sync Settings", "connection_status")
        self.assertIn("Connection failed", persisted)
        self.assertIn("tunnel refused", persisted)

    def _expect_connection_error_log(self):
        """Register the deliberate log_error title(s) as expected so the
        automatic ErrorLogGuard tearDown check ignores them (the log is intended
        behavior on the failure path, not a regression)."""
        if hasattr(self, "expectErrorLog"):
            self.expectErrorLog(
                "MijnRood Connection Test Failed",
                "MijnRood Fetch Lidmaatschapstypes Failed",
            )

    # ---- fetch_lidmaatschapstypes_from_mijnrood --------------------------

    def test_fetch_lidmaatschapstypes_appends_new_rows(self):
        """New status ids from MijnRood are appended with is_active/allows_login
        derived from allowed_access, and the result message counts them."""
        statuses = [
            {"id": 1, "name": "Active member", "allowed_access": 1},
            {"id": 2, "name": "Cancelled", "allowed_access": 0},
        ]
        fake = _make_fake_client(statuses=statuses)
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        self.assertTrue(result["success"])
        self.assertIn("2 new", result["message"])
        rows = self._reload_status_rows()
        self.assertIn(1, rows)
        self.assertIn(2, rows)
        self.assertEqual(rows[1].label, "Active member")
        self.assertEqual(rows[1].membership_type_string, "Active member")
        self.assertEqual(rows[1].is_active, 1)
        self.assertEqual(rows[1].allows_login, 1)
        # allowed_access=0 → inactive, and the controller sets termination_type.
        self.assertEqual(rows[2].is_active, 0)
        self.assertEqual(rows[2].allows_login, 0)
        self.assertEqual(rows[2].termination_type, "Administrative")

    def test_fetch_lidmaatschapstypes_updates_existing_row(self):
        """An existing row (same status id) gets label/string/allows_login/is_active
        refreshed from MijnRood when no admin membership-type override is set."""
        self.settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": 7,
                "label": "Old label",
                "membership_type_string": "Old",
                "is_active": 0,
                "allows_login": 0,
            },
        )
        self.settings.save()

        statuses = [{"id": 7, "name": "New label", "allowed_access": 1}]
        fake = _make_fake_client(statuses=statuses)
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        self.assertTrue(result["success"])
        self.assertIn("1 updated", result["message"])
        rows = self._reload_status_rows()
        self.assertEqual(rows[7].label, "New label")
        self.assertEqual(rows[7].membership_type_string, "New label")
        self.assertEqual(rows[7].allows_login, 1)
        # is_active refreshed from allowed_access because no override set.
        self.assertEqual(rows[7].is_active, 1)

    def test_fetch_lidmaatschapstypes_preserves_admin_membership_type_override(self):
        """When an admin has set verenigingen_membership_type, the fetch must NOT
        overwrite is_active (deliberate override) and must keep the override."""
        mtype = self._get_a_membership_type()
        self.settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": 9,
                "label": "Old",
                "membership_type_string": "Old",
                "is_active": 1,
                "verenigingen_membership_type": mtype,
            },
        )
        self.settings.save()

        # MijnRood now reports allowed_access=0 (would normally flip is_active→0).
        statuses = [{"id": 9, "name": "Renamed", "allowed_access": 0}]
        fake = _make_fake_client(statuses=statuses)
        with patch(_CLIENT_PATH, return_value=fake):
            self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        rows = self._reload_status_rows()
        # Override preserved, is_active NOT flipped despite allowed_access=0.
        self.assertEqual(rows[9].verenigingen_membership_type, mtype)
        self.assertEqual(rows[9].is_active, 1)
        # label/string still refreshed.
        self.assertEqual(rows[9].label, "Renamed")

    def test_fetch_lidmaatschapstypes_skips_missing_id_or_name_and_duplicates(self):
        """Rows missing id or name, and duplicate ids within the fetched data,
        are skipped and reported in the message."""
        statuses = [
            {"id": 1, "name": "Good", "allowed_access": 1},
            {"id": None, "name": "No id", "allowed_access": 1},  # skipped: no id
            {"id": 2, "name": "  ", "allowed_access": 1},  # skipped: blank name
            {"id": 1, "name": "Dup", "allowed_access": 1},  # skipped: duplicate id
        ]
        fake = _make_fake_client(statuses=statuses)
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        self.assertTrue(result["success"])
        self.assertIn("1 new", result["message"])
        self.assertIn("3 skipped", result["message"])
        rows = self._reload_status_rows()
        self.assertIn(1, rows)
        self.assertNotIn(2, rows)
        # The duplicate did not overwrite the first.
        self.assertEqual(rows[1].label, "Good")

    def test_fetch_lidmaatschapstypes_empty_result(self):
        """No statuses returned → success:False with the empty message, and no
        rows persisted."""
        fake = _make_fake_client(statuses=[])
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        self.assertFalse(result["success"])
        self.assertIn("No membership statuses found", result["message"])

    def test_fetch_lidmaatschapstypes_rate_limited(self):
        """When the rate-limit cache key is already set, the method returns the
        rate-limit message WITHOUT constructing the client at all."""
        frappe.cache.set_value(_LIDM_RATE_KEY, "1", expires_in_sec=60)
        with patch(_CLIENT_PATH) as client_cls:
            result = self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        self.assertFalse(result["success"])
        self.assertIn("60 seconds", result["message"])
        # The boundary was never touched — rate limit short-circuits first.
        client_cls.assert_not_called()

    def test_fetch_lidmaatschapstypes_connection_failure(self):
        """Client raises on connect → success:False with a 'Connection failed'
        message and an Error Log (expected)."""
        self._expect_connection_error_log()
        fake = _make_fake_client(raises=RuntimeError("ssh down"))
        with patch(_CLIENT_PATH, return_value=fake):
            result = self.settings.fetch_lidmaatschapstypes_from_mijnrood()

        self.assertFalse(result["success"])
        self.assertIn("Connection failed", result["message"])
        self.assertIn("ssh down", result["message"])

    def test_fetch_lidmaatschapstypes_sets_rate_limit_after_success(self):
        """A successful fetch arms the rate-limit cache so the next call is
        blocked."""
        fake = _make_fake_client(statuses=[{"id": 1, "name": "X", "allowed_access": 1}])
        with patch(_CLIENT_PATH, return_value=fake):
            self.settings.fetch_lidmaatschapstypes_from_mijnrood()
        self.assertTrue(frappe.cache.get_value(_LIDM_RATE_KEY))

    def _get_a_membership_type(self):
        existing = frappe.get_all("Membership Type", limit=1, pluck="name")
        if existing:
            return existing[0]
        # Use the factory's helper if available; otherwise create minimally.
        if hasattr(self, "create_test_membership_type"):
            return self.create_test_membership_type().name
        mt = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Remote Test Type",
                "amount": 10,
                "billing_period": "Annual",
            }
        )
        mt.insert()
        return mt.name

    # ---- fetch_document_folders (controller wiring + rate limit) ---------

    def test_fetch_document_folders_delegates_to_service(self):
        """The controller delegates to DocumentImportService.fetch_and_populate_folders
        and returns its result; on success it arms the rate-limit cache."""
        service_result = {"success": True, "message": "Fetched 3 folders"}
        with patch(
            "verenigingen.mijnrood_sync.services.document_import_service.DocumentImportService"
        ) as svc_cls:
            svc = svc_cls.return_value
            svc.fetch_and_populate_folders.return_value = service_result
            result = self.settings.fetch_document_folders()

        self.assertEqual(result, service_result)
        svc.fetch_and_populate_folders.assert_called_once()
        # Success arms the rate limit.
        self.assertTrue(frappe.cache.get_value(_FOLDER_RATE_KEY))

    def test_fetch_document_folders_rate_limited(self):
        """Rate-limit cache set → returns the wait message without building the
        service."""
        frappe.cache.set_value(_FOLDER_RATE_KEY, "1", expires_in_sec=60)
        with patch(
            "verenigingen.mijnrood_sync.services.document_import_service.DocumentImportService"
        ) as svc_cls:
            result = self.settings.fetch_document_folders()

        self.assertFalse(result["success"])
        self.assertIn("60 seconds", result["message"])
        svc_cls.assert_not_called()

    def test_fetch_document_folders_failure_does_not_set_rate_limit(self):
        """A failed fetch must NOT arm the rate limit (so the admin can retry)."""
        with patch(
            "verenigingen.mijnrood_sync.services.document_import_service.DocumentImportService"
        ) as svc_cls:
            svc_cls.return_value.fetch_and_populate_folders.return_value = {
                "success": False,
                "message": "boom",
            }
            result = self.settings.fetch_document_folders()

        self.assertFalse(result["success"])
        self.assertIsNone(frappe.cache.get_value(_FOLDER_RATE_KEY))

    # ---- auto_classify_folders (controller wiring) ----------------------

    def test_auto_classify_folders_delegates_to_service(self):
        """auto_classify_folders delegates to the service and returns its result."""
        service_result = {"success": True, "classified": 2}
        with patch(
            "verenigingen.mijnrood_sync.services.document_import_service.DocumentImportService"
        ) as svc_cls:
            svc = svc_cls.return_value
            svc.auto_classify_folder_mappings.return_value = service_result
            result = self.settings.auto_classify_folders()

        self.assertEqual(result, service_result)
        svc.auto_classify_folder_mappings.assert_called_once()

    # ---- diagnose_ssh_auth (REAL keys; static inspection) ---------------

    def test_diagnose_ssh_auth_stored_rsa_key(self):
        """A real RSA key in ssh_private_key resolves to the stored_key path with
        the correct key type and a fingerprint — exercising real
        build_ssh_auth_kwargs + paramiko parsing."""
        pem = self._generate_rsa_pem()
        self.settings.ssh_private_key = pem
        self.settings.ssh_host = "ssh.example.org"
        self.settings.ssh_username = "syncuser"

        report = self.settings.diagnose_ssh_auth(attempt_handshake=False)

        self.assertEqual(report["selected_path"], "stored_key")
        self.assertEqual(report["key_type"], "ssh-rsa")
        self.assertIn("fingerprint_sha256_hex", report)
        self.assertTrue(report["fingerprint_sha256_hex"])
        self.assertEqual(report["key_bits"], 2048)
        self.assertEqual(report["ssh_host"], "ssh.example.org")
        self.assertTrue(report["fields_set"]["ssh_private_key"])
        self.assertFalse(report["fields_set"]["ssh_password"])
        self.assertIn("paramiko_version", report)

    def test_diagnose_ssh_auth_stored_ecdsa_key(self):
        """A real ECDSA key resolves to stored_key with a non-RSA key_type —
        exercises the non-RSA branch of the parser. (Ed25519Key.generate() is
        unavailable in paramiko 4.x, so ECDSA is used as the second key type.)"""
        key = paramiko.ECDSAKey.generate()
        buf = io.StringIO()
        key.write_private_key(buf)
        self.settings.ssh_private_key = buf.getvalue()
        self.settings.ssh_host = "h"
        self.settings.ssh_username = "u"

        report = self.settings.diagnose_ssh_auth(attempt_handshake=False)

        self.assertEqual(report["selected_path"], "stored_key")
        self.assertEqual(report["key_type"], "ecdsa-sha2-nistp256")
        self.assertIn("fingerprint_sha256_hex", report)

    def test_diagnose_ssh_auth_password_path(self):
        """No key, only ssh_password → selected_path 'password' with the length
        but never the password itself."""
        self.settings.ssh_private_key = ""
        self.settings.ssh_private_key_path = ""
        self.settings.ssh_password = "s3cr3t-pw"
        self.settings.ssh_host = "h"
        self.settings.ssh_username = "u"

        report = self.settings.diagnose_ssh_auth(attempt_handshake=False)

        self.assertEqual(report["selected_path"], "password")
        self.assertEqual(report["password_length"], len("s3cr3t-pw"))
        # The raw password must never leak into the report.
        self.assertNotIn("s3cr3t-pw", str(report))

    def test_diagnose_ssh_auth_none_configured(self):
        """No key / no path / no password → selected_path 'none_configured'."""
        self.settings.ssh_private_key = ""
        self.settings.ssh_private_key_path = ""
        self.settings.ssh_password = ""
        self.settings.ssh_key_passphrase = ""
        self.settings.ssh_host = "h"
        self.settings.ssh_username = "u"

        report = self.settings.diagnose_ssh_auth(attempt_handshake=False)

        self.assertEqual(report["selected_path"], "none_configured")

    def test_diagnose_ssh_auth_falsy_does_not_run_probe(self):
        """attempt_handshake=False (the framework-coerced value) must NOT trigger
        the live handshake probe (which needs a real SSH server)."""
        self.settings.ssh_private_key = self._generate_rsa_pem()
        self.settings.ssh_host = "h"
        self.settings.ssh_username = "u"

        report = self.settings.diagnose_ssh_auth(attempt_handshake=False)
        self.assertNotIn("handshake", report)

    def test_diagnose_ssh_auth_truthy_runs_probe(self):
        """attempt_handshake=True routes into the probe branch. _run_handshake_probe
        is patched (a real SSH server is out of scope) only to assert the branch
        is reached and its result is surfaced under 'handshake'."""
        self.settings.ssh_private_key = self._generate_rsa_pem()
        self.settings.ssh_host = "h"
        self.settings.ssh_username = "u"

        sentinel = {"attempted": True, "stubbed": True}
        with patch.object(type(self.settings), "_run_handshake_probe", return_value=sentinel) as probe:
            report = self.settings.diagnose_ssh_auth(attempt_handshake=True)

        probe.assert_called_once()
        self.assertEqual(report["handshake"], sentinel)

    def test_diagnose_ssh_auth_whitelist_coerces_bool_strings(self):
        """FINDING: the in-body ``isinstance(attempt_handshake, str)`` normalization
        (controller lines 56-57) is effectively dead for framework-routed calls.
        The @frappe.whitelist() pydantic layer coerces bool-like strings to real
        bools BEFORE the method body runs, and rejects non-bool strings (e.g. "").

        This test pins that boundary contract: a coercible string like "true" is
        accepted (probe runs) and a non-coercible "" is rejected with
        FrappeTypeError — so the str branch in the body never actually executes.
        """
        self.settings.ssh_private_key = self._generate_rsa_pem()
        self.settings.ssh_host = "h"
        self.settings.ssh_username = "u"

        # "true" is coerced to bool True by the whitelist layer → probe runs.
        with patch.object(type(self.settings), "_run_handshake_probe", return_value={"ok": 1}):
            report = self.settings.diagnose_ssh_auth(attempt_handshake="true")
        self.assertIn("handshake", report)

        # "false" is coerced to bool False → probe does NOT run.
        report = self.settings.diagnose_ssh_auth(attempt_handshake="false")
        self.assertNotIn("handshake", report)

        # An empty string is NOT coercible → the whitelist layer rejects it.
        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            self.settings.diagnose_ssh_auth(attempt_handshake="")

    def _generate_rsa_pem(self):
        key = paramiko.RSAKey.generate(2048)
        buf = io.StringIO()
        key.write_private_key(buf)
        return buf.getvalue()

    # ---- trigger_sync_now ------------------------------------------------

    def test_trigger_sync_now_enqueues_sync_task(self):
        """Enqueues the canonical sync task on the long queue."""
        with patch("frappe.enqueue") as enq:
            result = self.settings.trigger_sync_now()

        self.assertTrue(result["success"])
        enq.assert_called_once()
        args, kwargs = enq.call_args
        self.assertEqual(args[0], "verenigingen.mijnrood_sync.tasks.run_mijnrood_sync")
        self.assertEqual(kwargs["queue"], "long")
        self.assertEqual(kwargs["job_name"], "mijnrood_sync_manual")

    # ---- import_documents (success path) --------------------------------

    def test_import_documents_success_enqueues_and_sets_status(self):
        """With at least one fully-configured folder mapping, import_documents
        enqueues the import job and sets document_import_status."""
        self.settings.append(
            "document_folder_mapping",
            {
                "mijnrood_folder_id": 1,
                "folder_name": "Notulen",
                "organization_type": "Chapter",
                "document_type": "Minutes",
            },
        )
        self.settings.save()

        with patch("frappe.enqueue") as enq:
            result = self.settings.import_documents()

        self.assertTrue(result["success"])
        enq.assert_called_once()
        args, kwargs = enq.call_args
        self.assertEqual(args[0], "verenigingen.mijnrood_sync.services.document_import_service.import_all")
        self.assertEqual(kwargs["job_name"], "mijnrood_document_import")
        persisted = frappe.db.get_single_value("MijnRood Sync Settings", "document_import_status")
        self.assertIn("Import job enqueued", persisted)
