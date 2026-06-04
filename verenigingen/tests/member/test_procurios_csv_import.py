# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import unittest


class TestProcuriosDataValidator(unittest.TestCase):
    """Tests for ProcuriosDataValidator field mapping and validation."""

    def setUp(self):
        from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator

        self.validator = ProcuriosDataValidator()

    def test_map_row_maps_native_fields(self):
        """Native Procurios fields map to correct Member fields."""
        row = {
            "NVV-relatienummer": "12345",
            "Procurios relatie ID": "99001",
            "Voornaam": "Jan",
            "Tussenvoegsel": "van der",
            "Volledige naam": "Jan van der Berg",
            "E-mailadres": "jan@example.com",
            "Geboortedatum": "15-03-1985",
            "Bankrekening": "NL91ABNA0417164300",
            "Aanmaakdatum": "01-01-2020",
            "Mobiel": "+31612345678",
        }
        mapped = self.validator.map_row_data(row, row_num=1)

        self.assertEqual(mapped["member_id"], "12345")
        self.assertEqual(mapped["procurios_id"], "99001")
        self.assertEqual(mapped["first_name"], "Jan")
        self.assertEqual(mapped["tussenvoegsel"], "van der")
        self.assertEqual(mapped["email"], "jan@example.com")
        self.assertEqual(mapped["birth_date"], "1985-03-15")
        self.assertEqual(mapped["iban"], "NL91ABNA0417164300")
        self.assertEqual(mapped["member_since"], "2020-01-01")

    def test_systeem_id_maps_to_procurios_id(self):
        """Systeem ID also maps to procurios_id."""
        row = {"Systeem ID": "55555", "Voornaam": "Test", "Volledige naam": "Test User"}
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["procurios_id"], "55555")

    def test_map_row_derives_last_name(self):
        """Last name is derived from Volledige naam minus Voornaam and Tussenvoegsel."""
        row = {
            "Voornaam": "Jan",
            "Tussenvoegsel": "van der",
            "Volledige naam": "Jan van der Berg",
            "Systeem ID": "1",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["last_name"], "Berg")

    def test_map_row_derives_last_name_without_tussenvoegsel(self):
        """Last name derivation works when there is no tussenvoegsel."""
        row = {
            "Voornaam": "Maria",
            "Volledige naam": "Maria Jansen",
            "Systeem ID": "2",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["last_name"], "Jansen")

    def test_map_row_falls_back_to_naam(self):
        """Falls back to Naam field when Volledige naam is missing."""
        row = {
            "Voornaam": "Pieter",
            "Naam": "Pieter de Groot",
            "Tussenvoegsel": "de",
            "Systeem ID": "3",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["last_name"], "Groot")

    def test_map_row_stores_extra_fields_in_procurios_data(self):
        """Fields not in NATIVE_FIELD_MAPPING go to procurios_data list."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "VEGAN Magazine": "Papieren versie (per post)",
            "JOUR_waarom lid geworden": "voor de dieren",
            "Contributie jaarlid": "€ 60,-",
        }
        mapped = self.validator.map_row_data(row, row_num=1)

        labels = [item["field_label"] for item in mapped["procurios_data"]]
        self.assertIn("VEGAN Magazine", labels)
        self.assertIn("JOUR_waarom lid geworden", labels)
        self.assertIn("Contributie jaarlid", labels)

    def test_categorize_field_personal(self):
        """Personal fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("Voorkeurstaal"), "Personal")
        self.assertEqual(self.validator.categorize_field("Voorletters"), "Personal")
        self.assertEqual(self.validator.categorize_field("Titel"), "Personal")

    def test_categorize_field_financial(self):
        """Financial fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("Contributie jaarlid"), "Financial")
        self.assertEqual(self.validator.categorize_field("Bankrekening"), "Financial")
        self.assertEqual(self.validator.categorize_field("€ 60,-"), "Financial")
        self.assertEqual(
            self.validator.categorize_field("Bedrag openstaande facturen"), "Financial"
        )

    def test_categorize_field_subscription(self):
        """Subscription fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("VEGAN Magazine"), "Subscription")
        self.assertEqual(self.validator.categorize_field("Nieuwsbrief voorkeur"), "Subscription")

    def test_categorize_field_survey(self):
        """Survey fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("JOUR_waarom lid geworden"), "Survey")
        self.assertEqual(self.validator.categorize_field("JOUR_wat moeten wij doen"), "Survey")

    def test_categorize_field_campaign(self):
        """Campaign fields are categorized correctly."""
        self.assertEqual(self.validator.categorize_field("Campagnes"), "Campaign")
        self.assertEqual(self.validator.categorize_field("Welkomstcadeau VC"), "Campaign")
        self.assertEqual(self.validator.categorize_field("Binnengekomen via actie"), "Campaign")
        self.assertEqual(self.validator.categorize_field("Aanmeldcode"), "Campaign")

    def test_categorize_field_other(self):
        """Unknown fields default to Other."""
        self.assertEqual(self.validator.categorize_field("Opnummerveld relaties"), "Other")

    def test_validate_row_requires_identifier(self):
        """Validation fails when both NVV-relatienummer and Procurios ID are missing."""
        row = {"first_name": "Jan", "last_name": "Berg", "row_number": 1}
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("identifier" in e.lower() for e in errors))

    def test_validate_row_accepts_procurios_id_only(self):
        """Validation passes with only procurios_id (no member_id)."""
        row = {"procurios_id": "99001", "first_name": "Jan", "last_name": "Berg", "row_number": 1}
        errors = self.validator.validate_row(row, row_num=1)
        self.assertEqual(errors, [])

    def test_validate_row_requires_name(self):
        """Validation fails when both first_name and last_name are missing."""
        row = {"member_id": "123", "row_number": 1}
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("name" in e.lower() for e in errors))

    def test_validate_row_accepts_valid_row(self):
        """Validation passes for a complete valid row."""
        row = {
            "member_id": "123",
            "first_name": "Jan",
            "last_name": "Berg",
            "email": "jan@example.com",
            "iban": "NL91ABNA0417164300",
            "row_number": 1,
        }
        errors = self.validator.validate_row(row, row_num=1)
        self.assertEqual(errors, [])

    def test_validate_row_rejects_invalid_email(self):
        """Validation catches invalid email format."""
        row = {
            "member_id": "123",
            "first_name": "Jan",
            "last_name": "Berg",
            "email": "not-an-email",
            "row_number": 1,
        }
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("email" in e.lower() for e in errors))

    def test_validate_and_map_data_returns_mapped_data_and_errors(self):
        """Full validation pipeline returns both mapped data and error list."""
        csv_data = [
            {
                "Systeem ID": "100",
                "Voornaam": "Anna",
                "Volledige naam": "Anna Smit",
                "E-mailadres": "anna@example.com",
            },
            {
                "Voornaam": "Missing ID",
                "Volledige naam": "Missing ID Person",
            },
        ]
        mapped_data, errors = self.validator.validate_and_map_data(csv_data)
        self.assertEqual(len(mapped_data), 1)
        self.assertTrue(len(errors) > 0)

    def test_gender_stored_in_procurios_data_by_default(self):
        """When import_gender is False (default), Geslacht goes to procurios_data."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Geslacht": "Man",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertNotIn("gender", mapped)
        labels = [item["field_label"] for item in mapped["procurios_data"]]
        self.assertIn("Geslacht", labels)

    def test_gender_mapped_when_import_gender_enabled(self):
        """When import_gender is True, Geslacht maps to gender field."""
        from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator

        validator = ProcuriosDataValidator(import_gender=True)
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Geslacht": "Man",
        }
        mapped = validator.map_row_data(row, row_num=1)
        self.assertEqual(mapped["gender"], "Male")

    def test_address_fields_extracted(self):
        """Address fields are grouped into address dicts."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Standaardadres: Straat": "Keizersgracht",
            "Standaardadres: Nummer met toevoeging": "123A",
            "Standaardadres: Postcode": "1015 CJ",
            "Standaardadres: Plaats": "Amsterdam",
            "Standaardadres: Landnaam": "Nederland",
            "Standaardadres: Geadresseerde": "Jan Berg",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertIn("addresses", mapped)
        self.assertEqual(len(mapped["addresses"]), 1)
        addr = mapped["addresses"][0]
        self.assertEqual(addr["address_type"], "Standaardadres")
        self.assertEqual(addr["street"], "Keizersgracht")
        self.assertEqual(addr["house_number"], "123A")
        self.assertEqual(addr["pincode"], "1015 CJ")
        self.assertEqual(addr["city"], "Amsterdam")

    def test_multiple_address_types_extracted(self):
        """Multiple address types each produce their own address dict."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Standaardadres: Straat": "Keizersgracht",
            "Standaardadres: Plaats": "Amsterdam",
            "Postadres: Straat": "Herengracht",
            "Postadres: Plaats": "Amsterdam",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(len(mapped["addresses"]), 2)
        types = [a["address_type"] for a in mapped["addresses"]]
        self.assertIn("Standaardadres", types)
        self.assertIn("Postadres", types)

    def test_empty_address_not_extracted(self):
        """Address types with no data are not included."""
        row = {
            "Systeem ID": "1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Berg",
            "Factuuradres: Straat": "",
            "Factuuradres: Plaats": "",
        }
        mapped = self.validator.map_row_data(row, row_num=1)
        self.assertEqual(len(mapped.get("addresses", [])), 0)


