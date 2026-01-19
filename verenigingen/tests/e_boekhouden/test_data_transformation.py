"""
Tests for eBoekhouden Data Transformation

Tests the transformation of eBoekhouden field values to ERPNext format:
- Date normalization
- Amount handling
- VAT/BTW code mapping
- UOM (Unit of Measure) mapping
- Item group classification

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_data_transformation
"""

import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from verenigingen.e_boekhouden.utils.data_integrity import normalize_date
from verenigingen.e_boekhouden.utils.field_mapping import (
    ACCOUNT_CODE_ITEM_HINTS,
    BTW_CODE_MAP,
    DEFAULT_ITEM_GROUPS,
    ITEM_GROUP_KEYWORDS,
    UOM_MAP,
    VAT_CATEGORY_HINTS,
)
from verenigingen.tests.e_boekhouden.fixtures import (
    BTW_CODE_TEST_CASES,
    DATE_FORMAT_SAMPLES,
    ITEM_GROUP_TEST_CASES,
    MUTATION_NEAR_ZERO_ROWS,
    MUTATION_ROW_SUM_MISMATCH,
    MUTATION_ROW_SUM_WITHIN_TOLERANCE,
    MUTATION_ZERO_MAIN_WITH_ROWS,
    UOM_TEST_CASES,
)


class TestDateNormalization(unittest.TestCase):
    """Test date normalization from various eBoekhouden formats"""

    def test_yyyymmdd_format(self):
        """Test E-Boekhouden YYYYMMDD format"""
        self.assertEqual(normalize_date("20250110"), "2025-01-10")
        self.assertEqual(normalize_date("20231231"), "2023-12-31")
        self.assertEqual(normalize_date("20240101"), "2024-01-01")

    def test_iso_datetime_format(self):
        """Test ISO datetime format with time component"""
        self.assertEqual(normalize_date("2025-01-10T00:00:00"), "2025-01-10")
        self.assertEqual(normalize_date("2025-01-10T12:30:45"), "2025-01-10")
        self.assertEqual(normalize_date("2025-01-10T23:59:59.999"), "2025-01-10")

    def test_iso_datetime_with_timezone(self):
        """Test ISO datetime format with timezone"""
        self.assertEqual(normalize_date("2025-01-10T00:00:00+01:00"), "2025-01-10")
        self.assertEqual(normalize_date("2025-01-10T00:00:00Z"), "2025-01-10")

    def test_already_correct_format(self):
        """Test already correct YYYY-MM-DD format"""
        self.assertEqual(normalize_date("2025-01-10"), "2025-01-10")
        self.assertEqual(normalize_date("2023-12-31"), "2023-12-31")

    def test_european_dash_format(self):
        """Test European DD-MM-YYYY format"""
        self.assertEqual(normalize_date("10-01-2025"), "2025-01-10")
        self.assertEqual(normalize_date("31-12-2023"), "2023-12-31")
        self.assertEqual(normalize_date("1-1-2024"), "2024-01-01")

    def test_european_slash_format(self):
        """Test European DD/MM/YYYY format"""
        self.assertEqual(normalize_date("10/01/2025"), "2025-01-10")
        self.assertEqual(normalize_date("31/12/2023"), "2023-12-31")

    def test_empty_and_none_values(self):
        """Test handling of empty and None values"""
        self.assertIsNone(normalize_date(None))
        self.assertIsNone(normalize_date(""))
        self.assertIsNone(normalize_date("   "))

    def test_integer_date(self):
        """Test that integer date values are converted"""
        result = normalize_date(20250110)
        self.assertEqual(result, "2025-01-10")

    def test_all_date_format_samples(self):
        """Test all date format samples from fixtures"""
        for sample in DATE_FORMAT_SAMPLES:
            with self.subTest(description=sample["description"]):
                result = normalize_date(sample["input"])
                self.assertEqual(
                    result,
                    sample["expected"],
                    f"Failed for {sample['description']}: input={sample['input']}",
                )


