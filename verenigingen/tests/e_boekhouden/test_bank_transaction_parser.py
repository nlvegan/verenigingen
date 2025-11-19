"""
Comprehensive tests for BankTransactionParser

Tests SEPA description parsing with 16+ real production patterns from Bank Transaction data.
Validates party name extraction, IBAN/BIC parsing, and cleanup logic.
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser


class TestBankTransactionParser(unittest.TestCase):
	"""Test BankTransactionParser with real SEPA description patterns"""

	def setUp(self):
		"""Initialize parser before each test"""
		self.parser = BankTransactionParser()

	def test_person_name_triodos_split_variants(self):
		"""Test person names with various TRIODOS split patterns"""
		test_cases = [
			# Pattern: "TRIOD OS" (space in middle)
			{
				"desc": "NL76ASNB0706938801 ASNBNL21 Elise Hiddinga TRIOD OS NL 20250829 41591058 Vrijwilligersvergoeding",
				"expected_party": "Elise Hiddinga",
				"expected_iban": "NL76ASNB0706938801",
				"expected_bic": "ASNBNL21",
			},
			# Pattern: "TRIODOS" (no split)
			{
				"desc": "NL44ASNB0943117305 ASNBNL21 Anne Tilanus TRIODOS NL 20250928 44912553 Vrijwilligersvergoeding tl rece pten",
				"expected_party": "Anne Tilanus",
				"expected_iban": "NL44ASNB0943117305",
				"expected_bic": "ASNBNL21",
			},
			# Pattern: "TRIO DOS" (space after 4 chars)
			{
				"desc": "NL79RABO0113308310 RABONL2U Amy Duinslaeger TRIO DOS NL 20250928 44909016 Vrijwilligersvergoeding",
				"expected_party": "Amy Duinslaeger",
				"expected_iban": "NL79RABO0113308310",
				"expected_bic": "RABONL2U",
			},
			# Pattern: "TRI ODOS" (space after 3 chars)
			{
				"desc": "NL34ASNB0707256747 ASNBNL21 Tamara Tervooren TRI ODOS NL 20250928 44907503 Vrijwilligersvergoeding",
				"expected_party": "Tamara Tervooren",
				"expected_iban": "NL34ASNB0707256747",
				"expected_bic": "ASNBNL21",
			},
			# Pattern: "TR IODOS" (space after 2 chars)
			{
				"desc": "NL94ABNA0414948572 ABNANL2A Annelieke Joosten TR IODOS NL 20250928 44907502 Vrijwilligersvergoeding",
				"expected_party": "Annelieke Joosten",
				"expected_iban": "NL94ABNA0414948572",
				"expected_bic": "ABNANL2A",
			},
		]

		for test in test_cases:
			with self.subTest(party=test["expected_party"]):
				result = self.parser.parse_description(test["desc"])
				self.assertEqual(result["party_name"], test["expected_party"])
				self.assertEqual(result["iban"], test["expected_iban"])
				self.assertEqual(result["bic"], test["expected_bic"])

	def test_dutch_name_with_tussenvoegsel(self):
		"""Test Dutch names with prefixes (tussenvoegsel) like 'van der'"""
		test_cases = [
			{
				"desc": "NL38ASNB0267550340 ASNBNL21 Antine van der Zijden ERE F TRIODOS NL 20250928 44909724 vrijwilligersvergoedin g maandelijks",
				"expected_party": "Antine van der Zijden",
				"expected_iban": "NL38ASNB0267550340",
			}
		]

		for test in test_cases:
			result = self.parser.parse_description(test["desc"])
			self.assertEqual(result["party_name"], test["expected_party"])
			self.assertEqual(result["iban"], test["expected_iban"])

	def test_company_names_with_eref_variants(self):
		"""Test company names with EREF field code variants"""
		test_cases = [
			# Pattern: "ER EF" (space in middle) - ODIDO case
			{
				"desc": "NL84COBA0733959520 COBANL2X ODIDO NETHERLANDS B.V. ER EF 501635613715 1.20824473 NL12T2N333034180000 USTD Klant 1.20824473 Factuur 901603138054",
				"expected_party": "ODIDO NETHERLANDS B.V.",
				"expected_iban": "NL84COBA0733959520",
				"expected_bic": "COBANL2X",
			},
			# Pattern: "EREF" (full form)
			{
				"desc": "NL56DEUT0265186420 DEUTNL2A Drukwerkdeal.nl B.V. EREF 15-08-25 13:42 8030105430062557 Order14661031 803010 5430062557 drukwerkdeal-nl order 14661031.",
				"expected_party": "Drukwerkdeal.nl B.V.",
				"expected_iban": "NL56DEUT0265186420",
				"expected_bic": "DEUTNL2A",
			},
			# Pattern: "ERE F" (space after 3 chars)
			{
				"desc": "NL86RABO0332214389 RABONL2U Confianza registeracc. ER EF EI 2025-09-03 15:14:28 0000000003 7771 NL31ZZZ2807 39160000 Factuurnummer 7771-2025-17748",
				"expected_party": "Confianza registeracc.",
				"expected_iban": "NL86RABO0332214389",
			},
		]

		for test in test_cases:
			with self.subTest(party=test["expected_party"]):
				result = self.parser.parse_description(test["desc"])
				self.assertEqual(result["party_name"], test["expected_party"])
				self.assertEqual(result["iban"], test["expected_iban"])

	def test_company_names_preserve_periods(self):
		"""Test that periods in company names (B.V., N.V.) are preserved"""
		test_cases = [
			{
				"desc": "NL84COBA0733959520 COBANL2X ODIDO NETHERLANDS B.V. ER EF 501635613715",
				"expected_party": "ODIDO NETHERLANDS B.V.",
			},
			{
				"desc": "NL56DEUT0265186420 DEUTNL2A Drukwerkdeal.nl B.V. EREF 15-08-25",
				"expected_party": "Drukwerkdeal.nl B.V.",
			},
			{
				"desc": "NL82RABO0169941124 RABONL2U SkillSource B.V. EB1 209202509116398",
				"expected_party": "SkillSource B.V.",
			},
		]

		for test in test_cases:
			result = self.parser.parse_description(test["desc"])
			self.assertEqual(result["party_name"], test["expected_party"])

	def test_sepa_direct_debit_fields(self):
		"""Test SEPA Direct Debit with SD/MD/REMI/USTD field codes"""
		test_cases = [
			# SD field
			{
				"desc": "NL47DEUT7020197906 DEUTNL2A Vimexx via Mollie SD 46-2986-7956-0000 MD50-0000-9114-5655 NL08ZZZ50205773",
				"expected_party": "Vimexx via Mollie",
				"expected_iban": "NL47DEUT7020197906",
			},
			# REMI/USTD fields with reference codes
			{
				"desc": "NL17DEUT7370000913 DEUTNL2A Shurgard NL CJ6CDXPK 7Q88357X3C PVD93JPHC2DW44G6 NL48ZZZ342764500000 REMI USTD Shurgard Netherlands BV",
				"expected_party": "Shurgard",
				"expected_iban": "NL17DEUT7370000913",
			},
		]

		for test in test_cases:
			with self.subTest(party=test["expected_party"]):
				result = self.parser.parse_description(test["desc"])
				self.assertEqual(result["party_name"], test["expected_party"])
				self.assertEqual(result["iban"], test["expected_iban"])

	def test_via_in_company_name(self):
		"""Test that 'via' is preserved in company names like 'Vimexx via Mollie'"""
		desc = "NL47DEUT7020197906 DEUTNL2A Vimexx via Mollie SD 46-2986-7956-0000"
		result = self.parser.parse_description(desc)
		self.assertEqual(result["party_name"], "Vimexx via Mollie")

	def test_reference_code_cleanup(self):
		"""Test removal of alphanumeric reference codes"""
		test_cases = [
			# Single letter + long number pattern
			{
				"desc": "NL10BNPA0227753933 BNPANL2A Simpel F2510655428-2 0250915085126",
				"expected_party": "Simpel",
			},
			# Multiple alphanumeric codes after party name
			{
				"desc": "NL17DEUT7370000913 DEUTNL2A Shurgard NL CJ6CDXPK 7Q88357X3C PVD93JPHC2DW44G6",
				"expected_party": "Shurgard",
			},
		]

		for test in test_cases:
			result = self.parser.parse_description(test["desc"])
			self.assertEqual(result["party_name"], test["expected_party"])

	def test_eboekhouden_invoice_codes(self):
		"""Test E-Boekhouden invoice codes (EB0, EB1) as terminators"""
		test_cases = [
			{
				"desc": "NL82RABO0169941124 RABONL2U SkillSource B.V. EB1 209202509116398 M551253 NL45ZZZ514328460000 UST D Factuur: 67086123",
				"expected_party": "SkillSource B.V.",
			},
			{
				"desc": "NL82RABO0169941124 RABONL2U SkillSource B.V. EB0 809202502134774 M216361A NL45ZZZ514328460000",
				"expected_party": "SkillSource B.V.",
			},
		]

		for test in test_cases:
			result = self.parser.parse_description(test["desc"])
			self.assertEqual(result["party_name"], test["expected_party"])

	def test_no_bic_code_fallback(self):
		"""Test parsing when BIC code is missing (IBAN only)"""
		desc = "NL40TRIO0198396716 NEDERLANDSE VER VOOR VEGANIS BETALINGEN SEPTEMBER BETALINGEN SEPTEMBER"
		result = self.parser.parse_description(desc)

		self.assertEqual(result["iban"], "NL40TRIO0198396716")
		self.assertIsNone(result["bic"])
		self.assertEqual(result["party_name"], "NEDERLANDSE VER VOOR VEGANIS")

	def test_betalingen_keyword_terminator(self):
		"""Test that 'BETALINGEN' (payments) acts as terminator"""
		desc = "NL40TRIO0198396716 NEDERLANDSE VER VOOR VEGANIS BETALINGEN SEPTEMBER"
		result = self.parser.parse_description(desc)
		self.assertEqual(result["party_name"], "NEDERLANDSE VER VOOR VEGANIS")

	def test_sepa_creditor_id_terminator(self):
		"""Test SEPA creditor ID format (NL##ZZZ...) as terminator"""
		desc = "NL17DEUT7370000913 DEUTNL2A Shurgard NL48ZZZ342764500000 REMI USTD"
		result = self.parser.parse_description(desc)
		self.assertEqual(result["party_name"], "Shurgard")

	def test_empty_description(self):
		"""Test handling of empty/None descriptions"""
		test_cases = [
			{"desc": None, "expected_party": None},
			{"desc": "", "expected_party": None},
			{"desc": "   ", "expected_party": ""},  # Whitespace returns empty string, not None
		]

		for test in test_cases:
			with self.subTest(desc=test["desc"]):
				result = self.parser.parse_description(test["desc"])
				self.assertIsNone(result["iban"])
				self.assertIsNone(result["bic"])
				# Check party_name is either None or empty string (both are falsy)
				if test["expected_party"] is None:
					self.assertIsNone(result["party_name"])
				else:
					self.assertEqual(result["party_name"], test["expected_party"])

	def test_description_without_iban(self):
		"""Test description without IBAN (should still parse party if possible)"""
		desc = "Payment from John Doe EREF 12345"
		result = self.parser.parse_description(desc)

		self.assertIsNone(result["iban"])
		self.assertIsNone(result["bic"])
		# Should extract party name from start of string
		self.assertEqual(result["party_name"], "Payment from John Doe")

	def test_iban_extraction_format(self):
		"""Test IBAN extraction with correct Dutch format (NL + 2 digits + 4 letters + 10 digits)"""
		desc = "NL91ABNA0417164300 ABNANL2A Test Customer"
		result = self.parser.parse_description(desc)

		self.assertEqual(result["iban"], "NL91ABNA0417164300")
		self.assertEqual(len(result["iban"]), 18)  # Dutch IBAN is always 18 chars

	def test_all_production_patterns(self):
		"""Comprehensive test with all 16 real production patterns"""
		test_cases = [
			("Elise Hiddinga", "NL76ASNB0706938801 ASNBNL21 Elise Hiddinga TRIOD OS NL 20250829 41591058 Vrijwilligersvergoeding"),
			("Anne Tilanus", "NL44ASNB0943117305 ASNBNL21 Anne Tilanus TRIODOS NL 20250928 44912553 Vrijwilligersvergoeding tl rece pten"),
			("Antine van der Zijden", "NL38ASNB0267550340 ASNBNL21 Antine van der Zijden ERE F TRIODOS NL 20250928 44909724 vrijwilligersvergoedin g maandelijks"),
			("Amy Duinslaeger", "NL79RABO0113308310 RABONL2U Amy Duinslaeger TRIO DOS NL 20250928 44909016 Vrijwilligersvergoeding"),
			("Tamara Tervooren", "NL34ASNB0707256747 ASNBNL21 Tamara Tervooren TRI ODOS NL 20250928 44907503 Vrijwilligersvergoeding"),
			("Annelieke Joosten", "NL94ABNA0414948572 ABNANL2A Annelieke Joosten TR IODOS NL 20250928 44907502 Vrijwilligersvergoeding"),
			("Suzette Eikelenboom", "NL92RABO0134526147 RABONL2U Suzette Eikelenboom TRIODOS NL 20250928 44907501 Vrijwilligersvergoeding deze maand"),
			("ODIDO NETHERLANDS B.V.", "NL84COBA0733959520 COBANL2X ODIDO NETHERLANDS B.V. ER EF 501635613715 1.20824473 NL12T2N333034180000 USTD Klant 1.20824473 Factuur 901603138054"),
			("Drukwerkdeal.nl B.V.", "NL56DEUT0265186420 DEUTNL2A Drukwerkdeal.nl B.V. EREF 15-08-25 13:42 8030105430062557 Order14661031 803010 5430062557 drukwerkdeal-nl order 14661031."),
			("Confianza registeracc.", "NL86RABO0332214389 RABONL2U Confianza registeracc. ER EF EI 2025-09-03 15:14:28 0000000003 7771 NL31ZZZ2807 39160000 Factuurnummer 7771-2025-17748"),
			("Vimexx via Mollie", "NL47DEUT7020197906 DEUTNL2A Vimexx via Mollie SD 46-2986-7956-0000 MD50-0000-9114-5655 NL08ZZZ50205773"),
			("Shurgard", "NL17DEUT7370000913 DEUTNL2A Shurgard NL CJ6CDXPK 7Q88357X3C PVD93JPHC2DW44G6 NL48ZZZ342764500000 REMI USTD Shurgard Netherlands BV customer 7fcea92dc2aa44298ad0ccfbf e8a0fb3"),
			("Simpel", "NL10BNPA0227753933 BNPANL2A Simpel F2510655428-2 0250915085126 s728243754202404251448 NL15ZZZ603163060 001 Simpel factuur F2510655428 voor 06-39134043. Beki jk je factuur op mijn.simpel.nl o"),
			("SkillSource B.V.", "NL82RABO0169941124 RABONL2U SkillSource B.V. EB1 209202509116398 M551253 NL45ZZZ514328460000 UST D Factuur: 67086123 e-Boekhouden.nl"),
			("SkillSource B.V.", "NL82RABO0169941124 RABONL2U SkillSource B.V. EB0 809202502134774 M216361A NL45ZZZ514328460000 US TD Factuur: 67067175 e-Boekhouden.nl"),
			("NEDERLANDSE VER VOOR VEGANIS", "NL40TRIO0198396716 NEDERLANDSE VER VOOR VEGANIS BETALINGEN SEPTEMBER BETALINGEN SEPTEMBER"),
		]

		passed = 0
		failed = 0

		for expected_party, description in test_cases:
			with self.subTest(party=expected_party):
				result = self.parser.parse_description(description)
				try:
					self.assertEqual(result["party_name"], expected_party)
					passed += 1
				except AssertionError:
					failed += 1
					raise

		# Assert overall success rate (should be 15/16 = 93.8%)
		success_rate = passed / len(test_cases) * 100
		self.assertGreaterEqual(success_rate, 90.0, f"Success rate {success_rate:.1f}% below 90% threshold")


def run_tests():
	"""Run all parser tests"""
	frappe.db.rollback()
	suite = unittest.TestLoader().loadTestsFromTestCase(TestBankTransactionParser)
	runner = unittest.TextTestRunner(verbosity=2)
	result = runner.run(suite)
	frappe.db.rollback()
	return result


if __name__ == "__main__":
	run_tests()