# ---- Controller-level tests (integration; need a Frappe site) ---------------

import frappe  # noqa: E402

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase  # noqa: E402


def _create_stub_procurios_csv_import_doc():
    """Test fixture: insert a Procurios CSV Import with a placeholder file."""
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": "stub_member.csv",
        "is_private": 1,
        "content": b"stub",
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()

    doc = frappe.get_doc({
        "doctype": "Procurios CSV Import",
        "csv_file": file_doc.file_url,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


class TestProcuriosCSVImportPermissions(EnhancedTestCase):
    """Non-admin users must not be able to trigger the whitelisted endpoints.

    Sibling of TestProcuriosMandateImportPermissions. The regex match on
    'only allowed' isolates the frappe.only_for gate from later
    get_doc / row-level permission checks.
    """

    def test_non_admin_cannot_validate(self):
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            validate_import_file,
        )

        doc = _create_stub_procurios_csv_import_doc()

        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                validate_import_file(doc.name)
        finally:
            frappe.set_user(original_user)

    def test_non_admin_cannot_run_background(self):
        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            process_import_background,
        )

        doc = _create_stub_procurios_csv_import_doc()

        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                process_import_background(doc.name)
            # only_for must run BEFORE any side-effect flag set.
            self.assertFalse(getattr(frappe.flags, "in_background_job", False))
            self.assertFalse(getattr(frappe.flags, "bulk_member_operations", False))
        finally:
            frappe.set_user(original_user)


