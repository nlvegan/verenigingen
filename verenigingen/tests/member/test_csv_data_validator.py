"""
Unit Tests for CSV Data Validator

Tests business rule validation for CSV import data including email, IBAN,
birth date validation, and field mapping.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.csv.csv_data_validator import CSVDataValidator


class TestCSVDataValidator(FrappeTestCase):
	"""Test suite for CSVDataValidator"""

	def setUp(self):
		"""Set up test environment"""
		super().setUp()
		self.validator = CSVDataValidator()

	def test_field_mapping_dutch_to_english(self):
		"""Test field mapping from Dutch CSV headers to Member fields"""
		csv_row = {
			"voornaam": "Jan",
			"achternaam": "Jansen",
			"e-mailadres": "jan@example.com",
			"telefoonnr.": "0612345678",
			"geboortedatum": "1990-01-01",
		}

		mapped = self.validator.map_row_data(csv_row, row_num=2)

		self.assertEqual(mapped["first_name"], "Jan")
		self.assertEqual(mapped["last_name"], "Jansen")
		self.assertEqual(mapped["email"], "jan@example.com")
		self.assertEqual(mapped["contact_number"], "0612345678")
		self.assertEqual(mapped["birth_date"], "1990-01-01")

	def test_field_mapping_tussenvoegsel(self):
		"""Test mapping of middle_name to tussenvoegsel"""
		csv_row = {"voornaam": "Jan", "middle_name": "van", "achternaam": "Dijk"}

		mapped = self.validator.map_row_data(csv_row, row_num=2)

		self.assertEqual(mapped["tussenvoegsel"], "van")

	def test_field_mapping_mollie_ids(self):
		"""Test mapping of Mollie customer and subscription IDs"""
		csv_row = {
			"voornaam": "Jan",
			"achternaam": "Jansen",
			"mollie cid": "cst_123abc",
			"mollie sid": "sub_456def",
		}

		mapped = self.validator.map_row_data(csv_row, row_num=2)

		self.assertEqual(mapped["custom_mollie_customer_id"], "cst_123abc")
		self.assertEqual(mapped["custom_mollie_subscription_id"], "sub_456def")

	def test_validate_email_valid_formats(self):
		"""Test email validation accepts valid formats"""
		valid_emails = [
			"test@example.com",
			"user.name@example.com",
			"user+tag@example.co.uk",
			"123@example.com",
			"a@b.co",
		]

		for email in valid_emails:
			with self.subTest(email=email):
				self.assertTrue(
					self.validator.validate_email(email),
					f"Should accept valid email: {email}"
				)

	def test_validate_email_invalid_formats(self):
		"""Test email validation rejects invalid formats"""
		invalid_emails = [
			"",
			"not-an-email",
			"@example.com",
			"user@",
			"user..name@example.com",  # Consecutive dots
			"user@.com",  # Domain starts with dot
			"a" * 65 + "@example.com",  # Local part too long
			"user@" + "a" * 256,  # Domain too long
			"user@domain",  # No TLD
		]

		for email in invalid_emails:
			with self.subTest(email=email):
				self.assertFalse(
					self.validator.validate_email(email),
					f"Should reject invalid email: {email}"
				)

	def test_validate_email_rfc_limits(self):
		"""Test email validation enforces RFC limits"""
		# Total length limit (320 chars)
		too_long = "a" * 321
		self.assertFalse(self.validator.validate_email(too_long))

		# Local part limit (64 chars)
		long_local = "a" * 65 + "@example.com"
		self.assertFalse(self.validator.validate_email(long_local))

		# Domain part limit (255 chars)
		long_domain = "user@" + "a" * 256
		self.assertFalse(self.validator.validate_email(long_domain))

	def test_validate_iban_valid_checksums(self):
		"""Test IBAN validation accepts valid IBANs with correct checksums"""
		valid_ibans = [
			"NL91ABNA0417164300",  # Netherlands
			"NL91 ABNA 0417 1643 00",  # With spaces
			"BE68539007547034",  # Belgium
			"DE89370400440532013000",  # Germany
			"GB29NWBK60161331926819",  # United Kingdom
		]

		for iban in valid_ibans:
			with self.subTest(iban=iban):
				self.assertTrue(
					self.validator.validate_iban(iban),
					f"Should accept valid IBAN: {iban}"
				)

	def test_validate_iban_invalid_checksums(self):
		"""Test IBAN validation rejects invalid checksums"""
		invalid_ibans = [
			"NL00ABNA0417164300",  # Invalid checksum
			"NL99ABNA0417164300",  # Invalid checksum
			"BE00539007547034",  # Invalid checksum
		]

		for iban in invalid_ibans:
			with self.subTest(iban=iban):
				self.assertFalse(
					self.validator.validate_iban(iban),
					f"Should reject IBAN with invalid checksum: {iban}"
				)

	def test_validate_iban_format_rules(self):
		"""Test IBAN validation enforces format rules"""
		# Too short
		self.assertFalse(self.validator.validate_iban("NL91ABNA"))

		# Too long
		self.assertFalse(self.validator.validate_iban("NL91ABNA" + "0" * 50))

		# Doesn't start with country code
		self.assertFalse(self.validator.validate_iban("9191ABNA0417164300"))

		# Check digits not numeric
		self.assertFalse(self.validator.validate_iban("NLABAABNA0417164300"))

		# Invalid characters in BBAN
		self.assertFalse(self.validator.validate_iban("NL91ABNA0417164300!"))

	def test_validate_row_required_fields(self):
		"""Test row validation requires first_name and last_name"""
		# Missing first_name
		row = {"last_name": "Jansen"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("First name is required" in e for e in errors))

		# Missing last_name
		row = {"first_name": "Jan"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Last name is required" in e for e in errors))

		# Both present
		row = {"first_name": "Jan", "last_name": "Jansen"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertEqual(len(errors), 0)

	def test_validate_row_name_length_limits(self):
		"""Test row validation enforces name length limits"""
		# First name too long
		row = {"first_name": "A" * 101, "last_name": "Jansen"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("First name too long" in e for e in errors))

		# Last name too long
		row = {"first_name": "Jan", "last_name": "A" * 101}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Last name too long" in e for e in errors))

	def test_validate_row_email_validation(self):
		"""Test row validation checks email format"""
		# Invalid email
		row = {"first_name": "Jan", "last_name": "Jansen", "email": "not-an-email"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Invalid email format" in e for e in errors))

		# Valid email
		row = {"first_name": "Jan", "last_name": "Jansen", "email": "jan@example.com"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertEqual(len(errors), 0)

	def test_validate_row_iban_validation(self):
		"""Test row validation checks IBAN format"""
		# Invalid IBAN
		row = {"first_name": "Jan", "last_name": "Jansen", "iban": "NL00INVALID"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Invalid IBAN format" in e for e in errors))

		# Valid IBAN
		row = {"first_name": "Jan", "last_name": "Jansen", "iban": "NL91ABNA0417164300"}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertEqual(len(errors), 0)

	def test_validate_row_birth_date_future(self):
		"""Test row validation rejects future birth dates"""
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"birth_date": "2099-01-01"
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Birth date cannot be in the future" in e for e in errors))

	def test_validate_row_birth_date_unrealistic(self):
		"""Test row validation rejects unrealistic birth dates"""
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"birth_date": "1800-01-01"  # Over 150 years old
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Birth date seems unrealistic" in e for e in errors))

	def test_validate_row_birth_date_invalid_format(self):
		"""Test row validation rejects invalid date formats"""
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"birth_date": "not-a-date"
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Invalid birth date format" in e for e in errors))

	def test_validate_row_contact_number_length(self):
		"""Test row validation enforces contact number length limit"""
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"contact_number": "0" * 51  # Too long
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Contact number too long" in e for e in errors))

	def test_validate_row_dues_rate_validation(self):
		"""Test row validation checks dues rate"""
		# Negative dues
		row = {"first_name": "Jan", "last_name": "Jansen", "dues_rate": -10}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Dues rate cannot be negative" in e for e in errors))

		# Unrealistic dues (over €10,000)
		row = {"first_name": "Jan", "last_name": "Jansen", "dues_rate": 10001}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Dues rate seems unrealistic" in e for e in errors))

		# Valid dues
		row = {"first_name": "Jan", "last_name": "Jansen", "dues_rate": 25.00}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertEqual(len(errors), 0)

	def test_validate_row_mollie_customer_id_format(self):
		"""Test row validation checks Mollie Customer ID format"""
		# Invalid format (doesn't start with cst_)
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"custom_mollie_customer_id": "invalid_123"
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Mollie Customer ID should start with 'cst_'" in e for e in errors))

		# Valid format
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"custom_mollie_customer_id": "cst_123abc"
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertEqual(len(errors), 0)

	def test_validate_row_mollie_subscription_id_format(self):
		"""Test row validation checks Mollie Subscription ID format"""
		# Invalid format (doesn't start with sub_)
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"custom_mollie_subscription_id": "invalid_456"
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertTrue(any("Mollie Subscription ID should start with 'sub_'" in e for e in errors))

		# Valid format
		row = {
			"first_name": "Jan",
			"last_name": "Jansen",
			"custom_mollie_subscription_id": "sub_456def"
		}
		errors = self.validator.validate_row(row, row_num=2)
		self.assertEqual(len(errors), 0)

	def test_validate_and_map_data_empty_csv(self):
		"""Test validation handles empty CSV data"""
		csv_data = []
		mapped, errors = self.validator.validate_and_map_data(csv_data)

		self.assertEqual(len(mapped), 0)
		self.assertEqual(len(errors), 1)
		self.assertIn("CSV file is empty", errors[0])

	def test_validate_and_map_data_missing_required_headers(self):
		"""Test validation detects missing required headers"""
		csv_data = [{"email": "test@example.com"}]  # Missing voornaam, achternaam
		mapped, errors = self.validator.validate_and_map_data(csv_data)

		self.assertEqual(len(mapped), 0)
		self.assertTrue(any("Missing required columns" in e for e in errors))

	def test_validate_and_map_data_complete_workflow(self):
		"""Test complete validation and mapping workflow"""
		csv_data = [
			{
				"voornaam": "Jan",
				"tussenvoegsel": "van",
				"achternaam": "Dijk",
				"e-mailadres": "jan@example.com",
				"geboortedatum": "1990-05-15",
				"iban": "NL91ABNA0417164300",
			},
			{
				"voornaam": "Maria",
				"achternaam": "de Jong",
				"e-mailadres": "maria@example.com",
			}
		]

		mapped, errors = self.validator.validate_and_map_data(csv_data)

		# Should have 2 valid rows
		self.assertEqual(len(mapped), 2)
		self.assertEqual(len(errors), 0)

		# Check first row mapping
		self.assertEqual(mapped[0]["first_name"], "Jan")
		self.assertEqual(mapped[0]["tussenvoegsel"], "van")
		self.assertEqual(mapped[0]["last_name"], "Dijk")
		self.assertEqual(mapped[0]["email"], "jan@example.com")

	def test_validate_and_map_data_with_errors(self):
		"""Test validation collects errors from invalid rows"""
		csv_data = [
			{
				"voornaam": "",  # Empty first name
				"achternaam": "Jansen",
				"e-mailadres": "invalid-email",  # Invalid email
			},
			{
				"voornaam": "Maria",
				"achternaam": "de Jong",
				"iban": "NL00INVALID",  # Invalid IBAN
			}
		]

		mapped, errors = self.validator.validate_and_map_data(csv_data)

		# No rows should be mapped due to errors
		self.assertEqual(len(mapped), 0)
		self.assertGreater(len(errors), 0)

		# Check specific errors
		error_text = " ".join(errors)
		self.assertIn("First name is required", error_text)
		self.assertIn("Invalid email format", error_text)
		self.assertIn("Invalid IBAN format", error_text)

	def test_validate_and_map_data_limits_errors(self):
		"""Test validation limits error list to 100 entries"""
		# Create CSV with 150 rows with errors
		csv_data = [{"voornaam": "", "achternaam": "Test"}] * 150

		mapped, errors = self.validator.validate_and_map_data(csv_data)

		# Errors should be limited to 100
		self.assertEqual(len(errors), 100)

	def test_validate_row_multiple_errors(self):
		"""Test row validation collects multiple errors per row"""
		row = {
			# Missing first_name and last_name
			"email": "not-an-email",  # Invalid email
			"iban": "NL00INVALID",  # Invalid IBAN
			"birth_date": "2099-01-01",  # Future date
			"dues_rate": -10,  # Negative
		}

		errors = self.validator.validate_row(row, row_num=5)

		# Should have multiple errors
		self.assertGreaterEqual(len(errors), 5)

		# All errors should reference row 5
		for error in errors:
			self.assertIn("Row 5", error)