class TestAmountHandling(unittest.TestCase):
    """Test amount extraction and validation"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"
        self.mock_frappe.utils.flt = lambda x, precision=None: round(float(x or 0), precision or 2)

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_get_amount_from_bedrag(self):
        """Test extracting amount from 'Bedrag' field (SOAP)"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        # Create a concrete implementation for testing
        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"Bedrag": 100.50}
        result = processor.get_amount(mutation)

        self.assertEqual(result, 100.50)

    def test_get_amount_from_bedrag_invoer(self):
        """Test extracting amount from 'BedragInvoer' field"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"BedragInvoer": 200.75}
        result = processor.get_amount(mutation)

        self.assertEqual(result, 200.75)

    def test_get_amount_from_amount_field(self):
        """Test extracting amount from 'amount' field (REST)"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"amount": 150.25}
        result = processor.get_amount(mutation)

        self.assertEqual(result, 150.25)

    def test_get_amount_negative(self):
        """Test negative amounts (refunds)"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"amount": -50.00}
        result = processor.get_amount(mutation)

        self.assertEqual(result, -50.00)

    def test_get_amount_zero(self):
        """Test zero amount"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"amount": 0}
        result = processor.get_amount(mutation)

        self.assertEqual(result, 0.0)

    def test_get_amount_missing_returns_zero(self):
        """Test that missing amount field returns 0.0"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"id": 1001}  # No amount field
        result = processor.get_amount(mutation)

        self.assertEqual(result, 0.0)


class TestRowAmountValidation(unittest.TestCase):
    """Test row amount validation"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"
        self.mock_frappe.utils.flt = lambda x, precision=None: round(float(x or 0), precision or 2)
        self.mock_frappe.as_json = lambda x, indent=None: str(x)

        # Also patch safe_log_mutation_error to prevent actual logging
        self.log_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.safe_log_mutation_error"
        )
        self.mock_log = self.log_patcher.start()

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()
        self.log_patcher.stop()

    def test_row_sum_within_tolerance(self):
        """Test that row sum within 0.01 tolerance passes validation"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_ROW_SUM_WITHIN_TOLERANCE)
        rows = mutation.get("rows", [])
        amount = mutation.get("amount", 0)

        is_valid, error_msg, diff = processor.validate_row_amounts(mutation, rows, amount)

        self.assertTrue(is_valid)
        self.assertEqual(error_msg, "")
        # Diff should be ~0.005 (100.00 rows vs 100.005 expected), clearly under 0.01 tolerance
        self.assertLess(diff, 0.01)

    def test_row_sum_mismatch_fails(self):
        """Test that row sum mismatch > tolerance fails validation"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_ROW_SUM_MISMATCH)
        rows = mutation.get("rows", [])
        amount = mutation.get("amount", 0)

        is_valid, error_msg, diff = processor.validate_row_amounts(mutation, rows, amount)

        self.assertFalse(is_valid)
        self.assertIn("mismatch", error_msg.lower())
        self.assertGreater(diff, 0.01)

    def test_near_zero_rows_skipped(self):
        """Test that near-zero rows (<0.01) are skipped in calculation"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_NEAR_ZERO_ROWS)
        rows = mutation.get("rows", [])
        amount = mutation.get("amount", 0)

        is_valid, error_msg, diff = processor.validate_row_amounts(mutation, rows, amount)

        # Should pass because near-zero rows are skipped
        self.assertTrue(is_valid)

    def test_net_amount_validation(self):
        """Test net amount validation for memorial bookings"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")

        # Test balanced journal entry
        mutation = {"id": 1001}
        total_debit = 100.0
        total_credit = 100.0
        expected_net = 0.0

        is_valid, error_msg, diff = processor.validate_journal_entry_net_amount(
            mutation, total_debit, total_credit, expected_net
        )

        self.assertTrue(is_valid)
        self.assertEqual(diff, 0.0)

    def test_net_amount_validation_unbalanced(self):
        """Test net amount validation fails for unbalanced entry"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")

        # Test unbalanced journal entry
        mutation = {"id": 1001}
        total_debit = 100.0
        total_credit = 95.0  # 5.00 difference
        expected_net = 0.0

        is_valid, error_msg, diff = processor.validate_journal_entry_net_amount(
            mutation, total_debit, total_credit, expected_net
        )

        self.assertFalse(is_valid)
        self.assertIn("mismatch", error_msg.lower())


class TestBtwCodeMapping(unittest.TestCase):
    """Test Dutch BTW/VAT code mapping"""

    def test_hoog_verk_21(self):
        """Test high VAT sales 21%"""
        btw = BTW_CODE_MAP.get("HOOG_VERK_21")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 21)
        self.assertEqual(btw["type"], "Output VAT")

    def test_laag_verk_9(self):
        """Test low VAT sales 9%"""
        btw = BTW_CODE_MAP.get("LAAG_VERK_9")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 9)
        self.assertEqual(btw["type"], "Output VAT")

    def test_hoog_ink_21(self):
        """Test high VAT purchase 21%"""
        btw = BTW_CODE_MAP.get("HOOG_INK_21")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 21)
        self.assertEqual(btw["type"], "Input VAT")

    def test_laag_ink_9(self):
        """Test low VAT purchase 9%"""
        btw = BTW_CODE_MAP.get("LAAG_INK_9")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 9)
        self.assertEqual(btw["type"], "Input VAT")

    def test_verlegde_btw(self):
        """Test reverse charge VAT"""
        btw = BTW_CODE_MAP.get("VERLEGDE_BTW")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 21)
        self.assertEqual(btw["type"], "Reverse Charge")

    def test_geen(self):
        """Test no VAT"""
        btw = BTW_CODE_MAP.get("GEEN")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 0)
        self.assertIsNone(btw["type"])

    def test_vrij(self):
        """Test VAT exempt"""
        btw = BTW_CODE_MAP.get("VRIJ")

        self.assertIsNotNone(btw)
        self.assertEqual(btw["rate"], 0)
        self.assertIsNone(btw["type"])

    def test_all_btw_code_samples(self):
        """Test all BTW code samples from fixtures"""
        for sample in BTW_CODE_TEST_CASES:
            with self.subTest(code=sample["code"]):
                btw = BTW_CODE_MAP.get(sample["code"])

                self.assertIsNotNone(btw, f"BTW code '{sample['code']}' not found")
                self.assertEqual(
                    btw["rate"],
                    sample["expected_rate"],
                    f"Rate mismatch for {sample['code']}",
                )
                self.assertEqual(
                    btw["type"],
                    sample["expected_type"],
                    f"Type mismatch for {sample['code']}",
                )


class TestUomMapping(unittest.TestCase):
    """Test Unit of Measure mapping"""

    def test_stk_to_nos(self):
        """Test 'Stk' maps to 'Nos'"""
        self.assertEqual(UOM_MAP.get("Stk"), "Nos")

    def test_stuks_to_nos(self):
        """Test 'Stuks' maps to 'Nos'"""
        self.assertEqual(UOM_MAP.get("Stuks"), "Nos")

    def test_uur_to_hour(self):
        """Test 'Uur' maps to 'Hour'"""
        self.assertEqual(UOM_MAP.get("Uur"), "Hour")

    def test_uren_to_hour(self):
        """Test 'Uren' maps to 'Hour'"""
        self.assertEqual(UOM_MAP.get("Uren"), "Hour")

    def test_dag_to_day(self):
        """Test 'Dag' maps to 'Day'"""
        self.assertEqual(UOM_MAP.get("Dag"), "Day")

    def test_maand_to_month(self):
        """Test 'Maand' maps to 'Month'"""
        self.assertEqual(UOM_MAP.get("Maand"), "Month")

    def test_kg_to_kg(self):
        """Test 'kg' maps to 'Kg'"""
        self.assertEqual(UOM_MAP.get("kg"), "Kg")

    def test_m2_to_sq_meter(self):
        """Test 'm2' maps to 'Sq Meter'"""
        self.assertEqual(UOM_MAP.get("m2"), "Sq Meter")

    def test_percent_mapping(self):
        """Test '%' maps to 'Percent'"""
        self.assertEqual(UOM_MAP.get("%"), "Percent")

    def test_all_uom_samples(self):
        """Test all UOM samples from fixtures"""
        for sample in UOM_TEST_CASES:
            with self.subTest(dutch=sample["dutch"]):
                result = UOM_MAP.get(sample["dutch"])
                self.assertEqual(
                    result,
                    sample["expected"],
                    f"UOM mapping failed for '{sample['dutch']}'",
                )


class TestItemGroupClassification(unittest.TestCase):
    """Test item group classification based on description keywords"""

    def test_service_keywords(self):
        """Test that service keywords map to Services group"""
        service_keywords = ITEM_GROUP_KEYWORDS.get("service", [])

        self.assertIn("dienst", service_keywords)
        self.assertIn("advies", service_keywords)
        self.assertIn("consultancy", service_keywords)
        self.assertIn("training", service_keywords)

    def test_product_keywords(self):
        """Test that product keywords map to Products group"""
        product_keywords = ITEM_GROUP_KEYWORDS.get("product", [])

        self.assertIn("product", product_keywords)
        self.assertIn("laptop", product_keywords)
        self.assertIn("hardware", product_keywords)
        self.assertIn("meubilair", product_keywords)

    def test_travel_keywords(self):
        """Test that travel keywords are defined"""
        travel_keywords = ITEM_GROUP_KEYWORDS.get("travel", [])

        self.assertIn("reis", travel_keywords)
        self.assertIn("hotel", travel_keywords)
        self.assertIn("parkeren", travel_keywords)
        self.assertIn("trein", travel_keywords)

    def test_office_keywords(self):
        """Test that office supply keywords are defined"""
        office_keywords = ITEM_GROUP_KEYWORDS.get("office", [])

        self.assertIn("kantoorartikelen", office_keywords)
        self.assertIn("papier", office_keywords)
        self.assertIn("printer", office_keywords)
        self.assertIn("toner", office_keywords)

    def test_default_item_groups_mapping(self):
        """Test that default item groups are properly mapped"""
        self.assertEqual(DEFAULT_ITEM_GROUPS.get("service"), "Services")
        self.assertEqual(DEFAULT_ITEM_GROUPS.get("product"), "Products")
        self.assertEqual(DEFAULT_ITEM_GROUPS.get("travel"), "Expense Items")
        self.assertEqual(DEFAULT_ITEM_GROUPS.get("office"), "Office Supplies")
        self.assertEqual(DEFAULT_ITEM_GROUPS.get("default"), "Services")

    def test_vat_category_hints(self):
        """Test VAT-based category hints"""
        self.assertEqual(VAT_CATEGORY_HINTS.get("GEEN"), "service")
        self.assertEqual(VAT_CATEGORY_HINTS.get("VRIJ"), "service")
        self.assertEqual(VAT_CATEGORY_HINTS.get("HOOG_VERK_21"), "product")

    def test_account_code_item_hints(self):
        """Test account code-based item hints"""
        # Check that ranges are defined
        self.assertGreater(len(ACCOUNT_CODE_ITEM_HINTS), 0)

        # Check specific ranges
        for (start, end), category in ACCOUNT_CODE_ITEM_HINTS.items():
            self.assertIsInstance(start, int)
            self.assertIsInstance(end, int)
            self.assertIsInstance(category, str)
            self.assertLessEqual(start, end)


class TestItemGroupClassificationFromDescription(unittest.TestCase):
    """Test item group classification based on actual descriptions"""

    def _classify_description(self, description: str) -> str:
        """Helper to classify description based on keywords"""
        description_lower = description.lower()

        for category, keywords in ITEM_GROUP_KEYWORDS.items():
            for keyword in keywords:
                if keyword in description_lower:
                    return DEFAULT_ITEM_GROUPS.get(category, "Services")

        return DEFAULT_ITEM_GROUPS.get("default", "Services")

    def test_service_descriptions(self):
        """Test service-related descriptions"""
        self.assertEqual(
            self._classify_description("Advies en consultancy diensten"),
            "Services",
        )
        self.assertEqual(
            self._classify_description("IT ondersteuning maandelijks"),
            "Services",
        )
        self.assertEqual(
            self._classify_description("Training workshop medewerkers"),
            "Services",
        )

    def test_product_descriptions(self):
        """Test product-related descriptions"""
        self.assertEqual(
            self._classify_description("Laptop Dell XPS 15"),
            "Products",
        )
        self.assertEqual(
            self._classify_description("Kantoor meubilair bureau"),
            "Products",
        )

    def test_travel_descriptions(self):
        """Test travel-related descriptions"""
        self.assertEqual(
            self._classify_description("Reiskosten trein Amsterdam-Utrecht"),
            "Expense Items",
        )
        self.assertEqual(
            self._classify_description("Hotel verblijf conferentie"),
            "Expense Items",
        )
        # Note: "parkeerkosten" doesn't match keyword "parkeren" (substring mismatch)
        # Use a description that contains the exact keyword
        self.assertEqual(
            self._classify_description("Parkeren bij vergadering"),
            "Expense Items",
        )

    def test_office_descriptions(self):
        """Test office supply descriptions"""
        self.assertEqual(
            self._classify_description("Kantoorartikelen papier en pennen"),
            "Office Supplies",
        )
        self.assertEqual(
            self._classify_description("Printer cartridge toner"),
            "Office Supplies",
        )

    def test_unknown_defaults_to_services(self):
        """Test that unknown descriptions default to Services"""
        self.assertEqual(
            self._classify_description("Some random text without keywords"),
            "Services",
        )


class TestPostingDateExtraction(unittest.TestCase):
    """Test posting date extraction from mutations"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_get_posting_date_from_datum(self):
        """Test extracting posting date from 'Datum' field (SOAP)"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"Datum": "20250115"}
        result = processor.get_posting_date(mutation)

        self.assertEqual(result, "2025-01-15")

    def test_get_posting_date_from_date(self):
        """Test extracting posting date from 'date' field (REST)"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"date": "2025-01-20"}
        result = processor.get_posting_date(mutation)

        self.assertEqual(result, "2025-01-20")

    def test_get_posting_date_from_date_capitalized(self):
        """Test extracting posting date from 'Date' field"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"Date": "2025-01-25"}
        result = processor.get_posting_date(mutation)

        self.assertEqual(result, "2025-01-25")

    def test_get_posting_date_priority(self):
        """Test that 'Datum' takes priority over 'date'"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {"Datum": "20250101", "date": "2025-12-31"}
        result = processor.get_posting_date(mutation)

        self.assertEqual(result, "2025-01-01")


if __name__ == "__main__":
    unittest.main()