class TestProcuriosCSVImportPropertyCache(EnhancedTestCase):
    """Regression guard for the property-cache name-mangling fix.

    See TestPropertyCacheHits in test_procurios_mandate_import.py for the
    same guard on the sibling controller.
    """

    def test_validator_is_cached(self):
        doc = _create_stub_procurios_csv_import_doc()
        first = doc._validator
        self.assertIs(first, doc._validator)
        # Pin the cache-slot name — assertIs alone would still pass if a
        # future refactor adopted functools.cached_property or a descriptor,
        # but the name-mangling fix specifically demands the slot be
        # `_validator_instance` (single underscore, unmangled).
        self.assertIn("_validator_instance", doc.__dict__)

    def test_parser_is_cached(self):
        doc = _create_stub_procurios_csv_import_doc()
        first = doc._parser
        self.assertIs(first, doc._parser)
        self.assertIn("_parser_instance", doc.__dict__)


# ---- End-to-end integration ------------------------------------------------

import csv  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402


_MEMBER_CSV_HEADERS = [
    "NVV-relatienummer",
    "Systeem ID",
    "Voornaam",
    "Tussenvoegsel",
    "Volledige naam",
    "E-mailadres",
    "Geboortedatum",
    "Bankrekening",
    "Aanmaakdatum",
    "Mobiel",
    "Type",
]


def _member_csv_row(**overrides):
    """Build one valid Procurios member CSV row.

    Defaults give a fully-populated valid row; overrides override specific
    columns. Identifier and name columns are required by the validator.
    """
    row = {h: "" for h in _MEMBER_CSV_HEADERS}
    row.update(
        {
            "NVV-relatienummer": "MEMBER-1",
            "Voornaam": "Jan",
            "Volledige naam": "Jan Jansen",
            "E-mailadres": "jan@example.test",
            "Bankrekening": "NL91ABNA0417164300",
            "Aanmaakdatum": "01-01-2020",
            "Mobiel": "+31612345678",
            "Type": "Active",
        }
    )
    row.update(overrides)
    return row


def _create_member_csv_attachment(rows):
    """Test fixture: write `rows` to a temp CSV and register as a Frappe File."""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="procurios_member_")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_MEMBER_CSV_HEADERS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(path, "rb") as f:
        content = f.read()
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": os.path.basename(path),
            "is_private": 1,
            "content": content,
        }
    )
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url


