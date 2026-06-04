# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Integration tests for the Procurios Mandate Import flow.

Real DB. No business-logic mocks (per project test-quality enforcer).
"""

import csv
import json
import os
import tempfile
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


CSV_HEADERS = [
    "Incasso-afspraak ID",
    "Type machtiging",
    "Type machtiging ID",
    "Mandaatnummer",
    "IBAN",
    "Incassant",
    "Incassant ID",
    "Rekeninghouder",
    "Debiteur naam",
    "Debiteur ID",
    "Datum van ondertekening",
    "Opzegdatum",
    "Pre-notificatie datum",
    "Administratie ID",
    "Administratie",
]


def _base_row(**overrides):
    row = {
        "Incasso-afspraak ID": "973",
        "Type machtiging": "Doorlopend",
        "Type machtiging ID": "2",
        "Mandaatnummer": "M-001",
        "IBAN": "NL91ABNA0417164300",
        "Incassant": "NVV",
        "Incassant ID": "2",
        "Rekeninghouder": "J. Jansen",
        "Debiteur naam": "Jan Jansen",
        "Debiteur ID": "PROC-1",
        "Datum van ondertekening": "2020-01-15",
        "Opzegdatum": "",
        "Pre-notificatie datum": "",
        "Administratie ID": "1",
        "Administratie": "NVV",
    }
    row.update(overrides)
    return row


def _create_csv_attach(rows):
    """Test fixture: write `rows` to a temp CSV and register as a Frappe File."""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="procurios_mandate_")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    with open(path, "rb") as f:
        content = f.read()

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": os.path.basename(path),
        "is_private": 1,
        "content": content,
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url


def _create_raw_csv_attach(raw_text: str, name_hint: str = "raw.csv"):
    """Test fixture: register an arbitrary CSV blob as a Frappe File."""
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": name_hint,
        "is_private": 1,
        "content": raw_text.encode("utf-8"),
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url


def _create_import_doc(file_url: str, **fields):
    """Test fixture: insert a Procurios Mandate Import pointing at `file_url`."""
    payload = {
        "doctype": "Procurios Mandate Import",
        "csv_file": file_url,
        "csv_delimiter": "Semicolon",
    }
    payload.update(fields)
    doc = frappe.get_doc(payload)
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


class TestProcuriosMandateImportValidate(EnhancedTestCase):
    """Validate / preview phase — no submission."""

    def test_validate_marks_ready_with_preview(self):
        rows = [_base_row(Mandaatnummer="M-001"), _base_row(Mandaatnummer="M-002")]
        file_url = _create_csv_attach(rows)
        doc = _create_import_doc(file_url)

        doc._validate_and_preview_csv()
        doc.reload()

        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertEqual(doc.total_rows, 2)
        preview = json.loads(doc.preview_data)
        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[0]["mandate_id"], "M-001")

    def test_validate_fails_on_missing_required_column(self):
        # CSV missing 'Mandaatnummer'
        file_url = _create_raw_csv_attach(
            "IBAN;Rekeninghouder\nNL91ABNA0417164300;J. Jansen\n",
            name_hint="missing_mandaatnummer.csv",
        )
        doc = _create_import_doc(file_url)

        doc._validate_and_preview_csv()
        doc.reload()

        self.assertEqual(doc.import_status, "Failed")
        self.assertIn("Mandaatnummer", doc.error_log or "")


def _create_member_with_procurios_id(test_case, procurios_id: str, **kwargs):
    """Test fixture: create a Member with a specific procurios_id."""
    member = test_case.create_test_member(procurios_id=procurios_id, **kwargs)
    return member


def _create_active_sepa_mandate(member_name: str, mandate_id: str, iban: str):
    """Test fixture: insert an Active SEPA Mandate for `member_name`."""
    mandate = frappe.get_doc({
        "doctype": "SEPA Mandate",
        "mandate_id": mandate_id,
        "member": member_name,
        "account_holder_name": "Test Holder",
        "iban": iban,
        "sign_date": "2023-01-01",
        "mandate_type": "RCUR",
        "scheme": "SEPA",
    })
    mandate.flags.ignore_permissions = True
    mandate.insert()
    return mandate


def _create_stub_import_doc():
    """Test fixture: an import doc with a placeholder file (file content unused)."""
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": "stub.csv",
        "is_private": 1,
        "content": b"stub",
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()

    doc = frappe.get_doc({
        "doctype": "Procurios Mandate Import",
        "csv_file": file_doc.file_url,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def _make_mandate_row(**kw):
    """Build a ProcuriosMandateRow for tests (pure-Python; no DB)."""
    from verenigingen.utils.csv.procurios_mandate_validator import ProcuriosMandateRow

    defaults = dict(
        row_number=1,
        mandate_id="M-100",
        iban="NL91ABNA0417164300",
        account_holder_name="J. Jansen",
        debiteur_id="PROC-1",
        debiteur_naam="Jan Jansen",
        sign_date="2020-01-15",
        cancelled_date=None,
        mandate_type="RCUR",
        notes="Imported from Procurios.",
    )
    defaults.update(kw)
    return ProcuriosMandateRow(**defaults)


def _empty_skip_counters():
    return {
        "no_member": 0,
        "ambiguous_member": 0,
        "duplicate": 0,
        "conflict": 0,
        "error": 0,
    }


def _recent_cancellation_date():
    """A cancellation date well inside the 12-month cutoff.

    Tests must not hard-code a wall-clock date here, or they will start
    failing as the real `date.today()` moves past 12 months from that
    date. Use a date 30 days ago relative to today.
    """
    from frappe.utils import add_days, today

    return add_days(today(), -30)


class TestProcuriosMandateImportProcessRow(EnhancedTestCase):
    """Per-row processor — exercises every branch of the decision tree."""

    def test_creates_mandate_when_member_exists(self):
        member = _create_member_with_procurios_id(self, "PROC-1")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-100", debiteur_id="PROC-1")

        status, name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "created")
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.member, member.name)
        self.assertEqual(mandate.status, "Active")
        # The validation service normalises IBAN spacing (e.g. "NL91 ABNA 0417 1643 00"),
        # so compare without spaces.
        self.assertEqual(mandate.iban.replace(" ", ""), "NL91ABNA0417164300")
        # Cache must be updated so a subsequent active row for same member triggers conflict.
        self.assertIn(member.name, caches.members_with_active_mandate)

    def test_skips_when_no_member_match(self):
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(debiteur_id="NO-SUCH-ID")

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(name, "")
        self.assertEqual(counters["no_member"], 1)

    def test_skips_duplicate_active(self):
        member = _create_member_with_procurios_id(self, "PROC-2")
        _create_active_sepa_mandate(member.name, "M-DUP", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-DUP", debiteur_id="PROC-2")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["duplicate"], 1)

    def test_updates_existing_when_csv_cancelled(self):
        member = _create_member_with_procurios_id(self, "PROC-3")
        existing = _create_active_sepa_mandate(member.name, "M-UPD", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        cancel_date = _recent_cancellation_date()
        row = _make_mandate_row(
            mandate_id="M-UPD", debiteur_id="PROC-3", cancelled_date=cancel_date
        )

        status, _name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "updated")
        updated = frappe.get_doc("SEPA Mandate", existing.name)
        self.assertEqual(str(updated.cancelled_date), cancel_date)
        self.assertEqual(updated.status, "Cancelled")
        # Active-count cache: this member's count should now be zero.
        self.assertNotIn(member.name, caches.members_with_active_mandate)
        self.assertEqual(caches.member_to_active_count.get(member.name, 0), 0)

    def test_skips_conflict_when_member_has_other_active(self):
        member = _create_member_with_procurios_id(self, "PROC-4")
        _create_active_sepa_mandate(member.name, "M-EXISTING", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-NEW", debiteur_id="PROC-4")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["conflict"], 1)
        self.assertFalse(frappe.db.exists("SEPA Mandate", {"mandate_id": "M-NEW"}))

    def test_cancelled_row_for_member_with_active_mandate_still_imports(self):
        # A historical cancelled mandate doesn't conflict with an active one.
        _create_member_with_procurios_id(self, "PROC-5")
        member_doc = frappe.get_value(
            "Member", {"procurios_id": "PROC-5"}, "name"
        )
        _create_active_sepa_mandate(member_doc, "M-ACTIVE", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="M-OLD", debiteur_id="PROC-5", cancelled_date=_recent_cancellation_date()
        )

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "created")
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.status, "Cancelled")
        self.assertEqual(counters["conflict"], 0)

    def test_two_active_rows_same_member_second_conflicts(self):
        _create_member_with_procurios_id(self, "PROC-6")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()  # member has no active mandate yet
        counters = _empty_skip_counters()
        errors = []

        s1, _ = doc._process_single_row(
            _make_mandate_row(mandate_id="M-A", debiteur_id="PROC-6"),
            errors, caches, counters,
        )
        s2, _ = doc._process_single_row(
            _make_mandate_row(mandate_id="M-B", debiteur_id="PROC-6"),
            errors, caches, counters,
        )
        self.assertEqual(s1, "created")
        self.assertEqual(s2, "skipped")
        self.assertEqual(counters["conflict"], 1)

    def test_invalid_iban_logs_error_and_skips(self):
        _create_member_with_procurios_id(self, "PROC-7")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-BAD", debiteur_id="PROC-7", iban="NOT-AN-IBAN")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["error"], 1)
        self.assertTrue(any("Row 1" in e for e in errors))


from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import (
    process_import_background,
)


class TestProcuriosMandateImportEndToEnd(EnhancedTestCase):
    """Full validate → process flow run in-process."""

    def test_end_to_end_mixed_outcomes(self):
        # Members for the active and cancellation rows. The orphan member ensures
        # the `filtered_old_cancelled` row has a procurios_id that exists in the
        # DB; even so the row will be filtered before reaching the processor.
        m_active = _create_member_with_procurios_id(self, "E2E-ACT")
        m_cancel = _create_member_with_procurios_id(self, "E2E-CAN")
        _create_member_with_procurios_id(self, "E2E-ORPH")

        # An existing active mandate that will be updated by a cancelled row.
        existing = _create_active_sepa_mandate(
            m_cancel.name, "E2E-EXISTING", "NL91ABNA0417164300"
        )

        recent_cancel = _recent_cancellation_date()
        rows = [
            # active import, member exists, new mandate id → CREATED
            _base_row(Mandaatnummer="E2E-NEW", Opzegdatum="", **{"Debiteur ID": "E2E-ACT"}),
            # cancelled import, matches existing mandate id → UPDATED
            _base_row(
                Mandaatnummer="E2E-EXISTING",
                Opzegdatum=recent_cancel,
                **{"Debiteur ID": "E2E-CAN"},
            ),
            # cancelled long ago → FILTERED (validator drops it before processing)
            _base_row(Mandaatnummer="E2E-OLD", Opzegdatum="2020-01-01", **{"Debiteur ID": "E2E-ORPH"}),
            # debiteur with no matching Member → no_member
            _base_row(Mandaatnummer="E2E-NOMBR", Opzegdatum="", **{"Debiteur ID": "DOES-NOT-EXIST"}),
        ]
        file_url = _create_csv_attach(rows)
        doc = _create_import_doc(file_url)
        doc.submit()  # enqueues; we drive synchronously

        process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.mandates_created, 1)
        self.assertEqual(doc.mandates_updated, 1)
        # skipped = filtered_old (1) + no_member (1) = 2
        self.assertEqual(doc.mandates_skipped, 2)

        self.assertIn("filtered_old_cancelled: 1", doc.skipped_summary)
        self.assertIn("no_member: 1", doc.skipped_summary)

        # Created mandate is linked to the member's sepa_mandates table via after_insert.
        # No defensive hasattr fallback — if the link table's field name changes,
        # we want this test to fail loudly with a clear AttributeError, not silently
        # collect Nones and miss the regression.
        member = frappe.get_doc("Member", m_active.name)
        member_mandate_refs = [
            link.mandate_reference for link in (member.sepa_mandates or [])
        ]
        self.assertIn("E2E-NEW", member_mandate_refs)

        # Existing mandate now cancelled.
        existing.reload()
        self.assertEqual(existing.status, "Cancelled")
        self.assertEqual(str(existing.cancelled_date), recent_cancel)


class TestProcuriosMandateImportAmbiguousMember(EnhancedTestCase):
    """Two Members share the same procurios_id → row is skipped, not silently
    assigned to the last Member that happened to be returned by the query."""

    def test_duplicate_procurios_id_yields_ambiguous_member_skip(self):
        m1 = _create_member_with_procurios_id(self, "DUP-ID", last_name="AmbigA")
        m2 = _create_member_with_procurios_id(self, "DUP-ID", last_name="AmbigB")
        self.assertNotEqual(m1.name, m2.name)

        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        self.assertIn("DUP-ID", caches.ambiguous_procurios_ids)
        self.assertNotIn("DUP-ID", caches.procurios_id_to_member)

        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="AMBIG-1", debiteur_id="DUP-ID")
        status, _ = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "skipped")
        self.assertEqual(counters["ambiguous_member"], 1)
        self.assertEqual(counters["no_member"], 0)
        self.assertFalse(frappe.db.exists("SEPA Mandate", {"mandate_id": "AMBIG-1"}))


class TestProcuriosMandateImportAllFilteredCompletes(EnhancedTestCase):
    """A CSV where every row is filtered by the cutoff is a Completed import,
    not a Failed one. The skipped_summary reports the filtered count."""

    def test_all_rows_filtered_marks_completed(self):
        _create_member_with_procurios_id(self, "AF-1", last_name="AllFilt1")
        _create_member_with_procurios_id(self, "AF-2", last_name="AllFilt2")

        rows = [
            _base_row(
                Mandaatnummer="AF-OLD-1",
                Opzegdatum="2020-01-01",
                **{"Debiteur ID": "AF-1"},
            ),
            _base_row(
                Mandaatnummer="AF-OLD-2",
                Opzegdatum="2019-06-15",
                **{"Debiteur ID": "AF-2"},
            ),
        ]
        file_url = _create_csv_attach(rows)
        doc = _create_import_doc(file_url)
        doc.submit()
        process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.mandates_created, 0)
        self.assertEqual(doc.mandates_updated, 0)
        self.assertEqual(doc.mandates_skipped, 2)
        self.assertIn("filtered_old_cancelled: 2", doc.skipped_summary)


class TestProcuriosMandateImportPermissions(EnhancedTestCase):
    """Non-admin users must not be able to trigger the whitelisted endpoints.

    Per project memory feedback_tests_run_as_admin.md: permission-sensitive
    flows need a test running as the actual target role (not Administrator),
    because Administrator bypasses all DocPerms.

    The exception-message regex ('only allowed') matches what
    frappe.only_for raises — this isolates the only_for gate from the
    later frappe.get_doc permission check (which would raise a different
    PermissionError with a different message). Without the regex match,
    deleting the only_for line would leave the test passing.
    """

    def test_non_admin_cannot_validate(self):
        from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import (
            validate_import_file,
        )

        # Create the import doc as Administrator so the test isn't blocked at
        # setup; then re-run the whitelisted entry point as a plain user.
        doc = _create_stub_import_doc()

        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                validate_import_file(doc.name)
        finally:
            frappe.set_user(original_user)

    def test_non_admin_cannot_run_background(self):
        from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import (
            process_import_background,
        )

        doc = _create_stub_import_doc()

        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                process_import_background(doc.name)
            # only_for must run BEFORE any side-effect flag set.
            self.assertFalse(getattr(frappe.flags, "in_background_job", False))
        finally:
            frappe.set_user(original_user)

    def test_admin_can_validate(self):
        """Positive symmetric test: an admin user should NOT raise."""
        from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import (
            validate_import_file,
        )

        doc = _create_stub_import_doc()
        # frappe.session.user is Administrator inside EnhancedTestCase by
        # default, which is in System Manager. Just call directly.
        result = validate_import_file(doc.name)
        # The stub CSV is intentionally malformed (just b"stub") so we
        # expect an error response — but it should be returned as a dict
        # from inside the function, not raised as PermissionError.
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)


class TestCoerceTestMode(unittest.TestCase):
    """Unit tests for the shared coerce_test_mode helper.

    Lives in verenigingen.utils.csv_import_processor and is now used by
    both Procurios CSV Import and Procurios Mandate Import. Whitelisted
    endpoints receive every arg as a string from REST, so non-empty
    strings like 'false' must NOT be treated as truthy.
    """

    def setUp(self):
        from verenigingen.utils.csv_import_processor import coerce_test_mode

        self.coerce = coerce_test_mode

    def test_real_booleans_passthrough(self):
        self.assertTrue(self.coerce(True))
        self.assertFalse(self.coerce(False))

    def test_truthy_strings(self):
        for s in ("true", "True", "TRUE", "1", "yes", " true "):
            self.assertTrue(self.coerce(s), f"expected truthy: {s!r}")

    def test_falsy_strings(self):
        for s in ("false", "False", "0", "no", "", "off", "anything-else"):
            self.assertFalse(self.coerce(s), f"expected falsy: {s!r}")

    def test_integer_values(self):
        self.assertTrue(self.coerce(1))
        self.assertFalse(self.coerce(0))

    def test_none_is_falsy(self):
        self.assertFalse(self.coerce(None))


class TestPropertyCacheHits(EnhancedTestCase):
    """Regression guard for the property-cache name-mangling fix.

    Both Procurios CSV Import and Procurios Mandate Import historically
    used `self.__validator` / `self.__parser` with `hasattr(self, "__x")`
    — the hasattr never matched the mangled attribute name, so the cache
    never hit. The fix renamed to single-underscore. Without these tests
    a future "cleanup" could silently restore the bug.
    """

    def test_mandate_import_validator_is_cached(self):
        doc = _create_stub_import_doc()
        # First access initialises the cache; second returns the same object.
        first = doc._validator
        self.assertIs(first, doc._validator)
        # Crucially: assert the cache landed on the UNMANGLED attribute name.
        # `assertIs` alone would still pass if some future refactor adopted
        # `functools.cached_property` or a descriptor, but the name-mangling
        # fix specifically demands the slot be `_validator_instance`.
        self.assertIn("_validator_instance", doc.__dict__)

    def test_mandate_import_parser_is_cached(self):
        doc = _create_stub_import_doc()
        first = doc._parser
        self.assertIs(first, doc._parser)
        # See comment above — pin the cache-slot name, not just identity.
        self.assertIn("_parser_instance", doc.__dict__)


import time


class TestProcuriosMandateImportScale(EnhancedTestCase):
    """Volume smoke test — 500 rows, mixed outcomes."""

    def test_500_rows_completes_in_reasonable_time(self):
        # Pre-create 350 members with sequential procurios_ids.
        # Pass explicit last_name so the factory's _global_unique_seq suffix is
        # applied — without it the name pool (20×20) exhausts after 20 members
        # and triggers Customer DuplicateEntryError.
        members_by_id = {}
        for i in range(350):
            m = _create_member_with_procurios_id(
                self, f"SCL-{i}", last_name=f"ScaleTest{i}"
            )
            members_by_id[f"SCL-{i}"] = m.name

        # Pre-create 30 active SEPA Mandates that subsequent CSV rows will
        # update to Cancelled — this exercises the _update_cancellation path
        # under load, the slowest path because it does a save() with the full
        # SEPA Mandate validate cycle.
        for i in range(30):
            _create_active_sepa_mandate(
                members_by_id[f"SCL-{300 + i}"],
                f"SCL-UPD-{i}",
                "NL91ABNA0417164300",
            )

        recent_cancel = _recent_cancellation_date()

        rows = []
        # 250 "active, new mandate" rows → CREATED
        for i in range(250):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-NEW-{i}",
                **{"Debiteur ID": f"SCL-{i}"},
            ))
        # 30 "cancelled, matches existing mandate id" rows → UPDATED
        for i in range(30):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-UPD-{i}",
                Opzegdatum=recent_cancel,
                **{"Debiteur ID": f"SCL-{300 + i}"},
            ))
        # 100 "no member" rows → SKIPPED no_member
        for i in range(100):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-NOMBR-{i}",
                **{"Debiteur ID": f"NOT-EXISTS-{i}"},
            ))
        # 70 "old cancelled" rows → FILTERED by the validator before processing
        for i in range(70):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-OLD-{i}",
                Opzegdatum="2020-01-01",
                **{"Debiteur ID": f"SCL-{i + 250}"},
            ))
        # 50 "active rows for members whose previous row already created an active
        # mandate" → CONFLICT
        for i in range(50):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-CONFLICT-{i}",
                **{"Debiteur ID": f"SCL-{i}"},
            ))

        file_url = _create_csv_attach(rows)
        doc = _create_import_doc(file_url)
        doc.submit()

        start = time.monotonic()
        process_import_background(doc.name, test_mode=False)
        elapsed = time.monotonic() - start

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.mandates_created, 250)
        self.assertEqual(doc.mandates_updated, 30)
        # skipped = no_member (100) + conflict (50) + filtered_old (70) = 220
        self.assertEqual(doc.mandates_skipped, 220)

        # Generous ceiling — local dev typically finishes well under 60s.
        # The point is to catch O(n^2) regressions, not to micro-benchmark.
        # The update path runs an actual save() with the full validate cycle
        # on the SEPA Mandate, which is more expensive than insert, so 30
        # updates add a measurable but bounded cost.
        self.assertLess(
            elapsed,
            180,
            f"500-row import took {elapsed:.1f}s (>180s) — likely a regression",
        )
