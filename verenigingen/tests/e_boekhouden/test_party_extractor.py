"""
Comprehensive tests for EBoekhoudenPartyExtractor

Tests party extraction from E-Boekhouden mutations (types 5 & 6) with both
SOAP and REST API formats. Validates party type determination and integration
with BankTransactionParser.
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor


class TestEBoekhoudenPartyExtractor(unittest.TestCase):
	"""Test EBoekhoudenPartyExtractor with real mutation patterns"""

	@classmethod
	def setUpClass(cls):
		"""Set up test company once for all tests"""
		# Ensure test company exists
		if not frappe.db.exists("Company", "Test Company"):
			company = frappe.new_doc("Company")
			company.company_name = "Test Company"
			company.abbr = "TC"
			company.default_currency = "EUR"
			company.country = "Netherlands"
			company.insert(ignore_permissions=True)
			frappe.db.commit()

		# Configure E-Boekhouden Settings with test company. The extractor only
		# reads default_company; api_token is a mandatory field we don't need
		# here, so bypass mandatory validation rather than persist a fake token.
		settings = frappe.get_single("E-Boekhouden Settings")
		settings.default_company = "Test Company"
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		"""Initialize extractor before each test"""
		self.extractor = EBoekhoudenPartyExtractor("Test Company")

	def test_rest_api_type_5_money_received(self):
		"""Test Type 5 (Money Received) with REST API format"""
		mutation = {
			"id": "8799",
			"type": 5,  # REST API field
			"description": "NL44ASNB0943117305 ASNBNL21 Anne Tilanus TRIODOS NL 20250928 44912553 Contribution",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_type"], "Customer")
		self.assertEqual(party_info["party_name"], "Anne Tilanus")
		self.assertEqual(party_info["extraction_method"], "description_pattern")

	def test_rest_api_type_6_money_paid(self):
		"""Test Type 6 (Money Paid) with REST API format"""
		mutation = {
			"id": "8800",
			"type": 6,  # REST API field
			"description": "NL84COBA0733959520 COBANL2X ODIDO NETHERLANDS B.V. ER EF 501635613715 Invoice",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_type"], "Supplier")
		self.assertEqual(party_info["party_name"], "ODIDO NETHERLANDS B.V.")
		self.assertEqual(party_info["extraction_method"], "description_pattern")

	def test_soap_api_type_5_money_received(self):
		"""Test Type 5 with SOAP API format (MutatieType, Omschrijving, RelatieCode)"""
		mutation = {
			"MutatieNummer": "41591058",
			"MutatieType": 5,  # SOAP API field
			"Omschrijving": "NL76ASNB0706938801 ASNBNL21 Elise Hiddinga TRIOD OS NL 20250829 Contribution",  # SOAP API field
			"RelatieCode": "",  # SOAP API field
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_type"], "Customer")
		self.assertEqual(party_info["party_name"], "Elise Hiddinga")

	def test_soap_api_type_6_money_paid(self):
		"""Test Type 6 with SOAP API format"""
		mutation = {
			"MutatieNummer": "44909016",
			"MutatieType": 6,  # SOAP API field
			"Omschrijving": "NL82RABO0169941124 RABONL2U SkillSource B.V. EB1 209202509116398 Invoice",
			"RelatieCode": "",
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_type"], "Supplier")
		self.assertEqual(party_info["party_name"], "SkillSource B.V.")

	def test_type_1_to_4_not_processed(self):
		"""Test that mutation types 1-4 are not processed (only 5 & 6)"""
		for mutation_type in [1, 2, 3, 4]:
			with self.subTest(type=mutation_type):
				mutation = {
					"type": mutation_type,
					"description": "NL91ABNA0417164300 ABNANL2A Test Party",
					"relationId": 0,
				}

				party_info = self.extractor.extract_party_from_mutation(mutation)
				self.assertIsNone(party_info)

	def test_party_type_determination_type_5(self):
		"""Test that Type 5 always creates Customer"""
		mutation = {
			"type": 5,
			"description": "NL91ABNA0417164300 ABNANL2A Test Person TRIODOS NL 20250928",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)
		self.assertEqual(party_info["party_type"], "Customer")

	def test_party_type_determination_type_6(self):
		"""Test that Type 6 always creates Supplier"""
		mutation = {
			"type": 6,
			"description": "NL91ABNA0417164300 ABNANL2A Test Company B.V. EREF 12345",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)
		self.assertEqual(party_info["party_type"], "Supplier")

	def test_dutch_name_with_tussenvoegsel(self):
		"""Test extraction of Dutch names with prefixes (van, de, van der, etc.)"""
		mutation = {
			"type": 5,
			"description": "NL38ASNB0267550340 ASNBNL21 Antine van der Zijden ERE F TRIODOS NL 20250928",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_name"], "Antine van der Zijden")
		# Verify Dutch prefixes are preserved
		self.assertIn("van der", party_info["party_name"])

	def test_company_name_with_bv_periods(self):
		"""Test that B.V./N.V. periods are preserved in company names"""
		mutation = {
			"type": 6,
			"description": "NL56DEUT0265186420 DEUTNL2A Drukwerkdeal.nl B.V. EREF 15-08-25",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_name"], "Drukwerkdeal.nl B.V.")
		# Verify periods are preserved
		self.assertIn("B.V.", party_info["party_name"])

	def test_company_with_via_keyword(self):
		"""Test that 'via' is preserved in company names"""
		mutation = {
			"type": 6,
			"description": "NL47DEUT7020197906 DEUTNL2A Vimexx via Mollie SD 46-2986-7956-0000",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_name"], "Vimexx via Mollie")

	def test_relation_id_extraction(self):
		"""Test that relationId/RelatieCode is extracted when present"""
		# REST API format
		mutation_rest = {
			"type": 5,
			"description": "NL91ABNA0417164300 ABNANL2A Test Customer",
			"relationId": 12345,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation_rest)
		self.assertEqual(party_info["relation_id"], 12345)

		# SOAP API format
		mutation_soap = {
			"MutatieType": 6,
			"Omschrijving": "NL91ABNA0417164300 ABNANL2A Test Supplier",
			"RelatieCode": 67890,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation_soap)
		self.assertEqual(party_info["relation_id"], 67890)

	def test_minimal_party_name_extraction(self):
		"""Test extraction with minimal but valid party name (3+ chars required)"""
		mutation = {
			"type": 5,
			"description": "NL91ABNA0417164300 ABNANL2A ABC EREF 12345",  # Minimal 3-char name "ABC"
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		# Should extract names with 3+ characters
		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_name"], "ABC")

	def test_empty_description(self):
		"""Test handling of empty description"""
		mutation = {
			"type": 5,
			"description": "",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)
		# Should return None when no description and no relation_id
		self.assertIsNone(party_info)

	def test_odido_er_ef_pattern(self):
		"""Test ODIDO transaction with 'ER EF' EREF pattern (original bug case)"""
		mutation = {
			"type": 6,
			"description": "NL84COBA0733959520 COBANL2X ODIDO NETHERLANDS B.V. ER EF 501635613715 1.20824473 NL12T2N333034180000 USTD Klant 1.20824473 Factuur 901603138054",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		self.assertEqual(party_info["party_type"], "Supplier")
		self.assertEqual(party_info["party_name"], "ODIDO NETHERLANDS B.V.")
		# Verify NETHERLANDS is preserved (not stripped as standalone "NL")
		self.assertIn("NETHERLANDS", party_info["party_name"])

	def test_multiple_triodos_split_variants(self):
		"""Test all TRIODOS split variants are handled correctly"""
		triodos_variants = [
			"TRIODOS",
			"TRIOD OS",
			"TRIO DOS",
			"TRI ODOS",
			"TR IODOS",
		]

		for variant in triodos_variants:
			with self.subTest(variant=variant):
				mutation = {
					"type": 5,
					"description": f"NL91ABNA0417164300 ABNANL2A Test Person {variant} NL 20250928",
					"relationId": 0,
				}

				party_info = self.extractor.extract_party_from_mutation(mutation)

				self.assertIsNotNone(party_info)
				self.assertEqual(party_info["party_name"], "Test Person")
				# Verify TRIODOS variant was stripped
				self.assertNotIn("TRIOD", party_info["party_name"])

	def test_error_handling_invalid_mutation(self):
		"""Test graceful error handling with invalid mutation data"""
		invalid_mutations = [
			None,
			{},
			{"type": None},
			{"description": None},
		]

		for mutation in invalid_mutations:
			with self.subTest(mutation=mutation):
				# Should not raise exception
				party_info = self.extractor.extract_party_from_mutation(mutation)
				# Should return None for invalid data
				self.assertIsNone(party_info)

	def test_integration_with_bank_transaction_parser(self):
		"""Test that EBoekhoudenPartyExtractor properly uses BankTransactionParser"""
		mutation = {
			"type": 6,
			"description": "NL17DEUT7370000913 DEUTNL2A Shurgard NL CJ6CDXPK 7Q88357X3C PVD93JPHC2DW44G6 NL48ZZZ342764500000",
			"relationId": 0,
		}

		party_info = self.extractor.extract_party_from_mutation(mutation)

		self.assertIsNotNone(party_info)
		# BankTransactionParser should clean up reference codes
		self.assertEqual(party_info["party_name"], "Shurgard")
		# Verify reference codes were stripped
		self.assertNotIn("CJ6CDXPK", party_info["party_name"])


def run_tests():
	"""Run all party extractor tests"""
	frappe.db.rollback()
	suite = unittest.TestLoader().loadTestsFromTestCase(TestEBoekhoudenPartyExtractor)
	runner = unittest.TextTestRunner(verbosity=2)
	result = runner.run(suite)
	frappe.db.rollback()
	return result


if __name__ == "__main__":
	run_tests()