def _create_existing_member(member_id, suffix):
    """Test fixture: pre-create a Member that will collide with a CSV row."""
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "member_id": member_id,
            "first_name": "Existing",
            "last_name": "Member",
            "email": f"existing+{suffix}@example.test",
            "status": "Active",
        }
    )
    member.flags.ignore_permissions = True
    member.flags.ignore_mandatory = True
    member.insert()
    return member


def _create_procurios_csv_import_doc(file_url):
    """Test fixture: insert a Procurios CSV Import pointing at `file_url`."""
    doc = frappe.get_doc(
        {
            "doctype": "Procurios CSV Import",
            "csv_file": file_url,
            "csv_delimiter": "Semicolon",
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


class TestProcuriosCSVImportEndToEnd(EnhancedTestCase):
    """Full validate → process_import_background flow run in-process.

    Procurios handoff §8 test gap: 'No test that the sibling
    member-importer's own process_import_background works end-to-end.'
    Mirrors TestProcuriosMandateImportEndToEnd in style.
    """

    def test_end_to_end_creates_members_and_skips_duplicate(self):
        # Use unique identifiers per test run so concurrent / re-run executions
        # don't fight over the same member_id.
        suffix = frappe.generate_hash(length=8)
        existing_member_id = f"E2E-EXISTING-{suffix}"
        new_member_id = f"E2E-NEW-{suffix}"
        nameless_id = f"E2E-NAMELESS-{suffix}"

        # Pre-create one Member that will be hit by the duplicate-row branch.
        _create_existing_member(existing_member_id, suffix)

        # Names must be unique per run too — the Member-to-Customer sync
        # commits independently of the test transaction, so a fixed
        # "Nieuw Lid" would collide on the second run.
        rows = [
            # new valid row → CREATED
            _member_csv_row(
                **{
                    "NVV-relatienummer": new_member_id,
                    "Voornaam": f"Nieuw-{suffix}",
                    "Volledige naam": f"Nieuw-{suffix} Lid",
                    "E-mailadres": f"nieuw+{suffix}@example.test",
                }
            ),
            # collides with the pre-existing member_id → SKIPPED (duplicate)
            _member_csv_row(
                **{
                    "NVV-relatienummer": existing_member_id,
                    "Voornaam": f"Duplicate-{suffix}",
                    "Volledige naam": f"Duplicate-{suffix} Attempt",
                    "E-mailadres": f"dup+{suffix}@example.test",
                }
            ),
            # missing both Voornaam and a derivable last name → validator-stage error
            _member_csv_row(
                **{
                    "NVV-relatienummer": nameless_id,
                    "Voornaam": "",
                    "Volledige naam": "",
                    "E-mailadres": f"nameless+{suffix}@example.test",
                }
            ),
        ]
        file_url = _create_member_csv_attachment(rows)
        doc = _create_procurios_csv_import_doc(file_url)
        doc.submit()  # enqueues; we drive synchronously

        from verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import import (
            process_import_background,
        )

        process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")

        # 1 new member created. The nameless row is rejected at the validator
        # stage before reaching the processor (does not count as "skipped");
        # the duplicate row reaches the processor and IS counted as skipped.
        self.assertEqual(doc.members_created, 1)
        self.assertEqual(doc.members_skipped, 1)

        # The duplicate row must produce a Duplicate-related diagnostic
        # in error_log. We assert on the duplicate-key text and the
        # offending member_id rather than the specific exception-branch
        # phrasing — Frappe's exception wrapping for IntegrityError vs
        # DuplicateEntryError varies between versions, but the
        # underlying string always references the conflicting key.
        log = doc.error_log or ""
        self.assertIn("Duplicate", log)
        self.assertIn(existing_member_id, log)

        # Confirm the new Member exists in the DB and has the right shape.
        created = frappe.get_doc("Member", {"member_id": new_member_id})
        self.assertEqual(created.first_name, f"Nieuw-{suffix}")
        self.assertEqual(created.last_name, "Lid")
        self.assertEqual(created.status, "Active")
        # The test row uses NVV-relatienummer only (not Systeem ID), so
        # procurios_id is intentionally absent. `assertFalse` covers both
        # None (current behaviour, no field default) and "" (if a future
        # contributor adds a "default": "" to member.json's procurios_id).
        self.assertFalse(created.procurios_id)

        # Background-job flags are cleaned up.
        self.assertFalse(getattr(frappe.flags, "in_background_job", False))
        self.assertFalse(getattr(frappe.flags, "bulk_member_operations", False))
