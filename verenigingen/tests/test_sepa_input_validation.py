"""
Test SEPA Input Validation

Comprehensive tests for SEPA batch input validation including:
- Parameter validation
- Amount validation  
- Date validation
- IBAN/BIC validation
- Text field validation
- Business rule validation
"""

import frappe
from frappe.utils import today, add_days
from decimal import Decimal
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.sepa_input_validation import SEPAInputValidator


class TestSEPAInputValidation(VereningingenTestCase):
    """Test SEPA input validation functionality"""
    
    def setUp(self):
        super().setUp()
        self.validator = SEPAInputValidator()
        
        # Create test data
        self.member = self.create_test_member(
            first_name="TestSEPA",
            email="sepa@example.com"
        )
        
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type="Monthly Standard"
        )
        
        # Create test invoice
        self.invoice = self.create_test_sales_invoice(
            customer=self.member.name,
            amount=25.00,
            status="Unpaid"
        )
    
    def test_validate_collection_date_valid(self):
        """Test valid collection date validation"""
        
        # Test with valid future date
        future_date = add_days(today(), 5)
        result = SEPAInputValidator.validate_collection_date(future_date)
        
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(result["cleaned_date"], future_date)
    
    def test_validate_collection_date_too_early(self):
        """Test collection date too early"""
        
        # Test with yesterday
        yesterday = add_days(today(), -1)
        result = SEPAInputValidator.validate_collection_date(yesterday)
        
        self.assertFalse(result["valid"])
        self.assertIn("Collection date too early", result["errors"][0])
    
    def test_validate_collection_date_too_late(self):
        """Test collection date too late"""
        
        # Test with date beyond maximum offset
        far_future = add_days(today(), 60)
        result = SEPAInputValidator.validate_collection_date(far_future)
        
        self.assertFalse(result["valid"])
        self.assertIn("Collection date too late", result["errors"][0])
    
    def test_validate_collection_date_weekend(self):
        """Test collection date on weekend"""
        
        # Find next Saturday (weekday 5)
        test_date = add_days(today(), 1)
        while test_date.weekday() != 5:  # Saturday
            test_date = add_days(test_date, 1)
            if (test_date - today()).days > 30:  # Safety check
                self.skipTest("Could not find Saturday within 30 days")
        
        result = SEPAInputValidator.validate_collection_date(test_date)
        
        self.assertFalse(result["valid"])
        self.assertIn("Collection date cannot be weekend", result["errors"][0])
    
    def test_validate_batch_type_valid(self):
        """Test valid batch type validation"""
        
        for batch_type in ["CORE", "B2B", "COR1"]:
            with self.subTest(batch_type=batch_type):
                result = SEPAInputValidator.validate_batch_type(batch_type)
                
                self.assertTrue(result["valid"])
                self.assertEqual(result["cleaned_type"], batch_type)
    
    def test_validate_batch_type_invalid(self):
        """Test invalid batch type validation"""
        
        invalid_types = ["INVALID", "", None, "core", "b2b"]
        
        for batch_type in invalid_types:
            with self.subTest(batch_type=batch_type):
                result = SEPAInputValidator.validate_batch_type(batch_type)
                
                self.assertFalse(result["valid"])
                self.assertGreater(len(result["errors"]), 0)
    
    def test_validate_amount_valid(self):
        """Test valid amount validation"""
        
        valid_amounts = [
            "25.00", "100.50", "1.23", 
            25.00, 100.50, 1.23,
            Decimal("25.00"), Decimal("100.50")
        ]
        
        for amount in valid_amounts:
            with self.subTest(amount=amount):
                result = SEPAInputValidator.validate_amount(amount)
                
                self.assertTrue(result["valid"], f"Amount {amount} should be valid")
                self.assertIsInstance(result["cleaned_amount"], Decimal)
                self.assertGreater(result["cleaned_amount"], 0)
    
    def test_validate_amount_invalid(self):
        """Test invalid amount validation"""
        
        invalid_amounts = [
            "0", "-25.00", "abc", "", None,
            0, -25.00, 
            "25.001",  # Too many decimal places
            str(SEPAInputValidator.MAX_AMOUNT + 1)  # Too large
        ]
        
        for amount in invalid_amounts:
            with self.subTest(amount=amount):
                result = SEPAInputValidator.validate_amount(amount)
                
                self.assertFalse(result["valid"], f"Amount {amount} should be invalid")
                self.assertGreater(len(result["errors"]), 0)
    
    def test_validate_mandate_reference_valid(self):
        """Test valid mandate reference validation"""
        
        valid_refs = ["MND-001", "MANDATE_123", "REF.456", "ABC-DEF-123"]
        
        for ref in valid_refs:
            with self.subTest(ref=ref):
                result = SEPAInputValidator.validate_mandate_reference(ref)
                
                self.assertTrue(result["valid"])
                self.assertEqual(result["cleaned_reference"], ref)
    
    def test_validate_mandate_reference_invalid(self):
        """Test invalid mandate reference validation"""
        
        invalid_refs = [
            "", None, "  ", 
            "REF WITH SPACES",  # Spaces not allowed
            "REF@INVALID",      # @ not allowed
            "A" * 40,           # Too long
        ]
        
        for ref in invalid_refs:
            with self.subTest(ref=ref):
                result = SEPAInputValidator.validate_mandate_reference(ref)
                
                self.assertFalse(result["valid"], f"Reference {ref} should be invalid")
                self.assertGreater(len(result["errors"]), 0)
    
    def test_validate_bic_valid(self):
        """Test valid BIC validation"""
        
        valid_bics = [
            "ABNANL2A",      # 8 characters
            "ABNANL2AXXX",   # 11 characters
            "INGBNL2A",      # Real Dutch bank
            "RABONL2U"       # Real Dutch bank
        ]
        
        for bic in valid_bics:
            with self.subTest(bic=bic):
                result = SEPAInputValidator.validate_bic(bic)
                
                self.assertTrue(result["valid"], f"BIC {bic} should be valid")
                self.assertEqual(result["cleaned_bic"], bic.upper())
    
    def test_validate_bic_invalid(self):
        """Test invalid BIC validation"""
        
        invalid_bics = [
            "", None, "  ",
            "ABCD123",       # Too short
            "ABCD12345678",  # Too long
            "123NANL2A",     # Numbers in bank code
            "ABNANL22",      # Invalid format
        ]
        
        for bic in invalid_bics:
            with self.subTest(bic=bic):
                result = SEPAInputValidator.validate_bic(bic)
                
                self.assertFalse(result["valid"], f"BIC {bic} should be invalid")
                self.assertGreater(len(result["errors"]), 0)
    
    def test_validate_sepa_text_valid(self):
        """Test valid SEPA text validation"""
        
        valid_texts = [
            "Invoice payment",
            "Member dues 2024",
            "Payment for services",
            "ABC-123 (test)",
            "Amount: 25.50 EUR"
        ]
        
        for text in valid_texts:
            with self.subTest(text=text):
                result = SEPAInputValidator.validate_sepa_text(text, 100, "test_field")
                
                self.assertTrue(result["valid"], f"Text '{text}' should be valid")
                self.assertEqual(result["cleaned_text"], text.strip())
    
    def test_validate_sepa_text_invalid(self):
        """Test invalid SEPA text validation"""
        
        invalid_texts = [
            "", None, "   ",  # Empty
            "Text with émojis 🎉",  # Non-SEPA characters
            "Text with @#$%",       # Invalid symbols
            "A" * 200,              # Too long (assuming max_length=100)
        ]
        
        for text in invalid_texts:
            with self.subTest(text=text):
                result = SEPAInputValidator.validate_sepa_text(text, 100, "test_field")
                
                self.assertFalse(result["valid"], f"Text '{text}' should be invalid")
                self.assertGreater(len(result["errors"]), 0)
    
    def test_validate_single_invoice_valid(self):
        """Test valid single invoice validation"""
        
        valid_invoice = {
            "invoice": "INV-001",
            "amount": "25.00",
            "iban": "NL91ABNA0417164300",  # Valid Dutch IBAN
            "member_name": "John Doe",
            "mandate_reference": "MND-123",
            "bic": "ABNANL2A",
            "currency": "EUR",
            "description": "Monthly dues"
        }
        
        result = SEPAInputValidator.validate_single_invoice(valid_invoice)
        
        self.assertTrue(result["valid"], f"Errors: {result.get('errors', [])}")
        self.assertEqual(len(result["errors"]), 0)
        
        cleaned = result["cleaned_invoice"]
        self.assertEqual(cleaned["invoice"], "INV-001")
        self.assertEqual(cleaned["amount"], Decimal("25.00"))
        self.assertEqual(cleaned["iban"], "NL91ABNA0417164300")
        self.assertEqual(cleaned["member_name"], "John Doe")
        self.assertEqual(cleaned["mandate_reference"], "MND-123")
    
    def test_validate_single_invoice_missing_required(self):
        """Test single invoice validation with missing required fields"""
        
        incomplete_invoice = {
            "invoice": "INV-001",
            "amount": "25.00",
            # Missing: iban, member_name, mandate_reference
        }
        
        result = SEPAInputValidator.validate_single_invoice(incomplete_invoice)
        
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)
        
        # Should mention missing required fields
        error_text = " ".join(result["errors"])
        self.assertIn("iban", error_text.lower())
        self.assertIn("member_name", error_text.lower())
        self.assertIn("mandate_reference", error_text.lower())
    
    def test_validate_invoice_list_valid(self):
        """Test valid invoice list validation"""
        
        valid_invoices = [
            {
                "invoice": "INV-001",
                "amount": "25.00",
                "iban": "NL91ABNA0417164300",
                "member_name": "John Doe",
                "mandate_reference": "MND-123"
            },
            {
                "invoice": "INV-002", 
                "amount": "50.00",
                "iban": "NL91RABO0315273637",
                "member_name": "Jane Smith",
                "mandate_reference": "MND-456"
            }
        ]
        
        result = SEPAInputValidator.validate_invoice_list(valid_invoices)
        
        self.assertTrue(result["valid"], f"Errors: {result.get('errors', [])}")
        self.assertEqual(len(result["cleaned_invoices"]), 2)
        self.assertEqual(len(result["errors"]), 0)
    
    def test_validate_invoice_list_duplicates(self):
        """Test invoice list validation with duplicates"""
        
        duplicate_invoices = [
            {
                "invoice": "INV-001",
                "amount": "25.00",
                "iban": "NL91ABNA0417164300",
                "member_name": "John Doe",
                "mandate_reference": "MND-123"
            },
            {
                "invoice": "INV-001",  # Duplicate
                "amount": "25.00",
                "iban": "NL91ABNA0417164300",
                "member_name": "John Doe",
                "mandate_reference": "MND-123"
            }
        ]
        
        result = SEPAInputValidator.validate_invoice_list(duplicate_invoices)
        
        self.assertFalse(result["valid"])
        self.assertIn("Duplicate invoice", " ".join(result["errors"]))
    
    def test_validate_invoice_list_empty(self):
        """Test invoice list validation with empty list"""
        
        result = SEPAInputValidator.validate_invoice_list([])
        
        self.assertFalse(result["valid"])
        self.assertIn("cannot be empty", " ".join(result["errors"]))
    
    def test_validate_invoice_list_too_large(self):
        """Test invoice list validation with too many invoices"""
        
        # Create a list that exceeds MAX_BATCH_SIZE
        large_invoice_list = []
        for i in range(SEPAInputValidator.MAX_BATCH_SIZE + 1):
            large_invoice_list.append({
                "invoice": f"INV-{i:06d}",
                "amount": "25.00",
                "iban": "NL91ABNA0417164300",
                "member_name": "John Doe",
                "mandate_reference": "MND-123"
            })
        
        result = SEPAInputValidator.validate_invoice_list(large_invoice_list)
        
        self.assertFalse(result["valid"])
        self.assertIn("Too many invoices", " ".join(result["errors"]))
    
    def test_validate_batch_creation_params_valid(self):
        """Test valid batch creation parameters"""
        
        valid_params = {
            "batch_date": add_days(today(), 5),
            "batch_type": "CORE",
            "invoice_list": [{
                "invoice": "INV-001",
                "amount": "25.00",
                "iban": "NL91ABNA0417164300",
                "member_name": "John Doe",
                "mandate_reference": "MND-123"
            }],
            "description": "Test batch"
        }
        
        result = SEPAInputValidator.validate_batch_creation_params(**valid_params)
        
        self.assertTrue(result["valid"], f"Errors: {result.get('errors', [])}")
        self.assertEqual(len(result["errors"]), 0)
        
        cleaned = result["cleaned_params"]
        self.assertIn("batch_date", cleaned)
        self.assertIn("batch_type", cleaned)
        self.assertIn("invoice_list", cleaned)
        self.assertIn("description", cleaned)
    
    def test_validate_batch_creation_params_missing_required(self):
        """Test batch creation parameters with missing required fields"""
        
        incomplete_params = {
            "batch_type": "CORE",
            # Missing: batch_date, invoice_list
        }
        
        result = SEPAInputValidator.validate_batch_creation_params(**incomplete_params)
        
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)
        
        error_text = " ".join(result["errors"])
        self.assertIn("batch_date", error_text)
        self.assertIn("invoice_list", error_text)
    
    def test_api_validate_sepa_batch_params(self):
        """Test API endpoint for batch parameter validation"""
        
        # Test with valid parameters
        valid_params = {
            "batch_date": str(add_days(today(), 5)),
            "batch_type": "CORE",
            "invoice_list": [{
                "invoice": "INV-001",
                "amount": "25.00",
                "iban": "NL91ABNA0417164300",
                "member_name": "John Doe",
                "mandate_reference": "MND-123"
            }]
        }
        
        result = frappe.call(
            "verenigingen.utils.sepa_input_validation.validate_sepa_batch_params",
            **valid_params
        )
        
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)
    
    def test_api_validate_single_sepa_invoice(self):
        """Test API endpoint for single invoice validation"""
        
        valid_invoice = {
            "invoice": "INV-001",
            "amount": "25.00",
            "iban": "NL91ABNA0417164300",
            "member_name": "John Doe",
            "mandate_reference": "MND-123"
        }
        
        result = frappe.call(
            "verenigingen.utils.sepa_input_validation.validate_single_sepa_invoice",
            invoice_data=valid_invoice
        )
        
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)
    
    def test_api_get_sepa_validation_rules(self):
        """Test API endpoint for getting validation rules"""
        
        result = frappe.call(
            "verenigingen.utils.sepa_input_validation.get_sepa_validation_rules"
        )
        
        self.assertIn("constraints", result)
        self.assertIn("valid_batch_types", result)
        self.assertIn("required_invoice_fields", result)
        
        constraints = result["constraints"]
        self.assertIn("max_batch_size", constraints)
        self.assertIn("min_amount", constraints)
        self.assertIn("max_amount", constraints)

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()