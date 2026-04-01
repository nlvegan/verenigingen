# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestProcuriosDataValidator(IntegrationTestCase):
    """Tests for ProcuriosDataValidator field mapping and validation."""

    def setUp(self):
        from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator

        self.validator = ProcuriosDataValidator()

    def test_map_row_maps_native_fields(self):
        """Native Procurios fields map to correct Member fields."""
        row = {
            "Systeem ID": "12345",
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
        self.assertEqual(mapped["first_name"], "Jan")
        self.assertEqual(mapped["tussenvoegsel"], "van der")
        self.assertEqual(mapped["email"], "jan@example.com")
        self.assertEqual(mapped["birth_date"], "1985-03-15")
        self.assertEqual(mapped["iban"], "NL91ABNA0417164300")
        self.assertEqual(mapped["member_since"], "2020-01-01")

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

    def test_validate_row_requires_systeem_id(self):
        """Validation fails when Systeem ID is missing."""
        row = {"first_name": "Jan", "last_name": "Berg", "row_number": 1}
        errors = self.validator.validate_row(row, row_num=1)
        self.assertTrue(any("Systeem ID" in e or "member_id" in e for e in errors))

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
