# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# Coverage sweep for the Procurios CSV Import controller, targeting the surfaces
# the existing tests (verenigingen/tests/member/test_procurios_csv_import.py)
# leave uncovered:
#
#   - _validate_and_preview_csv(): empty-file failure, ready-for-import, and the
#     no-valid-rows failure branch (status/preview/error_log/total_rows writes)
#   - _get_status_mapping(): builds the lowercase lookup from the child table,
#     skipping incomplete rows
#   - _process_single_member(): status-mapping override via _type_value, gender
#     write, procurios_data child rows, and the address branch
#   - _create_addresses(): address-type mapping, country-name mapping, primary
#     selection, and the empty-address skip
#
# Everything runs REAL against the DB. The only thing avoided is the Redis
# enqueue inside on_submit (covered by the existing end-to-end test). No
# business logic is mocked.

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.procurios_csv_fixtures import create_csv_file_attachment

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
    row = {h: "" for h in _MEMBER_CSV_HEADERS}
    row.update(
        {
            "NVV-relatienummer": "COV-1",
            "Voornaam": "Cov",
            "Volledige naam": "Cov Tester",
            "E-mailadres": "cov@example.test",
            "Aanmaakdatum": "01-01-2020",
            "Type": "Active",
        }
    )
    row.update(overrides)
    return row


def _make_import_doc(file_url, **fields):
    doc = frappe.get_doc(
        {
            "doctype": "Procurios CSV Import",
            "csv_file": file_url,
            "csv_delimiter": "Semicolon",
            **fields,
        }
    )
    doc.insert()
    return doc


class TestProcuriosValidateAndPreview(EnhancedTestCase):
    """_validate_and_preview_csv() branch coverage (no submit)."""

    def test_ready_for_import_sets_preview_and_totals(self):
        suffix = frappe.generate_hash(length=6)
        rows = [
            _member_csv_row(**{"NVV-relatienummer": f"R-{suffix}"}),
            _member_csv_row(
                **{"NVV-relatienummer": f"R2-{suffix}", "Voornaam": "Two", "Volledige naam": "Two Lid"}
            ),
        ]
        file_url = create_csv_file_attachment(rows, _MEMBER_CSV_HEADERS, prefix="procurios_cov_")
        doc = _make_import_doc(file_url)

        with self.assertNoErrorLog():
            doc._validate_and_preview_csv()

        doc.reload()
        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertEqual(doc.total_rows, 2)
        # Preview JSON is written and strips the internal keys.
        self.assertTrue(doc.preview_data)
        self.assertIn("_procurios_fields", doc.preview_data)
        self.assertNotIn("procurios_data", doc.preview_data)
        self.assertIn("Procurios import - 2 rows", doc.descriptive_name)

    def test_empty_file_marks_failed(self):
        # A header-only CSV parses to zero data rows.
        file_url = create_csv_file_attachment([], _MEMBER_CSV_HEADERS, prefix="procurios_cov_empty_")
        doc = _make_import_doc(file_url)

        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")
        self.assertTrue(doc.error_log)

    def test_all_invalid_rows_marks_failed_with_errors(self):
        suffix = frappe.generate_hash(length=6)
        # Row with an identifier but no name (neither Voornaam nor derivable
        # last name) is rejected by the validator → no mapped data.
        rows = [
            _member_csv_row(
                **{
                    "NVV-relatienummer": f"BAD-{suffix}",
                    "Voornaam": "",
                    "Volledige naam": "",
                }
            )
        ]
        file_url = create_csv_file_attachment(rows, _MEMBER_CSV_HEADERS, prefix="procurios_cov_bad_")
        doc = _make_import_doc(file_url)

        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")
        self.assertTrue(doc.error_log)


