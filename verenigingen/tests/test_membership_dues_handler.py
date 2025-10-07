"""
Unit Tests for MembershipDuesHandler

Tests membership and dues schedule creation logic extracted from CSV import.
"""

from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.csv.membership_dues_handler import MembershipDuesHandler


class TestMembershipDuesHandler(FrappeTestCase):
	"""Test suite for Membership and Dues Schedule handling"""

	def setUp(self):
		"""Set up test environment"""
		super().setUp()
		self.handler = MembershipDuesHandler()

	def test_map_payment_period_dutch_monthly(self):
		"""Test mapping Dutch monthly payment periods"""
		self.assertEqual(self.handler.map_payment_period_to_frequency("maandelijks"), "Monthly")
		self.assertEqual(self.handler.map_payment_period_to_frequency("per maand"), "Monthly")
		self.assertEqual(self.handler.map_payment_period_to_frequency("MAANDELIJKS"), "Monthly")  # Case insensitive

	def test_map_payment_period_dutch_quarterly(self):
		"""Test mapping Dutch quarterly payment periods"""
		self.assertEqual(self.handler.map_payment_period_to_frequency("kwartaal"), "Quarterly")
		self.assertEqual(self.handler.map_payment_period_to_frequency("per kwartaal"), "Quarterly")
		self.assertEqual(self.handler.map_payment_period_to_frequency("driemaandelijks"), "Quarterly")

	def test_map_payment_period_dutch_semiannual(self):
		"""Test mapping Dutch semi-annual payment periods"""
		self.assertEqual(self.handler.map_payment_period_to_frequency("halfjaar"), "Semi-Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency("halfjaarlijks"), "Semi-Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency("per halfjaar"), "Semi-Annual")

	def test_map_payment_period_dutch_annual(self):
		"""Test mapping Dutch annual payment periods"""
		self.assertEqual(self.handler.map_payment_period_to_frequency("jaar"), "Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency("jaarlijks"), "Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency("per jaar"), "Annual")

	def test_map_payment_period_english(self):
		"""Test mapping English payment periods"""
		self.assertEqual(self.handler.map_payment_period_to_frequency("monthly"), "Monthly")
		self.assertEqual(self.handler.map_payment_period_to_frequency("quarterly"), "Quarterly")
		self.assertEqual(self.handler.map_payment_period_to_frequency("semi-annual"), "Semi-Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency("annual"), "Annual")

	def test_map_payment_period_defaults_to_annual(self):
		"""Test payment period mapping defaults to Annual"""
		self.assertEqual(self.handler.map_payment_period_to_frequency(""), "Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency(None), "Annual")
		self.assertEqual(self.handler.map_payment_period_to_frequency("unknown"), "Annual")

	def test_calculate_next_invoice_date_monthly(self):
		"""Test next invoice date calculation for monthly billing"""
		start = date(2024, 1, 15)
		result = self.handler.calculate_next_invoice_date(start, "Monthly")
		self.assertEqual(result, "2024-02-15")

	def test_calculate_next_invoice_date_quarterly(self):
		"""Test next invoice date calculation for quarterly billing"""
		start = date(2024, 1, 15)
		result = self.handler.calculate_next_invoice_date(start, "Quarterly")
		self.assertEqual(result, "2024-04-15")

	def test_calculate_next_invoice_date_semiannual(self):
		"""Test next invoice date calculation for semi-annual billing"""
		start = date(2024, 1, 15)
		result = self.handler.calculate_next_invoice_date(start, "Semi-Annual")
		self.assertEqual(result, "2024-07-15")

	def test_calculate_next_invoice_date_annual(self):
		"""Test next invoice date calculation for annual billing"""
		start = date(2024, 1, 15)
		result = self.handler.calculate_next_invoice_date(start, "Annual")
		self.assertEqual(result, "2025-01-15")

	def test_calculate_next_invoice_date_defaults_to_annual(self):
		"""Test next invoice date calculation defaults to annual"""
		start = date(2024, 1, 15)
		result = self.handler.calculate_next_invoice_date(start, "Unknown")
		self.assertEqual(result, "2025-01-15")

	def test_determine_membership_type_from_explicit_csv(self):
		"""Test membership type determination from explicit CSV value"""
		row_data = {"membership_type": "Premium Membership"}
		result = self.handler.determine_membership_type(row_data)
		self.assertEqual(result, "Premium Membership")

	def test_determine_membership_type_from_payment_period_monthly(self):
		"""Test membership type determination from monthly payment period"""
		row_data = {"payment_period": "maandelijks"}
		result = self.handler.determine_membership_type(row_data)
		self.assertEqual(result, "Monthly Membership")

	def test_determine_membership_type_from_payment_period_quarterly(self):
		"""Test membership type determination from quarterly payment period"""
		row_data = {"payment_period": "kwartaal"}
		result = self.handler.determine_membership_type(row_data)
		self.assertEqual(result, "Quarterly Membership")

	def test_determine_membership_type_from_payment_period_semiannual(self):
		"""Test membership type determination from semi-annual payment period"""
		row_data = {"payment_period": "halfjaar"}
		result = self.handler.determine_membership_type(row_data)
		self.assertEqual(result, "Semi-Annual Membership")

	def test_determine_membership_type_from_payment_period_annual(self):
		"""Test membership type determination from annual payment period"""
		row_data = {"payment_period": "jaarlijks"}
		result = self.handler.determine_membership_type(row_data)
		self.assertEqual(result, "Annual Membership")

	def test_determine_membership_type_uses_settings_default(self):
		"""Test membership type determination uses settings default"""
		# No payment period, no membership_type - should use settings default
		row_data = {}
		result = self.handler.determine_membership_type(row_data)
		# Should return either settings default or fallback
		self.assertIsNotNone(result)
		self.assertTrue(len(result) > 0)

	def test_determine_membership_type_case_insensitive(self):
		"""Test membership type determination is case insensitive"""
		row_data = {"payment_period": "MAANDELIJKS"}
		result = self.handler.determine_membership_type(row_data)
		self.assertEqual(result, "Monthly Membership")

	def test_payment_period_mapping_completeness(self):
		"""Test that all expected payment periods are mapped"""
		expected_mappings = {
			"maandelijks": "Monthly",
			"monthly": "Monthly",
			"kwartaal": "Quarterly",
			"quarterly": "Quarterly",
			"halfjaar": "Semi-Annual",
			"semi-annual": "Semi-Annual",
			"jaar": "Annual",
			"annual": "Annual",
		}

		for period, expected_frequency in expected_mappings.items():
			result = self.handler.map_payment_period_to_frequency(period)
			self.assertEqual(
				result,
				expected_frequency,
				f"Failed for period '{period}': expected {expected_frequency}, got {result}"
			)