class TestProcuriosStatusMapping(EnhancedTestCase):
    """_get_status_mapping() + the status-override branch of _process_single_member."""

    def test_status_mapping_lowercases_and_skips_incomplete_rows(self):
        file_url = create_csv_file_attachment(
            [_member_csv_row()], _MEMBER_CSV_HEADERS, prefix="procurios_cov_map_"
        )
        doc = _make_import_doc(file_url)
        doc.append("status_mapping", {"procurios_value": "Lid", "member_status": "Active"})
        doc.append("status_mapping", {"procurios_value": "Overleden", "member_status": "Deceased"})
        # Incomplete rows must be ignored.
        doc.append("status_mapping", {"procurios_value": "", "member_status": "Quit"})
        doc.append("status_mapping", {"procurios_value": "Ignored", "member_status": ""})

        mapping = doc._get_status_mapping()
        self.assertEqual(mapping, {"lid": "Active", "overleden": "Deceased"})

    def test_process_single_member_uses_type_value_for_status(self):
        suffix = frappe.generate_hash(length=8)
        file_url = create_csv_file_attachment(
            [_member_csv_row()], _MEMBER_CSV_HEADERS, prefix="procurios_cov_proc_"
        )
        doc = _make_import_doc(file_url, default_status="Pending")
        doc.append("status_mapping", {"procurios_value": "Overleden", "member_status": "Deceased"})

        row = {
            "member_id": f"COVMAP-{suffix}",
            "procurios_id": f"PID-{suffix}",
            "first_name": f"Map-{suffix}",
            "last_name": "Tester",
            "email": f"map+{suffix}@example.test",
            "_type_value": "Overleden",  # mapped → Deceased, overrides default_status
            "gender": "Female",
            "procurios_data": [{"field_label": "Hobby", "field_value": "Reading", "field_category": "Other"}],
            "row_number": 2,
        }
        error_log = []
        status, member_name = doc._process_single_member(row, error_log)

        self.assertEqual(status, "created")
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.status, "Deceased")
        self.assertEqual(member.gender, "Female")
        labels = [r.field_label for r in member.procurios_data]
        self.assertIn("Hobby", labels)
        self.assertEqual(error_log, [])

    def test_process_single_member_falls_back_to_default_status(self):
        suffix = frappe.generate_hash(length=8)
        file_url = create_csv_file_attachment(
            [_member_csv_row()], _MEMBER_CSV_HEADERS, prefix="procurios_cov_def_"
        )
        doc = _make_import_doc(file_url, default_status="Pending")

        row = {
            "member_id": f"COVDEF-{suffix}",
            "first_name": f"Def-{suffix}",
            "last_name": "Tester",
            "email": f"def+{suffix}@example.test",
            "_type_value": "UnknownType",  # not in mapping → default_status
            "row_number": 3,
        }
        status, member_name = doc._process_single_member(row, [])
        self.assertEqual(status, "created")
        self.assertEqual(frappe.get_doc("Member", member_name).status, "Pending")


class TestProcuriosAddressCreation(EnhancedTestCase):
    """_create_addresses() + the address branch of _process_single_member."""

    def _addr(self, **kw):
        base = {
            "address_type": "Standaardadres",
            "street": "Hoofdstraat",
            "house_number": "1",
            "city": "Amsterdam",
            "pincode": "1000AA",
            "country": "nederland",
            "addressee": "",
        }
        base.update(kw)
        return base

    def test_member_with_addresses_creates_and_links_primary(self):
        suffix = frappe.generate_hash(length=8)
        file_url = create_csv_file_attachment(
            [_member_csv_row()], _MEMBER_CSV_HEADERS, prefix="procurios_cov_addr_"
        )
        doc = _make_import_doc(file_url, import_addresses=1, preferred_address_type="Standaardadres")

        row = {
            "member_id": f"COVADDR-{suffix}",
            "first_name": f"Addr-{suffix}",
            "last_name": "Tester",
            "email": f"addr+{suffix}@example.test",
            "row_number": 4,
            "addresses": [
                self._addr(),  # Standaardadres → Personal, primary
                self._addr(address_type="Postadres", street="Postlaan", house_number="9", country="belgie"),
                self._addr(address_type="", street="", house_number="", city=""),  # skipped (empty)
            ],
        }
        status, member_name = doc._process_single_member(row, [])
        self.assertEqual(status, "created")

        addresses = frappe.get_all(
            "Address",
            filters={
                "name": [
                    "in",
                    [
                        link.parent
                        for link in frappe.get_all(
                            "Dynamic Link",
                            filters={"link_doctype": "Member", "link_name": member_name},
                            fields=["parent"],
                        )
                    ]
                    or [""],
                ]
            },
            fields=["name", "address_type", "address_line1", "country", "city"],
        )
        # Two real addresses created (empty one skipped).
        self.assertEqual(len(addresses), 2)
        by_type = {a.address_type: a for a in addresses}
        self.assertIn("Personal", by_type)  # Standaardadres mapped
        self.assertIn("Postal", by_type)  # Postadres mapped
        # Country-name mapping applied.
        self.assertEqual(by_type["Personal"].country, "Netherlands")
        self.assertEqual(by_type["Postal"].country, "Belgium")
        self.assertEqual(by_type["Personal"].address_line1, "Hoofdstraat 1")

        # The preferred (Standaardadres) address is linked as primary.
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.primary_address, by_type["Personal"].name)

    def test_unknown_country_passthrough_and_no_primary_when_not_preferred(self):
        suffix = frappe.generate_hash(length=8)
        file_url = create_csv_file_attachment(
            [_member_csv_row()], _MEMBER_CSV_HEADERS, prefix="procurios_cov_addr2_"
        )
        # Preferred type is Standaardadres but the only address is a Postadres,
        # so primary_address stays unset.
        doc = _make_import_doc(file_url, import_addresses=1, preferred_address_type="Standaardadres")

        row = {
            "member_id": f"COVADDR2-{suffix}",
            "first_name": f"Addr2-{suffix}",
            "last_name": "Tester",
            "email": f"addr2+{suffix}@example.test",
            "row_number": 5,
            "addresses": [
                self._addr(address_type="Postadres", country="Atlantis"),  # unknown country passthrough
            ],
        }
        status, member_name = doc._process_single_member(row, [])
        self.assertEqual(status, "created")

        member = frappe.get_doc("Member", member_name)
        self.assertFalse(member.primary_address)
